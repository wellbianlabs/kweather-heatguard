"""시간 기반 stateless mock — 키 없이/서버리스에서 라이브 시연.

Vercel 서버리스는 백그라운드 워커·인메모리 상태를 유지할 수 없으므로, 측정값을
**현재 시각의 순수 함수**로 합성한다(난수 없음 → 폴링마다 부드럽게 표류).
- last_all_at(now): 수집 워커(collector)용 최신 측정값 리스트
- snapshot_at(now): 서버리스 /api/live 용 — 기기별 최신값 + 합성 히스토리 + 현재 활성 경보
"""
from __future__ import annotations

import math
from datetime import date as date_cls, datetime, timedelta

from .heat import LEVELS, classify

# 기기 정의: base=기준 체감온도, amp=진폭, phase=위상. 일부는 위험단계를 넘나든다.
STATIONS = [
    {"sn": "HG-OUT-001", "name": "A현장 옥외작업장", "kind": "outdoor", "base": 36.5, "amp": 2.6, "phase": 0.0},
    {"sn": "HG-OUT-002", "name": "B현장 자재야적장", "kind": "outdoor", "base": 33.2, "amp": 2.2, "phase": 1.7},
    {"sn": "HG-IN-001", "name": "용해로 작업동(밀폐)", "kind": "indoor", "base": 34.6, "amp": 2.4, "phase": 3.1},
    {"sn": "HG-IN-002", "name": "사무동 휴게실", "kind": "indoor", "base": 27.2, "amp": 1.6, "phase": 4.8},
]

_PERIOD_SEC = 150.0  # 한 주기(≈2.5분)마다 위험단계가 오르내림


def now_kst() -> datetime:
    """데모 기준 현재시각(KST). Vercel=UTC 환경에서도 한국 일과시간 곡선이 맞도록 보정."""
    return datetime.utcnow() + timedelta(hours=9)


def _feels_at(st: dict, ts: float) -> float:
    drift = st["amp"] * math.sin(ts / _PERIOD_SEC * 2 * math.pi + st["phase"])
    # 미세 흔들림(난수 대신 빠른 사인) — 그래프가 살아있게 보이도록
    jitter = 0.4 * math.sin(ts / 11.0 + st["phase"] * 2)
    return round(st["base"] + drift + jitter, 1)


def _reading(st: dict, when: datetime) -> dict:
    feels = _feels_at(st, when.timestamp())
    humi = round(max(35.0, min(85.0, 60.0 - (feels - 33.0) * 2)))
    temp = round(feels - 1.5, 1)
    return {
        "sn": st["sn"], "name": st["name"], "kind": st["kind"], "measured_at": when,
        "temperature": temp, "humidity": humi, "feels_like": feels,
        "co2": round(450 + 300 * (0.5 + 0.5 * math.sin(when.timestamp() / 40))) if st["kind"] == "indoor" else None,
        "pm10": round(25 + 15 * (0.5 + 0.5 * math.sin(when.timestamp() / 30))),
        "pm25": round(12 + 10 * (0.5 + 0.5 * math.sin(when.timestamp() / 35))), "voc": None,
    }


def last_all_at(now: datetime) -> list[dict]:
    return [_reading(st, now) for st in STATIONS]


def _history(st: dict, now: datetime, points: int = 40, step_sec: int = 5) -> list[dict]:
    out: list[dict] = []
    for i in range(points - 1, -1, -1):
        when = now - timedelta(seconds=i * step_sec)
        r = _reading(st, when)
        out.append({
            "at": when.isoformat(), "feels_like": r["feels_like"],
            "temperature": r["temperature"], "humidity": r["humidity"],
            "level": classify(r["feels_like"]).code,
        })
    return out


def snapshot_at(now: datetime) -> dict:
    """서버리스용 stateless 스냅샷 — 기기별 최신값+히스토리, 현재 활성 경보(주의↑)."""
    stations = []
    alerts = []
    for st in STATIONS:
        r = _reading(st, now)
        lvl = classify(r["feels_like"])
        latest = {**r, "measured_at": now.isoformat(),
                  "level": lvl.code, "level_label": lvl.label, "level_color": lvl.color}
        stations.append({
            "sn": st["sn"], "name": st["name"], "kind": st["kind"],
            "latest": latest, "history": _history(st, now),
        })
        if lvl.rank >= LEVELS["caution"].rank:   # 주의 이상은 현재 활성 경보로 표시
            from .alerts import ACTION
            alerts.append({
                "at": now.isoformat(), "sn": st["sn"], "name": st["name"], "kind": st["kind"],
                "level": lvl.code, "level_label": lvl.label, "level_color": lvl.color,
                "feels_like": r["feels_like"], "action": ACTION.get(lvl.code, ""),
            })
    alerts.sort(key=lambda a: a["feels_like"], reverse=True)
    return {"stations": stations, "alerts": alerts, "ts": now.isoformat()}


