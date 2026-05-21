from PySide6.QtWidgets import QWidget, QHBoxLayout
from ui2.phom.card_tile_lite import CardTileLite  # hoặc widget bạn đang dùng

class CardRow(QWidget):
    def __init__(self, cards=None):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.layout.setSpacing(8)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self._tiles = []
        self._stretch_added = False

        if cards is not None:
            self.set_cards(cards)

    def set_cards(self, cards):
        # clear toàn bộ layout (kể cả stretch)
        while self.layout.count():
            item = self.layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # IMPORTANT: vì stretch đã bị remove khi clear layout
        # nên phải reset cờ để add lại stretch ổn định
        self._stretch_added = False
        self._tiles = []

        for ws_code in cards:
            tile = CardTileLite()
            tile.set_card(int(ws_code), percent_text="", seen=False)
            self._tiles.append(tile)
            self.layout.addWidget(tile)

        # luôn đảm bảo có stretch để layout ổn định
        if not self._stretch_added:
            self.layout.addStretch(1)
            self._stretch_added = True

        self._apply_responsive_size()


    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_size()

    def _apply_responsive_size(self):
        n = len(self._tiles)
        if n <= 0:
            return

        # Baseline cố định theo 10 lá để 9/10 không bị nhảy size
        baseline_n = 10

        # spacing tương đối ổn định (đừng đổi nhiều theo n)
        # chỉ giảm nhẹ nếu width hẹp
        avail = max(1, self.width() - 2)
        if avail < 360:
            self.layout.setSpacing(4)
        elif avail < 480:
            self.layout.setSpacing(6)
        else:
            self.layout.setSpacing(8)

        spacing = self.layout.spacing()

        # Tính width theo baseline 10 lá
        w = (avail - spacing * (baseline_n - 1)) // baseline_n

        # clamp để không quá to / quá nhỏ
        if w > 76: w = 76
        if w < 34: w = 34

        # tỉ lệ lá bài
        h = int(w * 1.42)
        if h > 120: h = 120
        if h < 52:  h = 52

        for t in self._tiles:
            t.setFixedSize(w, h)
