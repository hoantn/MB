from typing import Any, Dict

import requests
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QSpinBox,
    QPushButton,
    QMessageBox,
    QGroupBox,
)
from PySide6.QtCore import Qt

from browser.manager import BrowserManager
from core.config import load_config, save_config
from core.proxyno1_provider import (
    proxyno1_change_ip_for_profile,
    proxyno1_get_proxy_info_for_profile,
)

class ProfileTab(QWidget):
    """Quản lý cấu hình trình duyệt / profile (P1, P2, P3).

    - Chọn profile hiện tại.
    - Sửa chrome_path, user_data_dir.
    - Sửa cấu hình cửa sổ (width, height, scale_percent).
    - Sửa proxy (host, port, user, pass, type).
    - Hỗ trợ TM-PROXY (API Key) để tự get IP/Port/User/Pass.
      + Cho phép chọn TM-PROXY dùng SOCKS5 hoặc HTTPS.
    - Nút Lưu cấu hình, Reload, Mở / Đóng trình duyệt.
    """

    def __init__(self, browser_manager: BrowserManager, parent=None) -> None:
        super().__init__(parent)
        self.browser_manager = browser_manager

        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["P1", "P2", "P3"])
        self.profile_combo.currentTextChanged.connect(self.load_profile)

        # Fields
        self.name_edit = QLineEdit()
        self.chrome_path_edit = QLineEdit()
        self.user_data_dir_edit = QLineEdit()

        self.win_width_spin = QSpinBox()
        self.win_width_spin.setRange(400, 9999)
        self.win_height_spin = QSpinBox()
        self.win_height_spin.setRange(300, 9999)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(30, 200)
        self.scale_spin.setSuffix(" %")

        # Proxy fields (proxy thường)
        self.proxy_type_combo = QComboBox()
        # index: 0-none, 1-http, 2-https, 3-socks5, 4-tmproxy, 5-no1proxy
        self.proxy_type_combo.addItems(
            ["Không dùng", "HTTP", "HTTPS", "SOCKS5", "TM-PROXY", "ProxyNo1"]
        )
        self.proxy_type_combo.currentIndexChanged.connect(
            self._on_proxy_type_changed
        )

        self.proxy_host_edit = QLineEdit()
        self.proxy_port_spin = QSpinBox()
        self.proxy_port_spin.setRange(0, 65535)
        self.proxy_user_edit = QLineEdit()
        self.proxy_pass_edit = QLineEdit()
        self.proxy_pass_edit.setEchoMode(QLineEdit.Password)

        # TM-PROXY fields
        self.tmproxy_api_key_edit = QLineEdit()
        self.tmproxy_get_btn = QPushButton("Get")
        self.tmproxy_reset_btn = QPushButton("Reset IP")
        self.tmproxy_status_label = QLabel("Chưa kết nối TM-PROXY")

        # Chọn loại TM-PROXY: socks5 / https
        self.tmproxy_type_combo = QComboBox()
        self.tmproxy_type_combo.addItem("HTTPS (HTTP proxy)", "https")
        self.tmproxy_type_combo.addItem("SOCKS5", "socks5")

        self.tmproxy_get_btn.clicked.connect(self.on_tmproxy_get_clicked)
        self.tmproxy_reset_btn.clicked.connect(self.on_tmproxy_reset_clicked)

        self._build_ui()
        self.load_profile("P1")

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Profile:"))
        top.addWidget(self.profile_combo)
        top.addStretch()
        root.addLayout(top)

        # Profile info
        prof_group = QGroupBox("Cấu hình Profile")
        prof_form = QFormLayout(prof_group)
        prof_form.addRow("Tên hiển thị:", self.name_edit)
        prof_form.addRow("Chrome path:", self.chrome_path_edit)
        prof_form.addRow("User data dir:", self.user_data_dir_edit)

        # Window config
        win_group = QGroupBox("Cửa sổ")
        win_form = QFormLayout(win_group)
        win_form.addRow("Width:", self.win_width_spin)
        win_form.addRow("Height:", self.win_height_spin)
        win_form.addRow("Scale (%):", self.scale_spin)

        # Proxy
        proxy_group = QGroupBox("Proxy")
        proxy_form = QFormLayout(proxy_group)
        proxy_form.addRow("Loại proxy:", self.proxy_type_combo)
        proxy_form.addRow("Host (IP / domain):", self.proxy_host_edit)
        proxy_form.addRow("Port:", self.proxy_port_spin)
        proxy_form.addRow("Username:", self.proxy_user_edit)
        proxy_form.addRow("Password:", self.proxy_pass_edit)

        # TM-PROXY rows
        api_row_widget = QWidget()
        api_row_layout = QHBoxLayout(api_row_widget)
        api_row_layout.setContentsMargins(0, 0, 0, 0)
        api_row_layout.addWidget(self.tmproxy_api_key_edit, 1)
        api_row_layout.addWidget(self.tmproxy_get_btn)
        api_row_layout.addWidget(self.tmproxy_reset_btn)

        proxy_form.addRow("TM-PROXY API key:", api_row_widget)
        proxy_form.addRow("TM-PROXY protocol:", self.tmproxy_type_combo)
        proxy_form.addRow("Trạng thái TM-PROXY:", self.tmproxy_status_label)

        middle = QHBoxLayout()
        middle.addWidget(prof_group, 2)
        middle.addWidget(win_group, 1)
        middle.addWidget(proxy_group, 3)
        root.addLayout(middle)

        # Buttons
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Lưu cấu hình")
        save_btn.clicked.connect(self.save_profile)
        reload_btn = QPushButton("Reload config")
        reload_btn.clicked.connect(self.reload_config)
        open_btn = QPushButton("Mở trình duyệt")
        open_btn.clicked.connect(self.open_browser)
        close_btn = QPushButton("Đóng trình duyệt")
        close_btn.clicked.connect(self.close_browser)

        for b in (save_btn, reload_btn, open_btn, close_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        root.addLayout(btn_row)

        root.addStretch()

        # Mặc định disable TM-PROXY controls (sẽ bật khi chọn TM-PROXY)
        self._update_tmproxy_controls_enabled()

    # ------------------------------------------------------------------ Helpers

    def _ensure_profiles_root(self, cfg: Dict[str, Any]) -> None:
        """Đảm bảo cấu trúc profiles / proxy đầy đủ key (TM-PROXY + ProxyNo1)."""
        if "profiles" not in cfg or not isinstance(cfg["profiles"], dict):
            cfg["profiles"] = {}

        for pid in ("P1", "P2", "P3"):
            if pid not in cfg["profiles"] or not isinstance(cfg["profiles"][pid], dict):
                cfg["profiles"][pid] = {
                    "name": f"Profile {pid[-1]}",
                    "chrome_path": "",
                    "user_data_dir": "",
                    "proxy": {
                        "host": "",
                        "port": 0,
                        "username": "",
                        "password": "",
                        # TMProxy
                        "tmproxy_api_key": "",
                        "tmproxy_type": "socks5",
                        # ProxyNo1
                        "proxyno1_api_key": "",
                        "provider": "none",
                    },
                    "window": {
                        "width": 1280,
                        "height": 720,
                        "scale_percent": 100,
                    },
                }
            else:
                prof = cfg["profiles"][pid]

                # Proxy
                if "proxy" not in prof or not isinstance(prof["proxy"], dict):
                    prof["proxy"] = {
                        "host": "",
                        "port": 0,
                        "username": "",
                        "password": "",
                        "tmproxy_api_key": "",
                        "tmproxy_type": "socks5",
                        "proxyno1_api_key": "",
                        "provider": "none",
                    }
                else:
                    proxy = prof["proxy"]
                    proxy.setdefault("host", "")
                    proxy.setdefault("port", 0)
                    proxy.setdefault("username", "")
                    proxy.setdefault("password", "")
                    proxy.setdefault("tmproxy_api_key", "")
                    proxy.setdefault("tmproxy_type", "socks5")
                    proxy.setdefault("proxyno1_api_key", "")
                    proxy.setdefault("provider", "none")
                    prof["proxy"] = proxy

                # Window
                if "window" not in prof or not isinstance(prof["window"], dict):
                    prof["window"] = {
                        "width": 1280,
                        "height": 720,
                        "scale_percent": 100,
                    }
                else:
                    win = prof["window"]
                    win.setdefault("width", 1280)
                    win.setdefault("height", 720)
                    win.setdefault("scale_percent", 100)
                    prof["window"] = win

    def _set_tmproxy_status(self, text: str, color: str = "gray") -> None:
        self.tmproxy_status_label.setText(text)
        self.tmproxy_status_label.setStyleSheet(f"color: {color};")

    def _update_tmproxy_controls_enabled(self) -> None:
        idx = self.proxy_type_combo.currentIndex()
        # 4 = TM-PROXY, 5 = ProxyNo1
        is_api_type = idx in (4, 5)

        # Ô API + nút Get/Reset dùng chung cho TM + ProxyNo1
        self.tmproxy_api_key_edit.setEnabled(is_api_type)
        self.tmproxy_get_btn.setEnabled(is_api_type)
        self.tmproxy_reset_btn.setEnabled(is_api_type)

        # Combo protocol chỉ dùng cho TM-PROXY
        self.tmproxy_type_combo.setEnabled(idx in (4, 5))

    def _infer_provider_for_proxy(self, proxy: Dict[str, Any]) -> str:
        """none | raw | tmproxy | proxyno1"""
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

    def _on_proxy_type_changed(self, index: int) -> None:
        self._update_tmproxy_controls_enabled()

    # ------------------------------------------------------------------ Slots: load/save

    def load_profile(self, profile_id: str) -> None:
        cfg = load_config()
        self._ensure_profiles_root(cfg)
        prof = cfg["profiles"].get(profile_id, {}) or {}

        # Thông tin cơ bản
        self.name_edit.setText(str(prof.get("name", "")))
        self.chrome_path_edit.setText(str(prof.get("chrome_path", "")))
        self.user_data_dir_edit.setText(str(prof.get("user_data_dir", "")))

        # Cửa sổ
        win = prof.get("window", {}) or {}
        self.win_width_spin.setValue(int(win.get("width", 1280)))
        self.win_height_spin.setValue(int(win.get("height", 720)))
        self.scale_spin.setValue(int(win.get("scale_percent", 100)))

        # Proxy
        proxy = prof.get("proxy", {}) or {}
        raw_host = str(proxy.get("host", "") or "")
        port = int(proxy.get("port", 0) or 0)
        username = str(proxy.get("username", "") or "")
        password = str(proxy.get("password", "") or "")
        tm_api_key = str(proxy.get("tmproxy_api_key", "") or "")
        proxyno1_api_key = str(proxy.get("proxyno1_api_key", "") or "")
        tm_type = str(proxy.get("tmproxy_type", "socks5") or "socks5").lower()

        # Suy luận provider nếu chưa có
        provider = str(proxy.get("provider", "") or "").lower()
        if not provider:
            if tm_api_key:
                provider = "tmproxy"
            elif raw_host and port:
                provider = "raw"
            else:
                provider = "none"

        # Tách scheme ra khỏi host nếu có: http://, https://, socks5://
        proxy_type_index = 0  # mặc định: Không dùng
        host_for_edit = raw_host

        if raw_host:
            lowered = raw_host.lower()
            if lowered.startswith("socks5://"):
                proxy_type_index = 3
                host_for_edit = raw_host[len("socks5://") :]
            elif lowered.startswith("https://"):
                proxy_type_index = 2
                host_for_edit = raw_host[len("https://") :]
            elif lowered.startswith("http://"):
                proxy_type_index = 1
                host_for_edit = raw_host[len("http://") :]
            else:
                # không có scheme nhưng có host/port -> mặc định http
                if port > 0:
                    proxy_type_index = 1

        # Override theo provider
        if provider == "tmproxy":
            proxy_type_index = 4
        elif provider == "proxyno1":
            proxy_type_index = 5
        elif tm_api_key and proxy_type_index == 0:
            # config cũ: có TM key nhưng chưa có provider
            proxy_type_index = 4

        # Set combo loại proxy
        self.proxy_type_combo.blockSignals(True)
        try:
            self.proxy_type_combo.setCurrentIndex(proxy_type_index)
        finally:
            self.proxy_type_combo.blockSignals(False)

        # Set TMProxy type combo (1: socks5, 0: https) – giữ đúng kiểu cũ
        if tm_type == "socks5":
            self.tmproxy_type_combo.setCurrentIndex(1)
        else:
            self.tmproxy_type_combo.setCurrentIndex(0)

        # Đổ dữ liệu vào field UI
        self.proxy_host_edit.setText(host_for_edit)
        self.proxy_port_spin.setValue(port)
        self.proxy_user_edit.setText(username)
        self.proxy_pass_edit.setText(password)

        # 1 ô API dùng chung, chọn theo provider
        if provider == "proxyno1":
            api_for_edit = proxyno1_api_key
        else:
            api_for_edit = tm_api_key
        self.tmproxy_api_key_edit.setText(api_for_edit)

        # Cập nhật trạng thái label
        if provider == "tmproxy" and tm_api_key:
            self._set_tmproxy_status("Đã cấu hình TM-PROXY (chưa kiểm tra)", "orange")
        elif provider == "proxyno1" and proxyno1_api_key:
            self._set_tmproxy_status("Đã cấu hình ProxyNo1 (chưa kiểm tra)", "orange")
        elif tm_api_key or proxyno1_api_key:
            self._set_tmproxy_status("Đã cấu hình proxy API (chưa kiểm tra)", "orange")
        else:
            self._set_tmproxy_status("Chưa cấu hình proxy API", "gray")

        # Bật / tắt ô API + nút Get/Reset theo loại proxy
        self._update_tmproxy_controls_enabled()

    def save_profile(self) -> None:
        pid = self.profile_combo.currentText()
        cfg = load_config()
        self._ensure_profiles_root(cfg)

        prof = cfg["profiles"][pid]
        prof["name"] = self.name_edit.text().strip()
        prof["chrome_path"] = self.chrome_path_edit.text().strip()
        # Legacy field kept in config for compatibility only.
        # Browser runtime/user-data is now managed automatically under tool/runtime/P?.
        prof["user_data_dir"] = ""

        prof["window"] = {
            "width": int(self.win_width_spin.value()),
            "height": int(self.win_height_spin.value()),
            "scale_percent": int(self.scale_spin.value()),
        }

        # Proxy save
        old_proxy = prof.get("proxy", {}) or {}
        old_proxyno1_key = str(old_proxy.get("proxyno1_api_key", "") or "")
        old_tm_key = str(old_proxy.get("tmproxy_api_key", "") or "")
        # Proxy save
        proxy_type_index = self.proxy_type_combo.currentIndex()
        host_input = self.proxy_host_edit.text().strip()
        port_val = int(self.proxy_port_spin.value())
        user_val = self.proxy_user_edit.text().strip()
        pass_val = self.proxy_pass_edit.text()
        api_key_input = self.tmproxy_api_key_edit.text().strip()
        tm_type = self.tmproxy_type_combo.currentData() or "socks5"

        # Hỗ trợ dán host:port[:user:pass] vào ô Host (import nhanh)
        if host_input and ":" in host_input and port_val == 0 and not user_val and not pass_val:
            parts = host_input.split(":")
            if len(parts) in (2, 4) and parts[1].isdigit():
                host_input = parts[0]
                port_val = int(parts[1])
                if len(parts) == 4:
                    user_val = parts[2]
                    pass_val = parts[3]

        # Encode loại proxy vào host bằng scheme (http://, https://, socks5://)
        if proxy_type_index == 0 or not host_input:
            # Không dùng proxy
            full_host = ""
            port_val = 0
            user_val = ""
            pass_val = ""
        else:
            if proxy_type_index == 1:
                scheme = "http://"
            elif proxy_type_index == 2:
                scheme = "https://"
            elif proxy_type_index == 3:
                scheme = "socks5://"
            elif proxy_type_index == 4:
                # TM-PROXY: chọn scheme theo tmproxy_type
                if tm_type == "socks5":
                    scheme = "socks5://"
                else:
                    # TMProxy "https" = HTTP proxy dùng cho HTTPS traffic
                    scheme = "http://"
            elif proxy_type_index == 5:
                # ProxyNo1: dùng chung combo protocol với TM-PROXY
                if tm_type == "socks5":
                    scheme = "socks5://"
                else:
                    scheme = "http://"
            full_host = scheme + host_input

        # Xác định provider: none | raw | tmproxy | proxyno1
        if proxy_type_index == 4:
            provider = "tmproxy"
        elif proxy_type_index == 5:
            provider = "proxyno1"
        elif proxy_type_index == 0 or not host_input:
            provider = "none"
        else:
            provider = "raw"

        # Lấy proxy cũ để giữ lại API key bên kia
        old_proxy = prof.get("proxy", {}) or {}
        old_tm_key = str(old_proxy.get("tmproxy_api_key", "") or "")
        old_no1_key = str(old_proxy.get("proxyno1_api_key", "") or "")
        old_provider = str(old_proxy.get("provider", "") or "").lower() or "none"

        # Xác định provider theo combo
        if proxy_type_index == 4:
            provider = "tmproxy"
        elif proxy_type_index == 5:
            provider = "proxyno1"
        elif proxy_type_index == 0:
            provider = "none"
        else:
            provider = "raw"

        # Phân phối API key vào đúng field
        tm_api_key_to_save = old_tm_key
        proxyno1_api_key_to_save = old_no1_key

        if provider == "tmproxy":
            tm_api_key_to_save = api_key_input
        elif provider == "proxyno1":
            proxyno1_api_key_to_save = api_key_input
        else:
            # các loại khác: giữ nguyên key cũ, không động
            pass

        prof["proxy"] = {
            "host": full_host,
            "port": port_val,
            "username": user_val,
            "password": pass_val,
            "tmproxy_api_key": tm_api_key_to_save,
            "tmproxy_type": tm_type,
            "proxyno1_api_key": proxyno1_api_key_to_save,
            "provider": provider,
        }

        save_config(cfg)
        if hasattr(self.browser_manager, "reload_config"):
            self.browser_manager.reload_config()

        QMessageBox.information(self, "Lưu cấu hình", f"Đã lưu cấu hình cho {pid}")

    def reload_config(self) -> None:
        if hasattr(self.browser_manager, "reload_config"):
            self.browser_manager.reload_config()
        self.load_profile(self.profile_combo.currentText())
        QMessageBox.information(self, "Reload", "Đã reload config từ file.")

    # ------------------------------------------------------------------ Slots: browser

    def open_browser(self) -> None:
        pid = self.profile_combo.currentText()
        if hasattr(self.browser_manager, "open_browser"):
            self.browser_manager.open_browser(pid)
        else:
            QMessageBox.warning(
                self, "Lỗi", "BrowserManager không hỗ trợ open_browser()."
            )

    def close_browser(self) -> None:
        pid = self.profile_combo.currentText()
        if hasattr(self.browser_manager, "close_browser"):
            self.browser_manager.close_browser(pid)
        else:
            QMessageBox.warning(
                self, "Lỗi", "BrowserManager không hỗ trợ close_browser()."
            )

    # ------------------------------------------------------------------ TM-PROXY logic

    def _call_tmproxy_api(self, api_key: str, new_proxy: bool) -> Dict[str, Any]:
        """Gọi TMProxy API: get-current-proxy hoặc get-new-proxy.

        new_proxy=False -> /get-current-proxy
        new_proxy=True  -> /get-new-proxy
        """
        if not api_key:
            raise ValueError("API key rỗng")

        if new_proxy:
            url = "https://tmproxy.com/api/proxy/get-new-proxy"
            payload: Dict[str, Any] = {
                "api_key": api_key,
                "id_location": 0,
                "id_isp": 0,
            }
        else:
            url = "https://tmproxy.com/api/proxy/get-current-proxy"
            payload = {"api_key": api_key}

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data

    def _apply_tmproxy_data_to_fields(self, data: Dict[str, Any]) -> None:
        """Parse JSON TMProxy, đổ IP/Port/User/Pass vào form."""
        if data.get("code") != 0:
            msg = data.get("message", "TMProxy trả về lỗi")
            raise RuntimeError(f"TMProxy error: {msg}")

        info = data.get("data") or {}

        tm_type = self.tmproxy_type_combo.currentData() or "socks5"

        if tm_type == "socks5":
            hp = info.get("socks5") or ""
            field_name = "socks5"
        else:
            hp = info.get("https") or ""
            field_name = "https"

        if not hp:
            raise RuntimeError(f"TMProxy không trả về trường '{field_name}'")

        if ":" not in hp:
            raise RuntimeError(f"Định dạng {field_name} không hợp lệ: {hp!r}")

        host, port_str = hp.split(":", 1)
        try:
            port_val = int(port_str)
        except ValueError:
            raise RuntimeError(
                f"Port không hợp lệ trong {field_name}: {hp!r}"
            )

        username = info.get("username") or ""
        password = info.get("password") or ""

        # Cập nhật UI: chọn TM-PROXY, điền host/port/user/pass
        self.proxy_type_combo.blockSignals(True)
        if self.proxy_type_combo.currentIndex() != 4:
            self.proxy_type_combo.setCurrentIndex(4)
        self.proxy_type_combo.blockSignals(False)

        self.proxy_host_edit.setText(host.strip())
        self.proxy_port_spin.setValue(port_val)
        self.proxy_user_edit.setText(username.strip())
        self.proxy_pass_edit.setText(password)

    def _call_proxyno1_change_ip(self, api_key: str) -> str:
        """Gọi API ProxyNo1 để đổi IP cho API key hiện tại.

        Ở tài liệu public, ví dụ gọi:
        https://app.proxyno1.com/api/change-key-ip/<APIKEY>
        và đọc message trong JSON. :contentReference[oaicite:3]{index=3}
        """
        if not api_key:
            raise ValueError("API key rỗng")

        url = f"https://app.proxyno1.com/api/change-key-ip/{api_key}"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        msg = str(data.get("message", "Đã gọi ProxyNo1 change-key-ip."))
        return msg

    def on_tmproxy_get_clicked(self) -> None:
        """
        Nút Get:
        - Nếu loại proxy là TM-PROXY -> gọi TMProxy get-current.
        - Nếu loại proxy là ProxyNo1 -> gọi ProxyNo1 change-ip cho profile.
        """
        pid = self.profile_combo.currentText()
        api_key = self.tmproxy_api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(
                self,
                "Proxy API",
                "Vui lòng nhập API key trước khi Get.",
            )
            return

        idx = self.proxy_type_combo.currentIndex()

        # Branch ProxyNo1: dùng protocol do người dùng chọn (HTTPS / SOCKS5)
        if idx == 5:
            # 1) Lưu API key + provider vào config
            cfg = load_config()
            self._ensure_profiles_root(cfg)
            prof = cfg["profiles"].get(pid, {}) or {}
            proxy = prof.get("proxy", {}) or {}
            proxy["proxyno1_api_key"] = api_key
            proxy["provider"] = "proxyno1"
            prof["proxy"] = proxy
            cfg["profiles"][pid] = prof
            save_config(cfg)

            # 2) Gọi key-status → lấy host + cả 2 port HTTP/SOCKS5
            self._set_tmproxy_status("ProxyNo1: đang lấy thông tin proxy...", "orange")
            ok, msg, info = proxyno1_get_proxy_info_for_profile(pid)
            if not ok or not info:
                self._set_tmproxy_status(f"ProxyNo1 lỗi: {msg}", "red")
                QMessageBox.critical(self, "ProxyNo1", msg)
                return

            host = str(info.get("host", "") or "")
            http_port = int(info.get("http_port", 0) or 0)
            socks_port = int(
                info.get("socks5_port", info.get("socks_port", 0) or 0)
            )
            user_val = str(info.get("username", "") or "")
            pass_val = str(info.get("password", "") or "")

            # 3) Chọn port theo protocol người dùng đã chọn trong combo
            tm_type = (self.tmproxy_type_combo.currentData() or "https").lower()

            used_protocol = ""
            port_val = 0

            if tm_type == "socks5" and socks_port > 0:
                used_protocol = "socks5"
                port_val = socks_port
            elif tm_type in ("https", "http") and http_port > 0:
                used_protocol = "http"
                port_val = http_port
            else:
                # Fallback: nếu user chọn loại không có port tương ứng → dùng default trong info
                used_protocol = str(info.get("protocol", "") or "")
                port_val = int(info.get("port", 0) or 0)

            if not host or port_val <= 0:
                self._set_tmproxy_status("ProxyNo1 lỗi: thiếu host/port hợp lệ.", "red")
                QMessageBox.critical(
                    self,
                    "ProxyNo1",
                    "Key-status không trả về host/port hợp lệ cho ProxyNo1.",
                )
                return

            # 4) Đảm bảo combo Loại proxy vẫn là ProxyNo1, KHÔNG tự đổi protocol combo
            self.proxy_type_combo.blockSignals(True)
            if self.proxy_type_combo.currentIndex() != 5:
                self.proxy_type_combo.setCurrentIndex(5)
            self.proxy_type_combo.blockSignals(False)

            # 5) Đổ dữ liệu vào field UI
            self.proxy_host_edit.setText(host)
            self.proxy_port_spin.setValue(port_val)
            self.proxy_user_edit.setText(user_val)
            self.proxy_pass_edit.setText(pass_val)

            # 6) Lưu lại config để BrowserManager đọc
            self.save_profile()

            self._set_tmproxy_status(
                f"ProxyNo1: Lấy proxy thành công ({used_protocol or 'auto'})", "green"
            )
            return

        # Branch TM-PROXY (giữ logic cũ)
        if idx != 4:
            QMessageBox.information(
                self,
                "Proxy",
                "Nút Get hiện chỉ dùng cho TM-PROXY hoặc ProxyNo1.",
            )
            return

        self._set_tmproxy_status("Đang lấy proxy (get-current)...", "orange")
        try:
            data = self._call_tmproxy_api(api_key, new_proxy=False)
            self._apply_tmproxy_data_to_fields(data)
            # Lưu lại config sau khi đổ dữ liệu
            self.save_profile()
        except Exception as e:
            self._set_tmproxy_status(f"Lỗi: {e}", "red")
            QMessageBox.critical(self, "TM-PROXY", f"Lỗi khi Get proxy:\n{e}")
            return

        self._set_tmproxy_status("Get proxy thành công (current)", "green")

    def on_tmproxy_reset_clicked(self) -> None:
        """
        Nút Reset:
        - TM-PROXY: get-new-proxy.
        - ProxyNo1: change-ip (reset IP line).
        """
        pid = self.profile_combo.currentText()
        api_key = self.tmproxy_api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(
                self,
                "Proxy API",
                "Vui lòng nhập API key trước khi Reset.",
            )
            return

        idx = self.proxy_type_combo.currentIndex()

        # ProxyNo1 branch
        if idx == 5:
            cfg = load_config()
            self._ensure_profiles_root(cfg)
            prof = cfg["profiles"].get(pid, {}) or {}
            proxy = prof.get("proxy", {}) or {}
            proxy["proxyno1_api_key"] = api_key
            proxy["provider"] = "proxyno1"
            prof["proxy"] = proxy
            cfg["profiles"][pid] = prof
            save_config(cfg)

            self._set_tmproxy_status("ProxyNo1: đang đổi IP (Reset)...", "orange")
            ok, msg = proxyno1_change_ip_for_profile(pid)
            if ok:
                self._set_tmproxy_status(f"ProxyNo1: {msg}", "green")
            else:
                self._set_tmproxy_status(f"ProxyNo1 lỗi: {msg}", "red")
                QMessageBox.critical(self, "ProxyNo1", msg)
            return

        # TM-PROXY branch (giữ logic cũ)
        if idx != 4:
            QMessageBox.information(
                self,
                "Proxy",
                "Nút Reset hiện chỉ dùng cho TM-PROXY hoặc ProxyNo1.",
            )
            return

        self._set_tmproxy_status("Đang đổi IP (get-new-proxy)...", "orange")
        try:
            data = self._call_tmproxy_api(api_key, new_proxy=True)
            self._apply_tmproxy_data_to_fields(data)
            self.save_profile()
        except Exception as e:
            self._set_tmproxy_status(f"Lỗi: {e}", "red")
            QMessageBox.critical(self, "TM-PROXY", f"Lỗi khi Reset IP:\n{e}")
            return

        self._set_tmproxy_status("Đổi IP TM-PROXY thành công", "green")
