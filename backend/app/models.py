"""ORM 모델 — heatguard 스키마(STS Supabase 재사용). 계정(Tenant)·기기(Device)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint, func
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
    kw_user_id: Mapped[str | None] = mapped_column(String)           # 계정별 AIR365 계정 ID
    kw_api_key: Mapped[str | None] = mapped_column(String)           # 계정별 AIR365 API 키
    plan_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_renews_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pg_provider: Mapped[str | None] = mapped_column(String)            # mobilians 등
    billing_key: Mapped[str | None] = mapped_column(String)            # 정기결제 빌링키(암호화 저장)
    card_name: Mapped[str | None] = mapped_column(String)              # 카드 표시명(끝 4자리 등)
    next_billing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    devices: Mapped[list["Device"]] = relationship(back_populates="tenant")
    sites: Mapped[list["Site"]] = relationship(back_populates="tenant")


class AppSetting(Base):
    """런타임 설정(서버 DB) — 관리자 페이지에서 입력하는 API 키 등. STS appsettings 대응."""
    __tablename__ = "app_settings"
    __table_args__ = SCHEMA

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str | None] = mapped_column(String)   # 비밀값은 암호화 저장('enc:')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SensorLog(Base):
    """실 IoT 측정 기록 — 케이웨더 API에서 읽어온 값을 적재(실시간 기록·시계열 표출)."""
    __tablename__ = "sensor_logs"
    __table_args__ = (UniqueConstraint("tenant_id", "serial", "measured_at", name="uq_sensorlog"), SCHEMA)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("heatguard.tenants.id", ondelete="CASCADE"), nullable=False)
    serial: Mapped[str] = mapped_column(String, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature: Mapped[float | None] = mapped_column(Float)
    humidity: Mapped[float | None] = mapped_column(Float)
    feels_like: Mapped[float | None] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    """결제 이력(감사 로그) — 정기결제·단건 공통."""
    __tablename__ = "payments"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("heatguard.tenants.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String, default="mobilians", nullable=False)
    plan: Mapped[str | None] = mapped_column(String)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    method: Mapped[str | None] = mapped_column(String)
    pg_tid: Mapped[str | None] = mapped_column(String)
    message: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Site(Base):
    """사업장 — 계정 아래, 기기 위의 계층(여러 사업장에 다종·다수 기기 설치)."""
    __tablename__ = "sites"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("heatguard.tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str | None] = mapped_column(String)   # 지역(수도권/영남 등) — 대규모 그룹핑
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
    kind: Mapped[str] = mapped_column(String, default="outdoor", nullable=False)  # indoor | outdoor (실내/실외)
    model: Mapped[str | None] = mapped_column(String)         # 모델명(5종 이상) — 시리얼/AIR365 기준
    device_type: Mapped[str | None] = mapped_column(String)   # AIR365 분류(IAQ/OAQ)
    location: Mapped[str | None] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, default="kweather", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="devices")
    site: Mapped["Site"] = relationship(back_populates="devices")
