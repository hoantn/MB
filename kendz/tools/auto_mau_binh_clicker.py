
from __future__ import annotations

"""Tool Phase 8.5 – Mậu Binh auto-click (drag & drop) cho GO88.

CHÚ Ý AN TOÀN:
- Mặc định tool chạy ở chế độ DRY-RUN (chỉ log).
- Muốn bật click thật, phải truyền thêm flag `--live`.
- Chỉ nên bật cho 1 profile để test trước.

Chức năng:
- Giống `auto_mau_binh_click_plan_dryrun`, nhưng có thể thực hiện drag thật.
- Luồng:
  1. Vision: crop 13 lá cho profile.
  2. Recognizer: nhận diện 13 lá.
  3. Engine: gợi ý chi1/chi2/chi3.
  4. Window binding: bind tới cửa sổ trình duyệt tương ứng.
  5. Planner: sinh danh sách DragAction để hoán vị 13 lá theo gợi ý.
  6. Executor: thực thi plan bằng `perform_actions`, ở DRY-RUN hoặc LIVE.

Cách dùng:

    # DRY-RUN (mặc định, chỉ log):
    python -m kendz.tools.auto_mau_binh_clicker --profile-id 1

    # LIVE (kéo-thả thật):
    python -m kendz.tools.auto_mau_binh_clicker --profile-id 1 --live

Mỗi profile nên chạy ở một cửa sổ CMD riêng.
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


def run_loop(profile_id: int = 1, live: bool = False) -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger
    game_id = ctx.config.core.default_game_id
    project_root = Path(__file__).resolve().parents[2]

    mode_str = "LIVE" if live else "DRY-RUN"
    logger.info(
        "AutoClicker: bắt đầu loop %s cho game_id=%s, profile=%d",
        mode_str,
        game_id,
        profile_id,
    )

    # 1) Bind cửa sổ trình duyệt cho profile này
    try:
        bound_win = bind_window_for_profile(
            game_id=game_id,
            profile_id=profile_id,
            project_root=project_root,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "AutoClicker: lỗi khi bind cửa sổ cho profile=%d: %s",
            profile_id,
            exc,
        )
        return

    logger.info(
        "AutoClicker: đã bind tới hwnd=%s, title='%s', rect=%s",
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
            # 2) Vision – crop 13 lá
            try:
                capture_and_crop_self_cards(ctx, profile_id=profile_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClicker: lỗi khi crop 13 lá (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            # 3) Recognizer – 13 mã bài
            try:
                cards = recognize_13_cards(base_dir, game_id, profile_id, logger)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClicker: lỗi nhận diện 13 lá (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            if len(cards) != 13:
                logger.warning(
                    "AutoClicker: nhận được %d lá (profile=%d), bỏ qua vòng này: %s",
                    len(cards),
                    profile_id,
                    cards,
                )
                time.sleep(delay)
                continue

            # 4) Chỉ xử lý khi bài thay đổi
            if last_cards is not None and cards == last_cards:
                time.sleep(delay)
                continue
            last_cards = cards

            logger.info(
                "AutoClicker: Bài 13 lá hiện tại (profile=%d): %s",
                profile_id,
                " ".join(cards),
            )

            # 5) Engine – gợi ý chi
            try:
                suggestion = suggest_for_13_cards(cards)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClicker: lỗi Engine khi xếp bài (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            logger.info(
                "AutoClicker: Gợi ý Engine (profile=%d): chi1=%s | chi2=%s | chi3=%s",
                profile_id,
                suggestion.chi1_symbols,
                suggestion.chi2_symbols,
                suggestion.chi3_symbols,
            )

            # 6) Planner – build drag plan
            try:
                actions = build_drag_plan_for_mau_binh(
                    cards_current=cards,
                    suggestion=suggestion,
                    self_layout=self_layout,
                    bound_win=bound_win,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClicker: lỗi khi build drag plan (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            if not actions:
                logger.info(
                    "AutoClicker: Bài đã khớp gợi ý, không cần drag (profile=%d).",
                    profile_id,
                )
                time.sleep(delay)
                continue

            # 7) Thực thi plan
            logger.info(
                "AutoClicker: bắt đầu thực thi plan %d bước (%s, profile=%d).",
                len(actions),
                mode_str,
                profile_id,
            )
            perform_actions(actions, dry_run=not live, logger=logger)
            logger.info(
                "AutoClicker: kết thúc plan (%s, profile=%d).",
                mode_str,
                profile_id,
            )

            time.sleep(delay)

    except KeyboardInterrupt:
        logger.info(
            "AutoClicker: nhận Ctrl+C, dừng loop cho profile=%d.",
            profile_id,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kendz Phase 8.5 – Mậu Binh auto-click (drag & drop).",
    )
    parser.add_argument(
        "--profile-id",
        type=int,
        default=1,
        help="ID profile (mặc định: 1, tương ứng profile_1).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Bật chế độ LIVE (kéo-thả thật). Nếu không truyền, mặc định DRY-RUN.",
    )
    args = parser.parse_args()

    print(
        f"[Kendz][AutoClicker] Khởi động loop cho profile_id={args.profile_id}, "
        f"mode={'LIVE' if args.live else 'DRY-RUN'} ...",
    )
    run_loop(profile_id=args.profile_id, live=bool(args.live))


if __name__ == "__main__":
    main()
