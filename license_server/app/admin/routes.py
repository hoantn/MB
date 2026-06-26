from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta
from uuid import uuid4
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update, func, delete
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, Device, License, RefreshToken, Session as DbSession, AdminUser
from app.security import HashingConfig, hash_license_key
from app.settings import settings
from app.utils.clock import now as now_vn
from app.admin.auth import require_admin, require_super_admin, verify_password, hash_password, verify_password_hash

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/admin", tags=["admin"])

HASH_CFG = HashingConfig(pepper=settings.license_key_pepper)
ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits


def utcnow() -> datetime:
    # Quy ước toàn hệ thống: giờ VN (UTC+7)
    return now_vn()


def days_left(expires_at: datetime | None) -> int | None:
    if expires_at is None:
        return None
    delta = expires_at - utcnow()
    # Round down; negative means expired
    return int(delta.total_seconds() // 86400)

def _is_super(request: Request) -> bool:
    return request.session.get("role") == "super"


def _agent_id(request: Request) -> str | None:
    if request.session.get("role") == "agent":
        return request.session.get("agent_id")
    return None


def _license_stmt_scoped(request: Request):
    stmt = select(License).order_by(License.created_at.desc())
    agent_id = _agent_id(request)
    if agent_id:
        stmt = stmt.where(License.owner_agent_id == agent_id)
    return stmt

def _get_license_scoped(db: Session, request: Request, license_id: str) -> License | None:
    # 1) Lấy license theo id (KHÔNG được gọi lại chính hàm này)
    lic = db.get(License, license_id)
    if not lic:
        return None

    # 2) Xác định quyền
    agent_id = _agent_id(request)
    role = request.session.get("role")

    is_super = (
        request.session.get("is_super")
        or request.session.get("is_root")
        or role in ("super", "admin")
        or (request.session.get("admin") and not agent_id)  # fallback kiểu cũ
    )

    # 3) Admin tổng xem tất cả
    if is_super:
        return lic

    # 4) Đại lý chỉ xem license thuộc về mình
    if agent_id and getattr(lic, "owner_agent_id", None) == agent_id:
        return lic

    return None
    
def _apply_license_filters_python(
    licenses: list,
    *,
    q: str,
    note: str,
    has_note: str,
    status: str,
    exp: str,
):
    q = (q or "").strip()
    note = (note or "").strip()
    has_note = (has_note or "").strip().lower()
    status = (status or "").strip().lower()
    exp = (exp or "").strip().lower()

    if q:
        qlow = q.lower()
        licenses = [
            l for l in licenses
            if (qlow in (l.id or "").lower())
            or (qlow in ((l.note or "").lower()))
        ]

    if note:
        nlow = note.lower()
        licenses = [l for l in licenses if nlow in ((l.note or "").lower())]

    if has_note in ("1", "true", "yes", "on"):
        licenses = [l for l in licenses if (l.note or "").strip()]

    if status in ("active", "blocked"):
        licenses = [l for l in licenses if (l.status or "").lower() == status]

    if exp:
        now = utcnow()

        # 1) đã hết hạn
        if exp == "expired":
            licenses = [l for l in licenses if l.expires_at and l.expires_at <= now]

        # 2) không thời hạn
        elif exp in ("none", "noexp", "no_exp", "no-exp"):
            licenses = [l for l in licenses if l.expires_at is None]

        # 3) “sắp hết hạn” theo ngày: 1d/3d/7d/30d...
        else:
            # alias nhanh
            if exp == "soon":
                exp = "7d"

            try:
                days = int(exp.replace("d", ""))
            except Exception:
                days = 0

            if days > 0:
                licenses = [
                    l for l in licenses
                    if l.expires_at and l.expires_at > now and (l.expires_at - now) <= timedelta(days=days)
                ]

    return licenses

def _check_agent_limit_before_activating(db: Session, request: Request, *, will_activate: bool) -> str | None:
    """Return an error string if agent exceeds max_active_licenses, else None.
    Rule: limit counts licenses that are active and not expired (expires_at > now).
    """
    agent_id = _agent_id(request)
    if not agent_id:
        return None

    user = db.execute(select(AdminUser).where(AdminUser.id == agent_id)).scalar_one_or_none()
    if not user or not user.is_active:
        return "AGENT_DISABLED"

    limit = int(user.max_active_licenses or 0)
    if limit <= 0:
        return None  # 0 = unlimited

    if not will_activate:
        return None

    now0 = utcnow()
    active_count = db.execute(
        select(func.count()).select_from(License).where(
            License.owner_agent_id == agent_id,
            License.status == "active",
            License.expires_at > now0,
        )
    ).scalar_one()

    if int(active_count) >= limit:
        return "LIMIT"
    return None



def _audit(db: Session, event_type: str, payload: dict | None = None, license_id=None, device_id=None, session_id=None):
    db.add(AuditLog(
        license_id=license_id,
        device_id=device_id,
        session_id=session_id,
        event_type=event_type,
        payload=payload or {},
    ))


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


def gen_key_15() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(15))


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    err = request.query_params.get("err")
    return templates.TemplateResponse("admin/login.html", {"request": request, "err": err})


