"""저장 데이터 암호화 — AIR365 API 키 등 민감 자격증명의 DB 평문 저장 방지.

Fernet(AES128-CBC + HMAC) 대칭 암호화. 키는 env APP_ENC_KEY(임의 패스프레이즈)에서
SHA-256으로 파생한 Fernet 키를 사용. 저장값은 'enc:' 접두로 구분(레거시 평문 호환).
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

log = logging.getLogger("heatguard.crypto")
_PREFIX = "enc:"


def _fernet() -> Fernet | None:
    sec = (settings.APP_ENC_KEY or "").strip()
    if not sec:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(sec.encode("utf-8")).digest())
    return Fernet(key)


def encrypt(plain: str | None) -> str | None:
    if not plain:
        return plain
    f = _fernet()
    if f is None:
        log.warning("APP_ENC_KEY 미설정 — 평문 저장(운영 시 키 설정 권장)")
        return plain
    return _PREFIX + f.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt(stored: str | None) -> str | None:
    if not stored:
        return stored
    if not stored.startswith(_PREFIX):
        return stored  # 레거시 평문(키 설정 전 저장분) 호환
    f = _fernet()
    if f is None:
        return None
    try:
        return f.decrypt(stored[len(_PREFIX):].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        log.error("자격증명 복호화 실패(키 불일치)")
        return None
