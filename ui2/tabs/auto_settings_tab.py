from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.config import load_config, save_config
from core.gold_threshold_notifier import GoldThresholdConfig, GoldThresholdNotifier


class AutoSettingsTab(QWidget):
    """Settings surface for lightweight automation alerts."""

    config_saved = Signal(object)

    def __init__(self, send_test: Optional[Callable[[], bool]] = None, parent=None) -> None:
        super().__init__(parent)
        self._send_test = send_test
        self._build_ui()
        self._load_config()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("Cài đặt Auto")
        title.setStyleSheet("font-size:16px; font-weight:900;")
        root.addWidget(title)

        telegram_box = QGroupBox("Telegram")
        telegram_form = QFormLayout(telegram_box)
        self.txt_token = QLineEdit()
        self.txt_token.setEchoMode(QLineEdit.Password)
        self.txt_chat_id = QLineEdit()
        telegram_form.addRow("Token bot:", self.txt_token)
        telegram_form.addRow("Chat ID nhóm nhận:", self.txt_chat_id)
        root.addWidget(telegram_box)

        threshold_box = QGroupBox("Cảnh báo vàng")
        threshold_form = QFormLayout(threshold_box)
        self.chk_gold_min_threshold = QCheckBox("Báo Ngưỡng Min")
        self.spn_gold_min_threshold = QSpinBox()
        self.spn_gold_min_threshold.setRange(0, 2_000_000_000)
        self.spn_gold_min_threshold.setSingleStep(1_000)
        self.chk_gold_max_threshold = QCheckBox("Báo Ngưỡng Max")
        self.spn_gold_max_threshold = QSpinBox()
        self.spn_gold_max_threshold.setRange(0, 2_000_000_000)
        self.spn_gold_max_threshold.setSingleStep(1_000)
        threshold_form.addRow(self.chk_gold_min_threshold)
        threshold_form.addRow("Ngưỡng Min:", self.spn_gold_min_threshold)
        threshold_form.addRow(self.chk_gold_max_threshold)
        threshold_form.addRow("Ngưỡng Max:", self.spn_gold_max_threshold)
        root.addWidget(threshold_box)

        mau_binh_box = QGroupBox("Mậu Binh")
        mau_binh_form = QFormLayout(mau_binh_box)
        self.chk_intentional_foul = QCheckBox("Tự binh lủng khi bị sập làng (kèm báo Telegram)")
        mau_binh_form.addRow(self.chk_intentional_foul)
        root.addWidget(mau_binh_box)

        actions = QHBoxLayout()
        btn_save = QPushButton("Lưu cấu hình")
        btn_save.clicked.connect(self._save_config)
        btn_test = QPushButton("Test gửi")
        btn_test.clicked.connect(self._test_send)
        actions.addWidget(btn_save)
        actions.addWidget(btn_test)
        actions.addStretch(1)
        root.addLayout(actions)
        root.addStretch(1)

    def _load_config(self) -> None:
        config = self._read_form_config(load_config())
        self.txt_token.setText(config.bot_token)
        self.txt_chat_id.setText(config.chat_id)
        self.chk_gold_min_threshold.setChecked(config.min_enabled)
        self.spn_gold_min_threshold.setValue(config.min_threshold)
        self.chk_gold_max_threshold.setChecked(config.max_enabled)
        self.spn_gold_max_threshold.setValue(config.max_threshold)
        self.chk_intentional_foul.setChecked(config.intentional_foul_enabled)

    @staticmethod
    def _read_form_config(raw_config: dict) -> GoldThresholdConfig:
        return GoldThresholdNotifier.config_from_dict(raw_config)

    def current_config(self) -> GoldThresholdConfig:
        return GoldThresholdConfig(
            bot_token=self.txt_token.text().strip(),
            chat_id=self.txt_chat_id.text().strip(),
            min_enabled=self.chk_gold_min_threshold.isChecked(),
            min_threshold=int(self.spn_gold_min_threshold.value()),
            max_enabled=self.chk_gold_max_threshold.isChecked(),
            max_threshold=int(self.spn_gold_max_threshold.value()),
            intentional_foul_enabled=self.chk_intentional_foul.isChecked(),
        )

    def _validate_config(self, config: GoldThresholdConfig) -> bool:
        if config.min_enabled and config.min_threshold <= 0:
            QMessageBox.warning(self, "Lỗi", "Ngưỡng Min phải lớn hơn 0")
            return False
        if config.max_enabled and config.max_threshold <= 0:
            QMessageBox.warning(self, "Lỗi", "Ngưỡng Max phải lớn hơn 0")
            return False
        if config.min_enabled and config.max_enabled and config.max_threshold <= config.min_threshold:
            QMessageBox.warning(self, "Lỗi", "Ngưỡng Max phải lớn hơn Ngưỡng Min")
            return False
        return True

    def _save_config(self) -> None:
        config = self.current_config()
        if not self._validate_config(config):
            return
        raw = load_config()
        root = raw.setdefault("auto_settings", {})
        telegram = root.setdefault("telegram", {})
        alerts = root.setdefault("alerts", {})
        min_threshold = alerts.setdefault("gold_min_threshold", {})
        max_threshold = alerts.setdefault("gold_max_threshold", {})
        intentional_foul = alerts.setdefault("opp_sap_lang_intentional_foul", {})
        alerts.pop("gold_threshold", None)
        telegram["bot_token"] = config.bot_token
        telegram["chat_id"] = config.chat_id
        min_threshold["enabled"] = config.min_enabled
        min_threshold["threshold"] = config.min_threshold
        max_threshold["enabled"] = config.max_enabled
        max_threshold["threshold"] = config.max_threshold
        intentional_foul["enabled"] = config.intentional_foul_enabled
        save_config(raw)
        self.config_saved.emit(config)
        QMessageBox.information(self, "Thành công", "Đã lưu cấu hình Auto")

    def _test_send(self) -> None:
        config = self.current_config()
        if not self._validate_config(config):
            return
        self.config_saved.emit(config)
        if self._send_test is None or not self._send_test():
            QMessageBox.warning(self, "Lỗi", "Thiếu token hoặc Chat ID nhóm nhận")
            return
        QMessageBox.information(self, "Thành công", "Đã đưa tin nhắn test vào hàng đợi")
