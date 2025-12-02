from __future__ import annotations

"""Test Recognizer trên 13 lá crop (Phase 9, suit-first + confidence).

- Đọc card_*.png từ data/vision_cards/<game_id>/profile_1/
- Dùng CardRecognizer suit-first + confidence check.
- Log CHẤT bằng ký hiệu ♣ ♦ ♥ ♠.
- Ghi ảnh debug 1 cột (tự resize về cùng kích thước để tránh lỗi shape).
"""

from pathlib import Path
from typing import List

import cv2
import numpy as np

from kendz.core.app_context import AppContext
from kendz.vision.card_recognizer import CardRecognizer, SUIT_SYMBOLS


def run_test(game_id: str, profile_id: int = 1) -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger

    base_dir = Path(__file__).resolve().parents[2]
    cards_dir = base_dir / "data" / "vision_cards" / game_id / f"profile_{profile_id}"

    if not cards_dir.exists():
        raise FileNotFoundError(cards_dir)

    logger.info("Test Recognizer Phase 9 - game_id=%s, profile=%d", game_id, profile_id)

    # Lấy ngưỡng từ config nếu có
    min_score = getattr(ctx.config.vision, "card_confidence_threshold", 0.75)
    min_margin = 0.03  # biên độ tối thiểu giữa best_score và second_score

    recognizer = CardRecognizer(
        base_dir=base_dir,
        game_id=game_id,
        min_score=min_score,
        min_margin=min_margin,
    )

    card_paths: List[Path] = sorted(cards_dir.glob("card_*.png"))
    if not card_paths:
        logger.warning("Không tìm thấy card_*.png trong %s", cards_dir)
        return

    debug_imgs: List = []

    for p in card_paths:
        img = cv2.imread(str(p))
        if img is None:
            continue

        rc = recognizer.recognize_card(img)

        suit_symbol = SUIT_SYMBOLS.get(rc.suit, "?")
        status = "OK" if rc.is_confident else "LOW"

        logger.info(
            "Card %s: code=%s (%s), score=%.4f, second=%.4f, margin=%.4f, status=%s",
            p.name,
            rc.code,
            suit_symbol,
            rc.score,
            rc.second_score,
            rc.confidence_margin,
            status,
        )

        debug_imgs.append(img)

    # Gộp thành 1 ảnh debug dọc (resize tất cả về cùng (w,h))
    if debug_imgs:
        h, w, c = debug_imgs[0].shape
        total_h = h * len(debug_imgs)
        canvas = 255 * np.ones((total_h, w, c), dtype=debug_imgs[0].dtype)
        for idx, im in enumerate(debug_imgs):
            im_resized = cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA)
            canvas[idx * h : (idx + 1) * h, 0:w] = im_resized

        out_path = base_dir / "data" / "vision_recognizer_debug.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), canvas)
        logger.info("Đã lưu ảnh debug recognizer tại %s", out_path)


def main() -> None:
    ctx = AppContext.bootstrap()
    game_id = ctx.config.core.default_game_id
    run_test(game_id=game_id, profile_id=1)


if __name__ == "__main__":
    main()