@router.post("/login")
def login(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
):
    username = (username or "").strip()

    # 1) SUPER ADMIN (giữ cơ chế cũ theo settings)
    if username == settings.admin_username and verify_password(password):
        request.session.clear()
        request.session["role"] = "super"
        return RedirectResponse(url="/admin", status_code=303)

    # 2) AGENT (đại lý) trong DB
    user = db.execute(select(AdminUser).where(AdminUser.username == username)).scalar_one_or_none()
    if not user or not user.is_active:
        return RedirectResponse(url="/admin/login?err=1", status_code=303)

    if not verify_password_hash(password, user.password_hash):
        return RedirectResponse(url="/admin/login?err=1", status_code=303)

    request.session.clear()
    request.session["role"] = "agent"
    request.session["agent_id"] = user.id
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/logout")
def logout(request: Request, _: None = Depends(require_admin)):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    agent_id = _agent_id(request)

    if agent_id:
        lic_count = db.query(License).filter(License.owner_agent_id == agent_id).count()
        active_lic = db.query(License).filter(License.owner_agent_id == agent_id, License.status == "active").count()
        active_sessions = (
            db.query(DbSession)
            .join(License, DbSession.license_id == License.id)
            .filter(License.owner_agent_id == agent_id, DbSession.status == "active")
            .count()
        )
        devices = (
            db.query(Device)
            .join(License, Device.license_id == License.id)
            .filter(License.owner_agent_id == agent_id)
            .count()
        )
    else:
        lic_count = db.query(License).count()
        active_lic = db.query(License).filter(License.status == "active").count()
        active_sessions = db.query(DbSession).filter(DbSession.status == "active").count()
        devices = db.query(Device).count()
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "lic_count": lic_count,
            "active_lic": active_lic,
            "active_sessions": active_sessions,
            "devices": devices,
        },
    )


