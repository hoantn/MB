from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4
from app.utils.clock import now as clock_now

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text, select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .settings import settings
from .db import engine, get_db
from .models import Base, License, Device, Session as DbSession, AuditLog, RefreshToken
from .schemas import (
    ActivateRequest, ActivateResponse,
    RefreshRequest, RefreshResponse,
    HeartbeatRequest, HeartbeatResponse
)
from .security import HashingConfig, validate_key_format, hash_license_key, hash_fingerprint
from .tokens import TokenConfig, issue_refresh_token, hash_refresh_token
from .entitlements import build_entitlements_payload, sign_entitlements
from .admin.routes import router as admin_router

app = FastAPI(title="License Server (DEV)", version="0.4.1")

# Admin Web (HTMX)
_secret = (settings.admin_session_secret or settings.license_key_pepper or "CHANGE_ME_NOW")
app.add_middleware(SessionMiddleware, secret_key=_secret)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(admin_router)


HASH_CFG = HashingConfig(pepper=settings.license_key_pepper)
TOKEN_CFG = TokenConfig(pepper=settings.license_key_pepper)


@app.on_event("startup")
def _startup():
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "ok": True,
        "service": "license-api-dev",
        "env": settings.app_env,
        "db_ok": db_ok,
        "db": f"sqlite:///{settings.sqlite_path}",
    }


def _audit(db: Session, event_type: str, payload: dict, license_id=None, device_id=None, session_id=None):
    db.add(AuditLog(
        license_id=license_id,
        device_id=device_id,
        session_id=session_id,
        event_type=event_type,
        payload=payload or {},
    ))


def _require_active_license(db: Session, lic: License) -> None:
    now = clock_now()
    if lic.status != "active":
        raise HTTPException(status_code=403, detail="LICENSE_BLOCKED")
    if lic.expires_at <= now:
        raise HTTPException(status_code=403, detail="LICENSE_EXPIRED")


def _kill_active_sessions(db: Session, license_id: str, now: datetime):
    db.execute(
        update(DbSession)
        .where(DbSession.license_id == license_id, DbSession.status == "active")
        .values(status="killed", last_heartbeat_at=now)
    )


def _revoke_refresh_tokens_for_license(db: Session, license_id: str, now: datetime):
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.license_id == license_id, RefreshToken.status == "active")
        .values(status="revoked", revoked_at=now)
    )


def _build_and_sign_entitlements(lic: License, dev: Device, session_id: str) -> tuple[str, str, str]:
    payload = build_entitlements_payload(
        license_id=lic.id,
        device_id=dev.id,
        session_id=session_id,
        status="active",
        expires_at=lic.expires_at,
        offline_grace_hours=lic.offline_grace_hours,
        features={
            # DEV default – sau này anh map theo gói tính năng
            "apply": True,
            "suggest": True,
            "special": True,
        },
        issued_at=clock_now(),
    )
    signed = sign_entitlements(payload)
    return signed.cbor_b64, signed.sig_b64, signed.pub_b64


