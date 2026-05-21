from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .anti_debug import detect_debugger_risk
from .fingerprint import get_fingerprint_hash, get_fingerprint_raw
from .storage import load_cache, save_cache, LicenseCache
from .client import LicenseApiClient
from .verify import verify_entitlements, check_expiry


@dataclass
class LicenseState:
    ok: bool
    reason: str = ""
    payload: dict | None = None


class LicenseManager(QObject):
    state_changed = Signal(object)  # LicenseState

    def __init__(self, *, base_url: str, app_version: str, offline_grace_hours: int = 720) -> None:
        super().__init__()
        self.base_url = base_url
        self.app_version = app_version
        self.offline_grace_hours = offline_grace_hours

        self.fp_raw = get_fingerprint_raw()
        self.fp_hash = get_fingerprint_hash()

        self.api = LicenseApiClient(base_url=base_url, timeout=8.0)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.state = LicenseState(ok=False, reason="NOT_INITIALIZED", payload=None)

    # NEW: getter cho UI
    def get_cached_license_id(self) -> Optional[str]:
        cache = load_cache(self.fp_hash)
        if cache is None:
            return None
        lid = (cache.license_id or "").strip()
        return lid or None

    def start(self) -> None:
        risk, reason = detect_debugger_risk()
        if risk:
            self.state = LicenseState(ok=False, reason=f"DEBUGGER:{reason}", payload=None)
            self.state_changed.emit(self.state)
            return

        cache = load_cache(self.fp_hash)
        if cache is None:
            self.state = LicenseState(ok=False, reason="NO_CACHE", payload=None)
            self.state_changed.emit(self.state)
            return

        # --- refresh online ngay khi mở tool để cập nhật exp mới ---
        try:
            ok_hb, _ = self.api.heartbeat(
                session_id=cache.session_id,
                device_id=cache.device_id,
                app_version=self.app_version,
            )
            if ok_hb:
                rr = self.api.refresh(
                    session_id=cache.session_id,
                    refresh_token=cache.refresh_token,
                    app_version=self.app_version,
                )
                if rr.ok and rr.data:
                    data = rr.data
                    cache.refresh_token = data["refresh_token"]
                    cache.entitlements_cbor_b64 = data["entitlements_cbor_b64"]
                    cache.entitlements_sig_b64 = data["entitlements_sig_b64"]
                    cache.signing_pub_b64 = data["signing_pub_b64"]
                    cache.last_online_ok_epoch = int(time.time())

                    # NEW: lưu license_id nếu server có trả
                    if "license_id" in data and data["license_id"]:
                        cache.license_id = str(data["license_id"])

                    save_cache(self.fp_hash, cache)

                    # Emit ngay state mới để UI cập nhật exp liền
                    try:
                        ok_sig2, _, payload2 = verify_entitlements(
                            entitlements_cbor_b64=cache.entitlements_cbor_b64,
                            entitlements_sig_b64=cache.entitlements_sig_b64,
                            signing_pub_b64=cache.signing_pub_b64,
                        )
                        if ok_sig2:
                            ok_exp2, _ = check_expiry(payload2)
                            if ok_exp2:
                                payload2["offline_hours"] = 0.0
                                self.state = LicenseState(ok=True, reason="", payload=payload2)
                                self.state_changed.emit(self.state)
                    except Exception:
                        pass
        except Exception:
            pass

        now = int(time.time())
        offline_hours = (now - int(cache.last_online_ok_epoch)) / 3600.0
        if offline_hours > float(self.offline_grace_hours):
            self.state = LicenseState(ok=False, reason="OFFLINE_GRACE_EXCEEDED", payload=None)
            self.state_changed.emit(self.state)
            return

        ok_sig, _, payload = verify_entitlements(
            entitlements_cbor_b64=cache.entitlements_cbor_b64,
            entitlements_sig_b64=cache.entitlements_sig_b64,
            signing_pub_b64=cache.signing_pub_b64,
        )

        if not ok_sig:
            self.state = LicenseState(ok=False, reason="CACHE_SIGNATURE_INVALID", payload=None)
            self.state_changed.emit(self.state)
            return

        ok_exp, reason_exp = check_expiry(payload)
        if not ok_exp:
            self.state = LicenseState(ok=False, reason=reason_exp, payload=None)
            self.state_changed.emit(self.state)
            return

        payload["offline_hours"] = offline_hours
        self.state = LicenseState(ok=True, reason="", payload=payload)
        self.state_changed.emit(self.state)

        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def activate_with_key(self, key: str, device_name: str) -> LicenseState:
        res = self.api.activate(key=key, fingerprint=self.fp_raw, device_name=device_name, app_version=self.app_version)
        if not res.ok or not res.data:
            self.state = LicenseState(ok=False, reason=res.detail, payload=None)
            self.state_changed.emit(self.state)
            return self.state

        data = res.data
        cache = LicenseCache(
            license_key=key,
            refresh_token=data["refresh_token"],
            session_id=data["session_id"],
            device_id=data["device_id"],
            entitlements_cbor_b64=data["entitlements_cbor_b64"],
            entitlements_sig_b64=data["entitlements_sig_b64"],
            signing_pub_b64=data["signing_pub_b64"],
            last_online_ok_epoch=int(time.time()),
        )

        # NEW: lưu license_id ngay từ activate nếu server có trả
        if "license_id" in data and data["license_id"]:
            cache.license_id = str(data["license_id"])

        save_cache(self.fp_hash, cache)

        self.state = LicenseState(ok=True, reason="", payload=res.payload or {})
        self.state_changed.emit(self.state)

        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

        return self.state

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                cache = load_cache(self.fp_hash)
                if cache is None:
                    self.state = LicenseState(ok=False, reason="CACHE_MISSING", payload=None)
                    self.state_changed.emit(self.state)
                    return

                ok_hb, reason = self.api.heartbeat(
                    session_id=cache.session_id,
                    device_id=cache.device_id,
                    app_version=self.app_version,
                )
                if not ok_hb:
                    self.state = LicenseState(ok=False, reason=f"HB:{reason}", payload=None)
                    self.state_changed.emit(self.state)
                    return
                self.state = LicenseState(ok=True, reason="OK", payload=self.state.payload)
                self.state_changed.emit(self.state)
                now = int(time.time())
                if (now - cache.last_online_ok_epoch) >= 6 * 3600:
                    rr = self.api.refresh(
                        session_id=cache.session_id,
                        refresh_token=cache.refresh_token,
                        app_version=self.app_version,
                    )
                    if not rr.ok or not rr.data:
                        # refresh fail thì bỏ qua entitlement update,
                        # không khóa tool nếu heartbeat trước đó vẫn OK
                        continue

                    data = rr.data
                    cache.refresh_token = data["refresh_token"]
                    cache.entitlements_cbor_b64 = data["entitlements_cbor_b64"]
                    cache.entitlements_sig_b64 = data["entitlements_sig_b64"]
                    cache.signing_pub_b64 = data["signing_pub_b64"]
                    cache.last_online_ok_epoch = now

                    # NEW: cập nhật license_id nếu có
                    if "license_id" in data and data["license_id"]:
                        cache.license_id = str(data["license_id"])

                    save_cache(self.fp_hash, cache)

                    self.state = LicenseState(ok=True, reason="", payload=rr.payload or {})
                    self.state_changed.emit(self.state)

            except Exception:
                pass

            self._stop.wait(30.0)
