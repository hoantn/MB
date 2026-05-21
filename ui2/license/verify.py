from __future__ import annotations

import base64
import time
from typing import Any, Dict, Tuple

import cbor2
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

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
