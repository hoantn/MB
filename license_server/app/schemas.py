from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class ActivateRequest(BaseModel):
    key: str = Field(..., description="15-char A-Za-z0-9 activation key")
    fingerprint: str = Field(..., min_length=6, description="device fingerprint (raw client string)")
    device_name: str | None = Field(default=None, max_length=128)
    app_version: str | None = Field(default=None, max_length=64)


class ActivateResponse(BaseModel):
    ok: bool
    license_id: str
    device_id: str
    session_id: str
    expires_at: datetime
    refresh_token: str

    # Signed entitlements (CBOR + Ed25519)
    entitlements_cbor_b64: str
    entitlements_sig_b64: str
    signing_pub_b64: str


class RefreshRequest(BaseModel):
    session_id: str
    refresh_token: str
    app_version: str | None = Field(default=None, max_length=64)


class RefreshResponse(BaseModel):
    ok: bool
    license_id: str
    device_id: str
    session_id: str
    expires_at: datetime
    refresh_token: str

    entitlements_cbor_b64: str
    entitlements_sig_b64: str
    signing_pub_b64: str


class HeartbeatRequest(BaseModel):
    session_id: str
    device_id: str
    app_version: str | None = Field(default=None, max_length=64)
    client_time: str | None = None
    uptime: float | None = None


class HeartbeatResponse(BaseModel):
    ok: bool
    status: str  # OK / KILL
    reason: str | None = None
    server_time: datetime
