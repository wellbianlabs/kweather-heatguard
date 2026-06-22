"""경보 엔진 — 위험단계 상향 교차 감지 → 디바운스 → Slack/Webhook 송출.

MVP 1채널(Slack/Webhook). 채널 미설정 시 경보는 WS 피드/로그로만 송출(PoC).
단계별 자동 대응 문구는 STS 폭염정책(고용노동부 2026)을 계승.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .config import settings
from .heat import LEVELS
from .store import Station

log = logging.getLogger("heatguard.alerts")

# 단계별 자동 대응 권고 — STS 도메인 규칙(체감 33℃↑ 2시간마다 20분 휴식 법적의무 등)
ACTION = {
    "caution": "작업시간 조정·단축. 체감 33℃↑ — 2시간마다 20분 이상 휴식(법적 의무).",
    "warning": "14~17시 옥외작업 중지 권고. 그늘·냉방 휴식 강화, 작업자 상태 수시 확인.",
    "danger": "폭염중대경보(체감 38℃↑). 긴급조치 외 옥외작업 중지. 즉시 대피·휴식.",
}


def should_alert(station: Station, prev: str, current: str) -> bool:
    """상향 교차(관심→주의→경고→위험)만, 그리고 디바운스 통과 시에만 경보."""
    if LEVELS[current].rank <= LEVELS[prev].rank:
        return False                      # 동급/하향은 경보 안 함
    if LEVELS[current].rank < LEVELS["caution"].rank:
        return False                      # 주의 미만(안전/관심)은 경보 제외
    last = station.last_alert_at.get(current)
    now = datetime.now()
    if last and (now - last).total_seconds() < settings.ALERT_DEBOUNCE_SEC:
        return False                      # 중복 억제
    station.last_alert_at[current] = now
    return True


def build_alert(station: Station, current: str) -> dict:
    lvl = LEVELS[current]
    latest = station.latest or {}
    return {
        "at": datetime.now().isoformat(),
        "sn": station.sn, "name": station.name, "kind": station.kind,
        "level": lvl.code, "level_label": lvl.label, "level_color": lvl.color,
        "feels_like": latest.get("feels_like"),
        "action": ACTION.get(current, ""),
    }


async def dispatch(alert: dict) -> None:
    """경보를 외부 채널로 송출(현재 Slack/Webhook). 미설정이면 로그만."""
    text = (
        f"🔥 [{alert['level_label']}] {alert['name']}({alert['sn']}) "
        f"체감 {alert['feels_like']}℃\n{alert['action']}"
    )
    if not settings.SLACK_WEBHOOK_URL:
        log.warning("ALERT(채널 미설정): %s", text)
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(settings.SLACK_WEBHOOK_URL, json={"text": text})
    except Exception as e:  # noqa: BLE001
        log.error("경보 송출 실패: %s", e)
