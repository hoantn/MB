from __future__ import annotations

import json
import os
import random
from typing import Dict, Any, Optional, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QCheckBox,
    QPlainTextEdit,
    QSpinBox,
    QGroupBox,
    QGridLayout,
    QFrame,
    QMessageBox,
)
from PySide6.QtGui import QPixmap
from browser.manager import BrowserManager
from capture.capture_manager import CaptureManager
from ui2.widgets.image_preview import ImagePreview

def _config_path() -> str:
    here = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(project_root, "config", "config.json")


class AutoSpamTab(QWidget):
    request_send_test = Signal(str, str)

    def __init__(
        self,
        browser_manager: BrowserManager,
        capture_manager: CaptureManager,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.browser_manager = browser_manager
        self.capture_manager = capture_manager

        self._cfg_path = _config_path()

        self.current_profile = "P1"
        self.current_full_pixmap: Optional[QPixmap] = None
        self.current_selection = None  # (x, y, w, h) theo tọa độ ảnh

        self._chat_pick_mode = False
        self._chat_pick_kind = ""  # "input" | "send"

        self._build_ui()
        self.current_profile = self._current_profile()
        self._load_profile_to_ui()

    # ==========================================================
    # UI
    # ==========================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        header = QFrame()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(4)

        lbl_title = QLabel("AUTO SPAM TÀI XỈU")
        lbl_title.setStyleSheet("font-size:20px; font-weight:800;")
        header_layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "Khi có kết quả phiên Tài/Xỉu, tool sẽ tự thay [KetQua] trong nội dung rồi chat lên game."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color:#666;")
        header_layout.addWidget(lbl_desc)

        root.addWidget(header)

        row_top = QHBoxLayout()
        row_top.setSpacing(12)

        row_top.addWidget(QLabel("Profile:"))
        self.cbo_profile = QComboBox()
        self.cbo_profile.addItems(["P1", "P2", "P3"])
        self.cbo_profile.currentTextChanged.connect(self._on_profile_changed)
        row_top.addWidget(self.cbo_profile)

        self.chk_enabled = QCheckBox("Bật auto chat")
        row_top.addWidget(self.chk_enabled)

        row_top.addStretch(1)

        self.btn_save = QPushButton("Lưu cấu hình")
        self.btn_save.clicked.connect(self._save_ui_to_profile)
        row_top.addWidget(self.btn_save)

        root.addLayout(row_top)
        row_capture = QHBoxLayout()
        row_capture.setSpacing(12)

        self.btn_capture = QPushButton("Chụp màn hình")
        self.btn_capture.clicked.connect(self.capture_full)
        row_capture.addWidget(self.btn_capture)

        self.btn_fix_input = QPushButton("Fix tọa độ nhập chữ")
        self.btn_fix_input.clicked.connect(self.fix_message_input_clicked)
        row_capture.addWidget(self.btn_fix_input)

        self.btn_fix_send = QPushButton("Fix tọa độ gửi")
        self.btn_fix_send.clicked.connect(self.fix_send_button_clicked)
        row_capture.addWidget(self.btn_fix_send)

        row_capture.addStretch(1)
        root.addLayout(row_capture)

        self.preview = ImagePreview(self)
        self.preview.selectionChanged.connect(self._on_selection_changed)
        root.addWidget(self.preview, stretch=2)
        box_message = QGroupBox("Nội dung chat")
        msg_layout = QVBoxLayout(box_message)

        lbl_sort = QLabel("Sortcode hỗ trợ: [KetQua]")
        lbl_sort.setStyleSheet("color:#666;")
        msg_layout.addWidget(lbl_sort)

        self.txt_template = QPlainTextEdit()
        self.txt_template.setPlaceholderText("Ví dụ: Kết quả phiên này là [KetQua]")
        self.txt_template.setMinimumHeight(100)
        msg_layout.addWidget(self.txt_template)

        row_preview = QHBoxLayout()
        self.btn_preview = QPushButton("Xem thử [KetQua]")
        self.btn_preview.clicked.connect(self._preview_message)
        row_preview.addWidget(self.btn_preview)

        self.btn_send_test = QPushButton("Gửi test")
        self.btn_send_test.clicked.connect(self._send_test)
        row_preview.addWidget(self.btn_send_test)

        row_preview.addStretch(1)
        msg_layout.addLayout(row_preview)

        self.lbl_preview = QLabel("Preview: -")
        self.lbl_preview.setWordWrap(True)
        self.lbl_preview.setStyleSheet("padding:8px; border:1px solid #DDD; border-radius:8px;")
        msg_layout.addWidget(self.lbl_preview)

        root.addWidget(box_message)

        box_coord = QGroupBox("Tọa độ chat")
        coord_layout = QGridLayout(box_coord)
        coord_layout.setHorizontalSpacing(12)
        coord_layout.setVerticalSpacing(10)

        coord_layout.addWidget(QLabel("Ô nhập chữ X"), 0, 0)
        self.sp_input_x = QSpinBox()
        self.sp_input_x.setRange(0, 10000)
        coord_layout.addWidget(self.sp_input_x, 0, 1)

        coord_layout.addWidget(QLabel("Ô nhập chữ Y"), 0, 2)
        self.sp_input_y = QSpinBox()
        self.sp_input_y.setRange(0, 10000)
        coord_layout.addWidget(self.sp_input_y, 0, 3)

        coord_layout.addWidget(QLabel("Nút gửi X"), 1, 0)
        self.sp_send_x = QSpinBox()
        self.sp_send_x.setRange(0, 10000)
        coord_layout.addWidget(self.sp_send_x, 1, 1)

        coord_layout.addWidget(QLabel("Nút gửi Y"), 1, 2)
        self.sp_send_y = QSpinBox()
        self.sp_send_y.setRange(0, 10000)
        coord_layout.addWidget(self.sp_send_y, 1, 3)

        root.addWidget(box_coord)

        self.lbl_status = QLabel("Sẵn sàng.")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("padding:8px; border:1px solid #DDD; border-radius:8px;")
        root.addWidget(self.lbl_status)

        root.addStretch(1)

    # ==========================================================
    # Config helpers
    # ==========================================================

    def _read_config(self) -> Dict[str, Any]:
        path = self._cfg_path
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _write_config(self, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self._cfg_path), exist_ok=True)
        with open(self._cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _ensure_auto_spam_root(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        game_ui = cfg.setdefault("game_ui", {})
        auto_spam = game_ui.setdefault("auto_spam", {})

        auto_spam.setdefault("enabled_profile", {})
        auto_spam.setdefault("template_profile", {})
        auto_spam.setdefault("message_input_profile", {})
        auto_spam.setdefault("send_button_profile", {})

        return auto_spam

    def _current_profile(self) -> str:
        return self.cbo_profile.currentText().strip() or "P1"

    # ==========================================================
    # UI <-> config
    # ==========================================================
    def _on_profile_changed(self, pid: str) -> None:
        self.current_profile = pid or "P1"
        self._load_profile_to_ui()

    def capture_full(self) -> None:
        pid = self._current_profile()
        img = self.capture_manager.capture_full(pid)
        if img is None:
            QMessageBox.warning(self, "Lỗi", f"Không capture được từ profile {pid}.")
            return

        from PIL.ImageQt import ImageQt

        qimage = ImageQt(img.convert("RGB"))
        pix = QPixmap.fromImage(qimage)
        self.current_full_pixmap = pix
        self.preview.setImage(pix)
        self.dat_trang_thai(f"Đã chụp màn hình cho {pid}")

    def fix_message_input_clicked(self) -> None:
        pid = self._current_profile()
        if self.current_full_pixmap is None:
            QMessageBox.warning(
                self,
                "Fix tọa độ nhập chữ",
                "Chưa có ảnh Preview.\nHãy bấm 'Chụp màn hình' trước.",
            )
            return

        self._chat_pick_mode = True
        self._chat_pick_kind = "input"

        QMessageBox.information(
            self,
            "Fix tọa độ nhập chữ",
            f"Profile {pid}: hãy drag một vùng nhỏ quanh ô nhập chat trên ảnh Preview.",
        )

    def fix_send_button_clicked(self) -> None:
        pid = self._current_profile()
        if self.current_full_pixmap is None:
            QMessageBox.warning(
                self,
                "Fix tọa độ gửi",
                "Chưa có ảnh Preview.\nHãy bấm 'Chụp màn hình' trước.",
            )
            return

        self._chat_pick_mode = True
        self._chat_pick_kind = "send"

        QMessageBox.information(
            self,
            "Fix tọa độ gửi",
            f"Profile {pid}: hãy drag một vùng nhỏ quanh nút gửi trên ảnh Preview.",
        )

    def _on_selection_changed(self, x: int, y: int, w: int, h: int) -> None:
        self.current_selection = (int(x), int(y), int(w), int(h))

        if self._chat_pick_mode:
            self._handle_chat_pick_from_selection()

    def _handle_chat_pick_from_selection(self) -> None:
        if not self._chat_pick_mode:
            return
        if not self.current_selection:
            return

        pid = self._current_profile()
        kind = (self._chat_pick_kind or "").strip().lower()
        if kind not in ("input", "send"):
            self._chat_pick_mode = False
            self._chat_pick_kind = ""
            return

        x, y, w, h = self.current_selection
        cx = int(x + w / 2)
        cy = int(y + h / 2)

        try:
            cfg = self._read_config()
            auto_spam = self._ensure_auto_spam_root(cfg)

            if kind == "input":
                target_map = auto_spam.setdefault("message_input_profile", {})
                target_map[pid] = {"x": cx, "y": cy}
                self.sp_input_x.setValue(cx)
                self.sp_input_y.setValue(cy)
                label = "ô nhập chữ"
                box_title = "Fix tọa độ nhập chữ"
            else:
                target_map = auto_spam.setdefault("send_button_profile", {})
                target_map[pid] = {"x": cx, "y": cy}
                self.sp_send_x.setValue(cx)
                self.sp_send_y.setValue(cy)
                label = "nút gửi"
                box_title = "Fix tọa độ gửi"

            self._write_config(cfg)

            self._chat_pick_mode = False
            self._chat_pick_kind = ""

            QMessageBox.information(
                self,
                box_title,
                f"Đã lưu tọa độ {label} cho {pid}: x={cx}, y={cy}",
            )
            self.dat_trang_thai(f"Đã lưu {label} cho {pid}: x={cx}, y={cy}")

        except Exception as e:
            self._chat_pick_mode = False
            self._chat_pick_kind = ""
            QMessageBox.critical(
                self,
                "Fix tọa độ Auto Spam",
                f"Lỗi khi lưu tọa độ cho {pid}: {e}",
            )
    def _load_profile_to_ui(self) -> None:
        pid = self._current_profile()
        cfg = self._read_config()
        auto_spam = ((cfg.get("game_ui") or {}).get("auto_spam") or {})

        enabled_profile = auto_spam.get("enabled_profile") or {}
        template_profile = auto_spam.get("template_profile") or {}
        input_profile = auto_spam.get("message_input_profile") or {}
        send_profile = auto_spam.get("send_button_profile") or {}

        self.chk_enabled.setChecked(bool(enabled_profile.get(pid, False)))
        self.txt_template.setPlainText(str(template_profile.get(pid, "")))

        input_pos = input_profile.get(pid) or {}
        send_pos = send_profile.get(pid) or {}

        self.sp_input_x.setValue(int(input_pos.get("x") or 0))
        self.sp_input_y.setValue(int(input_pos.get("y") or 0))
        self.sp_send_x.setValue(int(send_pos.get("x") or 0))
        self.sp_send_y.setValue(int(send_pos.get("y") or 0))

        self._preview_message()
        self.dat_trang_thai(f"Đã tải cấu hình {pid}")

    def _save_ui_to_profile(self) -> None:
        pid = self._current_profile()
        cfg = self._read_config()
        auto_spam = self._ensure_auto_spam_root(cfg)

        auto_spam.setdefault("enabled_profile", {})[pid] = self.chk_enabled.isChecked()
        auto_spam.setdefault("template_profile", {})[pid] = self.txt_template.toPlainText().strip()
        auto_spam.setdefault("message_input_profile", {})[pid] = {
            "x": int(self.sp_input_x.value()),
            "y": int(self.sp_input_y.value()),
        }
        auto_spam.setdefault("send_button_profile", {})[pid] = {
            "x": int(self.sp_send_x.value()),
            "y": int(self.sp_send_y.value()),
        }

        self._write_config(cfg)
        self.dat_trang_thai(f"Đã lưu cấu hình Auto Spam cho {pid}")
        self._preview_message()

    # ==========================================================
    # Runtime helpers
    # ==========================================================
    
    def _split_template_lines(self, raw_text: str) -> List[str]:
        lines: List[str] = []
        for line in str(raw_text or "").splitlines():
            text = line.strip()
            if text:
                lines.append(text)
        return lines
        
    def render_message(self, profile_id: str, ket_qua_text: str) -> str:
        cfg = self._read_config()
        auto_spam = ((cfg.get("game_ui") or {}).get("auto_spam") or {})
        template_profile = auto_spam.get("template_profile") or {}

        raw_template = str(template_profile.get(profile_id) or "").strip()
        if not raw_template:
            return ""

        lines = self._split_template_lines(raw_template)
        if not lines:
            return ""

        chosen = random.choice(lines)
        return chosen.replace("[KetQua]", ket_qua_text)

    def get_runtime_settings(self, profile_id: str) -> Dict[str, Any]:
        cfg = self._read_config()
        auto_spam = ((cfg.get("game_ui") or {}).get("auto_spam") or {})

        enabled_profile = auto_spam.get("enabled_profile") or {}
        template_profile = auto_spam.get("template_profile") or {}
        input_profile = auto_spam.get("message_input_profile") or {}
        send_profile = auto_spam.get("send_button_profile") or {}

        raw_template = str(template_profile.get(profile_id) or "")
        return {
            "enabled": bool(enabled_profile.get(profile_id, False)),
            "template": raw_template,
            "template_lines": self._split_template_lines(raw_template),
            "input_pos": input_profile.get(profile_id) or {},
            "send_pos": send_profile.get(profile_id) or {},
        }

    def dat_trang_thai(self, text: str) -> None:
        self.lbl_status.setText(text)

    # ==========================================================
    # Actions
    # ==========================================================

    def _preview_message(self) -> None:
        raw_text = self.txt_template.toPlainText().strip()
        lines = self._split_template_lines(raw_text)
        if not lines:
            self.lbl_preview.setText("Preview: -")
            return

        chosen = random.choice(lines)
        preview = chosen.replace("[KetQua]", "Tài - 14")
        self.lbl_preview.setText(f"Preview: {preview}")

    def _send_test(self) -> None:
        pid = self._current_profile()
        raw_text = self.txt_template.toPlainText().strip()
        lines = self._split_template_lines(raw_text)
        if not lines:
            self.dat_trang_thai("Chưa có nội dung test.")
            return

        chosen = random.choice(lines)
        msg = chosen.replace("[KetQua]", "Tài - 14")
        self.request_send_test.emit(pid, msg)
        self.dat_trang_thai(f"Đã yêu cầu gửi test cho {pid}: {msg}")