# kendz/tools/layout_calibrate_manual.py
"""Calibrate layout 13 lá bài Mậu Binh bằng tay (manual).

Ý tưởng:
- Chụp 1 frame màn hình (full HD 1920x1080 chẳng hạn).
- Hiển thị frame bằng OpenCV.
- Dùng chuột vẽ lần lượt 13 hình chữ nhật cho 13 lá bài NGỬA của bạn.
  + Left mouse: click & drag để tạo 1 rect.
  + Khi thả chuột -> rect được ghi nhận.
  + Right mouse: undo rect cuối cùng (nếu vẽ sai).
  + Phím ENTER (hoặc SPACE): kết thúc khi đã đủ 13 rect.
  + Phím ESC / q: thoát không lưu.
- Convert rect (x, y, w, h) sang tọa độ tương đối (0..1) để lưu vào YAML.
- Ghi vào file: config/layouts_mau_binh.yaml theo game_id & profile.

Cách dùng:
    python -m kendz.tools.layout_calibrate_manual

Lưu ý:
- Nên để game full màn hình, không di chuyển cửa sổ trong quá trình calibrate.
- Làm 1 lần cho mỗi game/profie/độ phân giải.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import cv2
import yaml

from kendz.core.app_context import AppContext
from kendz.vision.capture import capture_screen


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def tl(self) -> Tuple[int, int]:
        return (self.x, self.y)

    @property
    def br(self) -> Tuple[int, int]:
        return (self.x + self.w, self.y + self.h)


class RectDrawer:
    """Class hỗ trợ tương tác chuột để vẽ nhiều rect."""

    def __init__(self, window_name: str, image):
        self.window_name = window_name
        self.image_orig = image
        self.image_show = image.copy()
        self.rects: List[Rect] = []
        self.drawing = False
        self.start_point = None  # type: Tuple[int, int] | None
        self.current_point = None

    def reset_view(self):
        self.image_show = self.image_orig.copy()
        # vẽ lại tất cả rect đã chốt
        for idx, r in enumerate(self.rects, start=1):
            cv2.rectangle(self.image_show, r.tl, r.br, (0, 255, 0), 2)
            cv2.putText(
                self.image_show,
                str(idx),
                (r.x + 5, r.y + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = True
            self.start_point = (x, y)
            self.current_point = (x, y)

        elif event == cv2.EVENT_MOUSEMOVE:
            if self.drawing and self.start_point is not None:
                self.current_point = (x, y)
                self.reset_view()
                cv2.rectangle(self.image_show, self.start_point, self.current_point, (0, 255, 255), 1)

        elif event == cv2.EVENT_LBUTTONUP:
            if self.drawing and self.start_point is not None:
                self.drawing = False
                x0, y0 = self.start_point
                x1, y1 = x, y
                x_min, y_min = min(x0, x1), min(y0, y1)
                x_max, y_max = max(x0, x1), max(y0, y1)
                w = max(1, x_max - x_min)
                h = max(1, y_max - y_min)
                rect = Rect(x=x_min, y=y_min, w=w, h=h)
                self.rects.append(rect)
                self.reset_view()

        elif event == cv2.EVENT_RBUTTONDOWN:
            # undo rect cuối
            if self.rects:
                self.rects.pop()
                self.reset_view()

    def run(self, max_rects: int = 13) -> List[Rect]:
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)

        self.reset_view()
        while True:
            # hiển thị hướng dẫn đơn giản trên ảnh
            overlay = self.image_show.copy()
            text = f"Rects: {len(self.rects)}/{max_rects} | Left: ve rect, Right: undo, Enter: luu, ESC: thoat"
            cv2.putText(
                overlay,
                text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(self.window_name, overlay)

            key = cv2.waitKey(20) & 0xFF
            if key in (13, 32):  # Enter hoặc Space
                # chỉ cho phép lưu nếu có ít nhất 3 rect
                if len(self.rects) > 0:
                    break
            elif key in (27, ord("q")):
                self.rects = []
                break

            # auto stop nếu đủ max_rects
            if len(self.rects) >= max_rects:
                break

        cv2.destroyWindow(self.window_name)
        return self.rects


def _rects_to_relative(rects: List[Rect], screen_w: int, screen_h: int):
    result = []
    for idx, r in enumerate(rects, start=1):
        result.append(
            {
                "index": idx,
                "x": round(r.x / screen_w, 4),
                "y": round(r.y / screen_h, 4),
                "w": round(r.w / screen_w, 4),
                "h": round(r.h / screen_h, 4),
            }
        )
    return result


def _save_layout_yaml(base_dir: Path, game_id: str, profile_id: int, rel_cards: list) -> None:
    cfg_path = base_dir / "config" / "layouts_mau_binh.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    game_cfg = data.get(game_id, {})
    profiles = game_cfg.get("profiles", {})

    profiles[str(profile_id)] = {"self_cards": rel_cards}
    game_cfg["profiles"] = profiles
    data[game_id] = game_cfg

    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def run_manual_calibrate(game_id: str = "mau_binh_siteA", profile_id: int = 1) -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger

    frame = capture_screen()
    if frame is None:
        logger.error("LayoutCalibrate: không chụp được màn hình.")
        return

    h, w = frame.shape[:2]
    logger.info("LayoutCalibrate: frame size = %dx%d", w, h)

    drawer = RectDrawer("Kendz Layout Calibrate", frame)
    rects = drawer.run(max_rects=13)

    if not rects:
        logger.warning("LayoutCalibrate: không có rect nào được lưu (user thoát?).")
        return

    logger.info("LayoutCalibrate: đã nhận %d rect, sẽ ghi vào YAML.", len(rects))

    rel_cards = _rects_to_relative(rects, w, h)
    base_dir = Path(__file__).resolve().parents[2]
    _save_layout_yaml(base_dir, game_id, profile_id, rel_cards)

    logger.info(
        "LayoutCalibrate: đã lưu layout cho game_id=%s profile_id=%d vào config/layouts_mau_binh.yaml",
        game_id,
        profile_id,
    )


def main() -> None:
    ctx = AppContext.bootstrap()
    game_id = ctx.config.core.default_game_id
    run_manual_calibrate(game_id=game_id, profile_id=1)


if __name__ == "__main__":
    main()
