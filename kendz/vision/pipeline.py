# kendz/vision/pipeline.py
"""Pipeline nối Vision -> Engine (skeleton).

Giai đoạn hiện tại:
- Dùng LayoutManager để lấy toạ độ 13 lá bài của bản thân.
- Chụp màn hình (capture_screen).
- Crop 13 lá thành 13 ảnh nhỏ.
- Lưu các ảnh debug vào thư mục data/vision_cards/...

Chưa:
- Chưa nhận diện rank/suit.
- Chưa chuyển sang Card (engine).
- Chưa gọi arrange_advanced() trực tiếp từ pipeline.

Mục đích:
- Kiểm tra nhanh việc layout + crop đã đúng.
- Tạo dữ liệu ảnh để sau này huấn luyện / tạo template nhận diện.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from typing import List, Optional, Tuple

import cv2
import numpy as np

from kendz.core.app_context import AppContext
from kendz.vision.capture import capture_screen, capture_screen_region
from kendz.vision.layout_manager import LayoutManager
from kendz.vision.cards_detector import CardRegion, crop_card
from kendz.browser.cdp_capture import capture_frame_from_cdp

def capture_and_crop_self_cards(
    ctx: AppContext,
    profile_id: int = 1,
    window_rect: Optional[Tuple[int, int, int, int]] = None,
) -> None:

    """Chụp màn hình và crop 13 lá bài của bản thân.

    Kết quả:
    - Lưu 13 ảnh nhỏ vào thư mục:
      data/vision_cards/{game_id}/profile_{profile_id}/card_{index}.png

    Ghi log:
    - Thành công / thất bại
    - Số lá crop được
    """
    logger = ctx.logger
    game_id = ctx.config.core.default_game_id

    # Nếu có toạ độ window (trình duyệt) thì chụp đúng vùng đó,
    # nếu không thì fallback chụp full screen.
    # ƯU TIÊN: chụp bằng DevTools (CDP) – kể cả khi Chrome minimize/ẩn.
    frame = None
    viewport_w: Optional[int] = None
    viewport_h: Optional[int] = None

    try:
        frame_cdp, vw, vh = capture_frame_from_cdp()
        frame = frame_cdp
        viewport_w = vw
        viewport_h = vh
        logger.info(
            "Vision pipeline: đã chụp frame từ DevTools (viewport=%dx%d).",
            viewport_w,
            viewport_h,
        )
    except Exception as exc:
        logger.warning(
            "Vision pipeline: không chụp được từ DevTools (%s), fallback sang mss/capture_screen.",
            exc,
        )

    # FALLBACK: nếu DevTools không dùng được, quay về capture_screen_region / capture_screen
    if frame is None:
        if window_rect is not None:
            left, top, width, height = window_rect
            frame = capture_screen_region(left, top, width, height)
        else:
            frame = capture_screen()

    if frame is None:
        logger.error("Vision pipeline: không chụp được màn hình.")
        return


    project_root = Path(__file__).resolve().parents[2]
    out_dir = project_root / "data" / "vision_cards" / game_id / f"profile_{profile_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    layout_mgr = LayoutManager(project_root)
    self_layout = layout_mgr.get_self_layout(game_id, profile_id=profile_id)
    card_regions: List[CardRegion] = self_layout.card_regions

    saved_files = []

    for region in card_regions:
        card_img = crop_card(frame, region)
        out_path = out_dir / f"card_{region.index:02d}.png"
        cv2.imwrite(str(out_path), card_img)
        saved_files.append(out_path)

    logger.info(
        "Vision pipeline: đã crop %d lá bài cho game_id=%s profile=%d, lưu tại %s",
        len(saved_files),
        game_id,
        profile_id,
        out_dir,
    )

def capture_and_save_runtime_self_cards(
    ctx: AppContext,
    profile_id: int = 1,
    window_rect: Optional[Tuple[int, int, int, int]] = None,
) -> List[Path]:
    """Chụp màn hình và crop 13 lá bài vào thư mục runtime/self_cards.

    Mục đích:
    - Phục vụ UI LivePlayTab: hiển thị ảnh lá bài *thực tế* vừa quét.
    - Sử dụng cùng LayoutManager (CardRegion toạ độ tương đối 0..1) như pipeline chính.

    Kết quả:
    - Lưu 13 ảnh nhỏ vào thư mục:
      data/runtime/self_cards/profile_{profile_id}/slot_{index:02d}.png

    Trả về:
    - Danh sách đường dẫn file đã lưu.
    """
    logger = ctx.logger
    game_id = ctx.config.core.default_game_id

    # ƯU TIÊN: DevTools (CDP)
    frame = None
    viewport_w: Optional[int] = None
    viewport_h: Optional[int] = None

    try:
        frame_cdp, vw, vh = capture_frame_from_cdp()
        frame = frame_cdp
        viewport_w = vw
        viewport_h = vh
        logger.info(
            "Vision runtime: đã chụp frame từ DevTools (viewport=%dx%d).",
            viewport_w,
            viewport_h,
        )
    except Exception as exc:
        logger.warning(
            "Vision runtime: không chụp được từ DevTools (%s), fallback sang mss/capture_screen.",
            exc,
        )

    # FALLBACK: nếu DevTools không dùng được, quay về capture_screen_region / capture_screen
    if frame is None:
        if window_rect is not None:
            left, top, width, height = window_rect
            frame = capture_screen_region(left, top, width, height)
        else:
            frame = capture_screen()

    if frame is None:
        logger.error("Vision runtime: không chụp được màn hình (runtime self_cards).")
        return []

    project_root = Path(__file__).resolve().parents[2]
    out_dir = project_root / "data" / "runtime" / "self_cards" / f"profile_{profile_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    layout_mgr = LayoutManager(project_root)
    self_layout = layout_mgr.get_self_layout(game_id, profile_id=profile_id)
    card_regions: List[CardRegion] = self_layout.card_regions

    saved_files: List[Path] = []

    for region in card_regions:
        card_img = crop_card(frame, region)
        out_path = out_dir / f"slot_{region.index:02d}.png"
        cv2.imwrite(str(out_path), card_img)
        saved_files.append(out_path)

    logger.info(
        "Vision pipeline: đã crop %d lá (runtime) cho game_id=%s profile=%d, lưu tại %s",
        len(saved_files),
        game_id,
        profile_id,
        out_dir,
    )
    return saved_files
