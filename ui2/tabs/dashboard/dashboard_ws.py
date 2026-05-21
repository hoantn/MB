# ui2/tabs/dashboard/dashboard_ws.py
from typing import List

from PySide6.QtWidgets import QMessageBox

from core.logger import log
from ui2.bridge.ws_card_store import ws_card_store


def poll_ws_cards_impl(self) -> None:
    """
    Thân hàm gốc của DashboardTab._poll_ws_cards được chuyển sang đây.

    - Nếu card_source_mode != 'auto' => bỏ qua (manual scan).
    - Nếu WS chưa đủ 13 lá => bỏ qua.
    - Nếu snapshot giống lần trước => bỏ qua.
    - Nếu có bài mới => cập nhật snapshot + đẩy vào _on_profile_scanned.
    """
    # Nếu đang ở mode thủ công thì không auto poll
    if getattr(self, "card_source_mode", "auto") != "auto":
        return

    updated_any = False

    for pid in self.profiles:
        cards = ws_card_store.get_last_cards(pid)
        if not cards or len(cards) != 13:
            continue

        # Không thay đổi so với lần trước → bỏ qua
        prev = self.ws_cards_snapshot.get(pid)
        if prev is not None and list(cards) == list(prev):
            continue

        # Lưu snapshot mới
        self.ws_cards_snapshot[pid] = list(cards)

        # WS slot 1→13 (game) = dưới phải → trên trái
        # TOOL slot 0→12      = trên trái → dưới phải
        codes = list(reversed(cards))  # rất quan trọng, đừng đổi

        confs = [1.0] * 13
        images = [None] * 13

        # Dùng pipeline xử lý card hiện tại của DashboardTab
        self._on_profile_scanned(pid, codes, confs, images)
        updated_any = True

    if updated_any:
        log.info("Dashboard: auto cập nhật bài từ WebSocket")


def load_ws_cards_impl(self, profiles: List[str]) -> None:
    """
    Thân hàm gốc của DashboardTab.load_ws_cards được chuyển sang đây.

    Cho phép 'Quét bài WS thủ công' cho 1 hoặc nhiều profile.
    """
    for pid in profiles:
        cards = ws_card_store.get_last_cards(pid)
        if not cards or len(cards) != 13:
            QMessageBox.warning(
                self,
                "WS chưa có bài",
                f"Profile {pid}: chưa nhận đủ 13 lá từ WebSocket.",
            )
            # UI: nếu bấm quét thủ công mà WS chưa đủ bài, trả nút về mặc định
            try:
                if hasattr(self, "_mark_manual_scan_finished"):
                    self._mark_manual_scan_finished(pid)
                if hasattr(self, "_mark_scan_all_finished_if_done"):
                    self._mark_scan_all_finished_if_done()
            except Exception:
                pass
            continue

        # Lưu snapshot để về sau _poll_ws_cards còn so sánh được
        self.ws_cards_snapshot[pid] = list(cards)

        codes = list(reversed(cards))
        confs = [1.0] * 13
        images = [None] * 13

        self._on_profile_scanned(pid, codes, confs, images)
