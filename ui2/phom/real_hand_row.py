# ui2/phom/real_hand_row.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSizePolicy

from engine.phom.card import Card
from ui2.phom.card_tile_lite import CardTileLite


@dataclass
class HandItem:
    ws_code: int
    kind: str               # "phom" | "ca" | "trash" | "gui" | "discard"
    group_index: int = -1   # chỉ dùng cho phom (0,1,2,...)


def _card_sort_key(ws_code: int) -> Tuple[int, int]:
    """
    Sort ổn định: rank rồi suit.
    Không tự đoán luật đặc biệt; chỉ dùng Card(ws_code) đã tồn tại trong hệ thống.
    """
    c = Card(int(ws_code))
    try:
        r = int(c.rank)  # thường 2..14
    except Exception:
        r = 0
    s = str(c.suit)
    suit_ord = {"C": 1, "D": 2, "H": 3, "S": 4}.get(s, 9)
    return (r, suit_ord)


class RealHandRow(QWidget):
    """
    Render 1 hàng bài theo "REAL HAND FULL":
    [PHỎM groups] + [CẠ] + [RÁC] + [LÁ ĐÁNH]
    - phỏm nhóm viền màu theo group_index
    - cạ viền tím nét đứt
    - gửi bài (nếu có) viền xanh lá + badge "GỬI"
    - lá đánh viền cam + glow + badge "ĐÁNH" + to hơn
    """
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setSpacing(8)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._is_placeholder = True
        # đảm bảo có diện tích để vẽ khung placeholder
        self.setMinimumHeight(90)  # giảm để khi cửa sổ thấp không ép quá
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)

        self._tiles: List[CardTileLite] = []
        self._discard_tile: Optional[CardTileLite] = None

        # palette phỏm theo thứ tự (xanh, đỏ, vàng, tím, cam)
        self._phom_colors = [
            QColor(70, 140, 255),
            QColor(235, 80, 80),
            QColor(240, 200, 70),
            QColor(170, 90, 230),
            QColor(255, 140, 70),
        ]

        self._color_ca = QColor(160, 110, 255)     # cạ
        self._color_gui = QColor(80, 200, 120)    # gửi
        self._color_discard = QColor(255, 140, 70) # đánh

    def sizeHint(self):
        # Placeholder: đừng đòi width lớn, để coach có chỗ nở
        if self._is_placeholder or not self._tiles:
            return QSize(360, 120)

        # Tính width theo số lá đang render
        n = len(self._tiles)
        spacing = self.layout.spacing()

        # tile đã có fixed size sau _apply_responsive_size()
        tw = self._tiles[0].width()
        if tw <= 0:
            tw = 48  # fallback an toàn

        w = n * tw + max(0, n - 1) * spacing + 20
        return QSize(w, 120)

    def clear(self) -> None:
        while self.layout.count():
            it = self.layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._tiles = []
        self._discard_tile = None

    def set_hand(self, items: List[HandItem]) -> None:
        self.clear()
        self._is_placeholder = (len(items) == 0)

        normal_items: List[HandItem] = list(items)

        for it in normal_items:
            tile = CardTileLite()
            tile.set_card(int(it.ws_code), percent_text="", seen=False)

            # style theo kind
            if it.kind == "phom":
                color = self._phom_colors[it.group_index % len(self._phom_colors)] if it.group_index >= 0 else self._phom_colors[0]
                tile.set_border_style(color, border_width=3, dashed=False, glow=False)
            elif it.kind == "ca":
                tile.set_border_style(self._color_ca, border_width=3, dashed=True, glow=False)
                tile.percent_text = "CẠ"
            elif it.kind == "gui":
                tile.set_border_style(self._color_gui, border_width=3, dashed=False, glow=False)
                tile.percent_text = "GỬI"
            else:
                # trash: viền mặc định (None) giữ như cũ
                tile.set_border_style(None)

            tile.update()

            self._tiles.append(tile)
            self.layout.addWidget(tile)

        # add stretch để hàng luôn dồn trái
        self.layout.addStretch(1)

        self._apply_responsive_size()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_responsive_size()

    def _apply_responsive_size(self) -> None:
        """
        Responsive theo width của row:
        - tile thường: base_w/base_h
        - discard: to hơn 15%
        """
        n_normal = len(self._tiles)
        has_discard = self._discard_tile is not None
        if n_normal == 0 and not has_discard:
            return

        spacing = self.layout.spacing()
        avail = max(1, self.width() - 2)

        # tổng "weight": discard tính như 1.15 tile
        weight = n_normal + (1.15 if has_discard else 0.0)
        # trừ spacing giữa các tile (ước lượng)
        gaps = max(0, (n_normal + (1 if has_discard else 0)) - 1)
        usable = max(1, avail - spacing * gaps - 10)

        base_w = int(usable / max(1.0, weight))

        # clamp theo thực tế phỏm: muốn dễ nhìn nhưng không quá to
        if base_w < 30:
            base_w = 30
        if base_w > 58:
            base_w = 58

        base_h = int(base_w * 1.42)
        if base_h < 50:
            base_h = 50
        if base_h > 110:
            base_h = 110
        max_h_by_row = max(50, self.height() - 10)
        if base_h > max_h_by_row:
            base_h = max_h_by_row
            base_w = int(base_h / 1.42)

        for t in self._tiles:
            t.setFixedSize(base_w, base_h)

        if self._discard_tile is not None:
            dw = int(base_w * 1.15)
            dh = int(dw * 1.42)
            if dw > 90:
                dw = 90
                dh = int(dw * 1.42)
            self._discard_tile.setFixedSize(dw, dh)

    def paintEvent(self, event):
        super().paintEvent(event)

        if not self._is_placeholder:
            return

        from PySide6.QtGui import QPainter, QColor, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(2, 2, -2, -2)

        # khung mờ
        pen = QPen(QColor(255, 255, 255, 50))
        pen.setStyle(Qt.DashLine)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        painter.drawRoundedRect(rect, 10, 10)

        # text hint
        painter.setPen(QColor(255, 255, 255, 80))
        painter.drawText(
            rect,
            Qt.AlignCenter,
            "HAND: PHỎM • CẠ • RÁC • ĐÁNH"
        )

