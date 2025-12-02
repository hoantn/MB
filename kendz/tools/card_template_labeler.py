# kendz/tools/card_template_labeler.py
"""Tool gán nhãn template 52 lá từ các card crop.

Mục đích:
- Bạn đã có các ảnh card_01.png..card_13.png trong
  `data/vision_cards/<game_id>/profile_1/`.
- Dùng tool này để gán mã bài (vd: 3S, TD, AH, ...) cho từng ảnh.
- Tool sẽ lưu template chuẩn vào:
    `data/card_templates/<game_id>/<code>.png`

Cách dùng:
    python -m kendz.tools.card_template_labeler

Quy trình khuyến nghị:
    1. Chạy Kendz main vài ván để thu đủ nhiều card_*.png khác nhau.
    2. Chạy tool labeler, chỉ định folder nguồn.
    3. Gán mã cho từng ảnh cho tới khi đủ ~52 lá.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
from kendz.cards.templates import find_next_variant_index

from kendz.core.app_context import AppContext

RANKS = "23456789TJQKA"
SUITS = "CDHS"



def _is_valid_code(code: str) -> bool:
    code = code.upper()
    if len(code) != 2:
        return False
    return (code[0] in RANKS) and (code[1] in SUITS)


def run_labeler(game_id: str = "mau_binh_siteA", profile_id: int = 1) -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger

    base_dir = Path(__file__).resolve().parents[2]

    src_dir = base_dir / "data" / "vision_cards" / game_id / f"profile_{profile_id}"
    if not src_dir.exists():
        logger.error("Không tìm thấy folder card crop: %s", src_dir)
        return

    tpl_dir = base_dir / "data" / "card_templates" / game_id
    tpl_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Labeler: nguồn card crop = %s", src_dir)
    logger.info("Labeler: sẽ lưu template vào %s", tpl_dir)
    logger.info("Hướng dẫn: gõ mã bài (vd: 3S, TD, AH). Gõ 'skip' để bỏ qua, 'q' để thoát.")

    cv2.namedWindow("Kendz Labeler", cv2.WINDOW_NORMAL)

    for img_path in sorted(src_dir.glob("card_*.png")):
        img = cv2.imread(str(img_path))
        if img is None:
            continue

        while True:
            show = img.copy()
            info_text = f"File: {img_path.name}"
            cv2.putText(
                show,
                info_text,
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow("Kendz Labeler", show)
            cv2.waitKey(10)

            code = input(f"Nhập mã bài cho {img_path.name} (vd 3S, TD, AH, skip, q): ").strip()
            if code.lower() == "q":
                logger.info("Thoát labeler theo yêu cầu user.")
                cv2.destroyWindow("Kendz Labeler")
                return
            if code.lower() == "skip":
                logger.info("Bỏ qua %s", img_path.name)
                break
            if not _is_valid_code(code):
                print("Mã không hợp lệ. RANK: 2-9,T,J,Q,K,A; SUIT: C,D,H,S. Ví dụ: 3S, TD, AH.")
                continue

            code = code.upper()
            # Lưu template dưới dạng biến thể, không ghi đè.
            next_idx = find_next_variant_index(base_dir, game_id, code)
            out_path = tpl_dir / f"{code}_{next_idx}.png"
            cv2.imwrite(str(out_path), img)
            logger.info(
                "Đã lưu template %s (biến thể %s) -> %s",
                code,
                next_idx,
                out_path,
            )
            break

    cv2.destroyWindow("Kendz Labeler")
    logger.info("Đã xử lý xong tất cả card_*.png trong %s", src_dir)


def main() -> None:
    ctx = AppContext.bootstrap()
    game_id = ctx.config.core.default_game_id
    run_labeler(game_id=game_id, profile_id=1)


if __name__ == "__main__":
    main()
