# ui2/tools/ws_simulator_ui.py
from __future__ import annotations

import random
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QTextEdit, QGroupBox,
    QMessageBox, QScrollArea
)
from PySide6.QtCore import Qt

from core.logger import log

# Mapping 0..51 <-> "2B/TT/AC..."
from engine.ws_card_mapping import WS_CODE_TO_CARD, CARD_TO_WS_CODE

# Hàm inject WS bạn đã tạo
from ui2.bridge.ws_simulator import simulate_ws_cards


def _card_label(code_str: str) -> str:
    """
    code_str: "AB", "TC", ...
    Hiển thị gọn: "A♠" ... (chỉ để nhìn dễ), không ảnh hưởng logic.
    Suit:
      B = Bích, T = Tép, R = Rô, C = Cơ
    """
    if not code_str or len(code_str) < 2:
        return code_str
    r = code_str[:-1]
    s = code_str[-1]
    suit = {"B": "♠", "T": "♣", "R": "♦", "C": "♥"}.get(s, s)
    return f"{r}{suit}"


class WSSimulatorTab(QWidget):
    """
    Tab/UI giả lập WS 13 lá:
    - Random 13 lá (không trùng)
    - Chọn tay 52 lá để đủ 13
    - Gửi inject vào WS_EVENT_QUEUE thông qua simulate_ws_cards()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._selected_ws_codes: List[int] = []
        self._btn_by_ws_code: Dict[int, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ---- Header controls ----
        header = QHBoxLayout()
        header.setSpacing(8)

        header.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["P1", "P2", "P3"])
        self.profile_combo.setFixedWidth(70)
        header.addWidget(self.profile_combo)

        self.btn_random = QPushButton("Random 13")
        self.btn_clear = QPushButton("Clear")
        self.btn_send = QPushButton("Send WS (cmd=600)")

        header.addWidget(self.btn_random)
        header.addWidget(self.btn_clear)
        header.addStretch(1)
        header.addWidget(self.btn_send)

        root.addLayout(header)

        # ---- Selected summary ----
        self.lbl_count = QLabel("Đã chọn: 0/13")
        self.lbl_count.setStyleSheet("font-weight:600;")
        root.addWidget(self.lbl_count)

        self.txt_selected = QTextEdit()
        self.txt_selected.setReadOnly(True)
        self.txt_selected.setFixedHeight(70)
        root.addWidget(self.txt_selected)

        # ---- Manual picker grid (52 cards) ----
        box = QGroupBox("Chọn tay 52 lá (bấm để toggle). Đủ 13 lá thì Send.")
        box_layout = QVBoxLayout(box)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(6)

        # Tạo danh sách 52 lá theo ws_code 0..51
        # WS_CODE_TO_CARD: int -> "rank+suit" (vd "AC", "2B", ...)
        # Sắp xếp theo rank A..K, mỗi rank 4 suit
        # (hiển thị đẹp, không ảnh hưởng)
        all_ws = list(range(52))

        # Build labels for consistent ordering
        # Rank index = code//4 (0..12), suit index = code%4 (0..3)
        def _sort_key(c: int):
            return (c // 4, c % 4)

        all_ws.sort(key=_sort_key)

        # Grid layout: 13 ranks x 4 suits
        # Mỗi hàng = 1 rank, 4 cột = 4 suit
        row = 0
        col = 0
        for ws_code in all_ws:
            code_str = WS_CODE_TO_CARD[ws_code]  # "AB"...
            btn = QPushButton(_card_label(code_str))
            btn.setCheckable(True)
            btn.setFixedSize(56, 32)
            btn.clicked.connect(lambda checked, c=ws_code: self._toggle_card(c, checked))
            self._btn_by_ws_code[ws_code] = btn

            grid.addWidget(btn, row, col)
            col += 1
            if col >= 4:
                col = 0
                row += 1

        scroll.setWidget(container)
        box_layout.addWidget(scroll)
        root.addWidget(box)

        # ---- Extra input: paste ws_codes list ----
        box2 = QGroupBox("Nhập nhanh (tùy chọn): dán list ws_codes 13 số (0..51), cách nhau bởi dấu phẩy")
        b2 = QVBoxLayout(box2)
        self.txt_ws_codes = QTextEdit()
        self.txt_ws_codes.setPlaceholderText("Ví dụ: 12,25,23,3,26,40,1,33,46,29,17,36,43")
        self.txt_ws_codes.setFixedHeight(60)
        btn_apply_paste = QPushButton("Apply ws_codes (13 số)")
        btn_apply_paste.clicked.connect(self._apply_pasted_ws_codes)
        b2.addWidget(self.txt_ws_codes)
        b2.addWidget(btn_apply_paste)
        root.addWidget(box2)

        # ---- Wire events ----
        self.btn_random.clicked.connect(self._random_13)
        self.btn_clear.clicked.connect(self._clear)
        self.btn_send.clicked.connect(self._send)

        self._refresh_ui()

    # ---------------------------
    # Actions
    # ---------------------------

    def _clear(self) -> None:
        self._selected_ws_codes = []
        for btn in self._btn_by_ws_code.values():
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)
        self._refresh_ui()

    def _random_13(self) -> None:
        self._clear()
        picks = random.sample(range(52), 13)
        # giữ order theo ws_code để nhìn ổn định
        picks.sort()
        for ws_code in picks:
            self._selected_ws_codes.append(ws_code)
            btn = self._btn_by_ws_code.get(ws_code)
            if btn:
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)
        self._refresh_ui()

    def _toggle_card(self, ws_code: int, checked: bool) -> None:
        if checked:
            if ws_code in self._selected_ws_codes:
                return
            if len(self._selected_ws_codes) >= 13:
                # Không cho vượt 13
                btn = self._btn_by_ws_code.get(ws_code)
                if btn:
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.blockSignals(False)
                QMessageBox.warning(self, "Đủ 13 lá", "Bạn đã chọn đủ 13 lá. Hãy Clear hoặc bỏ chọn 1 lá trước.")
                return
            self._selected_ws_codes.append(ws_code)
        else:
            if ws_code in self._selected_ws_codes:
                self._selected_ws_codes.remove(ws_code)
        self._refresh_ui()

    def _apply_pasted_ws_codes(self) -> None:
        raw = (self.txt_ws_codes.toPlainText() or "").strip()
        if not raw:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Bạn chưa dán ws_codes.")
            return

        # parse ints
        parts = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
        try:
            nums = [int(x) for x in parts]
        except Exception:
            QMessageBox.warning(self, "Sai format", "Chỉ chấp nhận số nguyên 0..51, cách nhau bởi dấu phẩy.")
            return

        if len(nums) != 13:
            QMessageBox.warning(self, "Sai số lượng", f"Cần đúng 13 số. Hiện tại: {len(nums)}.")
            return

        if any((x < 0 or x > 51) for x in nums):
            QMessageBox.warning(self, "Sai giá trị", "Mỗi ws_code phải nằm trong 0..51.")
            return

        if len(set(nums)) != 13:
            QMessageBox.warning(self, "Trùng lá", "ws_codes bị trùng. Hãy kiểm tra lại.")
            return

        # apply
        self._clear()
        nums = list(nums)
        nums.sort()
        for ws_code in nums:
            self._selected_ws_codes.append(ws_code)
            btn = self._btn_by_ws_code.get(ws_code)
            if btn:
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)
        self._refresh_ui()

    def _send(self) -> None:
        if len(self._selected_ws_codes) != 13:
            QMessageBox.warning(self, "Chưa đủ 13 lá", f"Hiện tại bạn chọn {len(self._selected_ws_codes)}/13.")
            return

        # Validate 0..51, unique
        codes = list(self._selected_ws_codes)
        if any((x < 0 or x > 51) for x in codes) or len(set(codes)) != 13:
            QMessageBox.warning(self, "Dữ liệu lỗi", "ws_codes phải là 13 số khác nhau trong 0..51.")
            return

        profile_id = self.profile_combo.currentText().strip() or "P1"

        try:
            simulate_ws_cards(profile_id, codes)
        except Exception as e:
            log.exception("SIM-WS send failed")
            QMessageBox.critical(self, "Gửi thất bại", f"Lỗi: {e}")
            return

        QMessageBox.information(
            self,
            "Đã gửi",
            f"Đã inject WS cards cho {profile_id}.\n"
            f"Kiểm tra log: [SIM-WS] và [MB WS CARDS]."
        )

    # ---------------------------
    # UI refresh helpers
    # ---------------------------

    def _refresh_ui(self) -> None:
        self.lbl_count.setText(f"Đã chọn: {len(self._selected_ws_codes)}/13")

        # Hiển thị cả mã tool và ws_code để bạn đối chiếu
        codes = list(self._selected_ws_codes)
        codes.sort()

        lines = []
        for ws_code in codes:
            card = WS_CODE_TO_CARD.get(ws_code, "?")
            lines.append(f"{ws_code:02d} -> {card} ({_card_label(card)})")

        self.txt_selected.setPlainText("\n".join(lines))
