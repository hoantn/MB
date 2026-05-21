from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional

from nacl.secret import SecretBox
from nacl.utils import random as nacl_random

APP_SALT = b"MB_LICENSE_V1_SALT"


def _derive_key(fingerprint_hash: str) -> bytes:
    # 32-byte key via scrypt (reduced params to avoid OpenSSL memory limit on some Windows builds)
    return hashlib.scrypt(
        fingerprint_hash.encode("ascii"),
        salt=APP_SALT,
        n=2**14,   # was 2**15
        r=8,
        p=1,
        dklen=32,
        maxmem=64 * 1024 * 1024,  # 64MB cap to be explicit
    )


def _default_store_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        root = Path.home() / ".config"
    d = root / "MB_MauBinh"
    d.mkdir(parents=True, exist_ok=True)
    return d / "lic.dat"


@dataclass
class LicenseCache:
    # NEW: để đồng bộ tool <-> server
    license_id: str = ""

    license_key: str = ""
    refresh_token: str = ""
    session_id: str = ""
    device_id: str = ""
    entitlements_cbor_b64: str = ""
    entitlements_sig_b64: str = ""
    signing_pub_b64: str = ""
    last_online_ok_epoch: int = 0


def load_cache(fingerprint_hash: str, path: Optional[str] = None) -> Optional[LicenseCache]:
    p = Path(path) if path else _default_store_path()
    if not p.exists():
        return None
    try:
        blob = p.read_bytes()
        box = SecretBox(_derive_key(fingerprint_hash))
        nonce = blob[:24]
        ct = blob[24:]
        data = box.decrypt(ct, nonce)
        obj = json.loads(data.decode("utf-8"))

        # NEW: tương thích cache cũ / cache có field thừa (không crash)
        allowed = {f.name for f in fields(LicenseCache)}
        filtered = {k: v for k, v in obj.items() if k in allowed}

        return LicenseCache(**filtered)
    except Exception:
        return None


def save_cache(fingerprint_hash: str, cache: LicenseCache, path: Optional[str] = None) -> None:
    p = Path(path) if path else _default_store_path()
    box = SecretBox(_derive_key(fingerprint_hash))
    nonce = nacl_random(24)
    data = json.dumps(cache.__dict__, ensure_ascii=False).encode("utf-8")
    ct = box.encrypt(data, nonce).ciphertext
    p.write_bytes(nonce + ct)


def clear_cache(path: Optional[str] = None) -> None:
    p = Path(path) if path else _default_store_path()
    try:
        if p.exists():
            p.unlink()
    except Exception:
        pass
