
# coding: utf-8
"""Auto Mậu Binh theo ván – mỗi ván chỉ xếp 1 lần.

Ý tưởng:
- Dùng cùng logic như auto_mau_binh_click_once, nhưng đặt trong loop.
- Mỗi lần phát hiện *bài mới* (13 lá khác lần trước) thì:
  - Bind window (nếu chưa).
  - Crop + recognize.
  - Engine suggest.
  - Planner sinh DragAction.
  - Thực thi (dry-run hoặc live) 1 lần.
- Sau đó chờ đến khi xuất hiện bộ 13 lá khác (ván mới).

Công dụng:
- Dùng chơi thực tế lâu dài, nhưng tránh việc tool spam xếp lại liên tục
  trong cùng một ván.
- Khi cần debug từng ván, dùng auto_mau_binh_click_once.
"""  # noqa: D205, D400

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import List, Optional

from kendz.core.app_context import AppContext
from kendz.automation.window_binding import bind_window_for_profile
from kendz.vision.pipeline import capture_and_crop_self_cards
from kendz.tools.assist_profile1 import recognize_13_cards
from kendz.engine.assistant import suggest_for_13_cards
from kendz.automation.mau_binh_click_plan import build_drag_plan_for_mau_binh
from kendz.automation.click_actions import perform_actions
from kendz.vision.layout_manager import LayoutManager


def run_hand_loop(profile_id: int, live: bool) -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger
    project_root = Path(__file__).resolve().parents[2]
    game_id = ctx.config.core.default_game_id

    mode = "LIVE" if live else "DRY-RUN"
    logger.info(
        "AutoClickHandLoop: start for profile=%d, mode=%s",
        profile_id,
        mode,
    )

    # Bind một lần, dùng suốt
    bound = bind_window_for_profile(game_id, profile_id, project_root)
    logger.info("AutoClickHandLoop: bind ok: hwnd=%s, rect=%s", hex(bound.hwnd), bound.rect)

    layout_mgr = LayoutManager(project_root)
    self_layout = layout_mgr.get_self_layout(game_id, profile_id=profile_id)

    last_cards: Optional[List[str]] = None
    fps = getattr(ctx.config.vision, "fps", 1)
    delay = 1.0 / max(fps, 1)

    try:
        while True:
            # 1) Crop
            try:
                capture_and_crop_self_cards(ctx, profile_id=profile_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClickHandLoop: loi crop 13 la (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            # 2) Recognize
            try:
                cards = recognize_13_cards(project_root, game_id, profile_id, logger)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClickHandLoop: loi recognize 13 la (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            if len(cards) != 13:
                logger.debug(
                    "AutoClickHandLoop: so luong la != 13 (profile=%d): %s",
                    profile_id,
                    cards,
                )
                time.sleep(delay)
                continue

            # 3) Nếu bài giống lần trước -> cùng 1 ván, bỏ qua
            if last_cards is not None and cards == last_cards:
                time.sleep(delay)
                continue

            # Đánh dấu bài mới (ván mới)
            last_cards = list(cards)
            logger.info(
                "AutoClickHandLoop: phat hien van moi, 13 la (profile=%d): %s",
                profile_id,
                " ".join(cards),
            )

            # 4) Engine suggest
            try:
                suggestion = suggest_for_13_cards(cards)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClickHandLoop: loi Engine khi xep bai (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            logger.info(
                "AutoClickHandLoop: Engine (profile=%d): chi1=%s | chi2=%s | chi3=%s",
                profile_id,
                suggestion.chi1_symbols,
                suggestion.chi2_symbols,
                suggestion.chi3_symbols,
            )

            # 5) Planner
            try:
                actions = build_drag_plan_for_mau_binh(
                    cards_current=cards,
                    suggestion=suggestion,
                    self_layout=self_layout,
                    bound_win=bound,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "AutoClickHandLoop: loi planner (profile=%d): %s",
                    profile_id,
                    exc,
                )
                time.sleep(delay)
                continue

            if not actions:
                logger.info(
                    "AutoClickHandLoop: bai da dung theo goi y, bo qua (profile=%d).",
                    profile_id,
                )
                time.sleep(delay)
                continue

            logger.info(
                "AutoClickHandLoop: bat dau thuc thi plan %d buoc (%s, profile=%d).",
                len(actions),
                mode,
                profile_id,
            )
            perform_actions(actions, dry_run=not live, logger=logger)
            logger.info(
                "AutoClickHandLoop: ket thuc plan (%s, profile=%d).",
                mode,
                profile_id,
            )

            # Sau khi xep xong 1 ván, đợi một chút rồi mới quan sát tiếp
            time.sleep(delay)

    except KeyboardInterrupt:
        logger.info(
            "AutoClickHandLoop: nhan Ctrl+C, dung loop cho profile=%d.",
            profile_id,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AutoClickHandLoop cho Mau Binh – moi van click 1 lan.",
    )
    parser.add_argument("--profile-id", type=int, default=1)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Neu truyen flag nay thi keo that, neu khong thi chi DRY-RUN.",
    )
    args = parser.parse_args()

    print(
        f"[Kendz][AutoClickHandLoop] start profile_id={args.profile_id}, "
        f"mode={'LIVE' if args.live else 'DRY-RUN'}",
    )
    run_hand_loop(profile_id=args.profile_id, live=bool(args.live))


if __name__ == "__main__":
    main()
