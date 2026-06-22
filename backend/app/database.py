"""DB 엔진/세션 — STS Supabase 재사용(heatguard 스키마). DATABASE_URL 미설정 시 비활성.

서버리스(Vercel) 환경이라 NullPool(요청마다 새 커넥션, pgbouncer 트랜잭션 풀러와 안전).
모델은 schema='heatguard' 로 명시 → search_path 의존 없이 풀러에서 안전.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from .config import settings

Base = declarative_base()
engine = None
SessionLocal = None

if settings.DATABASE_URL:
    engine = create_engine(settings.DATABASE_URL, poolclass=NullPool, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def db_enabled() -> bool:
    return SessionLocal is not None
