# kendz/vision/capture.py
"""Chụp màn hình cho Kendz (Vision).

Giai đoạn đầu:
- Dùng thư viện mss để chụp toàn màn hình (capture_mode = 'screen').
- Sau này:
  + Có thể chụp theo window handle cụ thể (capture_mode = 'window').

Hàm chính:
- capture_screen(): trả về frame dạng numpy.ndarray (BGR) hoặc None nếu lỗi.
- save_frame_debug(): lưu frame ra file JPG/PNG phục vụ debug.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import mss
import numpy as np
import cv2


def capture_screen() -> Optional[np.ndarray]:
    """Chụp toàn màn hình.

    Trả về:
    - frame dạng numpy.ndarray (BGR) nếu thành công
    - None nếu có lỗi (ví dụ không truy cập được màn hình)
    """
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # monitor chính
            img = sct.grab(monitor)
            frame = np.array(img)

            # mss trả về BGRA, cần chuyển sang BGR cho OpenCV
            frame = frame[:, :, :3]
            return frame
    except Exception:
        return None

def capture_screen_region(left: int, top: int, width: int, height: int) -> Optional[np.ndarray]:
    """Chụp một vùng màn hình cụ thể (thường là cửa sổ trình duyệt).

    Tham số:
    - left, top: toạ độ góc trên bên trái
    - width, height: kích thước vùng

    Trả về:
    - frame BGR (numpy.ndarray) nếu thành công
    - None nếu lỗi
    """
    try:
        with mss.mss() as sct:
            monitor = {
                "left": int(left),
                "top": int(top),
                "width": int(width),
                "height": int(height),
            }
            img = sct.grab(monitor)
            frame = np.array(img)
            frame = frame[:, :, :3]  # BGRA -> BGR
            return frame
    except Exception:
        return None


def save_frame_debug(frame: np.ndarray, path: Path) -> None:
    """Lưu frame ra file ảnh phục vụ debug.

    Tham số:
    - frame: ảnh BGR (numpy.ndarray)
    - path: đường dẫn file cần lưu
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)
