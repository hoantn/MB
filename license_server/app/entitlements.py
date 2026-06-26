from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone

import cbor2
from nacl.signing import SigningKey

from .settings import settings


def _to_epoch_utc(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


@dataclass(frozen=True)
class SignedBlob:
    cbor_b64: str
    sig_b64: str
    pub_b64: str


def _b64_decode_lenient(s: str) -> bytes:
    s = (s or "").strip()
    # add padding if missing
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    return base64.b64decode(s.encode("ascii"))


def _load_signing_key() -> SigningKey:
    # Prefer hex to avoid padding issues
    seed_hex = (settings.ed25519_seed_hex or "").strip()
    if seed_hex:
        try:
            seed = bytes.fromhex(seed_hex)
        except ValueError:
            raise ValueError("ED25519_SEED_HEX must be 64 hex chars (32 bytes)")
        if len(seed) != 32:
            raise ValueError("ED25519_SEED_HEX must decode to 32 bytes")
        return SigningKey(seed)

    seed_b64 = (settings.ed25519_seed_b64 or "").strip()
    if not seed_b64:
        raise ValueError("Missing ED25519 seed. Set ED25519_SEED_HEX (preferred) or ED25519_SEED_B64")

    try:
        seed = _b64_decode_lenient(seed_b64)
    except binascii.Error as e:
        raise ValueError(f"ED25519_SEED_B64 invalid base64: {e}")

    if len(seed) != 32:
        raise ValueError("ED25519_SEED_B64 must decode to 32 bytes")
    return SigningKey(seed)


def sign_entitlements(payload: dict) -> SignedBlob:
    sk = _load_signing_key()
    pk = sk.verify_key.encode()

    raw = cbor2.dumps(payload)
    sig = sk.sign(raw).signature

    return SignedBlob(
        cbor_b64=base64.b64encode(raw).decode("ascii"),
        sig_b64=base64.b64encode(sig).decode("ascii"),
        pub_b64=base64.b64encode(pk).decode("ascii"),
    )


def build_entitlements_payload(
    *,
    license_id: str,
    device_id: str,
    session_id: str,
    status: str,
    expires_at: datetime,
    offline_grace_hours: int,
    features: dict,
    issued_at: datetime | None = None,
) -> dict:
    now = datetime.utcnow().replace(tzinfo=timezone.utc) if issued_at is None else issued_at
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    return {
        "ver": 1,
        "product_id": settings.license_product_id,
        "lic": license_id,
        "dev": device_id,
        "ses": session_id,
        "st": status,
        "iat": _to_epoch_utc(now),
        "exp": _to_epoch_utc(expires_at),
        "og": int(offline_grace_hours),
        "feat": features or {},
    }
