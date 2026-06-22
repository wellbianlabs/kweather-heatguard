"""시간 기반 stateless mock — 키 없이/서버리스에서 라이브 시연.

Vercel 서버리스는 백그라운드 워커·인메모리 상태를 유지할 수 없으므로, 측정값을
**현재 시각의 순수 함수**로 합성한다(난수 없음 → 폴링마다 부드럽게 표류).
- last_all_at(now): 수집 워커(collector)용 최신 측정값 리스트
- snapshot_at(now): 서버리스 /api/live 용 — 기기별 최신값 + 합성 히스토리 + 현재 활성 경보
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from .heat import LEVELS, classify

# 기기 정의: base=기준 체감온도, amp=진폭, phase=위상. 일부는 위험단계를 넘나든다.
STATIONS = [
    {"sn": "HG-OUT-001", "name": "A현장 옥외작업장", "kind": "outdoor", "base": 36.5, "amp": 2.6, "phase": 0.0},
    {"sn": "HG-OUT-002", "name": "B현장 자재야적장", "kind": "outdoor", "base": 33.2, "amp": 2.2, "phase": 1.7},
    {"sn": "HG-IN-001", "name": "용해로 작업동(밀폐)", "kind": "indoor", "base": 34.6, "amp": 2.4, "phase": 3.1},
    {"sn": "HG-IN-002", "name": "사무동 휴게실", "kind": "indoor", "base": 27.2, "amp": 1.6, "phase": 4.8},
]

_PERIOD_SEC = 150.0  # 한 주기(≈2.5분)마다 위험단계가 오르내림


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
