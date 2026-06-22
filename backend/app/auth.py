"""인증 — 회원가입/로그인/내 정보. 계정=테넌트(데이터 격리), 토큰=api_key(STS 방식)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .deps import get_db, get_tenant
from .models import Tenant
from .security import hash_password, new_api_key, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _out(t: Tenant) -> dict:
    return {"api_key": t.api_key, "email": t.email, "name": t.name,
            "is_demo": t.is_demo, "is_admin": t.is_admin}


@router.post("/signup")
def signup(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    email = (payload.get("email") or "").strip().lower()
    pw = payload.get("password") or ""
    name = (payload.get("name") or "").strip() or None
    if not email or "@" not in email:
        raise HTTPException(400, "유효한 이메일을 입력하세요.")
    if len(pw) < 6:
        raise HTTPException(400, "비밀번호는 6자 이상이어야 합니다.")
    if db.scalar(select(Tenant).where(Tenant.email == email)):
        raise HTTPException(409, "이미 가입된 이메일입니다.")
    t = Tenant(email=email, password_hash=hash_password(pw), api_key=new_api_key(),
               name=name or email.split("@")[0], is_demo=False, is_admin=False)
    db.add(t)
    db.commit()
    db.refresh(t)
    return _out(t)


@router.post("/login")
def login(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    email = (payload.get("email") or "").strip().lower()
    pw = payload.get("password") or ""
    t = db.scalar(select(Tenant).where(Tenant.email == email))
    if t is None or not verify_password(pw, t.password_hash):
        raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다.")
    return _out(t)


@router.get("/me")
def me(tenant: Tenant = Depends(get_tenant)) -> dict:
    return _out(tenant)
