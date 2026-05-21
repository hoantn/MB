from .dashboard.dashboard_constants import (
    SUITS,
    FULL_DECK,
    INDEX_TO_CHI,
    RANK_VALUE,
    _OPP_PIXMAP_CACHE,
    _OPP_IMG_ROOT,
    _load_opp_pixmap,
    _card_rank_code,
    _classify_five,
    _classify_three,
    classify_chis,
    hand_type_color,
    _format_suggestion_label,
)

from .dashboard.dashboard_scan_worker import ScanWorker

from .dashboard.dashboard_ws import (
    poll_ws_cards_impl,
    load_ws_cards_impl,
)

from .dashboard.dashboard_suggest import (
    get_scanned_cards_impl,
    build_suggestions_for_profile_impl,
    suggest_for_impl,
    on_suggestion_changed_impl,
    apply_suggestion_for_impl,
    update_engine_panel_impl,
)
from .dashboard.dashboard_view import (
    build_ui_impl,
    set_profile_state_impl,
    pulse_profile_box_impl,
    update_opponent_impl,
    refresh_player_thumbnails_impl,
    refresh_all_views_impl,
)
from .dashboard.dashboard_suggest_worker import build_suggestions_for_codes

from typing import Dict, List, Optional, Tuple
import os
import threading
import queue
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGroupBox,
    QPushButton,
    QLabel,
    QCheckBox,
    QMessageBox,
    QTextEdit,
    QComboBox,
    QGraphicsOpacityEffect,
    QRadioButton,
    QButtonGroup,
)

from PySide6.QtCore import (
    Qt,
    QThread,
    QPropertyAnimation,
    QEasingCurve,
    QTimer,
)

from PySide6.QtGui import QPixmap

from browser.manager import BrowserManager
from capture.capture_manager import CaptureManager
from vision.cropper import crop_slots
from vision.recognizer import recognize_card
from engine.card import Card
from engine.arranger import arrange_13_cards, arrange_cards, ArrangeStrategy
from engine.scorer import score_three_chi
from engine.action import apply_arrangement

try:
    from engine.scorer import score_matchup  # type: ignore
except Exception:  # pragma: no cover
    score_matchup = None  # type: ignore

from core.constants import RANK_ORDER
from core.logger import log
from ui2.bridge.ws_card_store import ws_card_store


