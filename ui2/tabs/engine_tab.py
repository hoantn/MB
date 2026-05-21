from typing import List

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QGroupBox,
)
from PySide6.QtCore import Qt

from engine.card import Card
from engine.arranger import arrange_13_cards
try:
    from engine.arranger import arrange_13_cards_vs_opp  # type: ignore
except Exception:  # pragma: no cover
    arrange_13_cards_vs_opp = None  # type: ignore

from engine.scorer import score_three_chi
try:
    from engine.scorer import score_matchup  # type: ignore
except Exception:  # pragma: no cover
    score_matchup = None  # type: ignore


class EngineTab(QWidget):
    """Tab test Engine.

    - Nhập 13 lá ở dạng code (ví dụ: AR, KT, 9B, ...).
    - Nút "Arrange" → đề xuất cách xếp 3 chi.
    - Nút "Score 3 chi" → tính điểm bộ tự nhập.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.card_edits: List[QLineEdit] = []
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        group = QGroupBox("Nhập 13 lá (code, ví dụ: AR, KT, 9B, ...)")
        g_layout = QVBoxLayout(group)

        rows = []
        for r in range(3):
            row = QHBoxLayout()
            for c in range(5 if r < 2 else 3):
                edit = QLineEdit()
                edit.setMaxLength(3)
                edit.setPlaceholderText("AR")
                edit.setFixedWidth(50)
                row.addWidget(edit)
                self.card_edits.append(edit)
            rows.append(row)
            g_layout.addLayout(row)

        root.addWidget(group)

        btn_row = QHBoxLayout()
        arrange_btn = QPushButton("Arrange 13 lá")
        arrange_btn.clicked.connect(self.arrange_cards_action)
        btn_row.addWidget(arrange_btn)

        score_btn = QPushButton("Score 3 chi (từ output)")
        score_btn.clicked.connect(self.score_current_three_chi)
        btn_row.addWidget(score_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        root.addWidget(QLabel("Kết quả:"), alignment=Qt.AlignLeft)
        root.addWidget(self.output)

    # ------------------------------------------------------------------ Helpers

    def _parse_cards(self) -> List[Card]:
        codes: List[str] = []
        for e in self.card_edits:
            code = e.text().strip().upper()
            if code:
                codes.append(code)
        if len(codes) != 13:
            raise ValueError(f"Cần đúng 13 code, hiện tại: {len(codes)}")
        return [Card.from_code(c) for c in codes]

    # ------------------------------------------------------------------ Actions

    def arrange_cards_action(self) -> None:
        self.output.clear()
        try:
            cards = self._parse_cards()
        except Exception as e:
            self.output.setPlainText(str(e))
            return

        chi1, chi2, chi3 = arrange_13_cards(cards)
        lines = []
        lines.append("Đề xuất xếp 3 chi:")
        lines.append("Chi 1: " + " ".join(c.to_code() for c in chi1))
        lines.append("Chi 2: " + " ".join(c.to_code() for c in chi2))
        lines.append("Chi 3: " + " ".join(c.to_code() for c in chi3))

        if score_three_chi:
            s = score_three_chi(chi1, chi2, chi3)
            lines.append(f"Score (3 chi): {s}")

        self.output.setPlainText("\n".join(lines))

    def score_current_three_chi(self) -> None:
        """Đọc 3 dòng 'Chi 1..3' trong output hiện tại và tính điểm."""
        if not score_three_chi:
            self.output.append("\nEngine scorer chưa hỗ trợ.")
            return

        text = self.output.toPlainText().splitlines()
        chi_lines = [ln for ln in text if ln.startswith("Chi ")]
        if len(chi_lines) < 3:
            self.output.append("\nKhông tìm thấy đủ 3 dòng 'Chi 1..3' trong output.")
            return

        def parse_line(ln: str) -> List[Card]:
            parts = ln.split(":", 1)
            if len(parts) != 2:
                return []
            codes = parts[1].strip().split()
            return [Card.from_code(c.strip().upper()) for c in codes if c.strip()]

        chi1 = parse_line(chi_lines[0])
        chi2 = parse_line(chi_lines[1])
        chi3 = parse_line(chi_lines[2])

        if len(chi1) != 3 or len(chi2) != 5 or len(chi3) != 5:
            self.output.append("\nSố lượng lá trong các chi không hợp lệ.")
            return

        s = score_three_chi(chi1, chi2, chi3)
        self.output.append(f"\nScore lại (3 chi): {s}")