@app.post("/v1/activate", response_model=ActivateResponse)
def activate(req: ActivateRequest, request: Request, db: Session = Depends(get_db)):
    key = (req.key or "").strip()
    if not validate_key_format(key):
        _audit(db, "activate_invalid_key_format", {"key_len": len(key)})
        db.commit()
        raise HTTPException(status_code=400, detail="INVALID_KEY_FORMAT")

    key_hash = hash_license_key(key, HASH_CFG)
    lic = db.execute(select(License).where(License.key_hash == key_hash)).scalar_one_or_none()

    if lic is None:
        _audit(db, "activate_key_not_found", {"key_hash_prefix": key_hash[:8]})
        db.commit()
        raise HTTPException(status_code=401, detail="KEY_NOT_FOUND")

    try:
        _require_active_license(db, lic)
    except HTTPException as e:
        _audit(db, "activate_license_denied", {"detail": e.detail}, license_id=lic.id)
        db.commit()
        raise

    now = clock_now()
    fp_raw = (req.fingerprint or "").strip()
    fp_hash = hash_fingerprint(fp_raw, HASH_CFG)

    # BUSINESS RULE:
    # - 1 key chỉ bind 1 máy (fingerprint) duy nhất.
    # - 1 máy có thể dùng N key khác nhau.
    # => KHÔNG được chặn "fingerprint đang dùng ở license khác".
    # Chỉ cần: nếu license đã bind fingerprint khác thì chặn.

    dev_existing = db.execute(select(Device).where(Device.license_id == lic.id)).scalar_one_or_none()
    if dev_existing is not None:
        # license đã bind rồi -> chỉ cho phép kích hoạt lại trên đúng fingerprint
        if dev_existing.fingerprint_hash != fp_hash:
            _audit(
                db,
                "activate_denied_other_device",
                {"existing_device_id": dev_existing.id},
                license_id=lic.id,
                device_id=dev_existing.id,
            )
            db.commit()
            raise HTTPException(status_code=409, detail="LICENSE_ALREADY_BOUND_TO_OTHER_DEVICE")

        dev = dev_existing
        dev.last_seen_at = now
        if req.device_name:
            dev.device_name = req.device_name
        if dev.status != "active":
            dev.status = "active"

    else:
        # license chưa bind -> tạo device mới
        dev = Device(
            id=str(uuid4()),
            license_id=lic.id,
            fingerprint_hash=fp_hash,
            device_name=req.device_name,
            status="active",
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(dev)

        # tránh race-condition (2 request activate đồng thời): unique(license_id)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            dev_existing2 = db.execute(select(Device).where(Device.license_id == lic.id)).scalar_one_or_none()
            if dev_existing2 is None:
                raise
            if dev_existing2.fingerprint_hash != fp_hash:
                _audit(
                    db,
                    "activate_denied_other_device",
                    {"existing_device_id": dev_existing2.id},
                    license_id=lic.id,
                    device_id=dev_existing2.id,
                )
                db.commit()
                raise HTTPException(status_code=409, detail="LICENSE_ALREADY_BOUND_TO_OTHER_DEVICE")

            dev = dev_existing2
            dev.last_seen_at = now
            if req.device_name:
                dev.device_name = req.device_name
            if dev.status != "active":
                dev.status = "active"

        _audit(db, "device_bound", {"device_name": req.device_name}, license_id=lic.id, device_id=dev.id)

    _kill_active_sessions(db, lic.id, now)
    _revoke_refresh_tokens_for_license(db, lic.id, now)

    session_id = str(uuid4())
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None

    s = DbSession(
        id=session_id,
        license_id=lic.id,
        device_id=dev.id,
        status="active",
        issued_at=now,
        last_heartbeat_at=now,
        ip=ip,
        user_agent=ua,
    )
    db.add(s)

    refresh_token = issue_refresh_token()
    rt_hash = hash_refresh_token(refresh_token, TOKEN_CFG)
    db.add(RefreshToken(
        license_id=lic.id,
        device_id=dev.id,
        session_id=session_id,
        token_hash=rt_hash,
        status="active",
        issued_at=now,
        revoked_at=None,
    ))

    ent_cbor_b64, ent_sig_b64, pub_b64 = _build_and_sign_entitlements(lic, dev, session_id)

    _audit(db, "activate_ok", {"ip": ip, "ua": ua, "app_version": req.app_version}, license_id=lic.id, device_id=dev.id, session_id=session_id)
    db.commit()

    return ActivateResponse(
        ok=True,
        license_id=lic.id,
        device_id=dev.id,
        session_id=session_id,
        expires_at=lic.expires_at,
        refresh_token=refresh_token,
        entitlements_cbor_b64=ent_cbor_b64,
        entitlements_sig_b64=ent_sig_b64,
        signing_pub_b64=pub_b64,
    )


@app.post("/v1/refresh", response_model=RefreshResponse)
def refresh(req: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    now = clock_now()
    session_id = (req.session_id or "").strip()
    token = (req.refresh_token or "").strip()

    if not session_id or not token:
        raise HTTPException(status_code=400, detail="MISSING_FIELDS")

    s = db.execute(select(DbSession).where(DbSession.id == session_id)).scalar_one_or_none()
    if s is None:
        _audit(db, "refresh_denied_session", {"session_id": session_id}, session_id=session_id)
        db.commit()
        raise HTTPException(status_code=403, detail="SESSION_INVALID")

    # nếu session bị kill trước đó nhưng license đã gia hạn lại -> revive
    if s.status != "active":
        lic = db.execute(select(License).where(License.id == s.license_id)).scalar_one_or_none()
        if lic is not None and lic.status == "active" and lic.expires_at > now:
            s.status = "active"
            _audit(db, "refresh_session_revived", {}, license_id=lic.id, session_id=session_id)
            db.flush()
        else:
            _audit(db, "refresh_denied_session", {"status": s.status}, session_id=session_id)
            db.commit()
            raise HTTPException(status_code=403, detail="SESSION_INVALID")

    lic = db.execute(select(License).where(License.id == s.license_id)).scalar_one_or_none()
    if lic is None:
        _audit(db, "refresh_denied_license_missing", {"license_id": s.license_id}, session_id=session_id)
        db.commit()
        raise HTTPException(status_code=403, detail="LICENSE_INVALID")

    try:
        _require_active_license(db, lic)
    except HTTPException as e:
        _audit(db, "refresh_denied_license", {"detail": e.detail}, license_id=lic.id, session_id=session_id)
        db.commit()
        raise

    token_hash = hash_refresh_token(token, TOKEN_CFG)
    rt = db.execute(
        select(RefreshToken).where(
            RefreshToken.session_id == session_id,
            RefreshToken.license_id == lic.id,
            RefreshToken.token_hash == token_hash,
            RefreshToken.status == "active",
        )
    ).scalar_one_or_none()

    if rt is None:
        _audit(db, "refresh_denied_bad_token", {}, license_id=lic.id, session_id=session_id)
        db.commit()
        raise HTTPException(status_code=403, detail="REFRESH_TOKEN_INVALID")

    # rotate
    rt.status = "revoked"
    rt.revoked_at = now

    new_token = issue_refresh_token()
    new_hash = hash_refresh_token(new_token, TOKEN_CFG)
    db.add(RefreshToken(
        license_id=lic.id,
        device_id=s.device_id,
        session_id=session_id,
        token_hash=new_hash,
        status="active",
        issued_at=now,
        revoked_at=None,
    ))

    dev = db.execute(select(Device).where(Device.id == s.device_id)).scalar_one()
    ent_cbor_b64, ent_sig_b64, pub_b64 = _build_and_sign_entitlements(lic, dev, session_id)

    _audit(db, "refresh_ok", {"app_version": req.app_version}, license_id=lic.id, device_id=s.device_id, session_id=session_id)
    db.commit()

    return RefreshResponse(
        ok=True,
        license_id=lic.id,
        device_id=s.device_id,
        session_id=session_id,
        expires_at=lic.expires_at,
        refresh_token=new_token,
        entitlements_cbor_b64=ent_cbor_b64,
        entitlements_sig_b64=ent_sig_b64,
        signing_pub_b64=pub_b64,
    )


@app.post("/v1/heartbeat", response_model=HeartbeatResponse)
def heartbeat(req: HeartbeatRequest, request: Request, db: Session = Depends(get_db)):
    now = clock_now()
    session_id = (req.session_id or "").strip()
    device_id = (req.device_id or "").strip()

    if not session_id or not device_id:
        raise HTTPException(status_code=400, detail="MISSING_FIELDS")

    s = db.execute(select(DbSession).where(DbSession.id == session_id)).scalar_one_or_none()
    if s is None:
        _audit(db, "hb_session_missing", {"session_id": session_id}, session_id=session_id)
        db.commit()
        return HeartbeatResponse(ok=True, status="KILL", reason="SESSION_MISSING", server_time=now)

    if s.status != "active":
        # Nếu session bị kill vì hết hạn trước đó, nhưng bây giờ license đã gia hạn lại
        lic = db.execute(select(License).where(License.id == s.license_id)).scalar_one_or_none()
        if (
            s.status == "killed"
            and lic is not None
            and lic.status == "active"
            and lic.expires_at > now
            and s.device_id == device_id  # giữ nếu client đúng UUID
        ):
            s.status = "active"
            s.last_heartbeat_at = now
            _audit(db, "hb_session_revived", {}, license_id=lic.id, device_id=device_id, session_id=session_id)
            db.commit()
            return HeartbeatResponse(ok=True, status="OK", reason=None, server_time=now)

        _audit(db, "hb_session_not_active", {"status": s.status}, license_id=s.license_id, device_id=s.device_id, session_id=session_id)
        db.commit()
        return HeartbeatResponse(ok=True, status="KILL", reason="SESSION_KILLED", server_time=now)

    if s.device_id != device_id:
        _audit(db, "hb_device_mismatch", {"expected": s.device_id, "got": device_id}, license_id=s.license_id, device_id=s.device_id, session_id=session_id)
        s.status = "killed"
        s.last_heartbeat_at = now
        db.commit()
        return HeartbeatResponse(ok=True, status="KILL", reason="DEVICE_MISMATCH", server_time=now)

    lic = db.execute(select(License).where(License.id == s.license_id)).scalar_one_or_none()
    if lic is None:
        s.status = "killed"
        s.last_heartbeat_at = now
        _audit(db, "hb_license_missing", {}, session_id=session_id)
        db.commit()
        return HeartbeatResponse(ok=True, status="KILL", reason="LICENSE_MISSING", server_time=now)

    if lic.status != "active":
        s.status = "killed"
        s.last_heartbeat_at = now
        _audit(db, "hb_license_blocked", {}, license_id=lic.id, device_id=device_id, session_id=session_id)
        db.commit()
        return HeartbeatResponse(ok=True, status="KILL", reason="LICENSE_BLOCKED", server_time=now)

    if lic.expires_at <= now:
        s.status = "killed"
        s.last_heartbeat_at = now
        _audit(db, "hb_license_expired", {"expires_at": lic.expires_at.isoformat()}, license_id=lic.id, device_id=device_id, session_id=session_id)
        db.commit()
        return HeartbeatResponse(ok=True, status="KILL", reason="LICENSE_EXPIRED", server_time=now)

    s.last_heartbeat_at = now
    dev = db.execute(select(Device).where(Device.id == device_id)).scalar_one_or_none()
    if dev:
        dev.last_seen_at = now

    _audit(db, "hb_ok", {"app_version": req.app_version}, license_id=lic.id, device_id=device_id, session_id=session_id)
    db.commit()

    return HeartbeatResponse(ok=True, status="OK", reason=None, server_time=now)
