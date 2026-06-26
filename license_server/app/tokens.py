from __future__ import annotations

import secrets
from dataclasses import dataclass

from .security import sha256_hex, HashingConfig


@dataclass(frozen=True)
class TokenConfig:
    pepper: str


def issue_refresh_token() -> str:
    # Opaque token (không mang data), khó đoán
    # urlsafe ~ 43-86 chars tùy bytes; dùng 32 bytes là đủ mạnh
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str, cfg: TokenConfig) -> str:
    # hash lưu DB: SHA256(pepper + token)
    return sha256_hex((cfg.pepper + token).encode("utf-8"))
