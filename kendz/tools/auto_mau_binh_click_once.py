# coding: utf-8
"""
Tool chạy 1 lần duy nhất:
- Bind window
- Crop 13 lá
- Recognize 13 lá
- Engine xếp bài
- Planner sinh drag plan
- Execute (dry-run hoặc live)
- Thoát ngay

Dùng để test chính xác từng bước mà không chạy vòng lặp vô hạn.
"""

from __future__ import annotations
import argparse
from pathlib import Path

from kendz.core.app_context import AppContext
from kendz.automation.window_binding import bind_window_for_profile
from kendz.vision.pipeline import capture_and_crop_self_cards
from kendz.tools.assist_profile1 import recognize_13_cards
from kendz.engine.assistant import suggest_for_13_cards
from kendz.automation.mau_binh_click_plan import build_drag_plan_for_mau_binh
from kendz.automation.click_actions import perform_actions
from kendz.vision.layout_manager import LayoutManager


def main():
    parser = argparse.ArgumentParser(description="AutoClickOnce cho Mậu Binh")
    parser.add_argument("--profile-id", type=int, default=1)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    ctx = AppContext.bootstrap()
    logger = ctx.logger

    project_root = Path(__file__).resolve().parents[2]
    game_id = ctx.config.core.default_game_id

    mode = "LIVE" if args.live else "DRY-RUN"
    logger.info("AutoClickOnce: bat dau cho profile=%d, mode=%s", args.profile_id, mode)

    # 1) Bind window
    bound = bind_window_for_profile(game_id, args.profile_id, project_root)
    logger.info("Bind ok: hwnd=%s, rect=%s", hex(bound.hwnd), bound.rect)

    # 2) Capture
    capture_and_crop_self_cards(ctx, profile_id=args.profile_id)

    # 3) Recognize 13 cards
    cards = recognize_13_cards(project_root, game_id, args.profile_id, logger)
    logger.info("Cards: %s", " ".join(cards))

    if len(cards) != 13:
        logger.error("Sai so luong card: %d", len(cards))
        return

    # 4) Engine suggest
    suggestion = suggest_for_13_cards(cards)
    logger.info(
        "Engine: chi1=%s | chi2=%s | chi3=%s",
        suggestion.chi1_symbols,
        suggestion.chi2_symbols,
        suggestion.chi3_symbols,
    )

    # 5) Planner build drag plan
    layout_mgr = LayoutManager(project_root)
    layout = layout_mgr.get_self_layout(game_id, profile_id=args.profile_id)

    actions = build_drag_plan_for_mau_binh(
        cards_current=cards,
        suggestion=suggestion,
        self_layout=layout,
        bound_win=bound,
    )

    logger.info("Plan co %d buoc", len(actions))
    for i, act in enumerate(actions, start=1):
        logger.info("Step %02d: %s", i, act)

    # 6) Execute one-shot
    perform_actions(actions, dry_run=not args.live, logger=logger)

    logger.info("AutoClickOnce: hoan thanh 1 luot, thoat.")


if __name__ == "__main__":
    main()
