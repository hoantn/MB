from __future__ import annotations

"""Tool Phase 8 – Mậu Binh Automation (dry-run).

Chức năng:
- Sử dụng lại pipeline + Recognizer + Engine giống assist_profile1_loop.
- Thay vì chỉ log gợi ý, tool này còn tạo ra "kế hoạch đánh" (strategy)
  từ ChiSuggestion và log chi tiết các bước.

Quan trọng:
- CHƯA thực hiện click chuột thật, chỉ dry-run (log text).
- Mục tiêu là kiểm tra logic xếp bài của Engine và dự kiến thao tác,
  trước khi code phần auto-click thực sự.

Cách dùng (tương tự assist_profile1_loop):

    python -m kendz.tools.auto_mau_binh_dryrun --profile-id 1
    python -m kendz.tools.auto_mau_binh_dryrun --profile-id 2
    python -m kendz.tools.auto_mau_binh_dryrun --profile-id 3

Mỗi profile nên chạy ở 1 cửa sổ CMD riêng.
"""

import argparse
import time
from pathlib import Path
from typing import List, Optional

from kendz.core.app_context import AppContext
from kendz.vision.pipeline import capture_and_crop_self_cards
from kendz.tools.assist_profile1 import recognize_13_cards
from kendz.engine.assistant import suggest_for_13_cards
from kendz.automation.mau_binh_plan import build_strategy_from_suggestion


def run_dryrun_loop(profile_id: int = 1) -> None:
    """Chạy vòng lặp Phase 8 ở chế độ dry-run cho 1 profile.

    Luồng cho mỗi vòng:
        - Vision: crop 13 lá của profile tương ứng.
        - Recognizer: nhận diện 13 lá.
        - Engine: gợi ý xếp bài (ChiSuggestion).
        - Planner: build strategy (list các bước) và log ra console.

    Không thực hiện click chuột thật.
    """
    ctx = AppContext.bootstrap()
    logger = ctx.logger
    game_id = ctx.config.core.default_game_id

    base_dir = Path(__file__).resolve().parents[2]

    fps = getattr(ctx.config.vision, "fps", 2)
    delay = 1.0 / max(fps, 1)

    logger.info(
        "AutoDryRun: bắt đầu Phase 8 dry-run cho game_id=%s, profile=%d, fps=%d",
        game_id,
        profile_id,
        fps,
    )

    last_cards: Optional[List[str]] = None

    try:
        while True:
            # 1) Vision – crop 13 lá hiện tại của profile
            try:
                capture_and_crop_self_cards(ctx, profile_id=profile_id)
            except Exception as exc:
                logger.error(
                    "AutoDryRun: lỗi khi crop 13 lá (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            # 2) Recognizer – nhận diện 13 lá
            try:
                cards = recognize_13_cards(base_dir, game_id, profile_id, logger)
            except Exception as exc:
                logger.error(
                    "AutoDryRun: lỗi khi nhận diện 13 lá (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            # 3) Chỉ xử lý khi bài thay đổi
            if last_cards is not None and cards == last_cards:
                time.sleep(delay)
                continue
            last_cards = cards

            logger.info(
                "AutoDryRun: Bài 13 lá hiện tại (profile=%d): %s",
                profile_id,
                " ".join(cards),
            )

            # 4) Engine – lấy gợi ý xếp bài
            try:
                suggestion = suggest_for_13_cards(cards)
            except Exception as exc:
                logger.error(
                    "AutoDryRun: lỗi Engine khi xếp bài (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            # 5) Planner – build strategy và log
            strategy_steps = build_strategy_from_suggestion(suggestion)

            logger.info("AutoDryRun: KẾ HOẠCH ĐÁNH (profile=%d):", profile_id)
            for idx, step in enumerate(strategy_steps, start=1):
                logger.info("  Bước %02d: %s", idx, step.description)

            time.sleep(delay)

    except KeyboardInterrupt:
        logger.info(
            "AutoDryRun: nhận Ctrl+C, dừng Phase 8 dry-run profile %d.",
            profile_id,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kendz Phase 8 – Mậu Binh Automation (dry-run).",
    )
    parser.add_argument(
        "--profile-id",
        type=int,
        default=1,
        help="ID profile (mặc định: 1, tương ứng profile_1).",
    )
    args = parser.parse_args()

    print(
        f"[Kendz][Phase8] Khởi động dry-run automation cho profile_id={args.profile_id} ..."
    )
    run_dryrun_loop(profile_id=args.profile_id)


if __name__ == "__main__":
    main()
