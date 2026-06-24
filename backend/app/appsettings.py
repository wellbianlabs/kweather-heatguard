"""런타임 설정(서버 DB) — 관리자 입력 API 키 등. 비밀값은 crypto로 암호화 저장.

인메모리 캐시(_cache)에 암호화된 원문을 담고, get() 시 복호화. 시작 시 load(), 저장 시 갱신.
STS appsettings 대응(코드 재배포 없이 키 변경).
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto
from .database import SessionLocal, db_enabled
from .models import AppSetting

log = logging.getLogger("heatguard.appsettings")
_cache: dict[str, str | None] = {}
SECRET_KEYS = {"KW_IOT_API_KEY", "KMA_API_KEY"}   # 암호화 대상


def load() -> None:
    if not db_enabled():
        return
    try:
        with SessionLocal() as db:
            _cache.clear()
            for r in db.scalars(select(AppSetting)):
                _cache[r.key] = r.value
    except Exception as e:  # noqa: BLE001
        log.warning("appsettings load 실패: %s", e)


def get(key: str) -> str | None:
    """저장값 복호화 반환(평문은 그대로)."""
    v = _cache.get(key)
    return crypto.decrypt(v) if v else v


def set_value(db: Session, key: str, value: str | None) -> None:
    stored = crypto.encrypt(value) if (value and key in SECRET_KEYS) else value
    row = db.get(AppSetting, key)
    if row:
        row.value = stored
    else:
        db.add(AppSetting(key=key, value=stored))
    db.commit()
    _cache[key] = stored
