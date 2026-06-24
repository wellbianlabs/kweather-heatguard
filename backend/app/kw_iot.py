"""케이웨더 IoT Open API 수집 — last-all 폴링(실시간 측정값).

STS에서 구현→제거됐던 연동(cd720aa^:services/kw_iot.py)을 실시간 트랙용으로 복원.
- 실 모드: GET {KW_IOT_BASE_URL}/last-all (stationType=ALL, idType=USER, id, api_key)
- mock 모드: 키 없이 구동 — 시간 기반 stateless 합성(app/mock.py). 위험단계를 넘나들어
  경보·라이브 대시보드를 시연. 서버리스(Vercel)와 동일 합성을 공유.

반환: 정규화된 reading dict 리스트
  {sn, name, kind, measured_at(datetime), temperature, humidity, feels_like, co2, pm10, pm25, voc}
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx

from . import mock
from .config import settings
from .feels import kma_feels_like

# 시리얼 접두(숫자 꼬리 제외)로 모델 식별. 알려진 모델은 친화 라벨, 그 외는 접두 코드 표기.
MODEL_LABELS = {
    "IST4W": "체감온도계 (IST4W)",
    "IVTKW": "실내공기질 (IVTKW)",
    "IVT": "실내공기질 (IVT)",
    "OST": "실외대기 (OST)",
}


def model_from_serial(serial: str) -> str:
    code = re.sub(r"\d+$", "", serial or "").rstrip("-_") or (serial or "")
    return MODEL_LABELS.get(code, code or "미상 모델")


def _apparent_temp(t: float | None, rh: float | None) -> float | None:
    """senseTemp 미제공 시 폴백 — 기상청 공식 체감온도."""
    f = kma_feels_like(t, rh)
    return f if f is not None else (float(t) if t is not None else None)


async def fetch_last_all() -> list[dict]:
    """케이웨더 IoT last-all 실시간 측정값."""
    if settings.USE_MOCK or not (settings.KW_IOT_API_KEY and settings.KW_IOT_USER_ID):
        return mock.last_all_at(mock.now_kst())
    return await fetch_real_readings()


def _clean(v: str | None) -> str:
    """env 주입 시 섞일 수 있는 BOM/CRLF/공백 제거(잘못된 키로 인한 401 방지)."""
    return (v or "").lstrip("﻿").strip()


def resolve_creds(api_key: str | None = None, user_id: str | None = None) -> tuple[str, str]:
    """우선순위: 인자(계정별) > 관리자 입력(DB appsettings) > 플랫폼 env."""
    from . import appsettings
    key = api_key or appsettings.get("KW_IOT_API_KEY") or settings.KW_IOT_API_KEY
    uid = user_id or appsettings.get("KW_IOT_USER_ID") or settings.KW_IOT_USER_ID
    return _clean(key), _clean(uid)


def has_credentials(api_key: str | None = None, user_id: str | None = None) -> bool:
    k, u = resolve_creds(api_key, user_id)
    return bool(k and u)


async def fetch_real_readings(api_key: str | None = None, user_id: str | None = None) -> list[dict]:
    """케이웨더 IoT last-all 실호출(USE_MOCK 무관) — 계정의 모든 기기 최신 측정값.

    반환 dict 의 measured_at 은 응답의 date(KST 'YYYYMMDDHHMM') 파싱값.
    """
    key, uid = resolve_creds(api_key, user_id)
    if not (key and uid):
        raise RuntimeError("AIR365 자격증명(API 키 / 계정 ID) 미설정")
    url = f"{_clean(settings.KW_IOT_BASE_URL)}/last-all"
    params = {"stationType": "ALL", "idType": "USER", "id": uid, "api_key": key}
    async with httpx.AsyncClient(timeout=15.0, verify=settings.KW_IOT_VERIFY_SSL) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        j = r.json()
    if str(j.get("error")) != "0":
        raise RuntimeError(j.get("message") or "KW IoT error")
    result = j.get("result", {}) or {}
    out: list[dict] = []
    for kind, key, dtype in (("indoor", "iaqList", "실내공기질(IAQ)"), ("outdoor", "oaqList", "실외대기(OAQ)")):
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
            metrics = [m for m, v in (("체감온도", feels), ("온도", temp), ("습도", humi),
                       ("CO2", it.get("co2")), ("미세먼지", it.get("pm10")),
                       ("초미세먼지", it.get("pm25")), ("VOC", it.get("voc"))) if v is not None]
            out.append({
                "sn": sn, "name": it.get("stationName") or sn, "kind": kind,
                "model": model_from_serial(sn),
                "device_type": dtype, "metrics": metrics, "measured_at": mt, "raw_date": ts,
                "temperature": temp, "humidity": humi, "feels_like": feels,
                "co2": it.get("co2"), "pm10": it.get("pm10"), "pm25": it.get("pm25"), "voc": it.get("voc"),
            })
    return out


async def probe(api_key: str | None = None, user_id: str | None = None) -> dict:
    """연결 점검 — 계정에서 보이는 시리얼·최신시각을 요약(기기 관리 페이지용)."""
    key, uid = resolve_creds(api_key, user_id)
    if not (key and uid):
        return {"configured": False, "reachable": False, "account": uid or None,
                "seen": [], "error": "자격증명 미설정"}
    try:
        readings = await fetch_real_readings(key, uid)
    except Exception as e:  # noqa: BLE001
        return {"configured": True, "reachable": False, "account": uid,
                "seen": [], "error": str(e)}
    seen = [{"serial": r["sn"], "kind": r["kind"], "feels_like": r["feels_like"],
             "temperature": r["temperature"], "humidity": r["humidity"],
             "date": r.get("raw_date")} for r in readings]
    return {"configured": True, "reachable": True, "account": settings.KW_IOT_USER_ID, "seen": seen}
