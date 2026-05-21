from typing import Optional, Tuple

from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QMouseEvent
from PySide6.QtCore import Qt, QRect, Signal


class ImagePreview(QLabel):
    """QLabel that displays an image and lets the user drag a rectangle selection.

    Emits selectionChanged with rectangle in *image* coordinates (x, y, w, h).
    """

    selectionChanged = Signal(int, int, int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(400, 300)
        self.setStyleSheet("background-color: #202020; border: 1px solid #404040;")

        self._pixmap: Optional[QPixmap] = None
        self._display_rect: Optional[QRect] = None

        self._dragging = False
        self._drag_start: Optional[Tuple[int, int]] = None
        self._drag_end: Optional[Tuple[int, int]] = None

    def setImage(self, pix: Optional[QPixmap]) -> None:
        self._pixmap = pix
        self._update_display_rect()
        self._dragging = False
        self._drag_start = None
        self._drag_end = None
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_display_rect()

    def _update_display_rect(self) -> None:
        if not self._pixmap:
            self._display_rect = None
            return
        # Fit pixmap into label while keeping aspect
        label_rect = self.rect()
        pix_w = self._pixmap.width()
        pix_h = self._pixmap.height()
        if pix_w <= 0 or pix_h <= 0:
            self._display_rect = None
            return

        ratio = min(label_rect.width() / pix_w, label_rect.height() / pix_h)
        disp_w = int(pix_w * ratio)
        disp_h = int(pix_h * ratio)
        x = label_rect.x() + (label_rect.width() - disp_w) // 2
        y = label_rect.y() + (label_rect.height() - disp_h) // 2
        self._display_rect = QRect(x, y, disp_w, disp_h)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._pixmap or not self._display_rect:
            return
        painter = QPainter(self)
        # Draw scaled pixmap
        painter.drawPixmap(self._display_rect, self._pixmap)

        # Draw selection rectangle
        if self._drag_start and self._drag_end:
            pen = QPen(QColor(0, 200, 0), 2, Qt.SolidLine)
            painter.setPen(pen)
            x0, y0 = self._drag_start
            x1, y1 = self._drag_end
            rect = QRect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            painter.drawRect(rect)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._display_rect:
            self._dragging = True
            self._drag_start = (event.pos().x(), event.pos().y())
            self._drag_end = self._drag_start
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and self._display_rect:
            self._drag_end = (event.pos().x(), event.pos().y())
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._dragging and self._display_rect:
            self._dragging = False
            self._drag_end = (event.pos().x(), event.pos().y())
            self.update()
            self._emit_selection()
        else:
            self._dragging = False

    def _emit_selection(self) -> None:
        if not (self._pixmap and self._display_rect and self._drag_start and self._drag_end):
            return

        x0, y0 = self._drag_start
        x1, y1 = self._drag_end
        rect = QRect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

        # Clip to display rect
        rect = rect.intersected(self._display_rect)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        # Map from widget/display coordinates to image coordinates
        disp = self._display_rect
        pix_w = self._pixmap.width()
        pix_h = self._pixmap.height()
        scale_x = pix_w / disp.width()
        scale_y = pix_h / disp.height()

        img_x = int((rect.x() - disp.x()) * scale_x)
        img_y = int((rect.y() - disp.y()) * scale_y)
        img_w = int(rect.width() * scale_x)
        img_h = int(rect.height() * scale_y)

        self.selectionChanged.emit(img_x, img_y, img_w, img_h)
