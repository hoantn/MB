# ui2/phom/unseen_row.py
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtCore import QObject, QEvent, QPoint
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea

from engine.phom.card import Card
from ui2.phom.card_row import CardRow

class DragScrollFilter(QObject):
    def __init__(self, scroll: QScrollArea):
        super().__init__(scroll)
        self.scroll = scroll
        self._dragging = False
        self._last_pos = QPoint()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_pos = event.pos()
            return True

        if event.type() == QEvent.MouseMove and self._dragging:
            delta = event.pos().x() - self._last_pos.x()
            self._last_pos = event.pos()
            sb = self.scroll.horizontalScrollBar()
            sb.setValue(sb.value() - delta)
            return True

        if event.type() == QEvent.MouseButtonRelease and self._dragging:
            self._dragging = False
            return True

        return False

class UnseenRow(QWidget):
    """
    Hàng 'CHƯA LỘ' (UNSEEN):
    - Chỉ hiển thị các lá chưa lộ (unseen) lấy từ store.compute_known_unseen("ALL")
    - Sort A -> K (dựa trên Card.sort_key)
    - Viewport chỉ nhìn ~9 lá; nếu nhiều hơn thì kéo ngang (horizontal scroll)
    - Realtime: mỗi lần refresh() gọi update_from_store -> tự loại trừ dần
    """
    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # Title
        self.lb = QLabel("ĐỐI THỦ • CHƯA LỘ: -")
        self.lb.setStyleSheet("font-weight:700; color: rgba(255,255,255,200);")
        root.addWidget(self.lb, 0)

        # Row + Scroll (chỉ kéo ngang)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(8)

        self.scroll = QScrollArea()
        from PySide6.QtWidgets import QSizePolicy
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Responsive: scroll chiếm hết chiều ngang của row
        # Height cố định để không làm vỡ layout
        self.scroll.setFixedHeight(160)

        self.row = CardRow(cards=[])
        self.scroll.setWidget(self.row)
        # Drag ngang bằng chuột trên vùng lá
        self._drag_filter = DragScrollFilter(self.scroll)
        self.scroll.viewport().installEventFilter(self._drag_filter)

        wrap.addWidget(self.scroll, 1)   # <-- quan trọng: cho scroll stretch

        root.addLayout(wrap, 0)

        # viền nhẹ để dễ nhìn, không phá layout
        self.setStyleSheet("""
            border: 1px solid rgba(255,255,255,50);
            border-radius: 10px;
            padding: 8px;
        """)

    def update_from_store(self) -> None:
        """
        Lấy unseen realtime từ engine:
        unseen = full_deck - seen_global (hand/discards/init_seen của ALL)
        """
        if not self.store or not getattr(self.store, "compute_known_unseen", None):
            self.lb.setText("ĐỐI THỦ • CHƯA LỘ: -")
            self.row.set_cards([])
            return

        snap = self.store.compute_known_unseen("ALL")
        unseen = list(getattr(snap, "unseen", set()) or [])

        # Sort A -> K (Card.sort_key đã là (rank_index, suit_ord))
        # rank_index: A=0 ... K=12
        unseen_sorted = sorted([int(x) for x in unseen], key=lambda ws: Card(int(ws)).sort_key)

        self.lb.setText(f"ĐỐI THỦ • CHƯA LỘ: {len(unseen_sorted)}")
        self.row.set_cards(unseen_sorted)
