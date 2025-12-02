# kendz/tools/auto_layout.py
"""Tool tự động dò layout 13 lá bài (toạ độ) và lưu vào YAML.

Vision Phase 6:
- Thích ứng với game Mậu Binh có 13 lá xếp thành NHIỀU HÀNG (3 hàng: 3 + 5 + 5).
- Phù hợp với giao diện như GO88/CX: chi3 ở trên, chi2 ở giữa, chi1 ở dưới.

Mục tiêu:
- Khi calibrate (chỉ chạy khi cần):
  + Tự phát hiện 13 lá theo nhiều hàng.
  + Gom theo hàng (cluster theo trục Y).
  + Gán index 1..13 theo thứ tự:
    * Hàng trên (chi3): trái -> phải
    * Hàng giữa (chi2): trái -> phải
    * Hàng dưới (chi1): trái -> phải
  + Lưu toạ độ tương đối vào YAML.

- Bình thường:
  + Kendz chỉ đọc `config/layouts_mau_binh.yaml` để crop nhanh.
  + Không chạy auto detect mỗi lần.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
import yaml

from kendz.core.app_context import AppContext
from kendz.vision.capture import capture_screen


@dataclass
class DetectedRect:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> Tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def aspect_ratio(self) -> float:
        if self.h == 0:
            return 0.0
        return self.w / float(self.h)


# -----------------------------
# 1. Dò hình chữ nhật giống lá
# -----------------------------


def _detect_card_rectangles(frame: np.ndarray) -> List[DetectedRect]:
    """Dò các hình chữ nhật giống lá bài trong frame.

    Chiến lược:
    - Dùng Canny edge + findContours.
    - Lọc theo:
      + diện tích tối thiểu (loại noise nhỏ).
      + tỷ lệ w/h ~ 0.6..0.8 (lá bài đứng).
    - Chỉ giữ contour ở nửa dưới màn hình (thường là bài người chơi).
    """
    h, w = frame.shape[:2]

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rects: List[DetectedRect] = []
    min_area = (w * h) * 0.0005  # có thể chỉnh nếu cần

    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < min_area:
            continue

        # chỉ xét nửa dưới màn hình
        y_center = y + ch / 2.0
        if y_center < h * 0.4:
            continue

        rect = DetectedRect(x=x, y=y, w=cw, h=ch)
        ar = rect.aspect_ratio
        # lá bài đứng: w/h khoảng 0.55 - 0.85
        if 0.55 <= ar <= 0.9:
            rects.append(rect)

    return rects


# -----------------------------------
# 2. Chọn 13 rect "đẹp" nhất (thô)
# -----------------------------------


def _select_best_13(rects: List[DetectedRect]) -> List[DetectedRect]:
    """Chọn ra 13 hình chữ nhật đại diện cho 13 lá (chưa xếp hàng).

    Heuristic:
    - Nếu ít hơn 13 rect -> trả về empty list.
    - Tính median height & area, chọn các rect gần median nhất.
    - Sau đó sort theo x để loại bớt outlier.
    """
    if len(rects) < 13:
        return []

    heights = sorted(r.h for r in rects)
    median_h = heights[len(heights) // 2]

    # lọc các rect có height gần median
    filtered = [
        r for r in rects
        if 0.7 * median_h <= r.h <= 1.3 * median_h
    ]
    if len(filtered) < 13:
        filtered = rects

    # sort theo x và lấy 13 rect giữa để tạm ổn định
    filtered.sort(key=lambda r: r.x)
    if len(filtered) > 13:
        start = max(0, (len(filtered) - 13) // 2)
        filtered = filtered[start:start + 13]

    return filtered[:13]


# -----------------------------------
# 3. Gom thành 3 hàng theo Y
# -----------------------------------


def _group_rows_by_y(rects: List[DetectedRect]) -> List[List[DetectedRect]]:
    """Gom các rect thành 3 hàng dựa trên y_center.

    Thuật toán:
    - sort theo y_center tăng dần.
    - tìm 2 khoảng cách lớn nhất giữa các y_center liên tiếp -> ngưỡng tách hàng.
    - cắt list thành 3 nhóm tương ứng (trên, giữa, dưới).
    """
    if len(rects) != 13:
        # vẫn cố gắng gom, nhưng yêu cầu chuẩn là 13
        pass

    rects_sorted = sorted(rects, key=lambda r: r.y + r.h / 2.0)
    y_centers = [r.y + r.h / 2.0 for r in rects_sorted]

    # tính khoảng cách giữa các y liên tiếp
    gaps = []
    for i in range(len(y_centers) - 1):
        gaps.append((y_centers[i + 1] - y_centers[i], i))

    # nếu không đủ phần tử, trả về 1 nhóm
    if len(gaps) < 2:
        return [rects_sorted]

    # chọn 2 gap lớn nhất
    gaps_sorted = sorted(gaps, key=lambda g: g[0], reverse=True)
    cut1_idx = min(gaps_sorted[0][1], gaps_sorted[1][1])
    cut2_idx = max(gaps_sorted[0][1], gaps_sorted[1][1])

    row1 = rects_sorted[: cut1_idx + 1]
    row2 = rects_sorted[cut1_idx + 1 : cut2_idx + 1]
    row3 = rects_sorted[cut2_idx + 1 :]

    rows = [row1, row2, row3]

    # sort từng hàng theo X tăng dần
    for row in rows:
        row.sort(key=lambda r: r.x)

    return rows


# -----------------------------------
# 4. Đánh index 1..13 theo 3 hàng
# -----------------------------------


def _rows_to_ordered_list(rows: List[List[DetectedRect]]) -> List[DetectedRect]:
    """Flatten 3 hàng (top, middle, bottom) thành list 13 rect.

    - Giả định game Mậu Binh hiển thị:
      + Hàng trên (chi3): 3 lá
      + Hàng giữa (chi2): 5 lá
      + Hàng dưới (chi1): 5 lá

    - rows đã được sort theo y_center tăng dần => rows[0]=trên, rows[1]=giữa, rows[2]=dưới.
    - Trong mỗi row đã sort theo X tăng dần.
    """
    if len(rows) == 1:
        # fallback: 1 hàng
        return rows[0]

    # Nếu có đúng 3 hàng thì flatten theo thứ tự trên -> giữa -> dưới
    ordered: List[DetectedRect] = []
    for row in rows:
        ordered.extend(row)

    return ordered


def _rects_to_relative(rects: List[DetectedRect], screen_w: int, screen_h: int):
    """Chuyển danh sách rect pixel sang toạ độ tương đối 0..1.

    Ở đây rects đã ở đúng thứ tự 1..13 theo luật game.
    """
    result = []
    for idx, r in enumerate(rects, start=1):
        rel = {
            "index": idx,
            "x": round(r.x / screen_w, 4),
            "y": round(r.y / screen_h, 4),
            "w": round(r.w / screen_w, 4),
            "h": round(r.h / screen_h, 4),
        }
        result.append(rel)
    return result


# -----------------------------------
# 5. Ghi YAML + ảnh debug
# -----------------------------------


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


def _save_debug_image(base_dir: Path, frame: np.ndarray, rects: List[DetectedRect]) -> None:
    """Lưu ảnh debug, vẽ hình chữ nhật và index 1..13."""
    debug = frame.copy()
    for i, r in enumerate(rects, start=1):
        cv2.rectangle(debug, (r.x, r.y), (r.x + r.w, r.y + r.h), (0, 255, 0), 2)
        cv2.putText(
            debug,
            str(i),
            (r.x + 5, r.y + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

    out_path = base_dir / "data" / "vision_layout_debug.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), debug)


# -----------------------------------
# 6. Hàm chính (calibrate)
# -----------------------------------


def run_auto_layout(game_id: str = "mau_binh_siteA", profile_id: int = 1) -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger

    frame = capture_screen()
    if frame is None:
        logger.error("AutoLayout: không chụp được màn hình.")
        return

    h, w = frame.shape[:2]
    logger.info("AutoLayout: frame size = %dx%d", w, h)

    rects = _detect_card_rectangles(frame)
    logger.info("AutoLayout: phát hiện %d vùng giống lá bài (thô).", len(rects))

    best = _select_best_13(rects)
    if len(best) < 13:
        logger.error(
            "AutoLayout: không chọn đủ 13 hình chữ nhật (chỉ có %d).",
            len(best),
        )
        base_dir = Path(__file__).resolve().parents[2]
        _save_debug_image(base_dir, frame, best)
        return

    rows = _group_rows_by_y(best)
    ordered = _rows_to_ordered_list(rows)

    if len(ordered) != 13:
        logger.error(
            "AutoLayout: sau khi gom hàng vẫn không đủ 13 lá (có %d).",
            len(ordered),
        )

    rel_cards = _rects_to_relative(ordered, w, h)

    base_dir = Path(__file__).resolve().parents[2]
    _save_layout_yaml(base_dir, game_id, profile_id, rel_cards)
    _save_debug_image(base_dir, frame, ordered)

    logger.info(
        "AutoLayout: đã lưu layout cho game_id=%s profile=%d vào config/layouts_mau_binh.yaml",
        game_id,
        profile_id,
    )
    logger.info(
        "AutoLayout: kiểm tra ảnh debug tại data/vision_layout_debug.png để xác nhận 13 khung cắt theo thứ tự 1..13 (3 hàng: 3+5+5)."
    )


def main() -> None:
    ctx = AppContext.bootstrap()
    game_id = ctx.config.core.default_game_id
    run_auto_layout(game_id=game_id, profile_id=1)


if __name__ == "__main__":
    main()
