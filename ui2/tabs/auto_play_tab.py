from __future__ import annotations

from collections import deque
from typing import Deque, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class AutoPlayTab(QWidget):
    auto_changed = Signal(bool, int, int, int)
    request_show = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._logs: Deque[str] = deque(maxlen=120)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        title = QLabel("Auto Play Mậu Binh")
        title.setStyleSheet("font-size:16px; font-weight:900;")
        root.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_toggle = QPushButton("AUTO PLAY: TẮT")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.clicked.connect(self._on_toggle)
        self.spn_rounds = QSpinBox()
        self.spn_rounds.setRange(1, 999)
        self.spn_rounds.setValue(999)
        self.spn_delay = QSpinBox()
        self.spn_delay.setRange(0, 60)
        self.spn_delay.setValue(5)
        self.spn_delay.setSuffix(" giây")
        self.spn_delay_to = QSpinBox()
        self.spn_delay_to.setRange(0, 60)
        self.spn_delay_to.setValue(20)
        self.spn_delay_to.setSuffix(" giây")
        self.lbl_status = QLabel("Trạng thái: tắt")
        row.addWidget(self.btn_toggle)
        row.addWidget(QLabel("Số ván"))
        row.addWidget(self.spn_rounds)
        row.addWidget(QLabel("Delay từ"))
        row.addWidget(self.spn_delay)
        row.addWidget(QLabel("đến"))
        row.addWidget(self.spn_delay_to)
        row.addWidget(self.lbl_status, 1)
        root.addLayout(row)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        root.addWidget(self.log_box, 1)

    def _on_toggle(self) -> None:
        enabled = self.btn_toggle.isChecked()
        rounds = int(self.spn_rounds.value())
        delay_a = int(self.spn_delay.value()) * 1000
        delay_b = int(self.spn_delay_to.value()) * 1000
        delay_min_ms = min(delay_a, delay_b)
        delay_max_ms = max(delay_a, delay_b)
        self.btn_toggle.setText("AUTO PLAY: BẬT" if enabled else "AUTO PLAY: TẮT")
        self.lbl_status.setText(f"Trạng thái: {'bật' if enabled else 'tắt'} | còn {rounds if enabled else 0} ván")
        self.auto_changed.emit(enabled, rounds, delay_min_ms, delay_max_ms)

    def set_auto_state(self, enabled: bool, remaining: int) -> None:
        self.btn_toggle.blockSignals(True)
        self.btn_toggle.setChecked(bool(enabled))
        self.btn_toggle.setText("AUTO PLAY: BẬT" if enabled else "AUTO PLAY: TẮT")
        self.btn_toggle.blockSignals(False)
        self.lbl_status.setText(f"Trạng thái: {'bật' if enabled else 'tắt'} | còn {int(remaining)} ván")

    def append_log(self, text: str) -> None:
        self._logs.append(str(text))
        self.log_box.setPlainText("\n".join(self._logs))
        bar = self.log_box.verticalScrollBar()
        bar.setValue(bar.maximum())
