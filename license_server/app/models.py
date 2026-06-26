from __future__ import annotations

from datetime import datetime
from typing import Optional
from app.utils.clock import now

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    JSON,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    status: Mapped[str] = mapped_column(String(16), default="active", index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    device_limit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    session_limit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    offline_grace_hours: Mapped[int] = mapped_column(Integer, default=720, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    device: Mapped[Optional["Device"]] = relationship(back_populates="license", uselist=False)
    sessions: Mapped[list["Session"]] = relationship(back_populates="license")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="license")

    owner_agent: Mapped[Optional["AdminUser"]] = relationship(back_populates="licenses")

    owner_agent_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("admin_users.id"), index=True, nullable=True)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    license_id: Mapped[str] = mapped_column(String(36), ForeignKey("licenses.id"), nullable=False)

    # IMPORTANT (business rule):
    # - 1 license_key chỉ được bind vào 1 máy (fingerprint) duy nhất.
    # - Nhưng 1 máy có thể dùng N license_key khác nhau (change key) trên cùng máy.
    # Do đó fingerprint_hash KHÔNG được unique toàn cục; chỉ cần index để tra cứu nhanh.
    fingerprint_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    device_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    license: Mapped["License"] = relationship(back_populates="device")
    sessions: Mapped[list["Session"]] = relationship(back_populates="device")

    __table_args__ = (
        UniqueConstraint("license_id", name="uq_devices_license_id"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    license_id: Mapped[str] = mapped_column(String(36), ForeignKey("licenses.id"), index=True, nullable=False)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("devices.id"), index=True, nullable=False)

    status: Mapped[str] = mapped_column(String(16), default="active", index=True, nullable=False)

    issued_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    license: Mapped["License"] = relationship(back_populates="sessions")
    device: Mapped["Device"] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_sessions_license_status", "license_id", "status"),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    license_id: Mapped[str] = mapped_column(String(36), ForeignKey("licenses.id"), index=True, nullable=False)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("devices.id"), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), index=True, nullable=False)

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True, nullable=False)

    issued_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    license: Mapped["License"] = relationship(back_populates="refresh_tokens")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    license_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, nullable=True)

    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # roles in DB: "agent" (SUPER admin vẫn dùng settings)
    role: Mapped[str] = mapped_column(String(16), default="agent", index=True, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Giới hạn số license active & chưa hết hạn mà agent được quản lý cùng lúc.
    # 0 = không giới hạn (unlimited)
    max_active_licenses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    licenses: Mapped[list["License"]] = relationship(back_populates="owner_agent")