@router.get("/licenses", response_class=HTMLResponse)
def licenses(
    request: Request,
    q: str | None = None,
    note: str | None = None,
    has_note: str | None = None,
    status: str | None = None,
    exp: str | None = None,
    agent: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    q = (q or "").strip()
    note = (note or "").strip()
    has_note = (has_note or "").strip().lower()
    status = (status or "").strip().lower()
    exp = (exp or "").strip().lower()
    agent = (agent or "").strip()
    agents = []
    selected_agent = agent

    stmt = _license_stmt_scoped(request)

    # SUPER: có thể lọc theo agent + load danh sách agent cho dropdown
    if _is_super(request):
        agents = db.execute(
            select(AdminUser).order_by(AdminUser.created_at.desc())
        ).scalars().all()

        if selected_agent:
            stmt = stmt.where(License.owner_agent_id == selected_agent)

    licenses = db.execute(stmt).scalars().all()

    # Filters in python (simple & safe for now)
    licenses = _apply_license_filters_python(
        licenses,
        q=q,
        note=note,
        has_note=has_note,
        status=status,
        exp=exp,
    )
    license_ids = [lic.id for lic in licenses]
    device_name_map = {}

    if license_ids:
        devices = db.execute(
            select(Device).where(Device.license_id.in_(license_ids))
        ).scalars().all()

        device_name_map = {
            d.license_id: (d.device_name or "").strip()
            for d in devices
        }
        
    return templates.TemplateResponse(
        "admin/licenses.html",
        {
            "request": request,
            "licenses": licenses,
            "q": q,
            "note": note,
            "has_note": has_note,
            "status": status,
            "exp": exp,
            "days_left": days_left,
            "now": utcnow(),
            "agents": agents,
            "selected_agent": selected_agent,
            "device_name_map": device_name_map,
        },
    )

@router.get("/licenses/table", response_class=HTMLResponse)
def licenses_table(
    request: Request,
    q: str | None = None,
    note: str | None = None,
    has_note: str | None = None,
    status: str | None = None,
    exp: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    q = (q or "").strip()
    note = (note or "").strip()
    has_note = (has_note or "").strip().lower()

    status = (status or "").strip().lower()
    exp = (exp or "").strip().lower()

    licenses = db.execute(_license_stmt_scoped(request)).scalars().all()

    licenses = _apply_license_filters_python(
        licenses,
        q=q,
        note=note,
        has_note=has_note,
        status=status,
        exp=exp,
    )
    license_ids = [lic.id for lic in licenses]
    device_name_map = {}

    if license_ids:
        devices = db.execute(
            select(Device).where(Device.license_id.in_(license_ids))
        ).scalars().all()

        device_name_map = {
            d.license_id: (d.device_name or "").strip()
            for d in devices
        }
    return templates.TemplateResponse(
        "admin/partials/license_table.html",
        {
            "request": request,
            "licenses": licenses,
            "days_left": days_left,
            "now": utcnow(),
            "device_name_map": device_name_map,
        },
    )

@router.get("/licenses/{license_id}", response_class=HTMLResponse)
def license_detail(request: Request, license_id: str, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    lic = _get_license_scoped(db, request, license_id)
    if lic is None:
        return templates.TemplateResponse("admin/not_found.html", {"request": request, "what": "License"})

    dev = db.execute(select(Device).where(Device.license_id == lic.id)).scalar_one_or_none()
    sessions = db.execute(
        select(DbSession).where(DbSession.license_id == lic.id).order_by(DbSession.issued_at.desc()).limit(50)
    ).scalars().all()
    audits = db.execute(
        select(AuditLog).where(AuditLog.license_id == lic.id).order_by(AuditLog.created_at.desc()).limit(100)
    ).scalars().all()

    return templates.TemplateResponse(
        "admin/license_detail.html",
        {"request": request, "lic": lic, "dev": dev, "sessions": sessions, "audits": audits},
    )

@router.post("/licenses/{license_id}/extend", response_class=HTMLResponse)
def extend_license(
    request: Request,
    license_id: str,
    days: int = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    lic = _get_license_scoped(db, request, license_id)
    if lic is None:
        return templates.TemplateResponse("admin/not_found.html", {"request": request, "what": "License"})

    now = utcnow()

    # AGENT: nếu license đã hết hạn và gia hạn làm license "hồi sinh" -> phải check limit
    will_activate = (lic.status == "active") and (lic.expires_at is None or lic.expires_at <= now)

    err = _check_agent_limit_before_activating(db, request, will_activate=will_activate)
    if err == "LIMIT":
        return RedirectResponse(url=f"/admin/licenses/{license_id}?err=LIMIT", status_code=303)
    if err == "AGENT_DISABLED":
        return RedirectResponse(url="/admin/login?err=1", status_code=303)

    # Gia hạn từ mốc hợp lý:
    # - Nếu license còn hạn -> cộng từ expires_at hiện tại
    # - Nếu đã hết hạn -> cộng từ thời điểm hiện tại
    base = lic.expires_at if lic.expires_at and lic.expires_at > now else now
    lic.expires_at = base + timedelta(days=int(days))
    lic.updated_at = now

    _audit(db, "admin_extend_license", {"days": int(days)}, license_id=lic.id)
    db.commit()

    # Nếu là HTMX: trả về đúng text expiry để update UI
    if request.headers.get("hx-request") == "true":
        return HTMLResponse(str(lic.expires_at))

    # Không phải HTMX: redirect về trang detail
    return RedirectResponse(url=f"/admin/licenses/{license_id}", status_code=303)
    
@router.post("/licenses/{license_id}/note", response_class=HTMLResponse)
def update_license_note(
    request: Request,
    license_id: str,
    note: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    lic = _get_license_scoped(db, request, license_id)
    if lic is None:
        return templates.TemplateResponse("admin/not_found.html", {"request": request, "what": "License"}, status_code=404)

    lic.note = (note or "").strip()[:255]
    lic.updated_at = utcnow()
    _audit(db, "admin_update_license_note", {"note": lic.note}, license_id=lic.id)
    db.commit()

    return RedirectResponse(url=f"/admin/licenses/{license_id}", status_code=303)

@router.post("/licenses/create", response_class=HTMLResponse)
def create_license(
    request: Request,
    days: int = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    # Generate 15-char key that matches validate_key_format().
    raw_key = gen_key_15()
    key_hash = hash_license_key(raw_key, HASH_CFG)

    # AGENT: enforce max_active_licenses (đang quản lý cùng lúc)
    agent_id = _agent_id(request)
    err = _check_agent_limit_before_activating(db, request, will_activate=True)
    if err == "LIMIT":
        return RedirectResponse(url="/admin/licenses?err=LIMIT", status_code=303)
    if err == "AGENT_DISABLED":
        return RedirectResponse(url="/admin/login?err=1", status_code=303)

    now = utcnow()
    lic = License(
        id=str(uuid4()),
        key_hash=key_hash,
        status="active",
        expires_at=now + timedelta(days=int(days)),
        note=(note or "").strip()[:255],
        created_at=now,
        updated_at=now,
        owner_agent_id=agent_id,
    )
    db.add(lic)
    _audit(db, "admin_create_license", {"days": int(days), "note": (note or "").strip()[:255]}, license_id=lic.id)
    db.commit()

    # Show raw key once.
    return templates.TemplateResponse(
        "admin/license_created.html",
        {"request": request, "raw_key": raw_key, "license_id": lic.id, "expires_at": lic.expires_at},
    )


@router.post("/licenses/{license_id}/block", response_class=HTMLResponse)
def block_license(request: Request, license_id: str, db: Session = Depends(get_db), _: None = Depends(require_super_admin)):
    lic = db.get(License, license_id)
    if lic is None:
        return templates.TemplateResponse("admin/not_found.html", {"request": request}, status_code=404)

    lic.status = "blocked"
    lic.updated_at = utcnow()
    _audit(db, "admin_block_license", {}, license_id=lic.id)
    db.commit()

    # For HTMX requests, return status badge partial; otherwise redirect.
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse("admin/partials/license_status.html", {"request": request, "lic": lic})
    return RedirectResponse(url=f"/admin/licenses/{license_id}", status_code=303)


@router.post("/licenses/{license_id}/unblock", response_class=HTMLResponse)
def unblock_license(request: Request, license_id: str, db: Session = Depends(get_db), _: None = Depends(require_super_admin)):
    lic = db.get(License, license_id)
    if lic is None:
        return templates.TemplateResponse("admin/not_found.html", {"request": request}, status_code=404)

    lic.status = "active"
    lic.updated_at = utcnow()
    _audit(db, "admin_unblock_license", {}, license_id=lic.id)
    db.commit()

    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse("admin/partials/license_status.html", {"request": request, "lic": lic})
    return RedirectResponse(url=f"/admin/licenses/{license_id}", status_code=303)


@router.post("/licenses/{license_id}/revoke", response_class=HTMLResponse)
def revoke_license_sessions(request: Request, license_id: str, db: Session = Depends(get_db), _: None = Depends(require_super_admin)):
    lic = db.get(License, license_id)
    if lic is None:
        return templates.TemplateResponse("admin/not_found.html", {"request": request}, status_code=404)
    now = utcnow()
    _kill_active_sessions(db, lic.id, now)
    _revoke_refresh_tokens_for_license(db, lic.id, now)
    _audit(db, "admin_revoke_sessions", {}, license_id=lic.id)
    db.commit()

    if request.headers.get("hx-request") == "true":
        # Return updated sessions table
        sessions = db.execute(
            select(DbSession).where(DbSession.license_id == lic.id).order_by(DbSession.issued_at.desc()).limit(50)
        ).scalars().all()
        return templates.TemplateResponse("admin/partials/session_table.html", {"request": request, "sessions": sessions})
    return RedirectResponse(url=f"/admin/licenses/{license_id}", status_code=303)

@router.post("/licenses/{license_id}/delete", response_class=HTMLResponse)
def delete_license(
    request: Request,
    license_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    lic = _get_license_scoped(db, request, license_id)
    if lic is None:
        return templates.TemplateResponse(
            "admin/not_found.html",
            {"request": request, "what": "License"},
            status_code=404,
        )
    now = utcnow()

    # Log tổng quát trước khi xóa để còn dấu vết support
    _audit(
        db,
        "admin_delete_license",
        {
            "deleted_license_id": lic.id,
            "deleted_key_hash": lic.key_hash,
            "deleted_note": lic.note,
            "deleted_at": str(now),
        },
        license_id=None,   # không gắn FK license_id để log không bị mất theo license
        device_id=None,
        session_id=None,
    )
    db.flush()

    # 1) lấy tất cả session id của license này
    session_ids = db.execute(
        select(DbSession.id).where(DbSession.license_id == lic.id)
    ).scalars().all()

    # 2) xóa refresh_tokens trước vì nó phụ thuộc session/device/license
    if session_ids:
        db.execute(
            delete(RefreshToken).where(RefreshToken.session_id.in_(session_ids))
        )

    # dự phòng: vẫn xóa theo license_id thêm 1 lớp an toàn
    db.execute(
        delete(RefreshToken).where(RefreshToken.license_id == lic.id)
    )

    # 3) xóa sessions
    db.execute(
        delete(DbSession).where(DbSession.license_id == lic.id)
    )

    # 4) xóa device
    db.execute(
        delete(Device).where(Device.license_id == lic.id)
    )

    # 5) xóa audit logs của chính license đó
    db.execute(
        delete(AuditLog).where(AuditLog.license_id == lic.id)
    )

    # 6) cuối cùng xóa license
    db.delete(lic)

    db.commit()
    return RedirectResponse(url="/admin/licenses", status_code=303)

@router.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request, db: Session = Depends(get_db), _: None = Depends(require_super_admin)):
    agents = db.execute(select(AdminUser).order_by(AdminUser.created_at.desc())).scalars().all()
    return templates.TemplateResponse("admin/agents.html", {"request": request, "agents": agents})


@router.post("/agents/create", response_class=HTMLResponse)
def agents_create(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    max_active_licenses: int = Form(0),
    db: Session = Depends(get_db),
    _: None = Depends(require_super_admin),
):
    username = (username or "").strip()
    if not username or not password:
        return RedirectResponse(url="/admin/agents?err=1", status_code=303)

    exists = db.execute(select(AdminUser).where(AdminUser.username == username)).scalar_one_or_none()
    if exists:
        return RedirectResponse(url="/admin/agents?err=EXISTS", status_code=303)

    user = AdminUser(
        id=str(uuid4()),
        username=username,
        password_hash=hash_password(password),
        role="agent",
        is_active=1,
        max_active_licenses=max(0, int(max_active_licenses or 0)),
    )
    db.add(user)
    _audit(db, "admin_create_agent", {"username": username, "max_active_licenses": user.max_active_licenses})
    db.commit()

    # Nếu gọi bằng JS (fetch/AJAX) thì trả JSON để frontend không bị Promise error
    accept = (request.headers.get("accept") or "").lower()
    xrw = (request.headers.get("x-requested-with") or "").lower()
    if "application/json" in accept or xrw == "xmlhttprequest":
        return JSONResponse({"ok": True, "agent_id": user.id, "username": user.username})

    # Submit form bình thường thì giữ redirect như cũ
    return RedirectResponse(url="/admin/agents", status_code=303)

@router.post("/agents/{agent_id}/toggle", response_class=HTMLResponse)
def agents_toggle(
    request: Request,
    agent_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_super_admin),
):
    user = db.execute(select(AdminUser).where(AdminUser.id == agent_id)).scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/admin/agents?err=NF", status_code=303)

    user.is_active = 0 if user.is_active else 1
    user.updated_at = utcnow()
    _audit(db, "admin_toggle_agent", {"agent_id": agent_id, "is_active": int(user.is_active)})
    db.commit()
    return RedirectResponse(url="/admin/agents", status_code=303)


@router.post("/agents/{agent_id}/reset_password", response_class=HTMLResponse)
def agents_reset_password(
    request: Request,
    agent_id: str,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_super_admin),
):
    user = db.execute(select(AdminUser).where(AdminUser.id == agent_id)).scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/admin/agents?err=NF", status_code=303)

    new_password = (new_password or "").strip()
    if not new_password:
        return RedirectResponse(url="/admin/agents?err=1", status_code=303)

    user.password_hash = hash_password(new_password)
    user.updated_at = utcnow()
    _audit(db, "admin_reset_agent_password", {"agent_id": agent_id})
    db.commit()
    return RedirectResponse(url="/admin/agents", status_code=303)



@router.get("/sessions", response_class=HTMLResponse)
def sessions(request: Request, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    stmt = select(DbSession).order_by(DbSession.issued_at.desc()).limit(200)
    agent_id = _agent_id(request)
    if agent_id:
        stmt = (
            select(DbSession)
            .join(License, DbSession.license_id == License.id)
            .where(License.owner_agent_id == agent_id)
            .order_by(DbSession.issued_at.desc())
            .limit(200)
        )
    sessions = db.execute(stmt).scalars().all()
    return templates.TemplateResponse("admin/sessions.html", {"request": request, "sessions": sessions})

@router.get("/audit", response_class=HTMLResponse)
def audit(request: Request, event: str | None = None, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    event = (event or "").strip()
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(300)
    agent_id = _agent_id(request)
    if agent_id:
        # Agent chỉ xem audit liên quan đến license của chính mình
        stmt = (
            select(AuditLog)
            .join(License, AuditLog.license_id == License.id)
            .where(License.owner_agent_id == agent_id)
            .order_by(AuditLog.created_at.desc())
            .limit(300)
        )
    audits = db.execute(stmt).scalars().all()
    if event:
        audits = [a for a in audits if (a.event_type or "") == event]
    return templates.TemplateResponse("admin/audit.html", {"request": request, "audits": audits, "event": event})