def build_real_hand_items(st_analysis) -> List[HandItem]:
    """
    Build REAL HAND FULL nhưng KHÔNG CÓ lá gợi ý (discard).
    Chỉ render: PHỎM / CẠ / GỬI / RÁC.
    """
    items: List[HandItem] = []

    # 1) PHỎM
    melds = getattr(st_analysis, "melds", None) or []
    for gi, meld in enumerate(melds):
        cards = sorted([int(x) for x in (meld or [])], key=_card_sort_key)
        for ws in cards:
            items.append(HandItem(ws_code=ws, kind="phom", group_index=gi))

    # 2) CẠ
    ca_list = getattr(st_analysis, "ca", None)
    if ca_list is None:
        ca_list = getattr(st_analysis, "cas", None)
    if ca_list:
        for ws in sorted([int(x) for x in ca_list], key=_card_sort_key):
            items.append(HandItem(ws_code=ws, kind="ca"))

    # 3) GỬI
    gui_list = getattr(st_analysis, "gui", None)
    if gui_list is None:
        gui_list = getattr(st_analysis, "send_cards", None)
    gui_set = set(int(x) for x in gui_list) if gui_list else set()

    # 4) RÁC (QUAN TRỌNG – BẠN ĐÃ LỠ XÓA)
    # trash = getattr(st_analysis, "trash", None) or []
    # trash_cards = sorted([int(x) for x in trash], key=_card_sort_key)

    # for ws in trash_cards:
        # if ws in gui_set:
            # items.append(HandItem(ws_code=ws, kind="gui"))
        # else:
            # items.append(HandItem(ws_code=ws, kind="trash"))

    return items
