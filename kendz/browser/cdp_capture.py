from __future__ import annotations

import io
from typing import Tuple

import cv2
import numpy as np
from PIL import Image

from .cdp_client import CDPSession


def capture_frame_from_cdp(
    host: str = "127.0.0.1",
    port: int = 9222,
    timeout: float = 5.0,
) -> Tuple[np.ndarray, int, int]:
    """Chụp 1 frame từ tab 'page' đầu tiên thông qua Chrome DevTools.

    Trả về:
        frame_bgr: np.ndarray (H, W, 3), màu BGR (phù hợp với OpenCV)
        viewport_width: int
        viewport_height: int

    Lưu ý:
    - Không phụ thuộc màn hình thật
    - Chrome có thể minimize / bị che / nằm dưới ứng dụng khác
    - Cần Chrome chạy với --remote-debugging-port=9222
    """
    session = CDPSession(host=host, port=port, timeout=timeout)
    try:
        session.connect()

        # 1) Lấy ảnh PNG (bytes) từ DevTools
        png_bytes = session.capture_screenshot_png(format="png")

        # 2) Decode PNG -> RGB dùng PIL
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        frame_rgb = np.array(img)  # (H, W, 3), RGB

        # 3) Đổi sang BGR cho OpenCV
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

        # 4) Lấy kích thước viewport để quy đổi normalized region
        vw, vh = session.get_layout_metrics()

        return frame_bgr, vw, vh

    finally:
        session.close()
