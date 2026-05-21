# ui2/phom/card_tile_lite.py
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import QWidget

from engine.phom.card import Card
from engine.phom.constants import CARD_IMAGE_EXTS


def _phom_assets_dir() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    mb_root = os.path.abspath(os.path.join(here, "..", ".."))
    return os.path.join(mb_root, "vision", "opp")


def resolve_card_image_path(ws_code: int) -> Optional[str]:
    c = Card(ws_code)
    base_dir = _phom_assets_dir()

    # Nếu Card.suit đã là hệ VN (R/C/B/T) thì dùng thẳng.
    # Chỉ khi Card.suit là hệ quốc tế (S/H/D/C) mới map sang VN.
    from engine.phom import card as card_mod

    rank = str(c.rank)  # đã là "A,2..9,T,J,Q,K"
    s = str(c.suit)

    if s in getattr(card_mod, "SUITS", []):  # SUITS = ["R","C","B","T"] (hoặc của bạn)
        suit = s
    else:
        suit_map = {"S": "B", "H": "C", "D": "R", "C": "T"}
        suit = suit_map.get(s, s)

    vn_code = rank + suit  # VD: "AT", "2R", "AC"

    candidates = [vn_code, c.code, str(ws_code)]

    for stem in candidates:
        for ext in CARD_IMAGE_EXTS:
            p = os.path.join(base_dir, stem + ext)
            if os.path.exists(p):
                return p
    return None


class CardTileLite(QWidget):
    """
    Lite card tile:
    - render ảnh lá bài từ vision/opp
    - hỗ trợ percent_text badge (đã có)
    - bổ sung style viền màu theo nhóm (phỏm/cạ/gửi/đánh)
    """
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.ws_code: Optional[int] = None
        self.percent_text: str = ""
        self.seen: bool = False

        self._pix: Optional[QPixmap] = None
        self._scaled_pix: Optional[QPixmap] = None
        self._scaled_for: Optional[QSize] = None

        # --- style additions (backward compatible) ---
        self._border_color: Optional[QColor] = None
        self._border_width: int = 1
        self._border_dashed: bool = False
        self._glow: bool = False

        self.setMinimumSize(28, 40)

    def set_card(self, ws_code: int, percent_text: str = "", seen: bool = False) -> None:
        self.ws_code = ws_code
        self.percent_text = percent_text or ""
        self.seen = bool(seen)
        self._scaled_pix = None
        self._scaled_for = None

        p = resolve_card_image_path(ws_code)
        self._pix = QPixmap(p) if p else None

        self.update()

    def set_border_style(
        self,
        border_color: Optional[QColor],
        border_width: int = 2,
        dashed: bool = False,
        glow: bool = False,
    ) -> None:
        """
        Optional: set border styling (phỏm/cạ/gửi/đánh).
        Backward compatible: nếu không gọi thì viền mặc định như cũ.
        """
        self._border_color = border_color
        self._border_width = max(1, int(border_width))
        self._border_dashed = bool(dashed)
        self._glow = bool(glow)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(58, 78)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()

        # Background
        painter.fillRect(rect, QColor(30, 30, 30) if self.seen else QColor(20, 20, 20))

        # Optional glow (for "ĐÁNH")
        if self._glow and self._border_color is not None:
            glow = QColor(self._border_color)
            glow.setAlpha(60)
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 8, 8)

        # Border (default: trắng mờ như cũ)
        if self._border_color is None:
            painter.setPen(QColor(255, 255, 255, 70))
            painter.drawRoundedRect(rect.adjusted(1, 1, -2, -2), 6, 6)
        else:
            pen = QPen(self._border_color)
            pen.setWidth(self._border_width)
            if self._border_dashed:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            inset = 1 + (self._border_width // 2)
            painter.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), 7, 7)

        # Image or fallback text
        img_rect = rect.adjusted(4, 4, -4, -4)

        if self._pix and not self._pix.isNull():
            if self._scaled_pix is None or self._scaled_for != img_rect.size():
                self._scaled_for = img_rect.size()
                self._scaled_pix = self._pix.scaled(
                    img_rect.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )

            pw = self._scaled_pix.width()
            ph = self._scaled_pix.height()
            x = img_rect.x() + (img_rect.width() - pw) // 2
            y = img_rect.y() + (img_rect.height() - ph) // 2
            painter.drawPixmap(x, y, self._scaled_pix)
        else:
            painter.setPen(QColor(255, 255, 255))
            f = QFont()
            f.setPointSize(10)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(rect, Qt.AlignCenter, str(self.ws_code) if self.ws_code is not None else "?")

        # Percent badge (only if not seen)
        if not self.seen and self.percent_text:
            badge_rect = rect.adjusted(2, rect.height() - 18 - 2, -2, -2)
            painter.fillRect(badge_rect, QColor(0, 0, 0, 180))
            painter.setPen(QColor(255, 255, 255))
            f = QFont()
            f.setPointSize(8)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(badge_rect, Qt.AlignCenter, self.percent_text)

        # Seen overlay
        if self.seen:
            painter.setPen(QColor(255, 255, 255, 120))
            painter.drawText(rect.adjusted(0, 0, 0, -2), Qt.AlignBottom | Qt.AlignHCenter, "SEEN")