# ── 일별/주간 시계열(리포트·차트용) ─────────────────────────────────────────
# 일중 변화(diurnal)를 가진 결정적 시계열. day_mean=일 평균 체감, day_amp=진폭(새벽↓/오후↓).
# 밀폐형 실내는 진폭이 작아 야간에도 더움. 전부 시각의 순수 함수(난수 없음).
DAY_PARAMS = {
    "HG-OUT-001": {"mean": 33.5, "amp": 5.2},   # 옥외작업장 — 오후 위험단계 진입
    "HG-OUT-002": {"mean": 31.2, "amp": 4.6},   # 자재야적장 — 오후 경고
    "HG-IN-001": {"mean": 34.2, "amp": 2.6},    # 용해로(밀폐) — 야간도 주의↑ 유지
    "HG-IN-002": {"mean": 25.2, "amp": 2.0},    # 사무동 휴게실 — 안전권
}


def station_by_sn(sn: str) -> dict | None:
    for st in STATIONS:
        if st["sn"] == sn:
            return st
    return None


def _diurnal(hour_f: float) -> float:
    # 14시 부근 최고, 새벽 최저 (sin 위상 8시 → 피크 14시)
    return math.sin((hour_f - 8.0) / 24.0 * 2 * math.pi)


def _date_offset(d: date_cls) -> float:
    # 날짜별 결정적 가감(폭염 강도 변동) — 주간 위젯에 일별 차이를 만든다.
    return ((d.day * 7 + d.month * 3) % 6) - 2.0


def day_series(sn: str, on: date_cls, step_min: int = 10) -> list[dict]:
    """해당 기기·날짜의 10분 간격 측정 시계열(결정적 합성)."""
    st = station_by_sn(sn)
    if st is None:
        return []
    p = DAY_PARAMS.get(sn, {"mean": 30.0, "amp": 4.0})
    off = _date_offset(on)
    out: list[dict] = []
    steps = (24 * 60) // step_min
    for i in range(steps):
        when = datetime(on.year, on.month, on.day) + timedelta(minutes=i * step_min)
        hour_f = when.hour + when.minute / 60.0
        wiggle = 0.35 * math.sin(hour_f * 1.7 + st["phase"])
        feels = round(p["mean"] + p["amp"] * _diurnal(hour_f) + off + wiggle, 1)
        humi = round(max(35.0, min(88.0, 62.0 - (feels - 33.0) * 2)))
        temp = round(feels - 1.4, 1)
        out.append({
            "at": when.isoformat(), "feels_like": feels, "temperature": temp,
            "humidity": humi, "level": classify(feels).code,
        })
    return out


def today_series(sn: str, now: datetime, step_min: int = 10) -> list[dict]:
    """오늘 00:00~현재까지의 시계열(대시보드 분석용)."""
    full = day_series(sn, now.date(), step_min)
    cutoff = now.isoformat()
    return [p for p in full if p["at"] <= cutoff]


def recent_days(sn: str, end: date_cls, days: int = 7) -> list[dict]:
    """최근 N일 일별 집계(최고/평균 체감, 최고 기온) — 주간 위젯용."""
    rows: list[dict] = []
    for k in range(days - 1, -1, -1):
        d = end - timedelta(days=k)
        series = day_series(sn, d)
        feels = [p["feels_like"] for p in series]
        temps = [p["temperature"] for p in series]
        mx = max(feels)
        rows.append({
            "date": d.isoformat(),
            "max_feels": round(mx, 1),
            "avg_feels": round(sum(feels) / len(feels), 1),
            "max_temp": round(max(temps), 1),
            "peak_level": classify(mx).code,
        })
    return rows


def available_dates(end: date_cls, days: int = 14) -> list[str]:
    return [(end - timedelta(days=k)).isoformat() for k in range(days)]
