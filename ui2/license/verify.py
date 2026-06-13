from __future__ import annotations

import base64
import time
from typing import Any, Dict, Tuple

import cbor2
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

from .product import LICENSE_PRODUCT_ID


def verify_entitlements(
    *,
    entitlements_cbor_b64: str,
    entitlements_sig_b64: str,
    signing_pub_b64: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    try:
        raw = base64.b64decode(entitlements_cbor_b64.encode("ascii"))
        sig = base64.b64decode(entitlements_sig_b64.encode("ascii"))
        pub = base64.b64decode(signing_pub_b64.encode("ascii"))
        vk = VerifyKey(pub)
        vk.verify(raw, sig)
        payload = cbor2.loads(raw)
        if not isinstance(payload, dict):
            return False, "PAYLOAD_NOT_DICT", {}
        return True, "", payload
    except BadSignatureError:
        return False, "BAD_SIGNATURE", {}
    except Exception:
        return False, "VERIFY_ERROR", {}


def check_expiry(payload: Dict[str, Any]) -> Tuple[bool, str]:
    exp = payload.get("exp")
    if not isinstance(exp, int):
        return False, "EXP_MISSING"
    now = int(time.time())
    if now >= exp:
        return False, "EXPIRED"
    return True, ""


def check_product(payload: Dict[str, Any]) -> Tuple[bool, str]:
    expected = str(LICENSE_PRODUCT_ID or "").strip()
    if not expected:
        return True, ""

    for key in ("product_id", "product", "app", "sku"):
        value = payload.get(key)
        if value is None:
            continue
        actual = str(value).strip()
        if not actual:
            continue
        if actual != expected:
            return False, "PRODUCT_MISMATCH"
        return True, ""

    # Backward-compatible while existing servers/caches do not include product.
    return True, ""
