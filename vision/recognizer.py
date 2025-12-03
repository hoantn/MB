from typing import Tuple, Dict, List
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from core.constants import TEMPLATES_DIR
from core.logger import log
import os


def pil_to_gray_np(img: Image.Image) -> np.ndarray:
    """Chuyển PIL.Image → grayscale np.ndarray."""
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)


# =========================
# LOAD TOÀN BỘ TEMPLATE
# =========================

@lru_cache(maxsize=1)
def _load_all_templates() -> Dict[str, List[np.ndarray]]:
    """
    Load toàn bộ templates trong vision/templates.
    Mỗi subfolder tên card_code (VD: 9C, AR, ...) chứa nhiều ảnh template.
    Kết quả: dict[code] = list[gray_np].
    """
    templates: Dict[str, List[np.ndarray]] = {}
    if not os.path.isdir(TEMPLATES_DIR):
        log.warning("TEMPLATES_DIR không tồn tại: %s", TEMPLATES_DIR)
        return templates

    for card_code in os.listdir(TEMPLATES_DIR):
        folder = os.path.join(TEMPLATES_DIR, card_code)
        if not os.path.isdir(folder):
            continue
        imgs: List[np.ndarray] = []
        for fname in os.listdir(folder):
            if not fname.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            path = os.path.join(folder, fname)
            try:
                img = Image.open(path)
                gray = pil_to_gray_np(img)
                imgs.append(gray)
            except Exception as e:
                log.error("Lỗi load template %s: %s", path, e)
        if imgs:
            templates[card_code] = imgs
    log.info("Loaded templates for %d card codes", len(templates))
    return templates


# =========================
# HỖ TRỢ CHUẨN HÓA & ROI
# =========================

TARGET_W = 80   # kích thước chuẩn để so khớp
TARGET_H = 120


def _normalize_gray(gray: np.ndarray) -> np.ndarray:
    """
    Resize về (TARGET_W, TARGET_H) và chuẩn hóa 0..1.
    Không quá quan trọng card gốc to/nhỏ lệch; mọi thứ về chung 1 form.
    """
    if gray is None or gray.size == 0:
        raise ValueError("gray image rỗng")
    resized = cv2.resize(gray, (TARGET_W, TARGET_H), interpolation=cv2.INTER_LINEAR)
    arr = resized.astype(np.float32) / 255.0
    return arr


def _extract_rank_roi(norm_gray: np.ndarray) -> np.ndarray:
    """
    Lấy vùng góc trên trái – nơi có số + suit nhỏ.
    Tỷ lệ box dựa trên dáng bài hiện tại; nếu game đổi skin thì chỉ cần chỉnh phần này.
    """
    h, w = norm_gray.shape
    # ví dụ: 40% width, 35% height ở góc trên trái
    x0, y0 = 0, 0
    x1, y1 = int(w * 0.40), int(h * 0.35)
    roi = norm_gray[y0:y1, x0:x1]
    return roi


def _match_score(src: np.ndarray, tmpl: np.ndarray) -> float:
    """
    Match src với tmpl (cùng size 2D).
    Dùng TM_CCOEFF_NORMED, kết quả [-1..1] → map về [0..1].
    """
    if src.shape != tmpl.shape:
        tmpl = cv2.resize(tmpl, (src.shape[1], src.shape[0]), interpolation=cv2.INTER_LINEAR)
    res = cv2.matchTemplate(src, tmpl, cv2.TM_CCOEFF_NORMED)
    if res.size == 0:
        return 0.0
    _, max_val, _, _ = cv2.minMaxLoc(res)
    # map [-1..1] → [0..1]
    score = (float(max_val) + 1.0) / 2.0
    # clamp
    return max(0.0, min(1.0, score))


# =========================
# API CHÍNH
# =========================

def recognize_card(img: Image.Image) -> Tuple[str, float, bool]:
    """
    Nhận diện lá bài bằng template matching nâng cấp:

    - Chuẩn hóa slot + template về cùng size (TARGET_W x TARGET_H).
    - So khớp:
        + full_score: toàn bộ lá.
        + rank_roi_score: ROI góc trên trái.
    - Điểm tổng hợp: score = 0.3 * full_score + 0.7 * rank_roi_score
      (ưu tiên góc rank/suit vì ít bị overlay & nền thay đổi).

    Trả về:
      code: mã lá bài, VD '9C', '2B'; '??' nếu không có template.
      confidence: 0..1
      is_new_shape: luôn True (để cơ chế auto-farm bên ngoài xử lý trùng).
    """
    templates = _load_all_templates()
    if not templates:
        return "??", 0.0, False

    # Chuẩn hóa slot
    gray = pil_to_gray_np(img)
    try:
        norm_slot = _normalize_gray(gray)
    except Exception as e:
        log.error("recognize_card: lỗi normalize slot: %s", e)
        return "??", 0.0, False

    roi_slot = _extract_rank_roi(norm_slot)

    best_code = "??"
    best_score = -1.0

    for code, tmpl_list in templates.items():
        for tmpl_gray in tmpl_list:
            try:
                norm_tmpl = _normalize_gray(tmpl_gray)
            except Exception as e:
                log.error("Lỗi normalize template cho %s: %s", code, e)
                continue

            roi_tmpl = _extract_rank_roi(norm_tmpl)

            full_score = _match_score(norm_slot, norm_tmpl)
            roi_score = _match_score(roi_slot, roi_tmpl)

            # Trọng số: ưu tiên ROI góc trên (rank + suit nhỏ)
            combined = 0.3 * full_score + 0.7 * roi_score

            if combined > best_score:
                best_score = combined
                best_code = code

    if best_score < 0:
        return "??", 0.0, False

    confidence = float(max(0.0, min(1.0, best_score)))
    is_new_shape = True  # logic auto-farm bên ngoài sẽ kiểm tra thêm
    return best_code, confidence, is_new_shape
def reload_templates() -> None:
    """
    Xóa cache templates để lần nhận diện tiếp theo load lại toàn bộ ảnh
    từ TEMPLATES_DIR (dùng sau khi thêm / xóa variant).
    """
    try:
        _load_all_templates.cache_clear()
        log.info("Recognizer template cache cleared (reload_templates).")
    except Exception as e:
        log.error("reload_templates: %s", e)
