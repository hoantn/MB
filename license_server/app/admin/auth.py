from __future__ import annotations

from fastapi import Request, HTTPException
from passlib.context import CryptContext

from app.settings import settings

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(password: str) -> bool:
    """Verify SUPER admin password (stored in settings.admin_password_hash)."""
    if not (settings.admin_password_hash or "").strip():
        return False
    return _pwd_ctx.verify(password, settings.admin_password_hash)


def hash_password(password: str) -> str:
    return _pwd_ctx.hash(password)


def verify_password_hash(password: str, password_hash: str) -> bool:
    return _pwd_ctx.verify(password, password_hash)


def require_admin(request: Request) -> None:
    """Require authenticated admin user (SUPER or AGENT)."""
    role = request.session.get("role")
    if role == "super":
        return
    if role == "agent" and request.session.get("agent_id"):
        return
    raise HTTPException(status_code=401, detail="ADMIN_AUTH_REQUIRED")


def require_super_admin(request: Request) -> None:
    if request.session.get("role") != "super":
        raise HTTPException(status_code=403, detail="SUPER_ADMIN_REQUIRED")
