"""케이웨더 IoT Open API 수집 — last-all 폴링(실시간 측정값).

STS에서 구현→제거됐던 연동(cd720aa^:services/kw_iot.py)을 실시간 트랙용으로 복원.
- 실 모드: GET {KW_IOT_BASE_URL}/last-all (stationType=ALL, idType=USER, id, api_key)
- mock 모드: 키 없이 구동 — 시간 기반 stateless 합성(app/mock.py). 위험단계를 넘나들어
  경보·라이브 대시보드를 시연. 서버리스(Vercel)와 동일 합성을 공유.

반환: 정규화된 reading dict 리스트
  {sn, name, kind, measured_at(datetime), temperature, humidity, feels_like, co2, pm10, pm25, voc}
"""
from __future__ import annotations

from datetime import datetime

import httpx

from . import mock
from .config import settings
from .feels import kma_feels_like


def _apparent_temp(t: float | None, rh: float | None) -> float | None:
    """senseTemp 미제공 시 폴백 — 기상청 공식 체감온도."""
    f = kma_feels_like(t, rh)
    return f if f is not None else (float(t) if t is not None else None)


async def fetch_last_all() -> list[dict]:
    """케이웨더 IoT last-all 실시간 측정값."""
    if settings.USE_MOCK or not (settings.KW_IOT_API_KEY and settings.KW_IOT_USER_ID):
        return mock.last_all_at(mock.now_kst())

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
