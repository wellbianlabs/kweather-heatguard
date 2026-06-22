"""ORM 모델 — heatguard 스키마(STS Supabase 재사용). 계정(Tenant)·기기(Device)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

SCHEMA = {"schema": "heatguard"}


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str | None] = mapped_column(String, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String)
    api_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    plan: Mapped[str | None] = mapped_column(String)                 # monthly | annual
    sub_status: Mapped[str] = mapped_column(String, default="none")  # active | demo | none | canceled
    plan_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_renews_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    devices: Mapped[list["Device"]] = relationship(back_populates="tenant")
    sites: Mapped[list["Site"]] = relationship(back_populates="tenant")


class Site(Base):
    """사업장 — 계정 아래, 기기 위의 계층(여러 사업장에 다종·다수 기기 설치)."""
    __tablename__ = "sites"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("heatguard.tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="sites")
    devices: Mapped[list["Device"]] = relationship(back_populates="site")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("tenant_id", "serial", name="uq_devices_tenant_serial"), SCHEMA)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("heatguard.tenants.id", ondelete="CASCADE"), nullable=False)
    site_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("heatguard.sites.id", ondelete="SET NULL"))
    serial: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="outdoor", nullable=False)
    device_type: Mapped[str | None] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, default="kweather", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="devices")
    site: Mapped["Site"] = relationship(back_populates="devices")
