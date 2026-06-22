"""비밀번호 해싱(pbkdf2, 추가 의존성 없음) + API 토큰 생성 — STS security.py 방식."""
from __future__ import annotations

import base64
import hashlib
import os
import secrets

_ITER = 100_000


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _ITER)
    return f"pbkdf2${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, s, d = stored.split("$")
        salt = base64.b64decode(s)
        expected = base64.b64decode(d)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _ITER)
        return secrets.compare_digest(dk, expected)
    except Exception:  # noqa: BLE001
        return False


def new_api_key() -> str:
    return secrets.token_urlsafe(24)
