"""사업장(Site) 레지스트리 — 계정 아래 사업장 관리(여러 사업장에 다종·다수 기기)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Device, Site, Tenant


def list_for(db: Session, tenant: Tenant) -> list[Site]:
    return list(db.scalars(select(Site).where(Site.tenant_id == tenant.id).order_by(Site.id)))


def device_counts(db: Session, tenant: Tenant) -> dict[int, int]:
    rows = db.execute(
        select(Device.site_id, func.count(Device.id))
        .where(Device.tenant_id == tenant.id, Device.site_id.isnot(None))
        .group_by(Device.site_id)
    ).all()
    return {sid: n for sid, n in rows}


def get(db: Session, tenant: Tenant, site_id: int) -> Site | None:
    return db.scalar(select(Site).where(Site.id == site_id, Site.tenant_id == tenant.id))


def add(db: Session, tenant: Tenant, name: str, address: str | None, region: str | None = None) -> Site:
    name = (name or "").strip()
    if not name:
        raise ValueError("사업장 이름이 필요합니다.")
    s = Site(tenant_id=tenant.id, name=name, address=(address or None), region=(region or None))
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def regions(db: Session, tenant: Tenant) -> list[str]:
    rows = db.scalars(select(Site.region).where(Site.tenant_id == tenant.id, Site.region.isnot(None)).distinct())
    return sorted({r for r in rows if r})


def remove(db: Session, tenant: Tenant, site_id: int) -> bool:
    s = get(db, tenant, site_id)
    if s is None:
        return False
    db.delete(s)   # devices.site_id → SET NULL (미배정으로)
    db.commit()
    return True


def as_dict(s: Site, count: int = 0) -> dict:
    return {"id": s.id, "name": s.name, "region": s.region, "address": s.address, "device_count": count}
