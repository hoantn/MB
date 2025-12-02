# kendz/tools/auto_template_layout.py
"""Auto layout dùng Template Matching (Phase 7.1 - Multi template).

- Dùng 2 template:
  + back_full.png : lá úp hàng dưới (đủ cạnh trên/dưới).
  + back_cut.png  : lá úp bị cắt (2 hàng trên).
- Template matching đa scale cho cả 2 template, merge kết quả, NMS.
- Chọn cluster người chơi (Y lớn nhất), gom 3 hàng (3+5+5), lưu layout.

Cách dùng:
  1. Mở bàn Mậu Binh (GO88/CX), để 13 lá bài của bạn hiển thị đầy đủ.
  2. Chạy: `python -m kendz.tools.auto_template_layout`
  3. Kiểm tra:
     - config/layouts_mau_binh.yaml
     - data/vision_layout_debug.png (13 khung xanh, index 1..13).
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
    score: float
    template_name: str

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


# -----------------------
# Helper: NMS cho boxes
# -----------------------


def _nms(rects: List[DetectedRect], overlap_thresh: float = 0.35) -> List[DetectedRect]:
    """Non-maximum suppression đơn giản trên list DetectedRect."""
    if not rects:
        return []

    rects = sorted(rects, key=lambda r: r.score, reverse=True)
    picked: List[DetectedRect] = []

    def iou(a: DetectedRect, b: DetectedRect) -> float:
        x1 = max(a.x, b.x)
        y1 = max(a.y, b.y)
        x2 = min(a.x + a.w, b.x + b.w)
        y2 = min(a.y + a.h, b.y + b.h)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2 - x1) * (y2 - y1)
        union = a.area + b.area - inter
        return inter / union if union > 0 else 0.0

    for r in rects:
        if all(iou(r, p) < overlap_thresh for p in picked):
            picked.append(r)

    return picked


# ---------------------------------------
# 1. Template matching đa scale 1 template
# ---------------------------------------


def _detect_by_template_single(frame_gray, tpl_gray_orig, tpl_name: str,
                               scale_list, threshold: float) -> List[DetectedRect]:
    h, w = frame_gray.shape[:2]
    th0, tw0 = tpl_gray_orig.shape[:2]
    rects: List[DetectedRect] = []

    for scale in scale_list:
        th = int(th0 * scale)
        tw = int(tw0 * scale)
        if th < 10 or tw < 10:
            continue
        if th >= h or tw >= w:
            continue

        tpl_gray = cv2.resize(tpl_gray_orig, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(frame_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)

        loc = np.where(res >= threshold)
        for pt in zip(*loc[::-1]):  # (x, y)
            x, y = int(pt[0]), int(pt[1])
            score = float(res[y, x])
            rects.append(DetectedRect(x=x, y=y, w=tw, h=th, score=score, template_name=tpl_name))

    return rects


def _detect_by_templates(frame: np.ndarray, templates: dict) -> List[DetectedRect]:
    """Dò lá úp bằng nhiều template, merge và NMS."""
    frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    all_rects: List[DetectedRect] = []

    # back_full: dùng ngưỡng cao hơn một chút
    if "back_full" in templates:
        tpl_full = cv2.cvtColor(templates["back_full"], cv2.COLOR_BGR2GRAY)
        rects_full = _detect_by_template_single(
            frame_gray,
            tpl_full,
            "back_full",
            scale_list=[0.7, 0.8, 0.9, 1.0, 1.1, 1.2],
            threshold=0.80,
        )
        all_rects.extend(rects_full)

    # back_cut: dùng threshold thấp hơn chút (vì bị cắt cạnh)
    if "back_cut" in templates:
        tpl_cut = cv2.cvtColor(templates["back_cut"], cv2.COLOR_BGR2GRAY)
        rects_cut = _detect_by_template_single(
            frame_gray,
            tpl_cut,
            "back_cut",
            scale_list=[0.7, 0.8, 0.9, 1.0, 1.1, 1.2],
            threshold=0.78,
        )
        all_rects.extend(rects_cut)

    return _nms(all_rects, overlap_thresh=0.35)


# ---------------------------------------
# 2. Lọc cluster lá của người chơi
# ---------------------------------------


def _select_player_cluster(rects: List[DetectedRect]) -> List[DetectedRect]:
    """Chọn cụm lá bài của người chơi (cluster có Y-center lớn nhất)."""
    if not rects:
        return []

    rects_sorted = sorted(rects, key=lambda r: r.y + r.h / 2.0)
    n = len(rects_sorted)
    if n <= 13:
        return rects_sorted

    # chia thô 3 tầng theo index
    split1 = n // 3
    split2 = 2 * n // 3
    clusters = [
        rects_sorted[:split1],
        rects_sorted[split1:split2],
        rects_sorted[split2:],
    ]

    def avg_y(cs: List[DetectedRect]) -> float:
        return float(sum(r.y + r.h / 2.0 for r in cs)) / len(cs) if cs else 0.0

    clusters.sort(key=lambda cs: avg_y(cs))
    player_cluster = clusters[-1]

    # nếu cụm có >13 lá thì lấy 13 lá gần avg_y nhất
    if len(player_cluster) > 13:
        mean_y = avg_y(player_cluster)
        player_cluster = sorted(
            player_cluster,
            key=lambda r: abs((r.y + r.h / 2.0) - mean_y),
        )[:13]

    return player_cluster


# ---------------------------------------
# 3. Gom 3 hàng (3 + 5 + 5)
# ---------------------------------------


def _group_rows_by_y(rects: List[DetectedRect]) -> List[List[DetectedRect]]:
    if len(rects) < 3:
        return [rects]

    rects_sorted = sorted(rects, key=lambda r: r.y + r.h / 2.0)
    y_centers = [r.y + r.h / 2.0 for r in rects_sorted]

    gaps = []
    for i in range(len(y_centers) - 1):
        gaps.append((y_centers[i + 1] - y_centers[i], i))

    if len(gaps) < 2:
        return [rects_sorted]

    gaps_sorted = sorted(gaps, key=lambda g: g[0], reverse=True)
    cut1_idx = min(gaps_sorted[0][1], gaps_sorted[1][1])
    cut2_idx = max(gaps_sorted[0][1], gaps_sorted[1][1])

    row1 = rects_sorted[: cut1_idx + 1]
    row2 = rects_sorted[cut1_idx + 1 : cut2_idx + 1]
    row3 = rects_sorted[cut2_idx + 1 :]

    rows = [row1, row2, row3]
    for row in rows:
        row.sort(key=lambda r: r.x)
    return rows


def _rows_to_ordered_list(rows: List[List[DetectedRect]]) -> List[DetectedRect]:
    if len(rows) == 1:
        return rows[0]
    ordered: List[DetectedRect] = []
    for row in rows:
        ordered.extend(row)
    return ordered


def _rects_to_relative(rects: List[DetectedRect], screen_w: int, screen_h: int):
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


# ---------------------------------------
# 4. Ghi YAML + debug image
# ---------------------------------------


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


def _save_debug_image(base_dir: Path, frame, rects: List[DetectedRect]) -> None:
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


# ---------------------------------------
# 5. Hàm chính calibrate
# ---------------------------------------


def run_auto_template_layout(game_id: str = "mau_binh_siteA", profile_id: int = 1) -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger

    frame = capture_screen()
    if frame is None:
        logger.error("AutoTemplateLayout: không chụp được màn hình.")
        return

    h, w = frame.shape[:2]
    logger.info("AutoTemplateLayout: frame size = %dx%d", w, h)

    base_dir = Path(__file__).resolve().parents[2]
    tpl_dir = base_dir / "data" / "templates" / game_id

    templates = {}
    full_path = tpl_dir / "back_full.png"
    cut_path = tpl_dir / "back_cut.png"

    if full_path.exists():
        templates["back_full"] = cv2.imread(str(full_path))
    if cut_path.exists():
        templates["back_cut"] = cv2.imread(str(cut_path))

    if not templates:
        logger.error("AutoTemplateLayout: không tìm thấy template nào trong %s", tpl_dir)
        return

    rects = _detect_by_templates(frame, templates)
    logger.info("AutoTemplateLayout: phát hiện %d lá bài úp (sau NMS).", len(rects))

    if not rects:
        logger.error("AutoTemplateLayout: không nhận được lá nào. Cần kiểm tra lại template.")
        _save_debug_image(base_dir, frame, [])
        return

    player_rects = _select_player_cluster(rects)
    logger.info("AutoTemplateLayout: cụm người chơi có %d lá (thô).", len(player_rects))

    rows = _group_rows_by_y(player_rects)
    ordered = _rows_to_ordered_list(rows)

    if len(ordered) < 5:
        logger.error("AutoTemplateLayout: số lá sau gom hàng quá ít (%d).", len(ordered))
    elif len(ordered) > 13:
        mean_y = sum(r.y + r.h / 2.0 for r in ordered) / len(ordered)
        ordered = sorted(ordered, key=lambda r: abs((r.y + r.h / 2.0) - mean_y))[:13]

    ordered = sorted(ordered, key=lambda r: (r.y + r.h / 2.0, r.x))

    rel_cards = _rects_to_relative(ordered, w, h)

    _save_layout_yaml(base_dir, game_id, profile_id, rel_cards)
    _save_debug_image(base_dir, frame, ordered)

    logger.info(
        "AutoTemplateLayout: đã lưu layout cho game_id=%s profile=%d vào config/layouts_mau_binh.yaml",
        game_id,
        profile_id,
    )
    logger.info(
        "AutoTemplateLayout: kiểm tra ảnh debug tại data/vision_layout_debug.png để xác nhận 13 khung."
    )


def main() -> None:
    ctx = AppContext.bootstrap()
    game_id = ctx.config.core.default_game_id
    run_auto_template_layout(game_id=game_id, profile_id=1)


if __name__ == "__main__":
    main()
