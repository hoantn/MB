# profiles_tab_v2.py
from __future__ import annotations

import socket
from typing import Optional, Tuple
import os
import shutil

from PySide6.QtCore import Qt, QObject, Signal, QThread, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QSizePolicy,
)

# Reuse 100% logic gốc
from core.config import load_config
from ui2.tabs.profile_tab import ProfileTab



class _ReconnectWorker(QObject):
    finished = Signal(str, bool, str)  # pid, ok, message

    def __init__(self, browser_manager, pid: str) -> None:
        super().__init__()
        self.browser_manager = browser_manager
        self.pid = pid

    def run(self) -> None:
        pid = self.pid
        bm = self.browser_manager
        try:
            # 1) Disconnect devtools cũ nếu có (bám dashboard)
            tab = None
            if hasattr(bm, "get_active_tab"):
                tab = bm.get_active_tab(pid)
            elif hasattr(bm, "tabs"):
                tab = bm.tabs.get(pid)

            if tab is not None:
                try:
                    tab.devtools.disconnect()
                except Exception:
                    pass

            # 2) Remove cache tab cũ
            if hasattr(bm, "tabs") and isinstance(bm.tabs, dict):
                bm.tabs.pop(pid, None)

            # 3) ensure_tab (đây là phần có thể block)
            if not hasattr(bm, "ensure_tab"):
                self.finished.emit(pid, False, "BrowserManager không hỗ trợ ensure_tab().")
                return

            new_tab = bm.ensure_tab(pid)
            if not new_tab:
                self.finished.emit(pid, False, "Không phát hiện Chrome đang chạy (hãy bấm Mở trình duyệt).")
                return

            self.finished.emit(pid, True, "Đã kết nối lại DevTools.")
        except Exception as e:
            self.finished.emit(pid, False, str(e))

