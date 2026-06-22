"""기기 레지스트리 — 계정(테넌트)별 DB 저장. STS Device 모델 대응.

IoT 트랙은 기기 시리얼로 케이웨더 API에서 값을 조회한다. 데모 계정은 데모 기기(source=demo),
실계정은 자신이 등록한 케이웨더 시리얼(source=kweather)을 관리한다.
"""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import Device, Site, Tenant


def list_for(db: Session, tenant: Tenant) -> list[Device]:
    return list(db.scalars(
        select(Device).where(Device.tenant_id == tenant.id).order_by(Device.source, Device.serial)))


def serials_for(db: Session, tenant: Tenant) -> list[str]:
    return [d.serial for d in list_for(db, tenant)]


def _filtered(tenant: Tenant, site_id=None, region=None, kind=None, model=None, q=None, unassigned=False):
    stmt = select(Device).where(Device.tenant_id == tenant.id)
    if unassigned:
        stmt = stmt.where(Device.site_id.is_(None))
    elif site_id:
        stmt = stmt.where(Device.site_id == int(site_id))
    if region:
        stmt = stmt.join(Site, Site.id == Device.site_id).where(Site.region == region)
    if kind:
        stmt = stmt.where(Device.kind == kind)
    if model:
        stmt = stmt.where(Device.model == model)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Device.serial.ilike(like), Device.name.ilike(like)))
    return stmt


def query(db: Session, tenant: Tenant, *, page=1, page_size=50, site_id=None, region=None,
          kind=None, model=None, q=None, unassigned=False) -> dict:
    """대규모 목록 — 필터 + 페이지네이션(서버측). 수천 대도 페이지 단위로만 조회."""
    stmt = _filtered(tenant, site_id, region, kind, model, q, unassigned)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = max(1, int(page)); page_size = min(200, max(1, int(page_size)))
    rows = db.scalars(stmt.order_by(Device.serial).offset((page - 1) * page_size).limit(page_size)).all()
    return {"devices": [as_dict(d) for d in rows], "total": total, "page": page,
            "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}


def summary(db: Session, tenant: Tenant) -> dict:
    where = Device.tenant_id == tenant.id
    total = db.scalar(select(func.count(Device.id)).where(where)) or 0
    by_kind = dict(db.execute(select(Device.kind, func.count(Device.id)).where(where).group_by(Device.kind)).all())
    n_sites = db.scalar(select(func.count(Site.id)).where(Site.tenant_id == tenant.id)) or 0
    n_regions = db.scalar(select(func.count(func.distinct(Site.region)))
                          .where(Site.tenant_id == tenant.id, Site.region.isnot(None))) or 0
    unassigned = db.scalar(select(func.count(Device.id)).where(where, Device.site_id.is_(None))) or 0
    model_list = sorted({m for m in db.scalars(
        select(Device.model).where(where, Device.model.isnot(None)).distinct()) if m})
    return {"total": total, "indoor": by_kind.get("indoor", 0), "outdoor": by_kind.get("outdoor", 0),
            "sites": n_sites, "regions": n_regions, "unassigned": unassigned,
            "models": len(model_list), "model_list": model_list}


def get(db: Session, tenant: Tenant, serial: str) -> Device | None:
    return db.scalar(select(Device).where(Device.tenant_id == tenant.id, Device.serial == serial))


def add(db: Session, tenant: Tenant, serial: str, name: str | None, kind: str,
        location: str | None, site_id: int | None = None, device_type: str | None = None,
        source: str = "kweather", model: str | None = None) -> Device:
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
        if model:
            existing.model = model
        db.commit()
        return existing
    dev = Device(tenant_id=tenant.id, serial=serial, name=(name or serial),
                 kind=("indoor" if kind == "indoor" else "outdoor"),
                 location=location, site_id=site_id, device_type=device_type, model=model, source=source)
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
            "kind": d.kind, "model": d.model, "device_type": d.device_type, "location": d.location,
            "site_id": d.site_id, "source": d.source}
