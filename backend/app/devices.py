"""기기 레지스트리 — 계정(테넌트)별 DB 저장. STS Device 모델 대응.

IoT 트랙은 기기 시리얼로 케이웨더 API에서 값을 조회한다. 데모 계정은 데모 기기(source=demo),
실계정은 자신이 등록한 케이웨더 시리얼(source=kweather)을 관리한다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Device, Tenant


def list_for(db: Session, tenant: Tenant) -> list[Device]:
    return list(db.scalars(
        select(Device).where(Device.tenant_id == tenant.id).order_by(Device.source, Device.serial)))


def serials_for(db: Session, tenant: Tenant) -> list[str]:
    return [d.serial for d in list_for(db, tenant)]


def get(db: Session, tenant: Tenant, serial: str) -> Device | None:
    return db.scalar(select(Device).where(Device.tenant_id == tenant.id, Device.serial == serial))


def add(db: Session, tenant: Tenant, serial: str, name: str | None, kind: str,
        location: str | None, site_id: int | None = None, device_type: str | None = None,
        source: str = "kweather") -> Device:
    serial = (serial or "").strip()
    if not serial:
        raise ValueError("시리얼 번호가 필요합니다.")
    existing = get(db, tenant, serial)
    if existing:
        existing.name = (name or existing.name)
        existing.kind = "indoor" if kind == "indoor" else "outdoor"
        existing.location = location or existing.location
        if site_id is not None:
            existing.site_id = site_id
        if device_type:
            existing.device_type = device_type
        db.commit()
        return existing
    dev = Device(tenant_id=tenant.id, serial=serial, name=(name or serial),
                 kind=("indoor" if kind == "indoor" else "outdoor"),
                 location=location, site_id=site_id, device_type=device_type, source=source)
    db.add(dev)
    db.commit()
    db.refresh(dev)
    return dev


def assign_site(db: Session, tenant: Tenant, serial: str, site_id: int | None) -> bool:
    dev = get(db, tenant, serial)
    if dev is None:
        return False
    dev.site_id = site_id
    db.commit()
    return True


def remove(db: Session, tenant: Tenant, serial: str) -> bool:
    dev = get(db, tenant, serial)
    if dev is None or dev.source == "demo":   # 데모 기기는 삭제 불가
        return False
    db.delete(dev)
    db.commit()
    return True


def as_dict(d: Device) -> dict:
    return {"device_sn": d.serial, "serial": d.serial, "name": d.name, "location_name": d.name,
            "kind": d.kind, "device_type": d.device_type, "location": d.location,
            "site_id": d.site_id, "source": d.source}
