from __future__ import annotations

from typing import Optional, List, Dict, Any
from PySide6.QtGui import QClipboard
import json
import os
import sys
import queue
import traceback
import atexit
import faulthandler
import signal
from ui2.tools.ws_simulator_ui import WSSimulatorTab
from ui2.phom.main_view import PhomMainView
from engine.phom.store import PhomVisibilityStore

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTabWidget,
    QWidget,
    QStatusBar,
    QComboBox,
    QLabel,
    QPushButton,
    QDialog,
    QVBoxLayout,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap

from core.logger import log
from core.constants import LOG_DIR
from db.database import init_db

# License
from ui2.license.manager import LicenseManager, LicenseState
from ui2.license.ui_activate_dialog import ActivateLicenseDialog

# Heavy modules (only init after license OK)
from browser.manager import BrowserManager
from ui2.game_controller import GameController
from capture.capture_manager import CaptureManager

from ui2.widgets.toast import DesktopToastManager
from ui2.tabs.dashboard_tab import DashboardTab
from ui2.tabs.strategy2 import StrategyTab as StrategyTabV2
from ui2.tabs.profile_tab import ProfileTab
from ui2.tabs.capture_tab import CaptureTab
from ui2.tabs.room_tab import RoomControlTab, TrangThaiPhong, NguoiChoiPhong
from ui2.tabs.profiles_tab_v2 import ProfilesTabV2
from ui2.tabs.config_tab import ConfigTab
from core.config import load_config
from ui2.tabs.players_tab import PlayersTab
from ui2.tabs.poker_tab import PokerTab

ENABLE_TAIXIU = False
if ENABLE_TAIXIU:
    from ui2.tabs.taixiu_tab import TaiXiuTab
    from ui2.tabs.taixiu_control_tab import TaiXiuControlTab
    from ui2.bridge.taixiu_store import tx_store
    from ui2.tabs.auto_spam_tab import AutoSpamTab
    from ui2.tabs.telegram_tab import TelegramTab
    
from ui2.theme import (
    apply_app_theme,
    apply_theme_by_name,
    get_available_themes,
    get_current_theme_name,
    set_current_theme_name,
)

from engine.room_engine import RoomEngine, WebSocketGateway, PhongLobby
from ui2.bridge.ws_http_bridge import (
    start_ws_http_bridge,
    WS_EVENT_QUEUE,
    enqueue_command,
)
from ui2.bridge.ws_payloads import (
    build_ws_payload_update_room_list,
    build_ws_payload_join_room,
    build_ws_payload_leave_room,
)
from ui2.bridge.ws_card_store import ws_card_store


def _global_excepthook(exc_type, exc, tb):
    try:
        log.exception("Uncaught exception", exc_info=(exc_type, exc, tb))
    except Exception:
        pass
    try:
        traceback.print_exception(exc_type, exc, tb)
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        try:
            input("\nỨng dụng gặp lỗi. Nhấn Enter để thoát...")
        except Exception:
            pass


sys.excepthook = _global_excepthook


_CRASH_LOG_FILE = os.path.join(LOG_DIR, "crash_native.log")
_CRASH_LOG_FP = None


def _setup_faulthandler() -> None:
    global _CRASH_LOG_FP
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _CRASH_LOG_FP = open(_CRASH_LOG_FILE, "w", encoding="utf-8")
        faulthandler.enable(file=_CRASH_LOG_FP, all_threads=True)
        try:
            faulthandler.register(signal.SIGTERM, file=_CRASH_LOG_FP, all_threads=True)
        except Exception:
            pass
        log.info("Faulthandler enabled, native crash log -> %s", _CRASH_LOG_FILE)
    except Exception as e:
        try:
            log.error("Không thể bật faulthandler: %s", e)
        except Exception:
            pass


def _on_process_exit() -> None:
    try:
        log.info("PROCESS EXIT: atexit hook được gọi, Qt event loop đã kết thúc.")
    except Exception:
        pass
    global _CRASH_LOG_FP
    if _CRASH_LOG_FP:
        try:
            _CRASH_LOG_FP.flush()
            _CRASH_LOG_FP.close()
        except Exception:
            pass


atexit.register(_on_process_exit)
_setup_faulthandler()


