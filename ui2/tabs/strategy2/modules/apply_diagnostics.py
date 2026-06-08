from __future__ import annotations

from datetime import datetime
import json
import os
import threading
from typing import Any, Optional

from core.constants import LOG_DIR
from core.logger import log


DIAGNOSTIC_PATH = os.path.join(LOG_DIR, "apply_failures.jsonl")
SCREENSHOT_DIR = os.path.join(LOG_DIR, "apply_failures")
_WRITE_LOCK = threading.Lock()


def record_apply_failure(
    event: str,
    profile_id: str,
    *,
    screenshot=None,
    **data: Any,
) -> Optional[str]:
    """
    Ghi chẩn đoán chi tiết chỉ khi thao tác kéo/xác nhận có bất thường.

    JSONL giúp tra cứu và so sánh layout; ảnh chụp giúp xác định lỗi tọa độ,
    animation, overlay hoặc game không nhận sự kiện chuột.
    """
    try:
        now = datetime.now()
        stamp = now.strftime("%Y%m%d-%H%M%S-%f")
        pid = str(profile_id or "-")
        image_path = None

        with _WRITE_LOCK:
            os.makedirs(LOG_DIR, exist_ok=True)
            if screenshot is not None:
                os.makedirs(SCREENSHOT_DIR, exist_ok=True)
                image_path = os.path.join(SCREENSHOT_DIR, f"{stamp}_{pid}_{event}.png")
                screenshot.save(image_path)

            payload = {
                "time": now.isoformat(timespec="milliseconds"),
                "event": str(event),
                "profile_id": pid,
                "thread": threading.current_thread().name,
                "screenshot": image_path,
                **data,
            }
            with open(DIAGNOSTIC_PATH, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
                handle.flush()
        log.warning(
            "[APPLY-DIAG] event=%s pid=%s screenshot=%s",
            event,
            pid,
            image_path or "-",
        )
        return image_path
    except Exception as exc:
        # Chẩn đoán không bao giờ được phép làm hỏng luồng xếp bài.
        log.warning("[APPLY-DIAG] không thể ghi chẩn đoán pid=%s: %s", profile_id, exc)
        return None
