from __future__ import annotations

"""Assist 1 profile: Vision -> Recognizer -> Engine -> Gợi ý.

Luồng xử lý:
1. Đọc config core để biết game_id mặc định.
2. Đọc 13 crop lá bài tại data/vision_cards/<game_id>/profile_1/card_*.png.
   (Giả định phần Vision layout đã chạy và tạo thư mục này.)
3. Dùng CardRecognizer (suit-first) để nhận diện 13 mã bài.
4. Gửi list 13 mã vào Engine (arrange_advanced) thông qua lớp trợ lý engine.assistant.
5. Log gợi ý xếp bài (chi 1/2/3) kèm kí hiệu ♣ ♦ ♥ ♠.
"""

from pathlib import Path
from typing import List

import cv2

from kendz.core.app_context import AppContext
from kendz.vision.card_recognizer import CardRecognizer, SUIT_SYMBOLS
from kendz.engine.assistant import suggest_for_13_cards


def recognize_13_cards(base_dir: Path, game_id: str, profile_id: int, logger) -> List[str]:
    """Đọc 13 file card_*.png và trả về list mã bài.

    Nếu thiếu hoặc hỏng file sẽ raise lỗi để caller biết.
    """
    src_dir = base_dir / "data" / "vision_cards" / game_id / f"profile_{profile_id}"
    if not src_dir.exists():
        raise FileNotFoundError(f"Không tìm thấy folder card crop: {src_dir}")

    recognizer = CardRecognizer(base_dir=base_dir, game_id=game_id)
    if not recognizer.templates:
        raise RuntimeError(
            f"Chưa có template nào trong data/card_templates/{game_id}. "
            "Hãy chuẩn bị template 52 lá trước."
        )

    logger.info(
        "Assist: dùng template của game_id=%s, tổng %d template.",
        game_id,
        len(recognizer.templates),
    )

    card_codes: List[str] = []
    debug_imgs = []

    card_paths = sorted(src_dir.glob("card_*.png"))
    if len(card_paths) != 13:
        raise RuntimeError(
            f"Mong đợi 13 file card_*.png trong {src_dir}, hiện có {len(card_paths)}."
        )

    for p in card_paths:
        img = cv2.imread(str(p))
        if img is None:
            raise RuntimeError(f"Không đọc được ảnh: {p}")
        rc = recognizer.recognize_card(img)
        code = rc.code
        suit = rc.suit
        sym = SUIT_SYMBOLS.get(suit, "?")
        logger.info(
            "  %s -> %s%s | score=%.3f, second=%.3f",
            p.name,
            code[0] if len(code) == 2 else "?",
            sym,
            rc.score,
            rc.second_score,
        )

        card_codes.append(code)

        # Ảnh debug
        debug = img.copy()
        label = f"{code[0] if len(code)==2 else '?'}{sym} ({rc.score:.2f})"
        cv2.putText(
            debug,
            label,
            (5, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        debug = cv2.resize(debug, (120, 180), interpolation=cv2.INTER_AREA)
        debug_imgs.append(debug)

    if debug_imgs:
        debug_final = cv2.vconcat(debug_imgs)
        out_path = base_dir / "data" / "vision_assist_profile1_debug.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), debug_final)
        logger.info("Assist: đã lưu ảnh debug recognition tại %s", out_path)

    return card_codes


def main() -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger
    game_id = ctx.config.core.default_game_id
    profile_id = 1

    base_dir = Path(__file__).resolve().parents[2]
    logger.info("Assist 1 profile: game_id=%s, profile=%s", game_id, profile_id)

    try:
        cards = recognize_13_cards(base_dir, game_id, profile_id, logger)
    except Exception as exc:
        logger.error("Assist: lỗi khi nhận diện 13 lá: %s", exc)
        return

    logger.info("Assist: Bài 13 lá (mã code): %s", " ".join(cards))

    try:
        suggestion = suggest_for_13_cards(cards)
    except Exception as exc:
        logger.error("Assist: lỗi Engine khi sắp xếp bài: %s", exc)
        return

    logger.info("Assist: GỢI Ý XẾP BÀI")
    logger.info("  Chi 1 (3 lá): %s", suggestion.chi1_symbols)
    logger.info("  Chi 2 (5 lá): %s", suggestion.chi2_symbols)
    logger.info("  Chi 3 (5 lá): %s", suggestion.chi3_symbols)
    if suggestion.is_binh_lung:
        logger.warning("  Trạng thái: Binh lũng (theo luật Engine).")
    if suggestion.note:
        logger.info("  Ghi chú: %s", suggestion.note)


if __name__ == "__main__":
    main()
