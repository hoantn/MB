from __future__ import annotations

import random
from typing import Dict, List

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.logger import log
from engine.ws_card_mapping import WS_CODE_TO_CARD
from ui2.bridge.ws_simulator import simulate_ws_cards


PROFILES = ("P1", "P2", "P3")

# Fixed scenario found to produce anti-sap suggestions against the derived NGU.
ANTI_SAP_CASE: Dict[str, List[int]] = {
    "P1": [28, 12, 45, 41, 38, 7, 5, 36, 1, 49, 33, 0, 4],
    "P2": [35, 20, 14, 51, 29, 34, 44, 39, 11, 42, 17, 15, 10],
    "P3": [21, 27, 50, 23, 3, 43, 9, 47, 6, 40, 18, 8, 46],
}


def _cards_text(ws_codes: List[int]) -> str:
    return " ".join(WS_CODE_TO_CARD.get(c, f"?{c}") for c in ws_codes)


def _rotate(values: List[int], amount: int) -> List[int]:
    if not values:
        return []
    n = amount % len(values)
    return list(values[n:] + values[:n])


class WSTestTab(QWidget):
    """
    Internal WS test tab.

    It emits the same cmd=600 card snapshots that the browser extension sends,
    so StrategyTab/anti-sap are tested through the real WS ingest path.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._case_nonce = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        title = QLabel("WS Test / Anti Sập")
        title.setObjectName("ws_test_title")
        title.setStyleSheet("font-size:16px; font-weight:900;")
        root.addWidget(title)

        actions_box = QGroupBox("Giả lập ván")
        actions = QHBoxLayout(actions_box)
        actions.setSpacing(10)

        self.btn_random_deal = QPushButton("Giả Lập Chia Bài")
        self.btn_anti_sap = QPushButton("Test Tối Ưu")
        actions.addWidget(self.btn_random_deal)
        actions.addWidget(self.btn_anti_sap)
        actions.addStretch(1)
        root.addWidget(actions_box)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Log giả lập WS sẽ hiển thị ở đây...")
        root.addWidget(self.log_view, 1)

        self.btn_random_deal.clicked.connect(self._deal_random)
        self.btn_anti_sap.clicked.connect(self._deal_anti_sap_case)

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        log.info("[WS-TEST] %s", text)

    def _emit_deal(self, hands: Dict[str, List[int]], label: str) -> None:
        self._append_log(f"=== {label} ===")
        for idx, pid in enumerate(PROFILES):
            cards = list(hands.get(pid) or [])
            if len(cards) != 13:
                self._append_log(f"{pid}: bỏ qua, không đủ 13 lá")
                continue

            self._append_log(f"{pid}: {cards} | {_cards_text(cards)}")
            QTimer.singleShot(
                idx * 120,
                lambda p=pid, c=cards: simulate_ws_cards(p, c),
            )
        self._append_log("Đã đưa cmd=600 giả lập vào WS_EVENT_QUEUE cho P1/P2/P3.")

    def _deal_random(self) -> None:
        deck = list(range(52))
        random.shuffle(deck)
        hands = {
            "P1": deck[0:13],
            "P2": deck[13:26],
            "P3": deck[26:39],
        }
        self._emit_deal(hands, "Giả lập chia bài ngẫu nhiên")

    def _deal_anti_sap_case(self) -> None:
        self._case_nonce += 1
        hands = {
            pid: _rotate(cards, self._case_nonce + i)
            for i, (pid, cards) in enumerate(ANTI_SAP_CASE.items())
        }
        self._emit_deal(hands, "Test Anti Sập có chủ đích")
