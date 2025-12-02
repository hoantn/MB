from __future__ import annotations

"""
Assist realtime cho 1 profile (multi-profile ready).

Mục tiêu:
- Giữ nguyên toàn bộ luồng đang chạy ổn cho profile 1.
- Bổ sung tham số --profile-id để có thể dùng cùng 1 module cho nhiều profile.
- Không thay đổi pipeline, Recognizer hay Engine.

Luồng xử lý mỗi profile:
- Chạy vòng lặp theo FPS cấu hình trong `config/vision.yaml`.
- Mỗi vòng:
  + Dùng Vision.pipeline để chụp màn hình + crop 13 lá của mình (theo profile_id).
  + Dùng Recognizer để nhận diện 13 mã bài từ folder crop tương ứng.
  + Gọi Engine Assistant để lấy gợi ý xếp bài (chi 1/2/3).
  + Log gợi ý nếu bài thay đổi so với vòng trước.
- Dừng bằng Ctrl+C (KeyboardInterrupt).

Cách dùng:
    python -m kendz.tools.assist_profile1_loop          # mặc định profile_id = 1
    python -m kendz.tools.assist_profile1_loop --profile-id 2
    python -m kendz.tools.assist_profile1_loop --profile-id 3

Module này tương thích ngược với bản cũ:
- Nếu không truyền --profile-id, hành vi y hệt: chạy realtime cho profile 1.
"""

import argparse
import time
from pathlib import Path
from typing import List, Optional

from kendz.core.app_context import AppContext
from kendz.vision.pipeline import capture_and_crop_self_cards
from kendz.tools.assist_profile1 import recognize_13_cards
from kendz.engine.assistant import suggest_for_13_cards


def _log_suggestion(logger, cards: List[str], note_header: str = "") -> None:
    """
    Ghi log gợi ý xếp bài cho 13 lá.

    Tách riêng hàm này để sau dễ tái sử dụng cho nhiều profile / UI khác.
    """
    logger.info("AssistLoop: Bài 13 lá (mã code): %s", " ".join(cards))

    suggestion = suggest_for_13_cards(cards)

    logger.info("%sGỢI Ý XẾP BÀI", note_header)
    logger.info("  Chi 1 (3 lá): %s", suggestion.chi1_symbols)
    logger.info("  Chi 2 (5 lá): %s", suggestion.chi2_symbols)
    logger.info("  Chi 3 (5 lá): %s", suggestion.chi3_symbols)
    if suggestion.is_binh_lung:
        logger.warning("  Trạng thái: Binh lũng (theo luật Engine).")
    if suggestion.note:
        logger.info("  Ghi chú: %s", suggestion.note)


def run_realtime_loop(profile_id: int = 1) -> None:
    """
    Chạy vòng lặp realtime assist cho 1 profile cụ thể.

    Tham số:
        profile_id: ID profile trong hệ thống layout/vision (profile_1, profile_2, ...).
    """
    # Khởi tạo AppContext (config, logger, DB, ...)
    ctx = AppContext.bootstrap()
    logger = ctx.logger
    game_id = ctx.config.core.default_game_id

    # Gốc project (dùng cho Recognizer & cấu trúc data hiện tại)
    base_dir = Path(__file__).resolve().parents[2]

    # FPS cho vòng lặp realtime
    fps = getattr(ctx.config.vision, "fps", 4)
    delay = 1.0 / max(fps, 1)  # thời gian nghỉ giữa 2 vòng

    logger.info(
        "AssistLoop: bắt đầu realtime cho game_id=%s, profile=%d, fps=%d",
        game_id,
        profile_id,
        fps,
    )

    last_cards: Optional[List[str]] = None

    try:
        while True:
            # 1) Chụp + crop 13 lá của mình cho profile tương ứng
            try:
                capture_and_crop_self_cards(ctx, profile_id=profile_id)
            except Exception as exc:
                logger.error(
                    "AssistLoop: lỗi khi crop 13 lá (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            # 2) Nhận diện 13 lá từ thư mục crop
            try:
                cards = recognize_13_cards(base_dir, game_id, profile_id, logger)
            except Exception as exc:
                logger.error(
                    "AssistLoop: lỗi khi nhận diện 13 lá (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            # 3) Nếu bài mới giống hệt bài cũ -> bỏ qua để tránh spam log
            if last_cards is not None and cards == last_cards:
                time.sleep(delay)
                continue

            last_cards = cards

            # 4) Gọi Engine Assistant để lấy gợi ý và log
            try:
                _log_suggestion(logger, cards, note_header=f"[Realtime p{profile_id}] ")
            except Exception as exc:
                logger.error(
                    "AssistLoop: lỗi Engine khi xếp bài (profile=%d): %s",
                    profile_id,
                    exc,
                )

            time.sleep(delay)

    except KeyboardInterrupt:
        logger.info(
            "AssistLoop: nhận Ctrl+C, dừng realtime assist profile %d.",
            profile_id,
        )


def main() -> None:
    """
    Entry point khi chạy module từ dòng lệnh.

    Giữ tương thích ngược:
    - Nếu không truyền tham số -> mặc định profile_id = 1.
    - Nếu truyền --profile-id N  -> chạy cho profile N.
    """
    parser = argparse.ArgumentParser(
        description="Kendz realtime assist cho 1 profile.",
    )
    parser.add_argument(
        "--profile-id",
        type=int,
        default=1,
        help="ID profile (mặc định: 1, tương ứng profile_1)",
    )
    args = parser.parse_args()

    print(f"[Kendz] Khởi động realtime assist cho profile_id={args.profile_id} ...")
    run_realtime_loop(profile_id=args.profile_id)


if __name__ == "__main__":
    main()
