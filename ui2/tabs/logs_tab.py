import os

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
)
from PySide6.QtCore import Qt

from core.constants import LOG_DIR, APP_NAME


class LogsTab(QWidget):
    """Đọc file log chính (logs/<APP_NAME>.log) và hiển thị nội dung."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self._build_ui()
        self.load_logs()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        reload_btn = QPushButton("Reload log file")
        reload_btn.clicked.connect(self.load_logs)
        btn_row.addWidget(reload_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        root.addWidget(self.text)

    def load_logs(self) -> None:
        self.text.clear()
        path = os.path.join(LOG_DIR, f"{APP_NAME}.log")
        if not os.path.exists(path):
            self.text.setPlainText("Chưa có file log.")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-500:]  # last 500 lines
            self.text.setPlainText("".join(lines))
        except Exception as e:
            self.text.setPlainText(f"Lỗi đọc log: {e}")
