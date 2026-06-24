"""인증 — 회원가입/로그인/내 정보. 계정=테넌트(데이터 격리), 토큰=api_key(STS 방식)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import billing
from .config import settings
from .deps import get_db, get_tenant
from .models import Tenant
from .security import hash_password, new_api_key, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def is_admin_email(email: str | None) -> bool:
    if not email:
        return False
    admins = {e.strip().lower() for e in (settings.ADMIN_EMAILS or "").split(",") if e.strip()}
    return email.lower() in admins


def _out(t: Tenant) -> dict:
    return {"api_key": t.api_key, "email": t.email, "name": t.name,
            "is_demo": t.is_demo, "is_admin": t.is_admin,
            "plan": t.plan, "plan_name": (billing.get_plan(t.plan) or {}).get("name"),
            "sub_status": t.sub_status,
            "plan_renews_at": t.plan_renews_at.isoformat() if t.plan_renews_at else None}


@router.get("/plans")
def plans() -> dict:
    return billing.catalog()


@router.post("/signup")
def signup(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    email = (payload.get("email") or "").strip().lower()
    pw = payload.get("password") or ""
    name = (payload.get("name") or "").strip() or None
    plan_code = payload.get("plan")
    plan = billing.get_plan(plan_code)
    if not email or "@" not in email:
        raise HTTPException(400, "유효한 이메일을 입력하세요.")
    if len(pw) < 6:
        raise HTTPException(400, "비밀번호는 6자 이상이어야 합니다.")
    if plan is None:
        raise HTTPException(400, "구독 상품(월간/연간)을 선택하세요.")
    if db.scalar(select(Tenant).where(Tenant.email == email)):
        raise HTTPException(409, "이미 가입된 이메일입니다.")
    # 실제 결제는 PSP 연동 자리(데모). 가입과 동시에 구독 활성으로 표기.
    now = datetime.now(timezone.utc)
    t = Tenant(email=email, password_hash=hash_password(pw), api_key=new_api_key(),
               name=name or email.split("@")[0], is_demo=False, is_admin=is_admin_email(email),
               plan=plan["code"], sub_status="active",
               plan_started_at=now, plan_renews_at=now + timedelta(days=plan["cycle_days"]))
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
    admin = is_admin_email(email)
    if t.is_admin != admin:   # ADMIN_EMAILS 변경분 반영
        t.is_admin = admin
        db.commit()
    return _out(t)


@router.get("/me")
def me(tenant: Tenant = Depends(get_tenant)) -> dict:
    return _out(tenant)