class MainWindow(QMainWindow, WebSocketGateway):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tập trung vào làm! Tài xỉu ít thôi.")

        from PySide6.QtCore import QSize
        self.setMinimumSize(QSize(820, 530))
        self.resize(1280, 630)

        init_db()

        # =========================
        # State placeholders (avoid attribute errors before init)
        # =========================
        self._app_inited = False
        self._activate_dialog_shown_once = False
        self._room_tab_is_floating: bool = False
        self._room_tab_float_window: Optional[QDialog] = None

        self.browser_manager = None
        self.game_controller = None
        self.capture_manager = None
        self.taixiu_tab = None
        self.taixiu_control_tab = None
        self.auto_spam_tab = None
        self.telegram_tab = None
        
        self.tab_widget: Optional[QTabWidget] = None
        self.toast: Optional[DesktopToastManager] = None
        self.room_engine: Optional[RoomEngine] = None

        self._ws_event_queue: "queue.Queue[Dict[str, Any]]" = WS_EVENT_QUEUE
        self._ws_server = None
        self._ws_timer: Optional[QTimer] = None
        self._tx_round_cache = {}
        self._tx_closed_saved = set()
        self._tx_last_sid_by_profile = {}
        self._tx_auto_spam_sent_keys = set()
        self._tx_telegram_sent_keys = set()
        self._tx_auto_scheduled_sids = set()
        self.theme_combo: Optional[QComboBox] = None

        # =========================
        # Minimal UI (LOCK screen)
        # =========================
        self._locked_placeholder = QWidget(self)
        self.setCentralWidget(self._locked_placeholder)

        # =========================
        # Status bar: ONLY license (commercial boot gate)
        # =========================
        status = QStatusBar(self)

        self.lic_label = QLabel("Bản quyền: Chưa kích hoạt")
        self.lic_label.setStyleSheet("padding-left:10px;")

        # NEW: hiển thị License ID + nút copy
        self.lic_id_label = QLabel("")
        self.lic_id_label.setStyleSheet("padding-left:10px;")
        self.lic_id_label.setVisible(False)
        self.lic_id_label.setCursor(Qt.PointingHandCursor)
        self.lic_id_label.setToolTip("Click để copy License ID")
        self.lic_id_label.mousePressEvent = self._on_click_license_id

        self.lic_btn = QPushButton("Kích hoạt")
        self.lic_btn.setFixedHeight(22)
        self.lic_btn.clicked.connect(self._open_activate_dialog)
        # NEW: hiển thị License Key + nút copy key
        self.lic_key_label = QLabel("")
        self.lic_key_label.setStyleSheet("padding-left:10px;")
        self.lic_key_label.setVisible(False)

        self.copy_key_btn = QPushButton("Copy Key")
        self.copy_key_btn.setFixedHeight(22)
        self.copy_key_btn.setVisible(False)
        self.copy_key_btn.clicked.connect(self._copy_license_key)

        status.addPermanentWidget(self.lic_label)
        status.addPermanentWidget(self.lic_id_label)
        status.addPermanentWidget(self.lic_btn)

        self._current_license_key = None

        status.addPermanentWidget(self.lic_key_label)
        status.addPermanentWidget(self.copy_key_btn)

        status.showMessage("Ready")
        self.setStatusBar(status)
        self._status_bar = status

        # =========================
        # License bootstrap (must be early; do NOT start heavy stuff yet)
        # =========================
        self.license_manager = LicenseManager(base_url="https://kiem.go88b.cx", app_version="0.1")
        self.license_manager.state_changed.connect(self._on_license_state_changed)

        # Start after UI is ready
        self.license_manager.start()

        # Sync UI even if first signal was missed
        st = getattr(self.license_manager, "state", None)
        if st is not None:
            self._on_license_state_changed(st)
        else:
            # fail-safe lock
            self._apply_lockdown(True)
            QTimer.singleShot(0, self._open_activate_dialog)

        log.info("MainWindow initialized (minimal boot)")

    # ==========================================================
    # Boot-gate core
    # ==========================================================

    def _apply_lockdown(self, locked: bool) -> None:
        """
        LOCK tuyệt đối:
        - Không khởi động bất kỳ service/worker/ws/timer nào khi chưa kích hoạt.
        - UI chỉ còn status bar + nút kích hoạt.
        """
        try:
            # central widget is either placeholder or tab_widget
            cw = self.centralWidget()
            if cw is not None:
                cw.setEnabled(not locked)

            # always allow activate button
            if self.lic_btn is not None:
                self.lic_btn.setEnabled(True)
                self.lic_btn.setVisible(locked)

            # if locked after being inited, stop background
            if locked:
                self._stop_background_services()
        except Exception:
            pass

    def _init_app_after_license_ok(self) -> None:
        """
        Init toàn bộ hệ thống nặng CHỈ KHI license OK.
        """
        if self._app_inited:
            return
        self._app_inited = True

        # ===== Heavy init starts here =====
        self.browser_manager = BrowserManager()

        self.game_controller = GameController(
            browser_manager=self.browser_manager,
            config=self.browser_manager.config,
        )

        self.capture_manager = CaptureManager(self.browser_manager)

        tabs = QTabWidget(self)
        tabs.setTabPosition(QTabWidget.North)
        tabs.setMovable(False)

        
        # self.dashboard_tab = DashboardTab(self.browser_manager, self.capture_manager, self)
        self.room_tab = RoomControlTab(self.browser_manager, self)
        if ENABLE_TAIXIU:
            # TAB PHÂN TÍCH TÀI XỈU
            # - chỉ đọc dữ liệu DB
            # - hiển thị cầu / lịch sử / money flow / profile result
            self.taixiu_tab = TaiXiuTab(self)

            # TAB KIỂM THỬ / THAO TÁC TÀI XỈU
            # - chứa control đặt cược theo profile
            # - phát signal request_play_tai_xiu như tab cũ
            self.taixiu_control_tab = TaiXiuControlTab(self)
            self.auto_spam_tab = AutoSpamTab(
                self.browser_manager,
                self.capture_manager,
                self,
            )
            self.telegram_tab = TelegramTab(self)
        # self.profile_tab = ProfileTab(self.browser_manager, self)
        self.capture_tab = CaptureTab(self.browser_manager, self.capture_manager, self)
        # self.phom_store = PhomVisibilityStore()
        # self.phom_tab = PhomMainView(store=self.phom_store)
        self.strategy_tab = StrategyTabV2(self.browser_manager, self)
        self.profiles_tab_v2 = ProfilesTabV2(self.browser_manager, self)
        self.config_tab = ConfigTab(self)
        self.players_tab = PlayersTab(self)
        # self.poker_tab = PokerTab(self)
        # PokerTab: realtime refresh snapshot khi có cmd=200 (vào/ra phòng)
        # self.poker_tab.yeu_cau_lam_moi_snapshot.connect(self._on_poker_request_refresh_snapshot)
        # self.ws_sim_tab = WSSimulatorTab(self)

        tabs.addTab(self.strategy_tab, "Chiến Thuật")
        # tabs.addTab(self.poker_tab, "Poker")
        # tabs.addTab(self.phom_tab, "Phỏm")
        tabs.addTab(self.room_tab, "Phòng Game")

        # Tách 2 tab riêng để:
        # - tab Phân Tích chỉ tập trung đọc dữ liệu
        # - tab Kiểm Thử chỉ tập trung thao tác
        if ENABLE_TAIXIU:
            tabs.addTab(self.taixiu_tab, "Tài Xỉu Phân Tích")
            tabs.addTab(self.taixiu_control_tab, "Tài Xỉu Kiểm Thử")
            tabs.addTab(self.auto_spam_tab, "Auto Spam")
            tabs.addTab(self.telegram_tab, "Đọc Lệnh TG")

        # tabs.addTab(self.profile_tab, "Hồ sơ & Trình duyệt")
        tabs.addTab(self.profiles_tab_v2, "Trình duyệt v2")
        tabs.addTab(self.capture_tab, "Fix tọa độ")
        # tabs.addTab(self.dashboard_tab, "Dashboard")
        tabs.addTab(self.config_tab, "Cấu hình")
        tabs.addTab(self.players_tab, "Người chơi")
        # tabs.addTab(self.ws_sim_tab, "Test Bài")
        
        self.tab_widget = tabs
        self.setCentralWidget(tabs)

        # Tự động đưa Phòng Game ra mini window nếu config bật
        try:
            from core.config import load_config

            cfg = load_config()
            ui = cfg.get("ui") or {}
            ui_room = ui.get("room") or {}
            if ui_room.get("mini_as_window"):
                # Dùng singleShot để đợi UI khởi tạo xong
                QTimer.singleShot(0, lambda: self._set_room_tab_floating(True))
        except Exception as e:
            log.error("MainWindow: load ui.room.mini_as_window failed: %s", e)

        # Toast
        self.toast = DesktopToastManager(timeout_ms=5000)

        # RoomEngine
        self.room_engine = RoomEngine(
            room_tab=self.room_tab,
            ws_gateway=self,
            game_controller=self.game_controller,
        )

        self.room_engine.sig_player_joined.connect(self._on_player_joined_toast)
        self.room_engine.sig_player_left.connect(self._on_player_left_toast)

        # Signal đặt cược chỉ lấy từ tab Kiểm Thử
        if ENABLE_TAIXIU:
            self.taixiu_control_tab.request_play_tai_xiu.connect(self._on_request_play_tai_xiu)
        if self.auto_spam_tab is not None:
            self.auto_spam_tab.request_send_test.connect(self._on_request_send_auto_spam_test)
        # WS bridge + poll timer
        self._ws_server = start_ws_http_bridge(port=9527)
        log.info("WS HTTP bridge listening on 127.0.0.1:9527")

        self._ws_timer = QTimer(self)
        self._ws_timer.setInterval(100)
        self._ws_timer.timeout.connect(self._poll_ws_events)
        self._ws_timer.start()

        # Add theme widgets AFTER OK (keep lock screen clean)
        self._init_theme_widgets()

        log.info("App initialized after license OK")

    def _set_room_tab_floating(self, floating: bool) -> None:
        """
        Đưa tab 'Phòng Game' ra cửa sổ mini (floating) hoặc đưa về lại QTabWidget (dock).
        Không tạo RoomControlTab mới, chỉ đổi parent của self.room_tab.
        """
        # Phòng hờ nếu chưa khởi tạo xong
        if not hasattr(self, "tab_widget") or not hasattr(self, "room_tab"):
            return

        # BẬT floating
        if floating:
            if self._room_tab_is_floating:
                # Đã ở trạng thái floating rồi thì bỏ qua
                return

            # Tìm index tab Phòng Game trong QTabWidget
            try:
                idx = self.tab_widget.indexOf(self.room_tab)
            except Exception:
                idx = -1

            # Gỡ tab khỏi QTabWidget (nếu còn nằm trong tabs)
            if idx != -1:
                self.tab_widget.removeTab(idx)

            # Tạo dialog mini
            dlg = QDialog(self)
            dlg.setWindowTitle("Phòng Game (Mini)")
            dlg.setAttribute(Qt.WA_DeleteOnClose)

            # Layout cho dialog
            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            dlg.setLayout(layout)

            # Đưa room_tab vào dialog + bắt buộc show lại
            layout.addWidget(self.room_tab)
            try:
                self.room_tab.show()
            except Exception:
                pass

            dlg.resize(610, 600)

            # Lưu state
            self._room_tab_float_window = dlg
            self._room_tab_is_floating = True

            # Khi dialog đóng bằng nút X → tự dock lại
            def _on_closed(_result: int = 0, self_ref=self) -> None:
                # Chỉ gọi lại nếu hiện tại vẫn đang floating
                if self_ref._room_tab_is_floating:
                    self_ref._set_room_tab_floating(False)

            dlg.finished.connect(_on_closed)

            dlg.show()
            return

        # TẮT floating → dock lại vào QTabWidget
        if not self._room_tab_is_floating:
            # Đã dock rồi thì bỏ qua
            return

        dlg = self._room_tab_float_window

        # Đánh dấu state TRƯỚC khi close dialog để tránh loop callback
        self._room_tab_is_floating = False
        self._room_tab_float_window = None

        # Tách room_tab khỏi dialog
        try:
            self.room_tab.setParent(None)
        except Exception:
            pass

        # Đóng dialog nếu còn
        if dlg is not None:
            try:
                dlg.close()
            except Exception:
                pass

        # Thêm lại tab Phòng Game nếu chưa có
        try:
            idx = self.tab_widget.indexOf(self.room_tab)
        except Exception:
            idx = -1

        if idx == -1:
            self.tab_widget.addTab(self.room_tab, "Phòng Game")

    def _on_request_play_tai_xiu(self, profile_id: str, params: dict) -> None:
        """
        Nhận signal từ tab Kiểm Thử Tài Xỉu và chuyển xuống game_controller.

        Lưu ý:
        - Tab Phân Tích không phát signal cược.
        - Tab Kiểm Thử mới là nơi thao tác.
        - Tuy nhiên vẫn cập nhật status cho cả 2 tab để người dùng nhìn đồng bộ.
        """
        if not ENABLE_TAIXIU:
            return

        if self.game_controller is None:
            msg = "Lỗi: game_controller chưa khởi tạo"

            try:
                if hasattr(self, "taixiu_control_tab") and self.taixiu_control_tab is not None:
                    self.taixiu_control_tab.dat_trang_thai(msg)
            except Exception:
                pass

            try:
                if hasattr(self, "taixiu_tab") and self.taixiu_tab is not None:
                    self.taixiu_tab.dat_trang_thai(msg)
            except Exception:
                pass

            return

        try:
            side = str(params.get("side") or "").strip().lower()
            bet = int(params.get("bet") or 0)
            delay_ms = int(params.get("delay_ms") or 0)

            self.game_controller.play_tai_xiu_once(
                profile_id=profile_id,
                bet=bet,
                side=side,
                delay_ms=delay_ms,
            )

            msg = f"Đã chơi {'TÀI' if side == 'tai' else 'XỈU'} | {profile_id} | Bet {bet}"

            # Tab Kiểm Thử: hiển thị status thao tác
            try:
                if hasattr(self, "taixiu_control_tab") and self.taixiu_control_tab is not None:
                    self.taixiu_control_tab.dat_trang_thai(msg)
                    self.taixiu_control_tab.dat_trang_thai_profile(profile_id, msg)
            except Exception:
                pass

            # Tab Phân Tích: chỉ hiển thị status chung
            try:
                if hasattr(self, "taixiu_tab") and self.taixiu_tab is not None:
                    self.taixiu_tab.dat_trang_thai(msg)
            except Exception:
                pass

        except Exception as e:
            msg = f"Lỗi: {e}"

            try:
                if hasattr(self, "taixiu_control_tab") and self.taixiu_control_tab is not None:
                    self.taixiu_control_tab.dat_trang_thai(msg)
                    self.taixiu_control_tab.dat_trang_thai_profile(profile_id, msg)
            except Exception:
                pass

            try:
                if hasattr(self, "taixiu_tab") and self.taixiu_tab is not None:
                    self.taixiu_tab.dat_trang_thai(msg)
            except Exception:
                pass
            
    def _on_request_send_auto_spam_test(self, profile_id: str, message: str) -> None:
        if not ENABLE_TAIXIU:
            return
        if self.game_controller is None:
            if self.auto_spam_tab is not None:
                self.auto_spam_tab.dat_trang_thai("Lỗi: game_controller chưa khởi tạo")
            return

        try:
            self.game_controller.send_auto_spam_message(profile_id, message)
            if self.auto_spam_tab is not None:
                self.auto_spam_tab.dat_trang_thai(
                    f"Gửi test thành công | {profile_id} | {message}"
                )
        except Exception as e:
            if self.auto_spam_tab is not None:
                self.auto_spam_tab.dat_trang_thai(f"Lỗi gửi test: {e}")

    def _trigger_taixiu_auto_spam(
        self,
        profile_id: str,
        sid: str,
        result_side: str,
        total: int,
    ) -> None:
        if not ENABLE_TAIXIU:
            return
        if self.game_controller is None:
            return
        if self.auto_spam_tab is None:
            return

        pid = str(profile_id or "P1")
        sid_str = str(sid or "").strip()
        side = str(result_side or "").strip().lower()

        if not sid_str:
            return
        if side not in ("tai", "xiu"):
            return

        sent_key = (pid, sid_str)
        if sent_key in self._tx_auto_spam_sent_keys:
            return

        settings = self.auto_spam_tab.get_runtime_settings(pid)
        if not bool(settings.get("enabled")):
            return

        ket_qua_text = f"{'Tài' if side == 'tai' else 'Xỉu'} - {int(total)}"
        message = self.auto_spam_tab.render_message(pid, ket_qua_text).strip()

        if not message:
            self.auto_spam_tab.dat_trang_thai(
                f"Bỏ qua auto spam {pid}: chưa có nội dung mẫu."
            )
            return

        try:
            self.game_controller.send_auto_spam_message(pid, message)
            self._tx_auto_spam_sent_keys.add(sent_key)
            self.auto_spam_tab.dat_trang_thai(
                f"Đã auto chat | {pid} | Phiên {sid_str} | {message}"
            )
        except Exception as e:
            self.auto_spam_tab.dat_trang_thai(
                f"Lỗi auto chat | {pid} | Phiên {sid_str} | {e}"
            )

    def _trigger_telegram_bot(
        self,
        profile_id: str,
        sid: str,
        result_side: str,
        total: int,
    ) -> None:
        if self.telegram_tab is None:
            return

        pid = str(profile_id or "P1")
        sid_str = str(sid or "").strip()

        if not sid_str:
            return

        sent_key = (pid, sid_str)
        if sent_key in self._tx_telegram_sent_keys:
            return

        try:
            cfg = self.telegram_tab._read_config()
            tg = ((cfg.get("game_ui") or {}).get("telegram_bot") or {})

            if not tg.get("enabled"):
                return

            token = tg.get("bot_token")
            chat_ids = tg.get("chat_ids", [])
            raw_schedules = tg.get("schedules", []) or []
            schedules = sorted(
                raw_schedules,
                key=lambda x: int((x or {}).get("delay", 0))
            )

            if not token or not chat_ids or not schedules:
                return

            self._tx_telegram_sent_keys.add(sent_key)

            import threading
            import time
            import requests

            ket_qua_text = f"{'Tài' if result_side == 'tai' else 'Xỉu'} - {int(total)}"

            def worker():
                start_time = time.time()

                for item in schedules:
                    delay = int(item.get("delay", 0))
                    template = str(item.get("template") or "").strip()

                    if not template:
                        continue

                    wait_time = delay - (time.time() - start_time)
                    if wait_time > 0:
                        time.sleep(wait_time)

                    msg = template.replace("[KetQua]", ket_qua_text)

                    for chat_id in chat_ids:
                        try:
                            requests.post(
                                f"https://api.telegram.org/bot{token}/sendMessage",
                                data={
                                    "chat_id": chat_id,
                                    "text": msg
                                },
                                timeout=5
                            )
                        except Exception as e:
                            print("TG send lỗi:", e)

            threading.Thread(target=worker, daemon=True).start()

        except Exception as e:
            print("Telegram auto lỗi:", e)
            
    def _init_theme_widgets(self) -> None:
        try:
            if self.theme_combo is not None:
                return

            self.theme_combo = QComboBox()
            self.theme_combo.addItems(get_available_themes())
            current_theme = get_current_theme_name()
            idx = self.theme_combo.findText(current_theme)
            if idx >= 0:
                self.theme_combo.setCurrentIndex(idx)
            self.theme_combo.currentTextChanged.connect(self.on_theme_changed)

            logo_label = QLabel()
            pix = QPixmap(resource_path("icon.ico"))
            pix = pix.scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pix)
            logo_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            logo_label.setStyleSheet("padding-left:6px; padding-bottom:2px;")

            self._status_bar.addPermanentWidget(logo_label)
            self._status_bar.addPermanentWidget(QLabel("Giao diện:"))
            self._status_bar.addPermanentWidget(self.theme_combo)
        except Exception:
            pass

    def _stop_background_services(self) -> None:
        """
        Stop everything heavy (idempotent).
        """
        try:
            if self._ws_timer is not None:
                self._ws_timer.stop()
        except Exception:
            pass
        try:
            if self._ws_server:
                self._ws_server.shutdown()
        except Exception:
            pass

        self._ws_timer = None
        self._ws_server = None

    # ==========================================================
    # License UI + gating
    # ==========================================================

    def _on_license_state_changed(self, state: LicenseState):
        try:
            ok = bool(getattr(state, "ok", False))
            reason = getattr(state, "reason", "")
            payload = getattr(state, "payload", None) or {}

            # Update bottom bar: expiry
            exp_text = ""
            exp = payload.get("exp")
            if isinstance(exp, int):
                try:
                    from datetime import datetime
                    exp_text = datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    exp_text = str(exp)

            if ok:
                if exp_text:
                    self.lic_label.setText(f"Bản quyền: OK | Hết hạn: {exp_text}")
                else:
                    self.lic_label.setText("Bản quyền: OK")

                # unlock + init app if needed
                self._apply_lockdown(False)
                self.lic_btn.setVisible(False)

                self._init_app_after_license_ok()
                lid = ""
                try:
                    lid = self.license_manager.get_cached_license_id() or ""
                except Exception:
                    lid = ""

                if lid:
                    self.lic_id_label.setText(f"License ID: {lid}")
                    self.lic_id_label.setVisible(True)
                else:
                    self.lic_id_label.setText("")
                    self.lic_id_label.setVisible(False)

                key = None
                try:
                    key = self.license_manager.get_cached_license_key()
                except Exception:
                    key = None

                self._current_license_key = key

                if key:
                    self.lic_key_label.setText(f"Key: {key}")
                    self.copy_key_btn.setVisible(True)
                else:
                    self.lic_key_label.setText("")
                    self.copy_key_btn.setVisible(False)

            else:
                if reason:
                    self.lic_label.setText(f"Bản quyền: LOCK | {reason}")
                else:
                    self.lic_label.setText("Bản quyền: Chưa kích hoạt")

                # vẫn hiện License ID để user copy gửi gia hạn
                lid = ""
                try:
                    lid = self.license_manager.get_cached_license_id() or ""
                except Exception:
                    lid = ""

                if lid:
                    self.lic_id_label.setText(f"License ID: {lid}")
                    self.lic_id_label.setVisible(True)
                else:
                    self.lic_id_label.setText("")
                    self.lic_id_label.setVisible(False)

                # lock absolutely
                self._apply_lockdown(True)
                self.lic_btn.setVisible(True)

                # auto show dialog once on boot / first lock
                if not self._activate_dialog_shown_once:
                    self._activate_dialog_shown_once = True
                    QTimer.singleShot(0, self._open_activate_dialog)

                self._current_license_key = None
                self.lic_key_label.setText("")
                self.copy_key_btn.setVisible(False)

        except Exception:
            log.exception("Lỗi trong _on_license_state_changed")

    def _open_activate_dialog(self):
        reason = ""
        try:
            st = getattr(self.license_manager, "state", None)
            if st is not None:
                reason = getattr(st, "reason", "") or ""
        except Exception:
            reason = ""

        dlg = ActivateLicenseDialog(self.license_manager, reason=reason, parent=self)
        dlg.exec()

    # ==========================================================
    # WS bridge polling (runs only after init OK)
    # ==========================================================

    def _poll_ws_events(self) -> None:
        if self._ws_timer is None:
            return
        if not self._app_inited:
            return

        max_per_tick = 15
        n = 0

        while n < max_per_tick:
            try:
                evt = self._ws_event_queue.get_nowait()
            except queue.Empty:
                break

            try:
                self._handle_bridge_event(evt)
            except Exception:
                log.exception("Lỗi xử lý event từ extension: %s", evt)

            n += 1

    def _handle_bridge_event(self, evt: Dict[str, Any]) -> None:
        if not self._app_inited:
            return

        kind = evt.get("kind")

        # Chỉ chặn các event cần RoomEngine khi RoomEngine chưa sẵn sàng.
        # Các event độc lập (poker/phom/self/cards) vẫn cho chạy để UI realtime.
        if self.room_engine is None and kind in ("room_list", "room_snapshot", "room_event"):
            return

        profile_id = str(evt.get("profile_id") or "P1")

        cs = None
        if isinstance(evt.get("cs"), list):
            cs = evt.get("cs")

        payload = evt.get("payload")
        # --- FIX: unwrap payload dạng [opcode, {...}] ---
        if isinstance(payload, list) and len(payload) >= 2 and isinstance(payload[1], dict):
            payload = payload[1]
            evt["payload"] = payload

        if cs is None and isinstance(payload, dict) and isinstance(payload.get("cs"), list):
            cs = payload.get("cs")

        cmd = None
        if isinstance(payload, dict):
            cmd = payload.get("cmd") or payload.get("CMD")
            
        # --- TÀI/XỈU: bản tối giản nhưng đủ để lưu theo phiên ---
        #
        # Mục tiêu:
        # 1) cmd 1008 -> tạo / cập nhật "khung phiên" và nhớ sid gần nhất theo profile
        # 2) cmd 1000 -> lưu user bet, kể cả khi packet thiếu sid (fallback last_sid)
        # 3) cmd 1003/1004/1005 -> lưu xúc xắc + kết quả, kể cả khi packet thiếu sid (fallback last_sid)
        # 4) khi có kết quả -> tự settle thắng / thua cho toàn bộ bet cùng sid
        #
        # Cố ý KHÔNG xử lý:
        # - 1011, 10000, 10003, 1015
        # để tránh bẩn DB và tránh đơ UI
        if kind == "taixiu_ws":
            if not ENABLE_TAIXIU:
                return

            try:
                if not isinstance(payload, dict):
                    return

                cmd = payload.get("cmd") or payload.get("CMD")
                sid = payload.get("sid")
                sid_str = str(sid) if sid is not None else None

                # Chỉ xử lý tài xỉu thường ở block này
                game_type = "normal"

                # --------------------------------------------------
                # Helper nhỏ:
                # Nếu packet không có sid thì lấy sid gần nhất của profile.
                # Đây là chìa khóa để bắt được result / bet khi server không gửi sid.
                # --------------------------------------------------
                last_sid = self._tx_last_sid_by_profile.get(profile_id)
                effective_sid = sid_str or last_sid

                # --------------------------------------------------
                # 1) USER BET - cmd 1000
                #
                # Trường hợp tốt nhất:
                # - packet có sid -> lưu trực tiếp
                #
                # Trường hợp packet không có sid:
                # - dùng sid gần nhất đã nhớ từ 1008 của chính profile đó
                # --------------------------------------------------
                if cmd == 1000:
                    if not effective_sid:
                        return

                    eid_raw = str(payload.get("eid") or "")
                    amount = int(payload.get("b") or 0)

                    # Mapping tối giản:
                    # - eid=1 => tài
                    # - eid=0 hoặc 2 => xỉu
                    bet_side = None
                    if eid_raw == "1":
                        bet_side = "tai"
                    elif eid_raw in ("0", "2"):
                        bet_side = "xiu"

                    tx_store.save_user_bet(
                        game_type=game_type,
                        sid=effective_sid,
                        profile_id=profile_id,
                        bet_side=bet_side,
                        bet_amount=amount,
                        eid_raw=eid_raw,
                        source_cmd=cmd,
                    )
                    return

                # --------------------------------------------------
                # 2) SNAPSHOT PHIÊN - cmd 1008
                #
                # Đây là packet quan trọng nhất để:
                # - lấy sid thật
                # - nhớ sid gần nhất của profile
                # - lưu totals và số user 2 bên
                # --------------------------------------------------
                if cmd == 1008:
                    if not sid_str:
                        return

                    # Nhớ sid gần nhất của profile để packet result / bet về sau fallback được
                    self._tx_last_sid_by_profile[profile_id] = sid_str

                    gi = payload.get("gi") or []
                    tai_total_bet = 0
                    xiu_total_bet = 0
                    tai_total_users = 0
                    xiu_total_users = 0

                    if isinstance(gi, list) and gi:
                        first = gi[0] if isinstance(gi[0], dict) else {}
                        b_side = first.get("B") or {}
                        s_side = first.get("S") or {}

                        if isinstance(b_side, dict):
                            tai_total_users = int(b_side.get("tU") or 0)
                            tai_total_bet = int(b_side.get("tB") or 0)

                        if isinstance(s_side, dict):
                            xiu_total_users = int(s_side.get("tU") or 0)
                            xiu_total_bet = int(s_side.get("tB") or 0)

                    tx_store.upsert_round(
                        game_type=game_type,
                        sid=sid_str,
                        updates={
                            "profile_id_first_seen": profile_id,
                            "profile_id_last_seen": profile_id,
                            "game_state": payload.get("gS"),
                            "remain_time_ms": payload.get("rmT"),
                            "tai_total_bet": tai_total_bet,
                            "xiu_total_bet": xiu_total_bet,
                            "tai_total_users": tai_total_users,
                            "xiu_total_users": xiu_total_users,
                            "totals_cmd": cmd,
                            "raw_last_json": None,
                        },
                    )
                    return

                # --------------------------------------------------
                # 3) KẾT QUẢ PHIÊN - cmd 1003 / 1004 / 1005
                #
                # Trường hợp packet không có sid:
                # - fallback sang sid gần nhất của profile
                #
                # Đây là phần còn thiếu lớn nhất trước đó.
                # --------------------------------------------------
                if cmd in (1003, 1004, 1005):
                    if not effective_sid:
                        return

                    if payload.get("d1") is None or payload.get("d2") is None or payload.get("d3") is None:
                        return

                    d1 = int(payload.get("d1") or 0)
                    d2 = int(payload.get("d2") or 0)
                    d3 = int(payload.get("d3") or 0)

                    total = d1 + d2 + d3
                    result_side = "tai" if total >= 11 else "xiu"
                    is_triple = 1 if (d1 == d2 == d3) else 0

                    updates = {
                        "profile_id_first_seen": profile_id,
                        "profile_id_last_seen": profile_id,
                        "game_state": payload.get("gS"),
                        "remain_time_ms": payload.get("rmT"),
                        "dice_1": d1,
                        "dice_2": d2,
                        "dice_3": d3,
                        "total": total,
                        "result_side": result_side,
                        "is_triple": is_triple,
                        "result_cmd": cmd,
                        "is_final": 1,
                        "raw_last_json": None,
                    }

                    # Nếu 1005 có luôn gi thì tranh thủ cập nhật totals
                    gi = payload.get("gi") or []
                    if isinstance(gi, list) and gi:
                        first = gi[0] if isinstance(gi[0], dict) else {}
                        b_side = first.get("B") or {}
                        s_side = first.get("S") or {}

                        if isinstance(b_side, dict):
                            updates["tai_total_users"] = int(b_side.get("tU") or 0)
                            updates["tai_total_bet"] = int(b_side.get("tB") or 0)

                        if isinstance(s_side, dict):
                            updates["xiu_total_users"] = int(s_side.get("tU") or 0)
                            updates["xiu_total_bet"] = int(s_side.get("tB") or 0)

                    # Lưu kết quả phiên
                    tx_store.upsert_round(
                        game_type=game_type,
                        sid=effective_sid,
                        updates=updates,
                    )

                    # Chốt thắng/thua cho toàn bộ cược cùng sid
                    tx_store.settle_user_bets(
                        game_type=game_type,
                        sid=effective_sid,
                        result_side=result_side,
                    )
                    # --------------------------------------------------
                    # AUTO KIỂM THỬ:
                    # Sau khi phiên vừa có kết quả final,
                    # đợi 20 giây rồi mới kích hoạt auto cho phiên kế tiếp.
                    # --------------------------------------------------
                    try:
                        final_sid_str = str(effective_sid or "").strip()
                        if (
                            final_sid_str
                            and self.taixiu_control_tab is not None
                            and final_sid_str not in self._tx_auto_scheduled_sids
                        ):
                            self._tx_auto_scheduled_sids.add(final_sid_str)

                            def _fire_auto_from_final(sid_to_use=final_sid_str, gt=game_type):
                                try:
                                    if self.taixiu_control_tab is None:
                                        return

                                    final_rows = tx_store.get_recent_final_rounds(
                                        game_type=gt,
                                        limit=200
                                    )

                                    self.taixiu_control_tab.on_auto_final_ready(
                                        sid_to_use,
                                        final_rows or []
                                    )
                                except Exception:
                                    log.exception("Auto control delayed fire failed")

                            QTimer.singleShot(20000, _fire_auto_from_final)
                            log.info(
                                "Auto control scheduled after final result | sid=%s | delay=20000ms",
                                final_sid_str
                            )
                    except Exception:
                        log.exception("Auto control schedule after final failed")

                    try:
                        self._trigger_taixiu_auto_spam(
                            profile_id=profile_id,
                            sid=effective_sid,
                            result_side=result_side,
                            total=total,
                        )
                        try:
                            self._trigger_telegram_bot(
                                profile_id=profile_id,
                                sid=effective_sid,
                                result_side=result_side,
                                total=total,
                            )
                        except Exception:
                            log.exception("Telegram auto failed")
                    except Exception:
                        log.exception(
                            "Auto spam Tài/Xỉu failed: pid=%s sid=%s side=%s total=%s",
                            profile_id,
                            effective_sid,
                            result_side,
                            total,
                        )
                    return

                # Các cmd còn lại: bỏ qua để tránh nặng UI
                return

            except Exception:
                log.exception("Lỗi xử lý taixiu_ws: profile=%s payload=%s", profile_id, payload)

            return
            
        # --- PHỎM: cmd 850/851/852 ---
        if kind == "phom_ws":
            try:
                # 1) update store phỏm trước (để UI có dữ liệu ngay)
                if hasattr(self, "phom_store") and self.phom_store is not None:
                    self.phom_store.update_from_ws_event(profile_id, payload)

                # 2) refresh UI ngay lập tức (realtime)
                if hasattr(self, "phom_tab") and self.phom_tab is not None:
                    self.phom_tab.refresh()

            except Exception:
                log.exception("Lỗi xử lý phom_ws: profile=%s payload=%s", profile_id, payload)
            return

        if cs is not None and (kind in ("cards_snapshot", "cards", "hand_cards") or cmd in (600, 606)):
            try:
                ws_card_store.update_cards(profile_id, cs)
            except Exception:
                log.exception("Lỗi khi cập nhật bài từ WS cho profile %s, cs=%s", profile_id, cs)
                
        # --- POKER: cmd 750 (phân vai) ---
        if kind == "poker_roles":
            try:
                if hasattr(self, "poker_tab") and self.poker_tab is not None and isinstance(payload, dict):
                    self.poker_tab.on_poker_roles(profile_id, payload)
            except Exception:
                log.exception("poker on_poker_roles failed: pid=%s payload=%s", profile_id, payload)
            return
                
        # --- SNAPSHOT PHÒNG: cmd 202 (lấy Seat# + danh sách người chơi) ---
        if cmd == 202 and isinstance(payload, dict) and isinstance(payload.get("ps"), list):
            try:
                if hasattr(self, "poker_tab") and self.poker_tab is not None:
                    self.poker_tab.on_room_snapshot(profile_id, payload)
            except Exception:
                log.exception("poker on_room_snapshot failed: pid=%s payload=%s", profile_id, payload)
            # KHÔNG return ở đây: để RoomEngine vẫn xử lý snapshot như cũ
        # --- NEW: self info (cmd=100) ---
        if isinstance(payload, dict) and cmd == 100:
            # payload ví dụ: {"cmd":100,"uid":"1_...","dn":"...","As":{"gold":...}}
            # 1) Update PHỎM store để UI Phỏm hiển thị Tên/Tiền/UID theo đúng profile
            try:
                if hasattr(self, "phom_store") and self.phom_store is not None:
                    # bạn sẽ thêm hàm này trong engine/phom/store.py (đã hướng dẫn trước)
                    self.phom_store.update_self_info(profile_id, payload)

                if hasattr(self, "phom_tab") and self.phom_tab is not None:
                    self.phom_tab.refresh()
            except Exception:
                log.exception("phom update_self_info failed: pid=%s payload=%s", profile_id, payload)

            # 2) Giữ nguyên luồng RoomEngine (không phá hệ thống phòng)
            try:
                if self.room_engine is not None:
                    self.room_engine.on_self_info_100(profile_id, payload)
            except Exception:
                log.exception("on_self_info_100 failed: pid=%s payload=%s", profile_id, payload)
            # 3) NEW: update Poker self UID (cực quan trọng cho Poker Decision Engine)
            try:
                if hasattr(self, "poker_tab") and self.poker_tab is not None:
                    self.poker_tab.on_self_info(profile_id, payload)
            except Exception:
                log.exception("poker on_self_info failed: pid=%s payload=%s", profile_id, payload)

            return

        if isinstance(payload, dict) and cmd == 200:
            # 1) RoomEngine xử lý như cũ
            if self.room_engine is not None:
                self.room_engine.on_room_event_200(profile_id, payload)

            # 2) NEW: PokerTab cũng phải nhận cmd=200 để trigger refresh snapshot
            try:
                if hasattr(self, "poker_tab") and self.poker_tab is not None:
                    self.poker_tab.on_room_event_200(profile_id, payload)
            except Exception:
                log.exception("poker on_room_event_200 failed: pid=%s payload=%s", profile_id, payload)

            return

        if kind == "room_list":
            rooms = evt.get("rooms") or []
            if isinstance(rooms, list):
                self.handle_ws_room_list(profile_id, rooms)

        elif kind == "room_snapshot":
            payload = evt.get("payload") or {}
            if isinstance(payload, dict):
                self.handle_ws_room_snapshot(profile_id, payload)

        else:
            log.debug("Nhận event WS chưa hỗ trợ (kind=%r): %s", kind, evt)
            
    def _on_poker_request_refresh_snapshot(self, profile_id: str) -> None:
        """
        PokerTab yêu cầu refresh snapshot (cmd=202) sau cmd=200.
        Không có ws_payload riêng cho snapshot, nên kích lại bằng join_room(rid hiện tại).
        """
        if not self._app_inited:
            return

        pid = str(profile_id or "P1")

        # Lấy rid từ state PokerTab (đã được cập nhật từ cmd=202 trước đó)
        rid = None
        try:
            if hasattr(self, "poker_tab") and self.poker_tab is not None:
                st = getattr(self.poker_tab, "_state", {}) or {}
                rid = (st.get(pid) or {}).get("room_id")
        except Exception:
            rid = None

        if not rid:
            log.debug("[Poker] refresh snapshot bỏ qua vì chưa có rid (pid=%s)", pid)
            return

        try:
            rid_int = int(rid)
        except Exception:
            log.debug("[Poker] rid không hợp lệ (pid=%s rid=%r)", pid, rid)
            return

        # Kích lại server gửi snapshot = gửi lại join_room rid hiện tại (idempotent trên đa số server)
        enqueue_command(
            {
                "profile_id": pid,
                "action": "join_room",
                "room_id": rid_int,
                "ws_payload": build_ws_payload_join_room(rid_int),
            }
        )

    # ===================== WebSocketGateway =====================

    def yeu_cau_cap_nhat_danh_sach_phong(self, profile_id: str, bet_muc_tieu: int | None) -> None:
        if not self._app_inited:
            return
        log.info("[WS-GW] %s yêu cầu CẬP NHẬT DANH SÁCH PHÒNG, bet_muc_tieu=%s", profile_id, bet_muc_tieu)
        enqueue_command(
            {
                "profile_id": profile_id,
                "action": "update_room_list",
                "bet_muc_tieu": bet_muc_tieu,
                "ws_payload": build_ws_payload_update_room_list(),
            }
        )

    def gui_lenh_tao_phong(self, profile_id: str, bet: int | None) -> None:
        if not self._app_inited:
            return
        log.info("[WS-GW] %s yêu cầu TẠO PHÒNG, bet=%s", profile_id, bet)

    def gui_lenh_vao_phong(self, profile_id: str, room_id: int) -> None:
        if not self._app_inited:
            return
        log.info("[WS-GW] %s JOIN_ROOM rid=%s", profile_id, room_id)
        enqueue_command(
            {
                "profile_id": profile_id,
                "action": "join_room",
                "room_id": int(room_id),
                "ws_payload": build_ws_payload_join_room(int(room_id)),
            }
        )

    def gui_lenh_thoat_phong(self, profile_id: str) -> None:
        if not self._app_inited:
            return
        log.info("[WS-GW] %s LEAVE_ROOM", profile_id)
        enqueue_command(
            {
                "profile_id": profile_id,
                "action": "leave_room",
                "ws_payload": build_ws_payload_leave_room(),
            }
        )

    # ======================================================================
    # Bridge -> Engine conversion
    # ======================================================================

    def handle_ws_room_list(self, profile_id: str, raw_rooms_payload: List[Dict[str, Any]]) -> None:
        if self.room_engine is None:
            return

        ds: List[PhongLobby] = []
        for r in raw_rooms_payload:
            try:
                room_id = int(r.get("rid"))
                bet = int(r.get("b"))
            except Exception:
                continue

            so_nguoi_toi_da = int(r.get("Mu", 4) or 4)
            so_nguoi_hien_tai = int(r.get("uC", 0) or 0)
            co_mat_khau = bool(r.get("hpwd", False))

            ds.append(
                PhongLobby(
                    room_id=room_id,
                    bet=bet,
                    so_nguoi_hien_tai=so_nguoi_hien_tai,
                    so_nguoi_toi_da=so_nguoi_toi_da,
                    co_mat_khau=co_mat_khau,
                )
            )

        self.room_engine.on_danh_sach_phong(profile_id, ds)

    def handle_ws_room_snapshot(self, profile_id: str, payload: Dict[str, Any]) -> None:
        if self.room_engine is None:
            return

        ps = payload.get("ps") or []
        so_nguoi = len(ps)
        so_nguoi_toi_da = int(payload.get("Mu", so_nguoi or 4) or 4)

        ds_nguoi_choi: List[NguoiChoiPhong] = []
        for p in ps:
            ds_nguoi_choi.append(
                NguoiChoiPhong(
                    ghe=int(p.get("sit", -1) or -1),
                    uid=str(p.get("uid", "")),
                    ten=str(p.get("dn", "")),
                    vang=(p.get("As") or {}).get("gold"),
                )
            )

        my_uid = None
        if ds_nguoi_choi:
            my_uid = ds_nguoi_choi[0].uid

        trang_thai = TrangThaiPhong(
            room_id=payload.get("rid"),
            bet=payload.get("b"),
            so_nguoi_hien_tai=so_nguoi,
            so_nguoi_toi_da=so_nguoi_toi_da,
            nguoi_choi=ds_nguoi_choi,
            my_uid=my_uid,
        )

        self.room_engine.on_trang_thai_phong(profile_id, trang_thai)

    # ======================================================================
    # UI utilities
    # ======================================================================

    def set_status(self, text: str) -> None:
        try:
            self._status_bar.showMessage(text)
        except Exception:
            pass

    def on_theme_changed(self, name: str) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme_by_name(app, name)
        set_current_theme_name(name)

    def closeEvent(self, event) -> None:
        try:
            self._stop_background_services()
        except Exception:
            pass
        super().closeEvent(event)

    def _on_player_joined_toast(self, pid: str, name: str, gold: int) -> None:
        if self.toast is None:
            return

        # Check config: ui.room.notify_enter_exit
        try:
            cfg = load_config()
            ui = cfg.get("ui") or {}
            ui_room = ui.get("room") or {}
            if not ui_room.get("notify_enter_exit", True):
                return
        except Exception:
            # Nếu lỗi đọc config, coi như vẫn cho hiển thị để tránh im lặng khó debug
            pass

        try:
            self.toast.show_player_join(name, gold)
        except Exception:
            log.exception("Toast show failed: pid=%s name=%r gold=%r", pid, name, gold)


    def _on_player_left_toast(self, pid: str, name: str, gold: int) -> None:
        if self.toast is None:
            return

        try:
            cfg = load_config()
            ui = cfg.get("ui") or {}
            ui_room = ui.get("room") or {}
            if not ui_room.get("notify_enter_exit", True):
                return
        except Exception:
            pass

        try:
            self.toast.show_player_left(name, gold)
        except Exception:
            try:
                log.exception("_on_player_left_toast failed")
            except Exception:
                pass
    def _copy_license_key(self):
        if not self._current_license_key:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(self._current_license_key)
        self.statusBar().showMessage("Đã copy License Key", 2000)
        
    def _on_click_license_id(self, event):
        # Click label -> copy y hệt nút Copy ID cũ
        self._copy_license_id()
        
    def _copy_license_id(self):
        try:
            from PySide6.QtWidgets import QApplication

            lid = ""
            try:
                if hasattr(self, "license_manager") and self.license_manager:
                    lid = self.license_manager.get_cached_license_id() or ""
            except Exception:
                lid = ""

            if lid:
                QApplication.clipboard().setText(lid)
                # nếu bạn có status bar object khác tên thì sửa lại đúng tên biến
                if hasattr(self, "_status_bar") and self._status_bar:
                    self._status_bar.showMessage("Đã copy License ID", 1500)
            else:
                if hasattr(self, "_status_bar") and self._status_bar:
                    self._status_bar.showMessage("Chưa có License ID", 1500)
        except Exception:
            pass


def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS  # PyInstaller
    except Exception:
        base_path = os.path.abspath(os.getcwd())
    return os.path.join(base_path, relative_path)


def run_app() -> None:
    app = QApplication(sys.argv)
    icon_path = resource_path("icon.ico")
    app.setWindowIcon(QIcon(icon_path))
    apply_app_theme(app)

    window = MainWindow()
    window.setWindowIcon(QIcon(icon_path))
    window.show()

    app.exec()


if __name__ == "__main__":
    try:
        run_app()
    except Exception:
        log.exception("Fatal error in run_app()")
        traceback.print_exc()
        if getattr(sys, "frozen", False):
            try:
                input("\nỨng dụng gặp lỗi. Nhấn Enter để thoát...")
            except Exception:
                pass

