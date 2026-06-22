"""케이웨더 IoT Open API 수집 — last-all 폴링(실시간 측정값).

STS에서 구현→제거됐던 연동(cd720aa^:services/kw_iot.py)을 실시간 트랙용으로 복원.
- 실 모드: GET {KW_IOT_BASE_URL}/last-all (stationType=ALL, idType=USER, id, api_key)
- mock 모드: 키 없이 PoC 구동 — 실내/실외 가상 기기의 체감온도가 천천히 표류하며
  주기적으로 위험단계 임계를 넘나들어 경보·라이브 대시보드를 시연.

반환: 정규화된 reading dict 리스트
  {sn, name, kind, measured_at(datetime), temperature, humidity, feels_like, co2, pm10, pm25, voc}
"""
from __future__ import annotations

import math
import random
from datetime import datetime

import httpx

from .config import settings
from .feels import kma_feels_like


def _apparent_temp(t: float | None, rh: float | None) -> float | None:
    """senseTemp 미제공 시 폴백 — 기상청 공식 체감온도."""
    f = kma_feels_like(t, rh)
    return f if f is not None else (float(t) if t is not None else None)


async def fetch_last_all() -> list[dict]:
    """케이웨더 IoT last-all 실시간 측정값."""
    if settings.USE_MOCK or not (settings.KW_IOT_API_KEY and settings.KW_IOT_USER_ID):
        return _mock_last_all()

    url = f"{settings.KW_IOT_BASE_URL}/last-all"
    params = {
        "stationType": "ALL",
        "idType": "USER",
        "id": settings.KW_IOT_USER_ID,
        "api_key": settings.KW_IOT_API_KEY,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        j = r.json()
    if str(j.get("error")) != "0":
        raise RuntimeError(j.get("message") or "KW IoT error")
    result = j.get("result", {}) or {}
    out: list[dict] = []
    for kind, key in (("indoor", "iaqList"), ("outdoor", "oaqList")):
        for it in result.get(key, []) or []:
            sn = it.get("serialNo") or it.get("stationName")
            if not sn:
                continue
            temp = it.get("temp")
            humi = it.get("humi")
            feels = it.get("senseTemp")
            if feels is None:
                feels = _apparent_temp(temp, humi)
            ts = str(it.get("date") or "")
            try:
                mt = datetime.strptime(ts[:12], "%Y%m%d%H%M")
            except Exception:  # noqa: BLE001
                mt = datetime.now()
            out.append({
                "sn": sn, "name": it.get("stationName"), "kind": kind, "measured_at": mt,
                "temperature": temp, "humidity": humi, "feels_like": feels,
                "co2": it.get("co2"), "pm10": it.get("pm10"), "pm25": it.get("pm25"), "voc": it.get("voc"),
            })
    return out


# ── mock 모드 ─────────────────────────────────────────────────────────────
# 위험단계를 시연하기 위해 기기별 기준 체감온도를 다르게 두고, 매 폴링마다
# 사인파 + 난수로 천천히 표류시킨다. 상태는 모듈 전역에 보존.
_MOCK_STATIONS = [
    {"sn": "HG-OUT-001", "name": "A현장 옥외작업장", "kind": "outdoor", "base": 36.5, "phase": 0.0},
    {"sn": "HG-OUT-002", "name": "B현장 자재야적장", "kind": "outdoor", "base": 33.0, "phase": 1.7},
    {"sn": "HG-IN-001", "name": "용해로 작업동(밀폐)", "kind": "indoor", "base": 34.5, "phase": 3.1},
    {"sn": "HG-IN-002", "name": "사무동 휴게실", "kind": "indoor", "base": 27.0, "phase": 4.8},
]
_mock_tick = 0


def _mock_last_all() -> list[dict]:
    global _mock_tick
    _mock_tick += 1
    now = datetime.now()
    out: list[dict] = []
    for st in _MOCK_STATIONS:
        drift = 2.2 * math.sin(_mock_tick / 6.0 + st["phase"]) + random.uniform(-0.6, 0.6)
        feels = round(st["base"] + drift, 1)
        # 체감온도에서 역으로 그럴듯한 온도/습도 합성
        humi = round(max(35.0, min(85.0, 60.0 - (feels - 33.0) * 2 + random.uniform(-3, 3))), 0)
        temp = round(feels - 1.5 + random.uniform(-0.5, 0.5), 1)
        out.append({
            "sn": st["sn"], "name": st["name"], "kind": st["kind"], "measured_at": now,
            "temperature": temp, "humidity": humi, "feels_like": feels,
            "co2": round(450 + random.uniform(0, 600)) if st["kind"] == "indoor" else None,
            "pm10": round(20 + random.uniform(0, 40)), "pm25": round(10 + random.uniform(0, 25)), "voc": None,
        })
    return out
