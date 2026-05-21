from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox,
    QHBoxLayout
)
from PySide6.QtCore import Qt
import os
import platform

class ActivateLicenseDialog(QDialog):
    def __init__(self, license_manager, reason: str = "", parent=None):
        super().__init__(parent)
        self.license_manager = license_manager
        self.reason = (reason or "").strip()
        
        self.setWindowTitle("Kích hoạt bản quyền")
        self.setFixedWidth(360)
        self.setModal(True)

        layout = QVBoxLayout(self)

        # --- Thông báo trạng thái license ---
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignLeft)

        reason_text = ""
        if self.reason == "EXPIRED":
            reason_text = "License đã hết hạn. Hãy copy License ID bên dưới và gửi cho quản trị viên để gia hạn."
        elif self.reason:
            reason_text = f"License đang bị khóa: {self.reason}"

        if reason_text:
            self.info_label.setText(reason_text)
            self.info_label.setStyleSheet("""
                QLabel {
                    color: #b91c1c;
                    background: #fef2f2;
                    border: 1px solid #fecaca;
                    border-radius: 8px;
                    padding: 10px;
                }
            """)
            layout.addWidget(self.info_label)

        # --- License ID ---
        cached_license_id = ""
        try:
            cached_license_id = self.license_manager.get_cached_license_id() or ""
        except Exception:
            cached_license_id = ""

        self.license_id_title = QLabel("License ID:")
        self.license_id_title.setVisible(bool(cached_license_id))

        self.license_id_value = QLineEdit()
        self.license_id_value.setReadOnly(True)
        self.license_id_value.setText(cached_license_id)
        self.license_id_value.setVisible(bool(cached_license_id))

        self.copy_id_btn = QPushButton("Copy License ID")
        self.copy_id_btn.setVisible(bool(cached_license_id))
        self.copy_id_btn.clicked.connect(self._copy_license_id)

        id_row = QHBoxLayout()
        id_row.addWidget(self.license_id_value, 1)
        id_row.addWidget(self.copy_id_btn)

        layout.addWidget(self.license_id_title)
        layout.addLayout(id_row)

        label = QLabel("Nhập KEY bản quyền:")
        label.setAlignment(Qt.AlignLeft)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("VD: ABC12xY9Z...")
        self.key_input.setMaxLength(32)

        self.btn_activate = QPushButton("Kích hoạt")
        self.btn_activate.clicked.connect(self._on_activate_clicked)

        layout.addSpacing(8)
        layout.addWidget(label)
        layout.addWidget(self.key_input)
        layout.addSpacing(10)
        layout.addWidget(self.btn_activate)

    def _on_activate_clicked(self):
        key = self.key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "Thiếu KEY", "Vui lòng nhập KEY.")
            return

        self.btn_activate.setEnabled(False)

        device_name = os.environ.get("COMPUTERNAME") or platform.node() or "PC"

        state = self.license_manager.activate_with_key(
            key=key,
            device_name=device_name
        )

        if state.ok:
            QMessageBox.information(
                self,
                "Kích hoạt thành công",
                "Bản quyền đã được kích hoạt."
            )
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Kích hoạt thất bại",
                f"Lý do: {state.reason}"
            )
            self.btn_activate.setEnabled(True)
            
    def _copy_license_id(self):
        try:
            from PySide6.QtWidgets import QApplication

            lid = self.license_id_value.text().strip()
            if not lid:
                QMessageBox.warning(self, "Thiếu License ID", "Không tìm thấy License ID để copy.")
                return

            QApplication.clipboard().setText(lid)
            QMessageBox.information(self, "Đã copy", "Đã copy License ID.")
        except Exception:
            QMessageBox.critical(self, "Lỗi", "Không thể copy License ID.")
