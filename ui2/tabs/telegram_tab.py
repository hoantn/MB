from __future__ import annotations

import json
import os
from typing import Dict, Any, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QCheckBox,
    QSpinBox, QGroupBox, QGridLayout, QFrame,
    QMessageBox
)

import requests

from ui2.runtime.task_runner import UiTaskResult, UiTaskRunner


def _config_path() -> str:
    here = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(project_root, "config", "config.json")


class TelegramTab(QWidget):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cfg_path = _config_path()
        self._tasks = UiTaskRunner(self)
        self._tasks.rejected.connect(self._on_task_rejected)
        self._build_ui()
        self._load_config()

    # ================= UI =================

    def _build_ui(self):
        root = QVBoxLayout(self)

        title = QLabel("ĐỌC LỆNH TELEGRAM")
        title.setStyleSheet("font-size:20px;font-weight:800;")
        root.addWidget(title)

        self.chk_enabled = QCheckBox("Bật Telegram Bot")
        root.addWidget(self.chk_enabled)

        # BOT CONFIG
        box_bot = QGroupBox("Cấu hình Bot")
        layout_bot = QVBoxLayout(box_bot)

        layout_bot.addWidget(QLabel("Bot Token"))
        self.txt_token = QPlainTextEdit()
        self.txt_token.setMaximumHeight(50)
        layout_bot.addWidget(self.txt_token)

        layout_bot.addWidget(QLabel("Danh sách nhóm (mỗi dòng 1 ID hoặc @username)"))
        self.txt_chat_ids = QPlainTextEdit()
        layout_bot.addWidget(self.txt_chat_ids)

        root.addWidget(box_bot)

        # SCHEDULE
        box_schedule = QGroupBox("Lịch gửi")
        self.schedule_layout = QVBoxLayout(box_schedule)

        self.rows: List[Dict[str, Any]] = []

        btn_add = QPushButton("+ Thêm dòng")
        btn_add.clicked.connect(self._add_row)
        self.schedule_layout.addWidget(btn_add)

        root.addWidget(box_schedule)

        # ACTION
        row_action = QHBoxLayout()

        btn_save = QPushButton("Lưu cấu hình")
        btn_save.clicked.connect(self._save_config)

        self.btn_test = QPushButton("Test gửi")
        self.btn_test.clicked.connect(self._test_send)

        row_action.addWidget(btn_save)
        row_action.addWidget(self.btn_test)

        root.addLayout(row_action)

    # ================= SCHEDULE =================

    def _add_row(self, delay=2, text="[KetQua]"):
        row = QHBoxLayout()

        sp_delay = QSpinBox()
        sp_delay.setRange(1, 999)
        sp_delay.setValue(delay)

        txt = QPlainTextEdit()
        txt.setMaximumHeight(40)
        txt.setPlainText(text)

        btn_del = QPushButton("X")
        btn_del.clicked.connect(lambda: self._remove_row(row))

        row.addWidget(QLabel("Delay"))
        row.addWidget(sp_delay)
        row.addWidget(txt)
        row.addWidget(btn_del)

        self.schedule_layout.addLayout(row)

        self.rows.append({
            "layout": row,
            "delay": sp_delay,
            "text": txt
        })

    def _remove_row(self, layout):
        for r in self.rows:
            if r["layout"] == layout:
                self.rows.remove(r)
                break
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ================= CONFIG =================

    def _read_config(self):
        if not os.path.exists(self._cfg_path):
            return {}
        with open(self._cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_config(self, data):
        os.makedirs(os.path.dirname(self._cfg_path), exist_ok=True)
        with open(self._cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_config(self):
        cfg = self._read_config()
        tg = ((cfg.get("game_ui") or {}).get("telegram_bot") or {})

        self.chk_enabled.setChecked(tg.get("enabled", False))
        self.txt_token.setPlainText(tg.get("bot_token", ""))
        self.txt_chat_ids.setPlainText("\n".join(tg.get("chat_ids", [])))

        schedules = tg.get("schedules", [])
        for s in schedules:
            self._add_row(s.get("delay", 2), s.get("template", ""))

    def _save_config(self):
        cfg = self._read_config()
        game_ui = cfg.setdefault("game_ui", {})
        tg = game_ui.setdefault("telegram_bot", {})

        tg["enabled"] = self.chk_enabled.isChecked()
        tg["bot_token"] = self.txt_token.toPlainText().strip()
        tg["chat_ids"] = [
            x.strip() for x in self.txt_chat_ids.toPlainText().splitlines() if x.strip()
        ]

        schedules = []
        for r in self.rows:
            schedules.append({
                "delay": r["delay"].value(),
                "template": r["text"].toPlainText().strip()
            })

        tg["schedules"] = schedules

        self._write_config(cfg)

        QMessageBox.information(self, "OK", "Đã lưu config Telegram")

    # ================= TEST =================

    def _on_task_rejected(self, res: UiTaskResult) -> None:
        QMessageBox.warning(self, "Đang chạy", res.error)

    def _test_send(self):
        cfg = self._read_config()
        tg = ((cfg.get("game_ui") or {}).get("telegram_bot") or {})

        token = tg.get("bot_token")
        chat_ids = tg.get("chat_ids", [])

        if not token or not chat_ids:
            QMessageBox.warning(self, "Lỗi", "Thiếu token hoặc chat_id")
            return

        msg = "Test: Tài - 14"

        def _work() -> int:
            sent = 0
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            errors = []
            for chat_id in chat_ids:
                try:
                    resp = requests.post(url, data={
                        "chat_id": chat_id,
                        "text": msg
                    }, timeout=5)
                    resp.raise_for_status()
                    sent += 1
                except Exception as e:
                    errors.append(f"{chat_id}: {e}")
            if errors:
                raise RuntimeError("; ".join(errors))
            return sent

        self.btn_test.setEnabled(False)
        self._tasks.run(
            key="telegram:test_send",
            name="Test gửi Telegram",
            fn=_work,
            on_success=lambda sent: QMessageBox.information(self, "OK", f"Đã gửi test ({sent})"),
            on_error=lambda err: QMessageBox.warning(self, "Lỗi", f"Gửi test thất bại: {err}"),
            on_finished=lambda _res: self.btn_test.setEnabled(True),
            timeout_ms=15_000,
        )
