# kendz/vision/service.py
"""VisionService - service điều phối module Vision của Kendz.

Phase 3:
- Chỉ cung cấp hàm test_capture() để:
  + Chụp 1 frame màn hình
  + Lưu file debug `data/vision_test.png`
- Sau này có thể:
  + Chạy loop theo FPS
  + Emit event 'vision.frame_captured' / 'vision.cards_detected'
"""

from __future__ import annotations

from pathlib import Path

from kendz.core.app_context import AppContext
from kendz.vision.capture import capture_screen, save_frame_debug


def test_capture(ctx: AppContext) -> None:
    """Hàm test đơn giản cho Vision.

    Bước:
    1. Chụp 1 frame màn hình.
    2. Nếu thành công -> lưu vào `data/vision_test.png`.
    3. Ghi log kết quả.

    Hàm này sẽ được gọi tạm thời từ main để kiểm tra
    rằng Vision hoạt động (thư viện mss + opencv ok).
    """
    logger = ctx.logger
    frame = capture_screen()
    if frame is None:
        logger.error("Vision: không chụp được màn hình (frame = None). Kiểm tra lại quyền hoặc mss.")
        return

    project_root = Path(__file__).resolve().parents[2]
    out_path = project_root / "data" / "vision_test.png"
    save_frame_debug(frame, out_path)
    logger.info("Vision: đã chụp 1 frame và lưu tại: %s", out_path)