class DashboardTab(QWidget):
    """Dashboard tổng quan 3 profile + đối thủ (OPP) – mode gợi ý."""

    def __init__(
        self,
        browser_manager: BrowserManager,
        capture_manager: CaptureManager,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.browser_manager = browser_manager
        self.capture_manager = capture_manager
        self.profiles = ["P1", "P2", "P3"]
        self.rows = ["OPP"] + self.profiles
        # --- Dashboard policy: NO cards / NO suggestions ---
        self.dashboard_cards_enabled = False   # tắt mọi xử lý bài trong Dashboard
        self.dashboard_suggest_enabled = False # tắt mọi gợi ý trong Dashboard

        self.card_codes_flat: Dict[str, List[Optional[str]]] = {
            row: [None] * 13 for row in self.rows
        }
        self.card_conf_flat: Dict[str, List[float]] = {
            row: [0.0] * 13 for row in self.rows
        }
        self.card_images_pil: Dict[str, List[Optional["Image.Image"]]] = {  # type: ignore
            row: [None] * 13 for row in self.rows
        }

        # suggestions[profile_id] = list các phương án gợi ý (Tiền / Max / Vs OPP)
        self.suggestions: Dict[str, List[dict]] = {pid: [] for pid in self.profiles}
        self.suggestion_combos: Dict[str, QComboBox] = {}

        # Worker gợi ý (engine) theo profile – chạy ở thread riêng (Python thread)
        # Mỗi profile có 1 thread đang xử lý job mới nhất (nếu còn sống).
        self._suggest_threads: Dict[str, threading.Thread] = {}
        # Generation để bỏ qua kết quả cũ khi đã có bài/quét mới.
        self._suggest_generation: Dict[str, int] = {pid: 0 for pid in self.profiles}
        # Hàng đợi kết quả từ worker → UI (poll bằng QTimer trong main thread).
        self._suggest_queue: "queue.Queue[tuple[str, int, list, str]]" = queue.Queue()

        # Lưu chi đang được preview cho từng row (OPP, P1, P2, P3)
        self.preview_chis: Dict[str, Optional[Tuple[List[Card], List[Card], List[Card]]]] = {
            row: None for row in self.rows
        }

        self.player_chi_labels: Dict[str, Dict[str, QLabel]] = {}
        self.player_card_labels: Dict[str, Dict[str, List[QLabel]]] = {}

        self.engine_panel: Optional[QTextEdit] = None
        # Các label hiển thị gợi ý engine cho P1/P2/P3
        self.engine_summary_labels: Dict[str, QLabel] = {}

        self._scan_thread: Optional[QThread] = None
        self._scan_worker: Optional[ScanWorker] = None

        # Trạng thái UI cho từng profile
        self.profile_state: Dict[str, str] = {pid: "idle" for pid in self.profiles}
        self.profile_state_labels: Dict[str, QLabel] = {}
        self.player_boxes: Dict[str, QGroupBox] = {}
        self._box_animations: Dict[str, QPropertyAnimation] = {}

        # --- WS mode ---
        # "auto": đọc bài từ WebSocket tự động, "manual": dùng scan ảnh (thủ công)
        self.card_source_mode: str = "auto"
        # Snapshot để tránh refresh liên tục khi cs không đổi
        self.ws_cards_snapshot: Dict[str, List[str]] = {}

        # Timer để auto poll bài từ WebSocket
        self._ws_timer = QTimer(self)
        self._ws_timer.setInterval(200)
        self._ws_timer.timeout.connect(self._poll_ws_cards)
        if self.dashboard_cards_enabled:
            self._ws_timer.start()


        # Timer poll kết quả gợi ý từ worker thread
        self._suggest_timer = QTimer(self)
        self._suggest_timer.setInterval(50)
        self._suggest_timer.timeout.connect(self._poll_suggestions)
        if self.dashboard_suggest_enabled:
            self._suggest_timer.start()



        # --- UI button refs/state (for active effects) ---
        # Buttons are created in dashboard_view.build_ui_impl; we keep references here to update styles safely.
        self.ui_btn_scan: Dict[str, QPushButton] = {}         # pid -> "Quét Bài Px"
        self.ui_btn_scan_all: Optional[QPushButton] = None    # "Quét Bài ALL"
        self.ui_btn_scan_opp: Optional[QPushButton] = None    # "Quét bài Đối Thủ (OPP)"
        self.ui_btn_apply: Dict[str, QPushButton] = {}        # pid -> "Áp dụng lên Px"
        self.ui_btn_reset: Dict[str, QPushButton] = {}        # pid -> "↻" reset connect
        # Internal state
        self._opp_scanned_ok: bool = False
        self._scan_pending: Dict[str, bool] = {pid: False for pid in self.profiles}  # manual WS scan pending
        self._build_ui()
        self.refresh_all_views()
        # Responsive: scale kích thước card theo kích thước ban đầu của Dashboard
        self._rescale_cards()

    def _rescale_cards(self) -> None:
        """
        Scale lại pixmap cho các QLabel lá bài theo kích thước hiện tại của layout.

        - Chỉ scale khi QLabel đang có pixmap hợp lệ (không null).
        - Bọc try/except để nếu có lỗi nhỏ về UI cũng không làm crash app.
        """
        try:
            # player_card_labels: Dict[row, Dict[chi_name, List[QLabel]]]
            for row, chi_map in self.player_card_labels.items():
                if not chi_map:
                    continue
                for chi_name, labels in chi_map.items():
                    if not labels:
                        continue
                    for label in labels:
                        if label is None:
                            continue

                        pix = label.pixmap()
                        # Bỏ qua nếu chưa có pixmap hoặc pixmap null
                        if pix is None or pix.isNull():
                            continue

                        size = label.size()
                        w, h = size.width(), size.height()
                        if w <= 0 or h <= 0:
                            # Label chưa layout xong → bỏ qua
                            continue

                        scaled = pix.scaled(
                            size,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                        label.setPixmap(scaled)
        except Exception as e:
            log.exception("Dashboard _rescale_cards crashed: %s", e)

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        build_ui_impl(self)

    def _set_profile_state(self, pid: str, state: str) -> None:
        set_profile_state_impl(self, pid, state)

    def _pulse_profile_box(self, pid: str) -> None:
        pulse_profile_box_impl(self, pid)

    # ------------- Browser -------------

    def open_browser(self, pid: str) -> None:
        if hasattr(self.browser_manager, "open_browser"):
            self.browser_manager.open_browser(pid)
            self._update_reset_btn_state(pid)
        else:
            QMessageBox.warning(self, "Lỗi", "BrowserManager không hỗ trợ open_browser().")

    def reset_browser(self, pid: str) -> None:
        """
        Reset / nối lại kết nối DevTools cho profile **KHÔNG mở thêm trình duyệt mới**.

        - Nếu có DevTools cũ → disconnect và xóa khỏi browser_manager.tabs.
        - Thử attach lại DevTools tới Chrome đang chạy qua BrowserManager.ensure_tab().
        - Nếu không có Chrome đang chạy → báo cho người dùng bấm nút 'Mở'.
        """
        bm = self.browser_manager
        try:
            # 1) Cắt kết nối DevTools cũ nếu có
            tab = None
            if hasattr(bm, "get_active_tab"):
                tab = bm.get_active_tab(pid)  # type: ignore[attr-defined]
            elif hasattr(bm, "tabs"):
                tab = bm.tabs.get(pid)  # type: ignore[attr-defined]

            if tab is not None:
                try:
                    tab.devtools.disconnect()
                except Exception as e:
                    log.warning("Lỗi disconnect DevTools cũ %s: %s", pid, e)

            # 2) Xoá entry cũ trong dict tabs (nếu tồn tại)
            if hasattr(bm, "tabs") and isinstance(bm.tabs, dict):  # type: ignore[attr-defined]
                bm.tabs.pop(pid, None)  # type: ignore[attr-defined]

            # 3) Chỉ attach lại DevTools, KHÔNG mở Chrome mới
            if hasattr(bm, "ensure_tab"):
                try:
                    new_tab = bm.ensure_tab(pid)  # type: ignore[attr-defined]
                except Exception as e:
                    log.error("Reset: ensure_tab thất bại cho %s: %s", pid, e)
                    QMessageBox.warning(
                        self,
                        "Không tìm thấy trình duyệt",
                        (
                            f"Không kết nối lại được tới trình duyệt đang chạy cho {pid}.\n"
                            f"Có thể Chrome chưa mở hoặc mở không đúng port debug.\n"
                            f"Hãy bấm nút 'Mở {pid}' để mở lại trình duyệt."
                        ),
                    )
                    return

                if new_tab is None:
                    QMessageBox.warning(
                        self,
                        "Không tìm thấy trình duyệt",
                        (
                            f"Không phát hiện Chrome đang chạy cho {pid}.\n"
                            f"Hãy bấm nút 'Mở {pid}' để mở lại trình duyệt."
                        ),
                    )
                    return
            else:
                QMessageBox.warning(
                    self,
                    "Reset lỗi",
                    "BrowserManager không hỗ trợ ensure_tab().",
                )
                return

            # 4) Sau reset: trạng thái về idle, để anh quét lại bài nếu muốn
            self._set_profile_state(pid, "idle")
            self._update_reset_btn_state(pid)
        except Exception as e:
            log.error("Lỗi reset_browser cho %s: %s", pid, e)
            QMessageBox.warning(
                self,
                "Reset lỗi",
                f"Không reset được kết nối cho {pid}: {e}",
            )
            self._update_reset_btn_state(pid)

    def close_browser(self, pid: str) -> None:
        if hasattr(self.browser_manager, "close_browser"):
            self.browser_manager.close_browser(pid)
            self._update_reset_btn_state(pid)
        else:
            QMessageBox.warning(self, "Lỗi", "BrowserManager không hỗ trợ close_browser().")


    # ---------------- UI active effects helpers ----------------
    def _btn_set_default(self, btn: Optional[QPushButton], text: Optional[str] = None) -> None:
        if btn is None:
            return
        try:
            if text is not None:
                btn.setText(text)
            btn.setEnabled(True)
            btn.setStyleSheet("")  # reset to default (theme handles)
        except Exception:
            pass

    def _btn_set_success(self, btn: Optional[QPushButton], text: Optional[str] = None) -> None:
        if btn is None:
            return
        try:
            if text is not None:
                btn.setText(text)
            btn.setEnabled(True)
            btn.setStyleSheet("background-color:#2e7d32; color:white; font-weight:bold;")
        except Exception:
            pass

    def _btn_set_busy(self, btn: Optional[QPushButton], text: Optional[str] = None) -> None:
        if btn is None:
            return
        try:
            if text is not None:
                btn.setText(text)
            btn.setEnabled(False)
            btn.setStyleSheet("background-color:#2e7d32; color:white; font-weight:bold;")
        except Exception:
            pass

    def _btn_set_error(self, btn: Optional[QPushButton], text: Optional[str] = None) -> None:
        if btn is None:
            return
        try:
            if text is not None:
                btn.setText(text)
            btn.setEnabled(True)
            btn.setStyleSheet("background-color:#c62828; color:white; font-weight:bold;")
        except Exception:
            pass

    def _is_profile_connected(self, pid: str) -> bool:
        bm = self.browser_manager
        try:
            if hasattr(bm, "get_active_tab"):
                t = bm.get_active_tab(pid)  # type: ignore[attr-defined]
                if t is not None:
                    return True
        except Exception:
            pass
        try:
            if hasattr(bm, "tabs") and isinstance(bm.tabs, dict):  # type: ignore[attr-defined]
                return bm.tabs.get(pid) is not None  # type: ignore[attr-defined]
        except Exception:
            pass
        return False

    def _update_reset_btn_state(self, pid: str) -> None:
        btn = self.ui_btn_reset.get(pid)
        if btn is None:
            return
        if self._is_profile_connected(pid):
            self._btn_set_default(btn, "↻")
        else:
            self._btn_set_error(btn, "↻")

    def _reset_opp_scan_state(self) -> None:
        self._opp_scanned_ok = False
        # Return to the original red style used by dashboard_view for this button.
        self._btn_set_error(self.ui_btn_scan_opp, "Quét bài Đối Thủ (OPP)")

    def _mark_manual_scan_started(self, pid: str) -> None:
        self._scan_pending[pid] = True
        self._btn_set_busy(self.ui_btn_scan.get(pid), f"Đang quét {pid}")

    def _mark_manual_scan_finished(self, pid: str) -> None:
        self._scan_pending[pid] = False
        self._btn_set_default(self.ui_btn_scan.get(pid), f"Quét Bài {pid}")

    def _mark_scan_all_started(self) -> None:
        self._btn_set_busy(self.ui_btn_scan_all, "Đang quét ALL")

    def _mark_scan_all_finished_if_done(self) -> None:
        if any(self._scan_pending.get(p) for p in self.profiles):
            return
        self._btn_set_default(self.ui_btn_scan_all, "Quét Bài ALL")

    def _apply_btn_set_busy(self, pid: str) -> None:
        self._btn_set_busy(self.ui_btn_apply.get(pid), "Đang xếp bài")

    def _apply_btn_set_default(self, pid: str) -> None:
        self._btn_set_default(self.ui_btn_apply.get(pid), f"Áp dụng lên {pid}")
    # ------------- Scan (thread) -------------

    def scan_profiles(self, profiles: List[str]) -> None:
        """
        TỪ BỎ: Dashboard hiện chỉ dùng WebSocket, scan ảnh đã tắt.
        Hàm này giữ lại cho tương thích nhưng không làm gì.
        """
        QMessageBox.information(
            self,
            "Scan ảnh đã tắt",
            "Dashboard hiện chỉ hỗ trợ quét bài qua WebSocket.\n"
            "Tính năng scan ảnh (capture + nhận dạng) đã được vô hiệu hoá."
        )
        return

    def _poll_ws_cards(self) -> None:
        if not self.dashboard_cards_enabled:
            return
        try:
            poll_ws_cards_impl(self)
        except Exception as e:
            log.exception("Dashboard _poll_ws_cards crashed: %s", e)

    def load_ws_cards(self, profiles: List[str]) -> None:
        """
        Wrapper mỏng gọi sang load_ws_cards_impl trong module dashboard_ws.

        UI active effects:
        - Khi bấm nút quét WS thủ công, đổi nút sang trạng thái "Đang quét".
        - Khi _on_profile_scanned nhận bài mới, nút sẽ tự trở về mặc định.
        """
        try:
            if set(profiles) == set(self.profiles):
                self._mark_scan_all_started()
                for pid in self.profiles:
                    self._mark_manual_scan_started(pid)
            else:
                for pid in profiles:
                    if pid in self.profiles:
                        self._mark_manual_scan_started(pid)
        except Exception:
            pass

        load_ws_cards_impl(self, profiles)

    def _on_profile_scanned(self, profile_id, codes, confs, images):
            """
            Được gọi khi WS (hoặc scan) trả về bài mới cho 1 profile.

            Thay vì build gợi ý trực tiếp trong UI thread (dễ lag khi 3P),
            ta đẩy việc build gợi ý sang SuggestionWorker chạy ở thread riêng.
            """
            if not self.dashboard_cards_enabled:
                return
            try:
                # 1. Lưu lại bài quét cho profile
                self.card_codes_flat[profile_id] = codes
                self.card_conf_flat[profile_id] = confs
                self.card_images_pil[profile_id] = images
                # Nếu có bài mới ở 1 trong 3P => reset trạng thái OPP scan (tránh dùng OPP ván cũ)
                if profile_id in self.profiles:
                    self._reset_opp_scan_state()

                # Trả nút quét WS thủ công về mặc định khi đã nhận bài mới
                if profile_id in self.profiles and self._scan_pending.get(profile_id):
                    self._mark_manual_scan_finished(profile_id)
                    self._mark_scan_all_finished_if_done()

                # 2. Gửi job build gợi ý cho profile đó sang worker riêng
                # self._start_suggestion_worker(profile_id)

                # 3. Refresh view + panel nhẹ để hiển thị thô bài mới.
                self.refresh_all_views()
                self.update_engine_panel()
            except Exception as e:
                log.exception(
                    "Dashboard _on_profile_scanned(%s) crashed: %s",
                    profile_id,
                    e,
                )

    def on_scan_opponent_clicked(self) -> None:
        """
        Quét bài đối thủ dựa trên 3P đã đủ 13 lá.

        Sau khi suy ra 13 lá OPP:
        - Xếp chi cho OPP theo mode OPP (Tiền / Max) đang chọn
        - Không đụng tới preview của P1/P2/P3
        - Cập nhật panel Engine + thumbnail OPP
        """
        self._btn_set_busy(self.ui_btn_scan_opp, "Đang quét OPP")
        missing: List[str] = []
        for pid in self.profiles:
            cards = self._get_scanned_cards(pid)
            if not cards or len(cards) != 13:
                missing.append(pid)

        if missing:
            QMessageBox.warning(
                self,
                "Chưa đủ bài 3P",
                "Không thể quét bài đối thủ khi chưa đủ 13 lá cho các profile:\n"
                + ", ".join(missing),
            )
            self._btn_set_error(self.ui_btn_scan_opp, "Quét bài Đối Thủ (OPP)")
            return

        # 1) Dùng logic cũ: 52 lá - (bài của 3P) -> OPP
        self.update_opponent()   # cập nhật self.card_codes_flat["OPP"]

        # 2) Xếp chi cho OPP theo opp-mode hiện tại
        self._arrange_opp_by_current_mode()
        
        # OPP đã có chi preview → rebuild gợi ý cho cả 3P để mode Tiền dùng VS OPP        
        for pid in self.profiles:
            self._start_suggestion_worker(pid)
            
        # 3) Cập nhật UI
        self.refresh_all_views()
        self.update_engine_panel()

        self._opp_scanned_ok = True
        self._btn_set_success(self.ui_btn_scan_opp, "OPP đã quét")

    def _arrange_opp_by_current_mode(self) -> None:
        """
        Sắp xếp chi cho OPP theo opp-mode (Tiền / Max) hiện tại.

        - Dùng 13 lá đã suy ra cho OPP trong self.card_codes_flat["OPP"].
        - Không đụng tới preview của P1/P2/P3.
        - Nếu chưa đủ 13 lá, chỉ reset preview OPP và để update_engine_panel tự xử lý.
        """
        try:
            # Lấy 13 lá đã suy ra cho OPP (dựa trên card_codes_flat["OPP"])
            cards = self._get_scanned_cards("OPP")
            if not cards or len(cards) != 13:
                # Chưa đủ bài → bỏ preview để panel tự hiện "Thiếu bài"
                self.preview_chis["OPP"] = None
                return

            # Xác định mode OPP: 0 = Tiền, 1 = Max
            mode_index = 0
            try:
                # Ưu tiên radio riêng cho OPP nếu có
                if getattr(self, "opp_mode_max", None) is not None and self.opp_mode_max.isChecked():
                    mode_index = 1
                elif getattr(self, "opp_mode_money", None) is not None and self.opp_mode_money.isChecked():
                    mode_index = 0
            except Exception:
                mode_index = 0

            strategy = (
                ArrangeStrategy.MAX_MONEY
                if mode_index == 0
                else ArrangeStrategy.MAX_STRENGTH
            )

            # Dùng cùng logic arrange_cards như phần engine
            chi1, chi2, chi3 = arrange_cards(cards, strategy=strategy)

            # Lưu chi preview cho OPP – update_engine_panel sẽ ưu tiên dùng preview_chis["OPP"]
            self.preview_chis["OPP"] = (chi1, chi2, chi3)
        except Exception as e:
            log.exception("Dashboard _arrange_opp_by_current_mode crashed: %s", e)
            # Nếu có lỗi, reset preview OPP để tránh dùng dữ liệu hỏng
            try:
                self.preview_chis["OPP"] = None
            except Exception:
                pass
    def on_opp_mode_radio_changed(self) -> None:
        """
        Slot được nối từ radio Tiền/Max của Đối thủ (OPP) trong dashboard_view.

        - Khi người dùng đổi mode OPP, ta chỉ sắp xếp lại chi OPP
          theo mode mới, KHÔNG đụng tới P1/P2/P3.
        """
        try:
            # Sắp xếp lại chi OPP theo radio hiện tại
            self._arrange_opp_by_current_mode()
            # Cập nhật hiển thị lá bài + panel Engine
            self.refresh_all_views()
            self.update_engine_panel()
        except Exception as e:
            log.exception("Dashboard on_opp_mode_radio_changed crashed: %s", e)

    def _on_scan_error(self, pid: str, msg: str) -> None:
        # Không còn dùng – chỉ log cho chắc nếu có ai gọi nhầm.
        log.warning("Scan ảnh đã tắt, _on_scan_error(%s, %s)", pid, msg)

    def _on_scan_finished(self) -> None:
        self._scan_thread = None
        self._scan_worker = None

    # ========= NEW SUGGESTION WORKER (thread thuần + queue) =========

    def _stop_suggestion_worker(self, profile_id: str) -> None:
        """Giữ lại cho tương thích – không cố gắng kill thread gợi ý đang chạy.

        Worker mới sẽ được tạo với thế hệ (generation) cao hơn,
        kết quả từ thread cũ (generation thấp hơn) sẽ bị bỏ qua
        trong _poll_suggestions.
        """
        thread = self._suggest_threads.get(profile_id)
        if thread is not None and not thread.is_alive():
            # Dọn các thread đã chết để tránh rò rỉ reference
            self._suggest_threads.pop(profile_id, None)
            
    def _get_opp_chis_snapshot_for_money(self):
        """
        Lấy snapshot chi của OPP để tính MAX_MONEY_VS_OPP cho 3P.
        Nguồn duy nhất: self.preview_chis["OPP"] (đã được _arrange_opp_by_current_mode set).
        """
        try:
            tpl = self.preview_chis.get("OPP")
            if not tpl:
                return None
            chi1, chi2, chi3 = tpl
            if not chi1 or not chi2 or not chi3:
                return None
            if len(chi1) != 5 or len(chi2) != 5 or len(chi3) != 3:
                return None
            return (chi1, chi2, chi3)
        except Exception:
            return None

    def _start_suggestion_worker(self, profile_id: str) -> None:
        """Tạo job SuggestionWorker chạy bằng Python thread thuần.

        - Không dùng QThread / QObject để tránh crash native trong Qt.
        - Mỗi profile chỉ quan tâm tới kết quả của thế hệ (generation) mới nhất.
        """
        if not self.dashboard_suggest_enabled:
            return
        codes = self.card_codes_flat.get(profile_id) or []
        if not codes:
            log.warning(
                "Không có codes để build gợi ý cho profile %s – bỏ qua SuggestionWorker.",
                profile_id,
            )
            return

        # Tăng generation cho profile, dùng để bỏ qua kết quả cũ
        gen = self._suggest_generation.get(profile_id, 0) + 1
        self._suggest_generation[profile_id] = gen

        # Dọn thread cũ nếu đã kết thúc
        self._stop_suggestion_worker(profile_id)

        def _worker(profile_id: str, codes_snapshot: list, generation: int) -> None:
            """Chạy trong Python thread – không đụng vào Qt / QWidget."""
            try:
                suggestions = build_suggestions_for_codes(profile_id, codes_snapshot, opp_chis=None)

                # status, pid, gen, suggestions, message
                self._suggest_queue.put(("ok", profile_id, generation, suggestions, ""))
            except Exception as e:
                log.exception(
                    "Suggestion worker thread cho %s gặp lỗi: %s",
                    profile_id,
                    e,
                )
                self._suggest_queue.put(("err", profile_id, generation, [], str(e)))
            finally:
                # Thread tự dọn reference của chính nó
                try:
                    if (
                        self._suggest_threads.get(profile_id) is threading.current_thread()
                    ):
                        self._suggest_threads.pop(profile_id, None)
                except Exception:
                    pass

        t = threading.Thread(
            target=_worker,
            name=f"MB-Suggest-{profile_id}",
            args=(profile_id, list(codes), gen),
            daemon=True,
        )
        self._suggest_threads[profile_id] = t
        log.info("Start suggestion thread cho profile %s (gen=%s)", profile_id, gen)
        t.start()

    def _poll_suggestions(self) -> None:
        """Rút kết quả từ hàng đợi gợi ý và chuyển về UI thread an toàn.

        Hàm này được gọi định kỳ bởi self._suggest_timer trong main thread.
        """
        try:
            while True:
                try:
                    status, pid, gen, suggestions, message = self._suggest_queue.get_nowait()
                except queue.Empty:
                    break

                # Bỏ qua kết quả cũ (generation thấp hơn)
                if gen != self._suggest_generation.get(pid):
                    continue

                if status == "ok":
                    self._on_suggestions_ready(pid, suggestions)
                else:
                    self._on_suggestion_error(pid, message)
        except Exception as e:
            log.exception("Dashboard _poll_suggestions crashed: %s", e)

    def _on_suggestions_ready(self, profile_id: str, suggestions: list[dict]) -> None:
        """
        Callback trong UI thread khi worker gợi ý trả kết quả thành công.

        - Đồng bộ self.suggestions[profile_id]
        - Cập nhật combobox gợi ý tương ứng
        - Chọn default theo Engine Mode (Tiền / Max)
        - Cập nhật preview_chis + engine panel giống behavior cũ.
        """
        try:
            combo = self.suggestion_combos.get(profile_id)
            suggestions = suggestions or []

            # Sắp xếp: Tiền trước, Max sau – cùng rule với build_suggestions_for_profile_impl
            if suggestions:
                order_weight = {"Tiền": 0, "Max": 1}

                def sort_key(s: dict) -> int:
                    return order_weight.get(s.get("label"), 99)

                suggestions_sorted = sorted(suggestions, key=sort_key)
            else:
                suggestions_sorted = []

            self.suggestions[profile_id] = suggestions_sorted

            # Trường hợp hiếm: chưa gắn combobox nhưng vẫn nhận được gợi ý
            if combo is None:
                if suggestions_sorted:
                    mode_index = 0
                    try:
                        if self.engine_mode_max.isChecked():
                            mode_index = 1
                    except Exception:
                        mode_index = 0

                    if mode_index >= len(suggestions_sorted):
                        mode_index = 0

                    chi1, chi2, chi3 = suggestions_sorted[mode_index]["chi"]
                    self.preview_chis[profile_id] = (chi1, chi2, chi3)
                    self._set_profile_state(profile_id, "preview")
                else:
                    self.preview_chis[profile_id] = None
                    self._set_profile_state(profile_id, "scanned")

                self.refresh_all_views()
                self.update_engine_panel(focus_profile=profile_id)
                return

            # Có combobox: cập nhật UI đúng flow cũ
            combo.blockSignals(True)
            combo.clear()

            if not suggestions_sorted:
                combo.addItem("Không tạo được gợi ý – xem log")
                combo.setEnabled(False)
                self.preview_chis[profile_id] = None
                self._set_profile_state(profile_id, "scanned")
                combo.blockSignals(False)

                self.refresh_all_views()
                self.update_engine_panel(focus_profile=profile_id)
                return

            combo.setEnabled(True)
            for s in suggestions_sorted:
                label_text = _format_suggestion_label(
                    s.get("label"),
                    s.get("money"),
                    s.get("vs_opp"),
                    s.get("chi_types"),
                )
                combo.addItem(label_text)

            # Chọn index theo Engine Mode hiện tại (0=Tiền, 1=Max)
            mode_index = 0
            try:
                if self.engine_mode_max.isChecked():
                    mode_index = 1
            except Exception:
                mode_index = 0

            if mode_index >= len(suggestions_sorted):
                mode_index = 0

            combo.setCurrentIndex(mode_index)
            combo.blockSignals(False)

            # Giữ behavior giống build_suggestions_for_profile_impl:
            # - Lưu preview_chis
            # - Cập nhật Engine panel
            self._on_suggestion_changed(profile_id)
            self._set_profile_state(profile_id, "preview")
        except Exception as e:
            log.exception(
                "Dashboard _on_suggestions_ready(%s) crashed: %s",
                profile_id,
                e,
            )

    def _on_suggestion_error(self, profile_id: str, message: str) -> None:
        """
        Callback khi worker gợi ý báo lỗi – chỉ cập nhật UI nhẹ, không crash.

        - Xoá gợi ý cũ của profile_id
        - Hiển thị thông báo lỗi trong combobox (nếu có)
        - Giữ lại bài đã quét, state chuyển về 'scanned'
        """
        try:
            combo = self.suggestion_combos.get(profile_id)
            if combo is not None:
                combo.blockSignals(True)
                combo.clear()

                text = message or "Lỗi gợi ý – xem log"
                combo.addItem(text)
                combo.setEnabled(False)

                combo.blockSignals(False)

            # Xoá danh sách gợi ý cũ nhưng KHÔNG đụng tới card_codes_flat
            self.suggestions[profile_id] = []
            self.preview_chis[profile_id] = None
            self._set_profile_state(profile_id, "scanned")

            self.refresh_all_views()
            self.update_engine_panel(focus_profile=profile_id)
        except Exception as e:
            log.exception(
                "Dashboard _on_suggestion_error(%s) crashed: %s",
                profile_id,
                e,
            )

    # ------------- Engine core -------------

    def update_opponent(self) -> None:
        update_opponent_impl(self)

    def _get_chi_strings_for_row(self, rowname: str) -> Dict[str, str]:
        codes = self.card_codes_flat[rowname]
        chi_codes: Dict[str, List[str]] = {"chi3": [], "chi2": [], "chi1": []}

        for idx, (chi_name, _) in enumerate(INDEX_TO_CHI):
            if idx >= len(codes):
                break
            code = codes[idx] or "--"
            chi_codes[chi_name].append(code)

        return {k: " ".join(v) if v else "-" for k, v in chi_codes.items()}

    def _refresh_player_thumbnails(self, rowname: str) -> None:
        refresh_player_thumbnails_impl(self, rowname)

    def refresh_all_views(self) -> None:
            """
            Refresh toàn bộ thumbnail + label bài.

            Bọc try/except để tránh 1 lỗi view nhỏ làm app tắt.
            """
            try:
                refresh_all_views_impl(self)
            except Exception as e:
                log.exception("Dashboard refresh_all_views crashed: %s", e)

    # ---- helpers for suggestion / apply ----

    def _get_scanned_cards(self, pid: str) -> Optional[List[Card]]:
        return get_scanned_cards_impl(self, pid)

    def _build_suggestions_for_profile(self, profile_id: str) -> None:
        build_suggestions_for_profile_impl(self, profile_id)

    def suggest_for(self, profile_id: str) -> None:
        suggest_for_impl(self, profile_id)

    def _on_suggestion_changed(self, profile_id: str) -> None:
        on_suggestion_changed_impl(self, profile_id)

    def apply_suggestion_for(self, profile_id: str) -> None:
        apply_suggestion_for_impl(self, profile_id)

    def update_engine_panel(
        self,
        focus_profile: Optional[str] = None,
        forced_chis=None,
    ) -> None:
        """
        Wrapper an toàn cho update_engine_panel_impl.

        - Chấp nhận cả kiểu tuple (hành vi cũ) và dict (chuẩn mới).
        - Convert tuple → dict theo focus_profile nếu cần.
        - Không thay đổi logic tính điểm, chỉ chuẩn hóa dữ liệu đầu vào.
        """
        try:
            # Nếu forced_chis là tuple → convert về dict theo focus_profile
            if forced_chis is not None and not isinstance(forced_chis, dict):
                if focus_profile is not None:
                    forced_chis = {focus_profile: forced_chis}
                else:
                    # không có profile để map → bỏ qua luôn forced_chis
                    forced_chis = None

            # Truyền xuống impl (giữ nguyên behavior cũ)
            update_engine_panel_impl(self, focus_profile, forced_chis)
        except Exception as e:
            log.exception("Dashboard update_engine_panel crashed: %s", e)

    # --------- Mode P1/P2/P3 & Mode OPP ---------

    def on_engine_mode_radio_changed(self) -> None:
        """
        Được gọi khi radio Tiền/Max (cho P1/P2/P3) thay đổi.
        Xác định index (0=Tiền, 1=Max) và chuyển cho layer engine.
        """
        index = 0 if self.engine_mode_money.isChecked() else 1
        self.on_engine_mode_changed(index)

    def on_engine_mode_changed(self, index: int) -> None:
        """
        Cập nhật preview_chis cho P1/P2/P3 theo Engine Mode (Tiền / Max).

        - Không đụng tới OPP (OPP dùng opp-mode riêng).
        - Giữ nguyên danh sách suggestions hiện có, chỉ chọn lại item
          tương ứng trong mỗi profile.
        - Sau khi đổi, cập nhật lại cả UI card lẫn panel Engine.
        """
        try:
            for pid in self.profiles:
                suggs = self.suggestions.get(pid) or []

                # Chọn suggestion theo index: 0 = Tiền, 1 = Max
                if 0 <= index < len(suggs):
                    selected = suggs[index]
                elif suggs:
                    # Nếu thiếu item tương ứng (ví dụ chỉ có 1 gợi ý),
                    # fallback về gợi ý đầu tiên để tránh None.
                    selected = suggs[0]
                else:
                    selected = None

                if selected is not None:
                    chi1, chi2, chi3 = selected["chi"]
                    self.preview_chis[pid] = (chi1, chi2, chi3)
                    self._set_profile_state(pid, "preview")

                    # Nếu có combobox gợi ý cho profile đó thì sync luôn index
                    combo = self.suggestion_combos.get(pid)
                    if combo is not None:
                        combo.blockSignals(True)
                        if 0 <= index < combo.count():
                            combo.setCurrentIndex(index)
                        elif combo.count() > 0:
                            combo.setCurrentIndex(0)
                        combo.blockSignals(False)
                else:
                    self.preview_chis[pid] = None
                    self._set_profile_state(pid, "scanned")

            # Cập nhật lại hiển thị lá bài và panel Engine
            self.refresh_all_views()
            self.update_engine_panel()
        except Exception as e:
            log.exception("Dashboard on_engine_mode_changed crashed: %s", e)
