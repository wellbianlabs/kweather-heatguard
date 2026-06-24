"""FastAPI 의존성 — DB 세션, 테넌트 인증(X-API-Key), 데모 쓰기 차단."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal, db_enabled
from .models import Tenant


def get_db():
    if not db_enabled():
        raise HTTPException(503, "데이터베이스가 구성되지 않았습니다(DATABASE_URL).")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_tenant(x_api_key: str | None = Header(None), db: Session = Depends(get_db)) -> Tenant:
    if not x_api_key:
        raise HTTPException(401, "인증이 필요합니다.")
    t = db.scalar(select(Tenant).where(Tenant.api_key == x_api_key.strip()))
    if t is None:
        raise HTTPException(401, "유효하지 않은 인증입니다.")
    return t


def block_demo(tenant: Tenant) -> None:
    if tenant.is_demo:
        raise HTTPException(403, "데모 계정은 읽기 전용입니다.")


def get_admin(tenant: Tenant = Depends(get_tenant)) -> Tenant:
    if not tenant.is_admin:
        raise HTTPException(403, "관리자 전용 페이지입니다.")
    return tenant
