from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
import threading
import time
from typing import Any, List, Optional

from core.apply_trace import apply_trace
from core.logger import log
from vision.cropper import crop_slots
from vision.recognizer import recognize_card


# OCR 13 lá là tác vụ CPU nặng. Dùng một khóa chung để tránh P1/P2/P3
# cùng nhận dạng một lúc làm CPU tăng đột biến và ảnh hưởng thao tác kéo.
_SCAN_LOCK = threading.Lock()


@dataclass(frozen=True)
class LayoutScanResult:
    """Kết quả của một ảnh chụp mới, không bao giờ đại diện cho cache cũ."""

    profile_id: str
    codes: List[str]
    captured_at: float
    confidences: List[float] = field(default_factory=list)
    image: Any = None


def trusted_layout_codes(
    result: Optional[LayoutScanResult],
    expected_codes: List[str],
    *,
    min_confidence: float = 0.70,
) -> Optional[List[str]]:
    """
    Chỉ chấp nhận OCR khi đủ 13 lá, khớp chính xác bộ bài WS và mọi slot đều
    đạt confidence tối thiểu. Kết quả không chắc chắn không được dùng để sửa bài.
    """
    if result is None:
        return None
    codes = list(result.codes or [])
    confidences = list(result.confidences or [])
    expected = list(expected_codes or [])
    if len(codes) != 13 or len(expected) != 13 or len(confidences) != 13:
        return None
    if Counter(map(str, codes)) != Counter(map(str, expected)):
        return None
    if min(confidences) < float(min_confidence):
        return None
    return codes


def scan_layout_fresh(
    profile_id: str,
    capture_manager,
    *,
    lock_timeout_s: float = 10.0,
) -> Optional[LayoutScanResult]:
    """
    Chụp và nhận dạng layout hiện tại của một P.

    Hàm chỉ trả về khi đủ 13 mã lá hợp lệ. Mỗi kết quả đều đến từ ảnh vừa chụp
    trong chính lần gọi này; tuyệt đối không fallback về _layout_codes/cache.
    """
    pid = str(profile_id)
    if capture_manager is None:
        apply_trace("fresh_scan_no_capture_manager", pid)
        return None

    acquired = _SCAN_LOCK.acquire(timeout=max(0.1, float(lock_timeout_s)))
    if not acquired:
        apply_trace("fresh_scan_lock_timeout", pid)
        return None

    started = time.monotonic()
    try:
        apply_trace("fresh_scan_capture_start", pid)
        image = capture_manager.capture_region(pid)
        captured_at = time.monotonic()
        if image is None:
            apply_trace("fresh_scan_no_image", pid)
            return None

        try:
            cfg_slot = int(getattr(getattr(capture_manager, "browser_manager", None), "_slot", 1) or 1)
        except Exception:
            cfg_slot = 1
        slots = crop_slots(pid, image, slot=cfg_slot)
        if len(slots) != 13 or any(slot is None for slot in slots):
            apply_trace("fresh_scan_bad_slots", pid, slots_len=len(slots or []))
            return None

        codes: List[str] = []
        confidences: List[float] = []
        for slot in slots:
            code, confidence, _is_new = recognize_card(slot)
            value = str(code or "").strip()
            if not value or value == "??":
                apply_trace("fresh_scan_bad_card", pid, index=len(codes))
                return None
            codes.append(value)
            confidences.append(float(confidence or 0.0))

        apply_trace(
            "fresh_scan_ok",
            pid,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        return LayoutScanResult(pid, codes, captured_at, confidences, image)
    except Exception as exc:
        apply_trace("fresh_scan_exception", pid, error=str(exc))
        log.exception("[Strategy2] fresh layout scan failed pid=%s: %s", pid, exc)
        return None
    finally:
        _SCAN_LOCK.release()
