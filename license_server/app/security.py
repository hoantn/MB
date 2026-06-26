from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

KEY_RE = re.compile(r"^[A-Za-z0-9]{15}$")


@dataclass(frozen=True)
class HashingConfig:
    pepper: str


def validate_key_format(key: str) -> bool:
    return bool(KEY_RE.fullmatch(key))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_license_key(key: str, cfg: HashingConfig) -> str:
    return sha256_hex((cfg.pepper + key).encode("utf-8"))


def hash_fingerprint(fingerprint: str, cfg: HashingConfig, salt: Optional[str] = None) -> str:
    base = fingerprint if salt is None else (salt + fingerprint)
    return sha256_hex((cfg.pepper + base).encode("utf-8"))
