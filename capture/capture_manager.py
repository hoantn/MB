from typing import Optional

from PIL import Image

from browser.manager import BrowserManager
from .region import (
    get_game_region,
    get_slots,
    set_game_region,
    set_slot,
    get_design_region,
    set_design_region,
    get_design_slots,
    set_design_slot,
)
from core.logger import log
from core.config import load_config
from capture.runtime_coordinates import read_live_runtime_info

DESIGN_W = 1280
DESIGN_H = 720


class CaptureManager:
    def __init__(self, browser_manager: BrowserManager):
        self.browser_manager = browser_manager

    def _slot(self) -> int:
        try:
            return int(getattr(self.browser_manager, "_slot", 1) or 1)
        except Exception:
            return 1

    def _get_or_attach_tab(self, profile_id: str):
        """Lấy tab DevTools; nếu chưa có thì thử attach lại."""
        tab = self.browser_manager.get_active_tab(profile_id)
        if tab:
            return tab

        # Thử dùng ensure_tab nếu BrowserManager có hỗ trợ
        if hasattr(self.browser_manager, "ensure_tab"):
            try:
                tab = self.browser_manager.ensure_tab(profile_id)
                if tab:
                    return tab
            except Exception as e:
                log.warning(
                    "CaptureManager: không attach được DevTools cho %s: %s",
                    profile_id,
                    e,
                )

        log.warning("No active DevTools tab for profile %s", profile_id)
        return None

    def capture_region(self, profile_id: str) -> Optional[Image.Image]:
        tab = self._get_or_attach_tab(profile_id)
        if not tab:
            return None

        region = get_game_region(profile_id, slot=self._slot())
        if region is None:
            log.warning("capture_region: region cho %s là None", profile_id)
            return None

        img = tab.capture(region=region)
        return img

    def capture_full(self, profile_id: str) -> Optional[Image.Image]:
        tab = self._get_or_attach_tab(profile_id)
        if not tab:
            return None

        img = tab.capture(region=None)
        return img
        
    def fix_coordinates(self, profile_id: str) -> tuple[bool, str]:
        """
        Fix toạ độ cho profile_id dựa trên hệ design 1280x720 + canvas Cocos.

        - Lần đầu:
            * Đọc game_region + slots hiện tại (screen).
            * Đọc canvas Cocos (left, top, width, height).
            * Convert sang design (1280x720) và lưu vào capture.design[profile].
            * KHÔNG đổi region/slots hiện tại.

        - Những lần sau:
            * Đọc design_region + design_slots từ capture.design[profile].
            * Đọc canvas Cocos hiện tại.
            * Từ design (1280x720) map ra screen mới → cập nhật regions + slots.
        """
        # Runtime-fixed mode: never auto-scale coordinates. The coordinates saved
        # in CaptureTab are valid only for the viewport/canvas recorded here.
        cfg_slot = self._slot()
        info = read_live_runtime_info(self.browser_manager, profile_id)
        if not info:
            msg = f"Không đọc được viewport/canvas hiện tại cho {profile_id}."
            log.warning("fix_coordinates[%s]: %s", profile_id, msg)
            return False, msg
        vp = info.get("viewport") or {}
        canvas_now = info.get("canvas") or {}
        design = info.get("design") or {}
        msg = (
            f"Runtime hiện tại của {profile_id}: "
            f"viewport={vp.get('width')}x{vp.get('height')}, "
            f"canvas={canvas_now.get('width')}x{canvas_now.get('height')}, "
            f"design={design.get('width')}x{design.get('height')}. "
            "Metadata chỉ được lưu khi bạn lưu tọa độ từ tab Fix."
        )
        log.info("fix_coordinates[%s]: %s", profile_id, msg)
        return True, msg

        # 1) Lấy tab + canvas Cocos hiện tại
        tab = self._get_or_attach_tab(profile_id)
        if not tab:
            msg = f"Không tìm thấy tab DevTools cho profile {profile_id}"
            log.warning("fix_coordinates[%s]: %s", profile_id, msg)
            return False, msg

        try:
            canvas = tab.get_cocos_canvas_info()
        except Exception as e:
            msg = f"Lỗi lấy canvas Cocos cho {profile_id}: {e}"
            log.error("fix_coordinates[%s]: %s", profile_id, msg)
            return False, msg

        if not canvas:
            msg = "Không lấy được canvas Cocos (cc.game.canvas)."
            log.warning("fix_coordinates[%s]: %s", profile_id, msg)
            return False, msg

        c_left = float(canvas.get("left", 0.0))
        c_top = float(canvas.get("top", 0.0))
        c_w = float(canvas.get("width", 0.0))
        c_h = float(canvas.get("height", 0.0))

        if c_w <= 0 or c_h <= 0:
            msg = f"Canvas Cocos hiện tại không hợp lệ: {c_w}x{c_h}"
            log.warning("fix_coordinates[%s]: %s", profile_id, msg)
            return False, msg

        # 2) Đọc region + slots hiện dùng
        cfg_slot = self._slot()
        game_region = get_game_region(profile_id, slot=cfg_slot)
        slots = get_slots(profile_id, slot=cfg_slot) or {}

        if not game_region:
            msg = f"Chưa có game_region cho {profile_id}, hãy cấu hình vùng game trước."
            log.warning("fix_coordinates[%s]: %s", profile_id, msg)
            return False, msg

        if not slots or len(slots) < 13:
            msg = f"Slots của {profile_id} chưa đủ 13 slot, hãy cấu hình slot trước."
            log.warning("fix_coordinates[%s]: %s", profile_id, msg)
            return False, msg

        # 3) Đọc design hiện có (nếu có)
        design_region = get_design_region(profile_id, slot=cfg_slot)
        design_slots = get_design_slots(profile_id, slot=cfg_slot)

        # ---------------- LẦN ĐẦU: tạo design từ config hiện tại ----------------
        if not design_region or not design_slots:
            gx = float(game_region["x"])
            gy = float(game_region["y"])
            gw = float(game_region["width"])
            gh = float(game_region["height"])

            # Region: screen -> design
            design_region = {
                "x": (gx - c_left) / c_w * DESIGN_W,
                "y": (gy - c_top) / c_h * DESIGN_H,
                "width": gw / c_w * DESIGN_W,
                "height": gh / c_h * DESIGN_H,
            }

            # Slots: screen -> design (ABS theo 1280x720)
            design_slots = {}
            for idx_str, rect in slots.items():
                sx = float(rect["x"])
                sy = float(rect["y"])
                sw = float(rect["width"])
                sh = float(rect["height"])

                slot_x0_screen = gx + sx
                slot_y0_screen = gy + sy

                design_slots[idx_str] = {
                    "x": (slot_x0_screen - c_left) / c_w * DESIGN_W,
                    "y": (slot_y0_screen - c_top) / c_h * DESIGN_H,
                    "width": sw / c_w * DESIGN_W,
                    "height": sh / c_h * DESIGN_H,
                }

            # Lưu design vào config
            set_design_region(profile_id, design_region, slot=cfg_slot)
            for idx_str, drect in design_slots.items():
                set_design_slot(profile_id, int(idx_str), drect, slot=cfg_slot)

            msg = (
                f"Đã khởi tạo toạ độ design 1280x720 cho {profile_id} từ cấu hình hiện tại. "
                f"Từ giờ, mỗi khi đổi kích thước trình duyệt hãy bấm lại 'Fix tọa độ' để cập nhật."
            )
            log.info("fix_coordinates[%s]: %s", profile_id, msg)
            return True, msg

        # ---------------- CÁC LẦN SAU: design -> screen mới ----------------
        drx = float(design_region["x"])
        dry = float(design_region["y"])
        drw = float(design_region["width"])
        drh = float(design_region["height"])

        # Region trong screen mới
        rx_screen = c_left + drx / DESIGN_W * c_w
        ry_screen = c_top + dry / DESIGN_H * c_h
        rw_screen = drw / DESIGN_W * c_w
        rh_screen = drh / DESIGN_H * c_h

        new_region = {
            "x": round(rx_screen),
            "y": round(ry_screen),
            "width": round(rw_screen),
            "height": round(rh_screen),
        }

        # Screen region để tính slot tương đối
        gx_new = rx_screen
        gy_new = ry_screen

        # Slots trong screen mới
        new_slots = {}
        for idx_str, drect in design_slots.items():
            dsx = float(drect["x"])
            dsy = float(drect["y"])
            dsw = float(drect["width"])
            dsh = float(drect["height"])

            slot_x0_screen = c_left + dsx / DESIGN_W * c_w
            slot_y0_screen = c_top + dsy / DESIGN_H * c_h
            slot_w_screen = dsw / DESIGN_W * c_w
            slot_h_screen = dsh / DESIGN_H * c_h

            slot_rel_x = slot_x0_screen - gx_new
            slot_rel_y = slot_y0_screen - gy_new

            new_slots[idx_str] = {
                "x": round(slot_rel_x),
                "y": round(slot_rel_y),
                "width": round(slot_w_screen),
                "height": round(slot_h_screen),
            }

        # Lưu lại region + slots mới
        set_game_region(profile_id, new_region, slot=cfg_slot)
        for idx_str, rect in new_slots.items():
            set_slot(profile_id, int(idx_str), rect, slot=cfg_slot)

        msg = (
            f"Đã cập nhật vùng game và 13 slot cho {profile_id} theo canvas Cocos mới "
            f"(canvas={c_w:.1f}x{c_h:.1f}, design=1280x720)."
        )
        log.info("fix_coordinates[%s]: %s", profile_id, msg)
        return True, msg