class ProfilesTabV2(ProfileTab):
    """
    ProfilesTabV2: UI #1 (Sidebar + Detail Panel) dựa 100% trên logic ProfileTab gốc.

    - Không đổi contract, không đổi schema config.
    - Chỉ thay layout + thêm sidebar list.
    """

    def __init__(self, browser_manager, parent=None) -> None:
        super().__init__(browser_manager=browser_manager, parent=parent)
        self._refresh_sidebar_status()

        # State cho reconnect thread (fix crash lifecycle)
        self._reconnect_thread: Optional[QThread] = None
        self._reconnect_worker: Optional[_ReconnectWorker] = None
        self._reconnect_result: Optional[Tuple[str, bool, str]] = None
    # ------------------------------------------------------------------ UI (override)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        # ---------------- Sidebar
        sidebar = QFrame()
        sidebar.setFrameShape(QFrame.StyledPanel)
        sidebar.setMinimumWidth(260)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(8)

        title = QLabel("PROFILES")
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        sidebar_layout.addWidget(title)

        self._profiles_list = QListWidget()
        self._profiles_list.setSpacing(2)
        self._profiles_list.setSelectionMode(QListWidget.SingleSelection)
        sidebar_layout.addWidget(self._profiles_list, 1)

        # Hidden combo (giữ nguyên contract của base)
        self.profile_combo.setVisible(False)
        sidebar_layout.addWidget(self.profile_combo)

        # Action nhanh ở sidebar
        quick_actions = QGroupBox("Quick actions")
        qa = QVBoxLayout(quick_actions)
        qa.setContentsMargins(8, 10, 8, 10)
        qa.setSpacing(6)

        # --- Row 1: Open browser + ALL
        open_row = QWidget()
        open_row_l = QHBoxLayout(open_row)
        open_row_l.setContentsMargins(0, 0, 0, 0)
        open_row_l.setSpacing(6)

        self._btn_open_quick = QPushButton("Mở trình duyệt")
        self._btn_open_all = QPushButton("ALL")

        # --- Row 2: Reconnect + ALL
        reload_row = QWidget()
        reload_row_l = QHBoxLayout(reload_row)
        reload_row_l.setContentsMargins(0, 0, 0, 0)
        reload_row_l.setSpacing(6)

        self._btn_reload_quick = QPushButton("Kết nối lại")
        self._btn_reload_all = QPushButton("ALL")

        # Responsive: nút chính co giãn, nút ALL cố định nhỏ
        for b in (self._btn_open_quick, self._btn_reload_quick):
            b.setMinimumHeight(32)
            b.setMinimumWidth(0)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        for b in (self._btn_open_all, self._btn_reload_all):
            b.setMinimumHeight(32)
            b.setFixedWidth(56)
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        open_row_l.addWidget(self._btn_open_quick, 1)
        open_row_l.addWidget(self._btn_open_all, 0)
        reload_row_l.addWidget(self._btn_reload_quick, 1)
        reload_row_l.addWidget(self._btn_reload_all, 0)

        qa.addWidget(open_row)
        qa.addWidget(reload_row)

        sidebar_layout.addWidget(quick_actions)

        # Wire quick actions vào logic gốc
        self._btn_open_quick.clicked.connect(self.open_browser)
        self._btn_open_all.clicked.connect(self._open_all_browsers_v2)

        self._btn_reload_quick.clicked.connect(self._reconnect_browser_v2)
        self._btn_reload_all.clicked.connect(self._reconnect_all_profiles_v2)

        # ---------------- Detail panel
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(12, 12, 12, 12)
        detail_layout.setSpacing(10)

        header_row = QHBoxLayout()
        self._current_pid_label = QLabel("Profile: P1")
        self._current_pid_label.setStyleSheet("font-weight: 700; font-size: 16px;")
        self._current_status_label = QLabel("Status: —")
        self._current_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._current_status_label.setStyleSheet("color: gray;")
        header_row.addWidget(self._current_pid_label, 1)
        header_row.addWidget(self._current_status_label, 1)
        detail_layout.addLayout(header_row)

        # --- Profile info group
        prof_group = QGroupBox("Cấu hình Profile")
        prof_form = QFormLayout(prof_group)
        prof_form.addRow("Tên hiển thị:", self.name_edit)
        prof_form.addRow("Chrome path:", self.chrome_path_edit)
        prof_form.addRow("User data dir:", self.user_data_dir_edit)

        # --- Window group
        win_group = QGroupBox("Cửa sổ")
        win_form = QFormLayout(win_group)
        win_form.addRow("Width:", self.win_width_spin)
        win_form.addRow("Height:", self.win_height_spin)
        win_form.addRow("Scale (%):", self.scale_spin)

        # --- Proxy group
        proxy_group = QGroupBox("Proxy")
        proxy_form = QFormLayout(proxy_group)
        proxy_form.addRow("Loại proxy:", self.proxy_type_combo)
        proxy_form.addRow("Host (IP / domain):", self.proxy_host_edit)
        proxy_form.addRow("Port:", self.proxy_port_spin)
        proxy_form.addRow("Username:", self.proxy_user_edit)
        proxy_form.addRow("Password:", self.proxy_pass_edit)

        # --- TM-PROXY rows (reuse y nguyên widgets gốc)
        proxy_form.addRow("API key:", self.tmproxy_api_key_edit)

        # Actions row: Get / Reset IP / Check nằm ở dòng dưới
        tm_actions_widget = QWidget()
        tm_actions_layout = QHBoxLayout(tm_actions_widget)
        tm_actions_layout.setContentsMargins(0, 0, 0, 0)
        tm_actions_layout.setSpacing(6)
        tm_actions_layout.addWidget(self.tmproxy_get_btn)
        tm_actions_layout.addWidget(self.tmproxy_reset_btn)

        self.tmproxy_check_btn = QPushButton("Check")
        tm_actions_layout.addWidget(self.tmproxy_check_btn)

        tm_actions_layout.addStretch(1)

        proxy_form.addRow("", tm_actions_widget)

        proxy_form.addRow("Loại Protocol:", self.tmproxy_type_combo)
        proxy_form.addRow("Trạng thái:", self.tmproxy_status_label)

        # Connect check handler (V2-only)
        self.tmproxy_check_btn.clicked.connect(self._on_proxy_check_clicked_v2)

        # Layout chính phần detail: 2 cột (Profile+Window | Proxy)
        mid = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.addWidget(prof_group)
        left_col.addWidget(win_group)
        
        # Nút Tạo Profile Mặc định + ALL (cùng hàng, responsive)
        default_row = QWidget()
        default_row_l = QHBoxLayout(default_row)
        default_row_l.setContentsMargins(0, 0, 0, 0)
        default_row_l.setSpacing(6)

        self._btn_create_default = QPushButton("Tạo Profile Mặc định")
        self._btn_create_default.setMinimumHeight(32)
        self._btn_create_default.setMinimumWidth(0)
        self._btn_create_default.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._btn_create_default.setStyleSheet(
            "background-color: #33CC66; color: #052e16; font-weight: 700;"
        )
        self._btn_create_default.clicked.connect(self._on_create_default_profile_clicked_v2)

        self._btn_create_default_all = QPushButton("ALL")
        self._btn_create_default_all.setMinimumHeight(32)
        self._btn_create_default_all.setFixedWidth(56)
        self._btn_create_default_all.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._btn_create_default_all.setStyleSheet(
            "background-color: #4ade80; color: #052e16; font-weight: 800;"
        )
        self._btn_create_default_all.setToolTip("Tạo profile mặc định cho P1, P2, P3")
        self._btn_create_default_all.clicked.connect(self._on_create_default_all_profiles_clicked_v2)

        default_row_l.addWidget(self._btn_create_default, 1)
        default_row_l.addWidget(self._btn_create_default_all, 0)

        left_col.addWidget(default_row)
                
        # Nút Xóa Profile + ALL (cùng hàng, responsive)
        delete_row = QWidget()        
        delete_row_l = QHBoxLayout(delete_row)
        delete_row_l.setContentsMargins(0, 0, 0, 0)
        delete_row_l.setSpacing(6)

        self._btn_delete_profile = QPushButton("Xóa Profile")
        self._btn_delete_profile.setMinimumHeight(32)
        self._btn_delete_profile.setMinimumWidth(0)
        self._btn_delete_profile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._btn_delete_profile.setStyleSheet(
            "background-color: #dc2626; color: white; font-weight: 600;"
        )
        self._btn_delete_profile.clicked.connect(self._on_delete_profile_clicked_v2)

        self._btn_delete_all_profiles = QPushButton("ALL")
        self._btn_delete_all_profiles.setMinimumHeight(32)
        self._btn_delete_all_profiles.setFixedWidth(56)
        self._btn_delete_all_profiles.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._btn_delete_all_profiles.setStyleSheet(
            "background-color: #991b1b; color: white; font-weight: 700;"
        )
        self._btn_delete_all_profiles.clicked.connect(self._on_delete_all_profiles_clicked_v2)

        delete_row_l.addWidget(self._btn_delete_profile, 1)
        delete_row_l.addWidget(self._btn_delete_all_profiles, 0)

        left_col.addWidget(delete_row)

                
        left_col.addStretch()

        mid.addLayout(left_col, 2)
        mid.addWidget(proxy_group, 3)
        detail_layout.addLayout(mid, 1)

        # --- Buttons row (chỉ giữ "Lưu cấu hình")
        btn_row = QHBoxLayout()
        self._btn_save = QPushButton("Lưu cấu hình")
        self._btn_save.setMinimumHeight(34)
        self._btn_save.clicked.connect(self._on_save_clicked_v2)
        btn_row.addWidget(self._btn_save)
        btn_row.addStretch()
        detail_layout.addLayout(btn_row)

        # ---------------- Assemble root
        root.addWidget(sidebar, 0)
        root.addWidget(detail, 1)

        # ---------------- Init sidebar items + wiring selection
        self._profiles_list.clear()
        for pid in ("P1", "P2", "P3"):
            item = QListWidgetItem(pid)
            item.setData(Qt.UserRole, pid)
            self._profiles_list.addItem(item)

        self._profiles_list.currentItemChanged.connect(self._on_sidebar_item_changed)
        self.profile_combo.currentTextChanged.connect(self._sync_ui_for_pid)
        # Khi đổi loại proxy → đổi provider + key hiển thị
        self.proxy_type_combo.currentIndexChanged.connect(self._on_proxy_type_changed_v2)
        current_pid = self.profile_combo.currentText() or "P1"
        self._select_sidebar_pid(current_pid)
        self._sync_ui_for_pid(current_pid)

        # Keep TM-PROXY enable/disable behavior y nguyên (base)
        self._update_tmproxy_controls_enabled()

        # Đồng bộ enable/disable cho nút Check theo trạng thái của base
        try:
            self.tmproxy_check_btn.setEnabled(True)
        except Exception:
            pass

    # ------------------------------------------------------------------ V2 helpers / sync

    def _on_save_clicked_v2(self) -> None:
        """V2 chỉ gọi save_profile() của base, mọi logic provider đã ở ProfileTab."""
        pid = self.profile_combo.currentText() or "P1"
        self.save_profile()
        self._refresh_sidebar_status()
        self._sync_ui_for_pid(pid)

    def _on_sidebar_item_changed(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        if not current:
            return
        pid = str(current.data(Qt.UserRole) or current.text())
        if pid and pid != self.profile_combo.currentText():
            self.profile_combo.setCurrentText(pid)
        else:
            self._sync_ui_for_pid(pid)

    def _select_sidebar_pid(self, pid: str) -> None:
        pid = str(pid)
        for i in range(self._profiles_list.count()):
            it = self._profiles_list.item(i)
            if it and (it.data(Qt.UserRole) == pid or it.text() == pid):
                self._profiles_list.blockSignals(True)
                self._profiles_list.setCurrentRow(i)
                self._profiles_list.blockSignals(False)
                break

    def _sync_ui_for_pid(self, pid: str) -> None:
        pid = str(pid or "P1")
        self._current_pid_label.setText(f"Profile: {pid}")
        self._select_sidebar_pid(pid)

        # Rule UI: nếu không dùng proxy thì combo phải hiển thị "không dùng proxy" (nếu có item phù hợp)
        self._ensure_no_proxy_display(pid)

        # Cập nhật label + sidebar
        self._update_current_status_label(pid)
        self._refresh_sidebar_status()

        # Đồng bộ ô API key theo provider trong config
        try:
            cfg = load_config()
            self._ensure_profiles_root(cfg)
            prof = (cfg.get("profiles") or {}).get(pid, {}) or {}
            proxy = prof.get("proxy", {}) or {}

            provider = self._infer_provider_from_proxy_dict(proxy)
            if provider == "tmproxy":
                api_key = str(proxy.get("tmproxy_api_key", "") or "")
            elif provider == "proxyno1":
                api_key = str(proxy.get("proxyno1_api_key", "") or "")
            else:
                api_key = ""

            self.tmproxy_api_key_edit.setText(api_key)
        except Exception:
            pass

    def _open_all_browsers_v2(self) -> None:
        """
        Nút ALL: mở trình duyệt lần lượt P1 -> P2 -> P3 (tuần tự).
        Reuse 100% open_browser() của base (dựa theo profile_combo).
        """
        if getattr(self, "_open_all_running", False):
            return

        self._open_all_queue = ["P1", "P2", "P3"]
        self._open_all_running = True

        try:
            self._btn_open_all.setEnabled(False)
        except Exception:
            pass

        self._run_next_open_in_queue_v2()


    def _run_next_open_in_queue_v2(self) -> None:
        if not getattr(self, "_open_all_running", False):
            return

        queue = getattr(self, "_open_all_queue", None)
        if not queue:
            self._open_all_running = False
            try:
                self._btn_open_all.setEnabled(True)
            except Exception:
                pass
            try:
                self._current_status_label.setText("Status: OPEN ALL | Done")
            except Exception:
                pass
            return

        pid = queue.pop(0)

        try:
            self.profile_combo.setCurrentText(pid)
        except Exception:
            pass

        try:
            self.open_browser()
        except Exception:
            pass

        QTimer.singleShot(50, self._run_next_open_in_queue_v2)

    def _reconnect_all_profiles_v2(self) -> None:
        """
        Nút ALL: reconnect lần lượt P1 -> P2 -> P3 (tuần tự).
        Tái sử dụng 100% cơ chế reconnect hiện có (_reconnect_browser_v2).
        """
        # Nếu đang reconnect 1 profile thì không cho bấm ALL chồng lên
        if self._reconnect_thread is not None:
            return

        # Hàng đợi reconnect
        self._reconnect_all_queue = ["P1", "P2", "P3"]
        self._reconnect_all_running = True

        # Disable nút ALL để tránh double click
        try:
            self._btn_reload_all.setEnabled(False)
        except Exception:
            pass

        self._run_next_reconnect_in_queue_v2()


    def _run_next_reconnect_in_queue_v2(self) -> None:
        # Nếu không còn chạy ALL thì thôi
        if not getattr(self, "_reconnect_all_running", False):
            return

        queue = getattr(self, "_reconnect_all_queue", None)
        if not queue:
            # Hoàn tất ALL
            self._reconnect_all_running = False
            try:
                self._btn_reload_all.setEnabled(True)
            except Exception:
                pass
            try:
                self._current_status_label.setText("Status: ALL | Done")
            except Exception:
                pass
            return

        pid = queue.pop(0)

        # Chuyển profile hiện tại sang pid (reuse luồng sync UI hiện có)
        try:
            self.profile_combo.setCurrentText(pid)
        except Exception:
            pass

        # Gắn cờ để handler finished biết đang ở mode ALL
        self._reconnect_all_current_pid = pid

        # Gọi reconnect hiện có (tạo QThread + worker)
        self._reconnect_browser_v2()

    # ------------------------------------------------------------------ Reconnect (FIX QThread lifecycle)

    def _reconnect_browser_v2(self) -> None:
        pid = self.profile_combo.currentText() or "P1"

        # Chặn double-click khi đang chạy
        if self._reconnect_thread is not None:
            return

        # Disable nút + cập nhật trạng thái nhẹ
        try:
            self._btn_reload_quick.setEnabled(False)
        except Exception:
            pass
        try:
            self._current_status_label.setText(f"Status: Đang kết nối lại ({pid})…")
        except Exception:
            pass

        thread = QThread()
        worker = _ReconnectWorker(self.browser_manager, pid)
        worker.moveToThread(thread)

        self._reconnect_thread = thread
        self._reconnect_worker = worker
        self._reconnect_result = None

        def _store_result(p: str, ok: bool, msg: str) -> None:
            self._reconnect_result = (p, ok, msg)

        thread.started.connect(worker.run)

        # Worker finished: chỉ store result + yêu cầu thread quit (KHÔNG cleanup tại đây)
        worker.finished.connect(_store_result)
        worker.finished.connect(thread.quit)

        # Cleanup đúng thời điểm: khi thread thật sự finished
        thread.finished.connect(self._on_reconnect_thread_finished_v2)

        # deleteLater objects
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.start()

    def _on_reconnect_thread_finished_v2(self) -> None:
        # Re-enable nút
        try:
            self._btn_reload_quick.setEnabled(True)
        except Exception:
            pass

        res = self._reconnect_result
        if res:
            pid, ok, message = res
            if ok:
                try:
                    self._current_status_label.setText(f"Status: {pid} | Connected")
                except Exception:
                    pass
            else:
                try:
                    self._current_status_label.setText(f"Status: {pid} | Reconnect failed")
                except Exception:
                    pass
                QMessageBox.warning(self, "Kết nối lại thất bại", f"{pid}: {message}")

        # Cleanup refs (CHỈ cleanup ở thread.finished)
        self._reconnect_worker = None
        self._reconnect_thread = None
        self._reconnect_result = None
        # Nếu đang chạy ALL -> chạy tiếp profile kế tiếp
        if getattr(self, "_reconnect_all_running", False):
            try:
                cur = getattr(self, "_reconnect_all_current_pid", "")
                self._current_status_label.setText(f"Status: {cur} | Done, next…")
            except Exception:
                pass

            # chạy tiếp item kế
            self._run_next_reconnect_in_queue_v2()
            return

        # Nếu không chạy ALL thì đảm bảo nút ALL luôn bật
        try:
            self._btn_reload_all.setEnabled(True)
        except Exception:
            pass

    # ------------------------------------------------------------------ Core: status & sidebar

    def _update_current_status_label(self, pid: str) -> None:
        cfg = load_config()
        self._ensure_profiles_root(cfg)
        prof = (cfg.get("profiles") or {}).get(pid, {}) or {}

        chrome_path = str(prof.get("chrome_path", "") or "").strip()
        user_data_dir = str(prof.get("user_data_dir", "") or "").strip()
        proxy = prof.get("proxy", {}) or {}

        host = str(proxy.get("host", "") or "").strip()
        port = int(proxy.get("port", 0) or 0)
        provider = self._infer_provider_from_proxy_dict(proxy)

        parts = []
        if chrome_path and user_data_dir:
            parts.append("Configured")
        else:
            parts.append("Missing config")

        if provider == "tmproxy":
            parts.append("TM-PROXY")
        elif provider == "proxyno1":
            parts.append("ProxyNo1")
        elif host and port:
            parts.append("Proxy")
        else:
            parts.append("No proxy")

        text = " | ".join(parts) if parts else "—"

        if "Missing" in text:
            self._current_status_label.setStyleSheet("color: #b45309;")
        else:
            self._current_status_label.setStyleSheet("color: #166534;")
        self._current_status_label.setText(f"Status: {text}")

    def _refresh_sidebar_status(self) -> None:
        cfg = load_config()
        self._ensure_profiles_root(cfg)
        profiles = cfg.get("profiles") or {}

        for i in range(self._profiles_list.count()):
            item = self._profiles_list.item(i)
            if not item:
                continue
            pid = str(item.data(Qt.UserRole) or item.text())
            prof = profiles.get(pid, {}) or {}

            chrome_path = str(prof.get("chrome_path", "") or "").strip()
            user_data_dir = str(prof.get("user_data_dir", "") or "").strip()
            proxy = prof.get("proxy", {}) or {}

            host = str(proxy.get("host", "") or "").strip()
            port = int(proxy.get("port", 0) or 0)
            provider = self._infer_provider_from_proxy_dict(proxy)

            badge = "✅" if (chrome_path and user_data_dir) else "⚠"

            if provider == "tmproxy":
                p_badge = "TM"
            elif provider == "proxyno1":
                p_badge = "N1"
            elif host and port:
                p_badge = "PX"
            else:
                p_badge = "—"

            item.setText(f"{pid}  {badge}   Proxy:{p_badge}")

    # ------------------------------------------------------------------ Proxy UI correctness (no-guess)

    def _ensure_no_proxy_display(self, pid: str) -> None:
        cfg = load_config()
        self._ensure_profiles_root(cfg)
        prof = (cfg.get("profiles") or {}).get(pid, {}) or {}
        proxy = prof.get("proxy", {}) or {}

        provider = self._infer_provider_from_proxy_dict(proxy)
        tm_key = str(proxy.get("tmproxy_api_key", "") or "").strip()
        host = str(proxy.get("host", "") or "").strip()
        port = int(proxy.get("port", 0) or 0)

        # Nếu provider đã là tmproxy / proxyno1 thì KHÔNG ép combo về "không dùng proxy"
        if provider in ("tmproxy", "proxyno1"):
            return

        no_proxy = (not tm_key) and (not host) and (port <= 0)
        if not no_proxy:
            return

    def _find_no_proxy_index(self) -> Optional[int]:
        keywords = ["không", "no proxy", "none", "off", "disabled", "tắt"]
        for i in range(self.proxy_type_combo.count()):
            t = (self.proxy_type_combo.itemText(i) or "").strip().lower()
            if not t:
                continue
            for kw in keywords:
                if kw in t:
                    return i
        return None

    # ------------------------------------------------------------------ Proxy check (make it actually useful)

    def _on_proxy_check_clicked_v2(self) -> None:
        """
        Check proxy:
        - Nếu host/port trống nhưng có TM-PROXY API key: tự bấm Get (reuse handler gốc của base),
          rồi đọc lại host/port để check.
        - Sau đó check TCP connect host:port.
        """
        # 1) Đọc host/port hiện tại
        host_raw = (self.proxy_host_edit.text() or "").strip()
        port = int(self.proxy_port_spin.value() or 0)

        # 2) Nếu thiếu host/port mà có API key -> thử "Get" để base tự fill
        api_key = (self.tmproxy_api_key_edit.text() or "").strip()
        if (not host_raw or port <= 0) and api_key:
            try:
                # reuse đúng nút gốc (đã có handler trong ProfileTab)
                self.tmproxy_get_btn.click()
            except Exception:
                pass

            host_raw = (self.proxy_host_edit.text() or "").strip()
            port = int(self.proxy_port_spin.value() or 0)

        if not host_raw or port <= 0:
            self.tmproxy_status_label.setText("Check proxy: Thiếu host/port (không dùng proxy?)")
            return

        host = self._normalize_host_for_socket(host_raw)

        ok, err = self._tcp_check(host, port, timeout_sec=3.0)
        if ok:
            self.tmproxy_status_label.setText(f"Check proxy: OK (TCP) → {host}:{port}")
        else:
            self.tmproxy_status_label.setText(f"Check proxy: FAIL → {host}:{port} ({err})")

    def _normalize_host_for_socket(self, host: str) -> str:
        h = host.strip()
        for prefix in ("http://", "https://", "socks5://", "socks4://"):
            if h.lower().startswith(prefix):
                h = h[len(prefix):]
                break
        return h.strip().strip("/")

    def _tcp_check(self, host: str, port: int, timeout_sec: float = 3.0) -> Tuple[bool, str]:
        try:
            with socket.create_connection((host, port), timeout=timeout_sec):
                return True, ""
        except Exception as e:
            return False, str(e)
    # ------------------------------------------------------------------ Provider helpers

    def _detect_provider_from_combo_text(self) -> str:
        """
        Đọc text của proxy_type_combo hiện tại → map sang provider:
        none | raw | tmproxy | proxyno1
        """
        t = (self.proxy_type_combo.currentText() or "").strip().lower()

        # không dùng proxy
        for kw in ("không", "no proxy", "none", "off", "disabled", "tắt"):
            if kw in t:
                return "none"

        # tmproxy
        for kw in ("tm-proxy", "tm proxy", "tmproxy"):
            if kw in t:
                return "tmproxy"

        # proxyno1
        for kw in ("no1", "proxy no1", "proxyno1"):
            if kw in t:
                return "proxyno1"

        # còn lại coi là proxy thường (raw)
        return "raw"

    def _infer_provider_from_proxy_dict(self, proxy: dict) -> str:
        """
        Suy luận provider từ config (dùng khi load UI).
        Ưu tiên field 'provider', fallback theo key cũ.
        """
        provider = str(proxy.get("provider", "") or "").strip().lower()
        if provider:
            return provider

        tm_key = str(proxy.get("tmproxy_api_key", "") or "").strip()
        host = str(proxy.get("host", "") or "").strip()
        port = int(proxy.get("port", 0) or 0)

        if tm_key:
            return "tmproxy"
        if host and port > 0:
            return "raw"
        return "none"

    def _on_proxy_type_changed_v2(self) -> None:
        """
        Khi đổi loại proxy trong combo:
        - Cập nhật enable/disable TMProxy controls như cũ.
        - Tự chuyển ô API key sang đúng field (tmproxy / proxyno1) theo provider.
        """
        # Giữ behavior base
        try:
            self._update_tmproxy_controls_enabled()
        except Exception:
            pass

        pid = self.profile_combo.currentText() or "P1"

        try:
            cfg = load_config()
            self._ensure_profiles_root(cfg)
            prof = (cfg.get("profiles") or {}).get(pid, {}) or {}
            proxy = prof.get("proxy", {}) or {}

            provider = self._detect_provider_from_combo_text()
            current_text = ""

            if provider == "tmproxy":
                current_text = str(proxy.get("tmproxy_api_key", "") or "")
            elif provider == "proxyno1":
                current_text = str(proxy.get("proxyno1_api_key", "") or "")
            else:
                # none/raw ⇒ không cần API key
                current_text = ""

            self.tmproxy_api_key_edit.setText(current_text)
        except Exception:
            # Nếu có lỗi đọc config thì không làm crash UI
            pass

    def _on_create_default_profile_clicked_v2(self) -> None:
        """
        Tạo Profile Mặc định cho profile hiện tại:
        - Copy user-data-dir hiện tại (P1/P2/P3) -> tạo thư mục P?-D cùng cấp
        - Nếu P?-D đã tồn tại: báo lỗi & bỏ qua
        """
        pid = self.profile_combo.currentText() or "P1"
        ok, msg = self._create_default_profile_for_pid_v2(pid)

        if ok:
            QMessageBox.information(self, "Hoàn tất", f"{pid}: {msg}")
        else:
            QMessageBox.warning(self, "Không thể tạo Profile mặc định", f"{pid}: {msg}")


    def _on_create_default_all_profiles_clicked_v2(self) -> None:
        """
        Tạo Profile Mặc định cho cả 3 profile P1, P2, P3 (tuần tự).
        - Nếu P?-D đã tồn tại: báo lỗi & bỏ qua P đó, vẫn chạy các P còn lại
        """
        ret = QMessageBox.question(
            self,
            "Tạo Profile Mặc định (ALL)",
            (
                "Bạn có chắc chắn muốn tạo Profile Mặc định cho P1, P2, P3?\n"
                "Tool sẽ copy thư mục user-data-dir hiện tại và tạo P1-D, P2-D, P3-D cùng cấp.\n"
                "Nếu thư mục -D đã tồn tại, profile đó sẽ bị bỏ qua."
            ),
        )
        if ret != QMessageBox.Yes:
            return

        # Chặn double click
        if getattr(self, "_create_default_running", False):
            return

        self._create_default_queue = ["P1", "P2", "P3"]
        self._create_default_running = True
        self._create_default_results = []  # list[(pid, ok, msg)]

        try:
            self._btn_create_default_all.setEnabled(False)
            self._btn_create_default.setEnabled(False)
        except Exception:
            pass

        self._run_next_create_default_in_queue_v2()


    def _run_next_create_default_in_queue_v2(self) -> None:
        if not getattr(self, "_create_default_running", False):
            return

        queue = getattr(self, "_create_default_queue", None)
        if not queue:
            # Done
            self._create_default_running = False
            try:
                self._btn_create_default_all.setEnabled(True)
                self._btn_create_default.setEnabled(True)
            except Exception:
                pass

            # Tổng kết gọn
            results = getattr(self, "_create_default_results", []) or []
            ok_list = [f"{p}: OK" for (p, ok, _m) in results if ok]
            fail_list = [f"{p}: {_m}" for (p, ok, _m) in results if not ok]

            lines = []
            if ok_list:
                lines.append("Thành công:")
                lines.extend(ok_list)
            if fail_list:
                lines.append("")
                lines.append("Bỏ qua / Lỗi:")
                lines.extend(fail_list)

            QMessageBox.information(self, "Hoàn tất (ALL)", "\n".join(lines).strip() or "Không có tác vụ.")
            return

        pid = queue.pop(0)

        # Chuyển UI sang pid (để đúng “đang xử lý P nào”)
        try:
            self.profile_combo.setCurrentText(pid)
        except Exception:
            pass

        ok, msg = self._create_default_profile_for_pid_v2(pid)
        try:
            self._create_default_results.append((pid, ok, msg))
        except Exception:
            pass

        # Chạy tiếp P kế (nhả event loop nhẹ)
        QTimer.singleShot(50, self._run_next_create_default_in_queue_v2)


    def _create_default_profile_for_pid_v2(self, pid: str) -> Tuple[bool, str]:
        """
        Core tạo P?-D:
        - Đọc user_data_dir từ config
        - dest = <parent_of_user_data_dir> / f"{pid}-D"
        - Nếu dest tồn tại: return False với msg "Đã tồn tại, bỏ qua"
        - Nếu src không tồn tại: return False với msg "Không tìm thấy src"
        - Copy toàn bộ folder
        """
        pid = str(pid or "P1")

        try:
            cfg = load_config()
            self._ensure_profiles_root(cfg)
            prof = (cfg.get("profiles") or {}).get(pid, {}) or {}
            src = str(prof.get("user_data_dir", "") or "").strip()
        except Exception as e:
            return False, f"Lỗi đọc config: {e}"

        if not src:
            return False, "Thiếu user_data_dir trong config."

        # Chuẩn hóa path
        src = os.path.abspath(src)
        if not os.path.isdir(src):
            return False, f"Không tìm thấy thư mục nguồn: {src}"

        parent = os.path.dirname(src)
        dest = os.path.join(parent, f"{pid}-D")

        if os.path.exists(dest):
            return False, f"Đã tồn tại: {dest} (bỏ qua)"

        try:
            shutil.copytree(src, dest)
            return True, f"Đã tạo: {dest}"
        except Exception as e:
            return False, f"Lỗi copy: {e}"

    def _on_delete_all_profiles_clicked_v2(self) -> None:
        """
        Xóa toàn bộ user-data-dir của P1, P2, P3 (tuần tự).
        Reuse đúng cơ chế delete_profile_user_data() của BrowserManager.
        - KHÔNG xóa config.
        """
        ret = QMessageBox.question(
            self,
            "Xóa Toàn Bộ Profile",
            (
                "Bạn có chắc chắn muốn xóa toàn bộ dữ liệu Chrome (user-data-dir) của P1, P2, P3?\n"
                "Cookie, cache, lịch sử đăng nhập của cả 3 profile sẽ bị xóa.\n"
                "Cấu hình profile trong file config vẫn được giữ nguyên."
            ),
        )
        if ret != QMessageBox.Yes:
            return

        bm = getattr(self, "browser_manager", None)
        if bm is None or not hasattr(bm, "delete_profile_user_data"):
            QMessageBox.warning(self, "Lỗi", "BrowserManager không hỗ trợ delete_profile_user_data().")
            return

        # queue xóa tuần tự
        self._delete_all_queue = ["P1", "P2", "P3"]
        self._delete_all_running = True

        # disable nút để tránh bấm lặp
        try:
            self._btn_delete_all_profiles.setEnabled(False)
            self._btn_delete_profile.setEnabled(False)
        except Exception:
            pass

        self._run_next_delete_in_queue_v2()

    def _run_next_delete_in_queue_v2(self) -> None:
        if not getattr(self, "_delete_all_running", False):
            return

        queue = getattr(self, "_delete_all_queue", None)
        if not queue:
            # done
            self._delete_all_running = False
            try:
                self._btn_delete_all_profiles.setEnabled(True)
                self._btn_delete_profile.setEnabled(True)
            except Exception:
                pass
            QMessageBox.information(self, "Hoàn tất", "Đã xóa dữ liệu user-data của P1, P2, P3.")
            return

        pid = queue.pop(0)

        # chuyển UI sang pid (để đồng bộ cảm giác + reuse luồng sync hiện có)
        try:
            self.profile_combo.setCurrentText(pid)
        except Exception:
            pass

        ok = self.browser_manager.delete_profile_user_data(pid)
        if not ok:
            # stop sớm, báo đúng profile fail
            self._delete_all_running = False
            try:
                self._btn_delete_all_profiles.setEnabled(True)
                self._btn_delete_profile.setEnabled(True)
            except Exception:
                pass
            QMessageBox.warning(self, "Lỗi", f"Không thể xóa dữ liệu user-data của {pid}. Vui lòng xem log.")
            return

        # tiếp profile kế
        self._run_next_delete_in_queue_v2()

    def _on_delete_profile_clicked_v2(self) -> None:
        """
        Xóa sạch user-data-dir của profile hiện tại.
        - KHÔNG xóa cấu hình trong config.
        """
        pid = self.profile_combo.currentText() or "P1"

        ret = QMessageBox.question(
            self,
            "Xóa Profile",
            (
                f"Bạn có chắc chắn muốn xóa toàn bộ dữ liệu Chrome (user-data-dir) của {pid}?\n"
                "Cookie, cache, lịch sử đăng nhập của profile này sẽ bị xóa.\n"
                "Cấu hình profile trong file config vẫn được giữ nguyên."
            ),
        )
        if ret != QMessageBox.Yes:
            return

        bm = getattr(self, "browser_manager", None)
        if bm is None or not hasattr(bm, "delete_profile_user_data"):
            QMessageBox.warning(
                self,
                "Lỗi",
                "BrowserManager không hỗ trợ delete_profile_user_data().",
            )
            return

        ok = bm.delete_profile_user_data(pid)
        if ok:
            QMessageBox.information(
                self,
                "Hoàn tất",
                f"Đã xóa dữ liệu user-data của {pid}.\n"
                "Lần mở trình duyệt tiếp theo sẽ là profile sạch.",
            )
        else:
            QMessageBox.warning(
                self,
                "Lỗi",
                f"Không thể xóa dữ liệu user-data của {pid}. Vui lòng xem log.",
            )
