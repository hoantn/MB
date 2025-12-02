
from __future__ import annotations

"""Tool Phase 8.4 – Mậu Binh click-plan (drag) ở chế độ dry-run.

Chức năng:
- Kết hợp toàn bộ pipeline:
  - Vision: crop 13 lá.
  - Recognizer: nhận diện 13 lá.
  - Engine: gợi ý chi1/chi2/chi3.
  - Window binding: gắn với cửa sổ trình duyệt của profile.
  - Click planner: build danh sách DragAction để xếp bài theo gợi ý.
- Thực thi plan bằng `perform_actions` với `dry_run=True`:
  - Chỉ log chi tiết từng bước drag (from->to), KHÔNG kéo thật.

Cách chạy:

    python -m kendz.tools.auto_mau_binh_click_plan_dryrun --profile-id 1

Mỗi profile nên chạy ở 1 cửa sổ CMD riêng để tránh lẫn log.
"""  # noqa: D205, D400

import argparse
import time
from pathlib import Path
from typing import List, Optional

from kendz.automation.click_actions import perform_actions
from kendz.automation.mau_binh_click_plan import build_drag_plan_for_mau_binh
from kendz.automation.window_binding import bind_window_for_profile
from kendz.core.app_context import AppContext
from kendz.engine.assistant import suggest_for_13_cards
from kendz.tools.assist_profile1 import recognize_13_cards
from kendz.vision.layout_manager import LayoutManager
from kendz.vision.pipeline import capture_and_crop_self_cards


def run_loop(profile_id: int = 1) -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger
    game_id = ctx.config.core.default_game_id
    project_root = Path(__file__).resolve().parents[2]

    logger.info(
        "AutoClickPlan: bắt đầu dry-run click-plan cho game_id=%s, profile=%d",
        game_id,
        profile_id,
    )

    # Bind cửa sổ trình duyệt cho profile này
    try:
        bound_win = bind_window_for_profile(
            game_id=game_id,
            profile_id=profile_id,
            project_root=project_root,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "AutoClickPlan: lỗi khi bind cửa sổ cho profile=%d: %s",
            profile_id,
            exc,
        )
        return

    logger.info(
        "AutoClickPlan: đã bind tới hwnd=%s, title='%s', rect=%s",
        hex(bound_win.hwnd),
        bound_win.title,
        bound_win.rect,
    )

    layout_mgr = LayoutManager(project_root)
    self_layout = layout_mgr.get_self_layout(game_id, profile_id=profile_id)

    base_dir = project_root

    fps = getattr(ctx.config.vision, "fps", 1)
    delay = 1.0 / max(fps, 1)

    last_cards: Optional[List[str]] = None

    try:
        while True:
            # 1) Vision – crop 13 lá
            try:
                capture_and_crop_self_cards(ctx, profile_id=profile_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClickPlan: lỗi khi crop 13 lá (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            # 2) Recognizer – 13 mã bài
            try:
                cards = recognize_13_cards(base_dir, game_id, profile_id, logger)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClickPlan: lỗi nhận diện 13 lá (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            if len(cards) != 13:
                logger.warning(
                    "AutoClickPlan: nhận được %d lá (profile=%d), bỏ qua vòng này: %s",
                    len(cards),
                    profile_id,
                    cards,
                )
                time.sleep(delay)
                continue

            # 3) Chỉ xử lý khi bài thay đổi
            if last_cards is not None and cards == last_cards:
                time.sleep(delay)
                continue
            last_cards = cards

            logger.info(
                "AutoClickPlan: Bài 13 lá hiện tại (profile=%d): %s",
                profile_id,
                " ".join(cards),
            )

            # 4) Engine – gợi ý chi
            try:
                suggestion = suggest_for_13_cards(cards)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClickPlan: lỗi Engine khi xếp bài (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            logger.info(
                "AutoClickPlan: Gợi ý Engine (profile=%d): chi1=%s | chi2=%s | chi3=%s",
                profile_id,
                suggestion.chi1_symbols,
                suggestion.chi2_symbols,
                suggestion.chi3_symbols,
            )

            # 5) Planner – build drag plan
            try:
                actions = build_drag_plan_for_mau_binh(
                    cards_current=cards,
                    suggestion=suggestion,
                    self_layout=self_layout,
                    bound_win=bound_win,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClickPlan: lỗi khi build drag plan (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            if not actions:
                logger.info(
                    "AutoClickPlan: Bài đã khớp gợi ý, không cần drag (profile=%d).",
                    profile_id,
                )
                time.sleep(delay)
                continue

            # 6) Thực thi plan ở chế độ DRY-RUN (chỉ log, không kéo thật)
            logger.info(
                "AutoClickPlan: bắt đầu thực thi plan %d bước (DRY-RUN, profile=%d).",
                len(actions),
                profile_id,
            )
            perform_actions(actions, dry_run=True, logger=logger)
            logger.info(
                "AutoClickPlan: kết thúc plan (DRY-RUN, profile=%d).",
                profile_id,
            )

            time.sleep(delay)

    except KeyboardInterrupt:
        logger.info(
            "AutoClickPlan: nhận Ctrl+C, dừng loop cho profile=%d.",
            profile_id,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kendz Phase 8 – Mậu Binh click-plan (dry-run).",
    )
    parser.add_argument(
        "--profile-id",
        type=int,
        default=1,
        help="ID profile (mặc định: 1, tương ứng profile_1).",
    )
    args = parser.parse_args()

    print(
        f"[Kendz][AutoClickPlan] Khởi động dry-run click-plan cho profile_id={args.profile_id} ...",
    )
    run_loop(profile_id=args.profile_id)


if __name__ == "__main__":
    main()
