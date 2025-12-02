
from __future__ import annotations

"""Tool debug Window Binding cho Kendz (Phase 8).

Chức năng:
- Bind tới cửa sổ trình duyệt tương ứng với profile.
- Đọc layout 13 lá (self_cards) cho game hiện tại.
- Tính toán toạ độ pixel (màn hình) của tâm từng lá bài.
- Log ra để kiểm tra việc map toạ độ đã đúng chưa.

Không gửi click chuột thật. Chỉ dùng để kiểm tra:
- Config automation.yaml
- Window title của từng profile
- Sự khớp nhau giữa layout (x,y,w,h) và kích thước cửa sổ thực tế.
"""  # noqa: D205, D400

import argparse
from pathlib import Path

from kendz.core.app_context import AppContext
from kendz.vision.layout_manager import LayoutManager
from kendz.automation.window_binding import bind_window_for_profile


def run_debug(profile_id: int = 1) -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger
    game_id = ctx.config.core.default_game_id

    project_root = Path(__file__).resolve().parents[2]

    logger.info(
        "WindowDebug: bắt đầu debug binding cho game_id=%s, profile=%d",
        game_id,
        profile_id,
    )

    # 1) Bind cửa sổ theo config/automation.yaml
    try:
        bound_win = bind_window_for_profile(
            game_id=game_id,
            profile_id=profile_id,
            project_root=project_root,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("WindowDebug: lỗi khi bind cửa sổ cho profile=%d: %s", profile_id, exc)
        return

    logger.info(
        "WindowDebug: đã bind tới cửa sổ hwnd=%s, title='%s', rect=%s",
        hex(bound_win.hwnd),
        bound_win.title,
        bound_win.rect,
    )

    # 2) Lấy layout 13 lá (self_cards) cho profile này
    layout_mgr = LayoutManager(project_root)
    self_layout = layout_mgr.get_self_layout(game_id, profile_id=profile_id)

    logger.info(
        "WindowDebug: tổng %d vùng card (self_cards) cho profile=%d",
        len(self_layout.card_regions),
        profile_id,
    )

    # 3) Tính toạ độ pixel tâm mỗi lá bài
    for region in self_layout.card_regions:
        # tâm từng lá trong toạ độ tương đối
        x_rel = region.x + region.w / 2.0
        y_rel = region.y + region.h / 2.0
        x_px, y_px = bound_win.to_screen_from_rel(x_rel, y_rel)

        logger.info(
            "WindowDebug: card_%02d -> rel=(%.3f, %.3f) -> screen=(%d, %d)",
            region.index,
            x_rel,
            y_rel,
            x_px,
            y_px,
        )

    logger.info(
        "WindowDebug: hoàn tất debug binding cho profile=%d. "
        "Nếu toạ độ có vẻ sai lệch, hãy kiểm tra lại layout hoặc title cửa sổ.",
        profile_id,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kendz – debug window binding cho Mậu Binh.",
    )
    parser.add_argument(
        "--profile-id",
        type=int,
        default=1,
        help="ID profile (mặc định: 1, tương ứng profile_1)",
    )
    args = parser.parse_args()

    print(f"[Kendz][WindowDebug] Bắt đầu debug cho profile_id={args.profile_id} ...")
    run_debug(profile_id=args.profile_id)


if __name__ == "__main__":
    main()
