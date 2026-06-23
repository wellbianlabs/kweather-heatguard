"""실 IoT 측정 기록(적재) + 시계열 조회.

케이웨더 API에서 읽어온 현재값을 sensor_logs 에 적재(중복은 (tenant,serial,measured_at) 유니크로 무시).
대시보드 폴링/크론이 호출하면 새 측정시각이 들어올 때마다 누적되어 실시간 기록이 된다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto, devices as dev_db, kw_iot
from .models import SensorLog, Tenant


async def ingest_for_tenant(db: Session, tenant: Tenant) -> dict:
    """테넌트의 등록 기기 현재값을 케이웨더에서 읽어 적재. 반환: 신규 적재 수."""
    serials = set(dev_db.serials_for(db, tenant))
    if not serials:
        return {"fetched": 0, "stored": 0, "devices": []}
    try:
        readings = await kw_iot.fetch_real_readings(crypto.decrypt(tenant.kw_api_key), tenant.kw_user_id)
    except Exception as e:  # noqa: BLE001
        return {"fetched": 0, "stored": 0, "error": str(e)}
    stored = 0
    seen = []
    for r in readings:
        sn = r["sn"]
        if sn not in serials:
            continue
        mt = r.get("measured_at")
        if not isinstance(mt, datetime):
            continue
        seen.append(sn)
        exists = db.scalar(select(SensorLog.id).where(
            SensorLog.tenant_id == tenant.id, SensorLog.serial == sn, SensorLog.measured_at == mt))
        if exists:
            continue
        db.add(SensorLog(tenant_id=tenant.id, serial=sn, measured_at=mt,
                         temperature=_f(r.get("temperature")), humidity=_f(r.get("humidity")),
                         feels_like=_f(r.get("feels_like"))))
        stored += 1
    if stored:
        db.commit()
    return {"fetched": len(readings), "stored": stored, "devices": sorted(set(seen))}


def _f(v):
    try:
        return float(v) if v is not None else None
    except Exception:  # noqa: BLE001
        return None


def history(db: Session, tenant: Tenant, serial: str, limit: int = 240) -> list[dict]:
    rows = db.scalars(select(SensorLog).where(
        SensorLog.tenant_id == tenant.id, SensorLog.serial == serial)
        .order_by(SensorLog.measured_at.desc()).limit(limit)).all()
    rows = list(reversed(rows))
    return [{"at": r.measured_at.isoformat(), "feels_like": r.feels_like,
             "temperature": r.temperature, "humidity": r.humidity} for r in rows]


def day_logs(db: Session, tenant: Tenant, serial: str, day) -> list[dict]:
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    rows = db.scalars(select(SensorLog).where(
        SensorLog.tenant_id == tenant.id, SensorLog.serial == serial,
        SensorLog.measured_at >= start, SensorLog.measured_at < end)
        .order_by(SensorLog.measured_at)).all()
    return [{"at": r.measured_at.isoformat(), "feels_like": r.feels_like,
             "temperature": r.temperature, "humidity": r.humidity} for r in rows]
