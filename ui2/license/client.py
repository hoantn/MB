from __future__ import annotations

import requests
from dataclasses import dataclass
from typing import Optional, Tuple

from .verify import verify_entitlements, check_expiry

@dataclass
class ActivateResult:
    ok: bool
    detail: str
    data: Optional[dict] = None
    payload: Optional[dict] = None

class LicenseApiClient:
    def __init__(self, base_url: str, timeout: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def activate(self, *, key: str, fingerprint: str, device_name: str, app_version: str) -> ActivateResult:
        url = f"{self.base_url}/v1/activate"
        r = requests.post(
            url,
            json={"key": key, "fingerprint": fingerprint, "device_name": device_name, "app_version": app_version},
            timeout=self.timeout,
        )
        if r.status_code != 200:
            try:
                return ActivateResult(False, r.json().get("detail", f"HTTP_{r.status_code}"))
            except Exception:
                return ActivateResult(False, f"HTTP_{r.status_code}")

        data = r.json()
        ok, reason, payload = verify_entitlements(
            entitlements_cbor_b64=data.get("entitlements_cbor_b64", ""),
            entitlements_sig_b64=data.get("entitlements_sig_b64", ""),
            signing_pub_b64=data.get("signing_pub_b64", ""),
        )
        if not ok:
            return ActivateResult(False, reason)
        ok2, reason2 = check_expiry(payload)
        if not ok2:
            return ActivateResult(False, reason2)
        return ActivateResult(True, "", data=data, payload=payload)

    def refresh(self, *, session_id: str, refresh_token: str, app_version: str) -> ActivateResult:
        url = f"{self.base_url}/v1/refresh"
        r = requests.post(url, json={"session_id": session_id, "refresh_token": refresh_token, "app_version": app_version}, timeout=self.timeout)
        if r.status_code != 200:
            try:
                return ActivateResult(False, r.json().get("detail", f"HTTP_{r.status_code}"))
            except Exception:
                return ActivateResult(False, f"HTTP_{r.status_code}")

        data = r.json()
        ok, reason, payload = verify_entitlements(
            entitlements_cbor_b64=data.get("entitlements_cbor_b64", ""),
            entitlements_sig_b64=data.get("entitlements_sig_b64", ""),
            signing_pub_b64=data.get("signing_pub_b64", ""),
        )
        if not ok:
            return ActivateResult(False, reason)
        ok2, reason2 = check_expiry(payload)
        if not ok2:
            return ActivateResult(False, reason2)
        return ActivateResult(True, "", data=data, payload=payload)

    def heartbeat(self, *, session_id: str, device_id: str, app_version: str) -> Tuple[bool, str]:
        url = f"{self.base_url}/v1/heartbeat"
        r = requests.post(url, json={"session_id": session_id, "device_id": device_id, "app_version": app_version}, timeout=self.timeout)
        if r.status_code != 200:
            return False, f"HTTP_{r.status_code}"
        try:
            data = r.json()
            if data.get("status") == "OK":
                return True, ""
            return False, data.get("reason", "KILL")
        except Exception:
            return False, "BAD_RESPONSE"
