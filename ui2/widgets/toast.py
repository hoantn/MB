# ui2/widgets/toast.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Union

from PySide6.QtCore import (
    Qt,
    QTimer,
    QObject,
    Signal,
    QEvent,
    QPoint,
)
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QHBoxLayout,
    QToolButton,
    QWidget,
)


def _format_money(n: Union[int, float, str]) -> str:
    """Format money with thousands separators. Safe for str input."""
    try:
        v = int(float(str(n).replace(",", "").strip()))
        return f"{v:,}"
    except Exception:
        return str(n)


@dataclass
class ToastPayload:
    player_name: str
    gold: Union[int, float, str]
    message_type: str = "join"  # reserved for future (leave, warn, etc.)


class ToastWidget(QFrame):
    """A single toast overlay widget (self-closing, with close button)."""

    closed = Signal(object)  # emits self when closed

    def __init__(
        self,
        parent: Optional[QWidget],
        payload: ToastPayload,
        timeout_ms: int = 5000,
        width: int = 360,
    ) -> None:
        # parent có thể None để thành top-level window (desktop overlay)
        super().__init__(parent)
        self.setObjectName("ToastWidget")

        # TOP-LEVEL + ALWAYS ON TOP + FRAMELESS
        # Qt.Tool giúp không xuất hiện trong taskbar; stays-on-top giúp đè lên mọi cửa sổ.
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        # Không cướp focus
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # Vẫn cho phép click nút X
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        # Một số hệ Qt/OS cần hint này để không nhận focus
        try:
            self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        except Exception:
            pass

        self._timeout_ms = max(500, int(timeout_ms))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)

        self._build_ui(payload, width)

        # Start auto-close timer
        self._timer.start(self._timeout_ms)

    def _build_ui(self, payload: ToastPayload, width: int) -> None:
        self.setFixedWidth(int(width))

        self.setStyleSheet(
            """
            QFrame#ToastWidget {
                background-color: #1e1e1e;
                border: 1px solid #444444;
                border-radius: 8px;
            }
            QLabel {
                color: #dddddd;
            }
            QToolButton#ToastCloseBtn {
                border: none;
                color: #aaaaaa;
                padding: 0px;
            }
            QToolButton#ToastCloseBtn:hover {
                color: #ffffff;
            }
            """
        )

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.lbl = QLabel(self)
        self.lbl.setTextFormat(Qt.RichText)
        self.lbl.setWordWrap(True)

        f = QFont()
        f.setPointSize(10)
        self.lbl.setFont(f)

        name_html = (
            f"<span style='color:#ff4d4f; font-weight:800; font-size:14pt;'>"
            f"{payload.player_name}"
            f"</span>"
        )
        gold_html = (
            f"<span style='color:#fadb14; font-weight:800;'>"
            f"{_format_money(payload.gold)}"
            f"</span>"
        )

        # message_type: join | leave (reserved for future types)
        if (payload.message_type or "join") == "leave":
            html = (
                f"Khứa {name_html} "
                f"<span style='color:#dddddd;'>- (</span>{gold_html}"
                f"<span style='color:#dddddd;'>) đã ra khỏi phòng.</span>"
            )
        else:
            html = (
                f"Khứa {name_html} "
                f"<span style='color:#dddddd;'>- (</span>{gold_html}"
                f"<span style='color:#dddddd;'>) đã xin nộp.</span>"
            )

        self.lbl.setText(html)

        self.btn_close = QToolButton(self)
        self.btn_close.setObjectName("ToastCloseBtn")
        self.btn_close.setText("✕")
        self.btn_close.setToolTip("Đóng")
        self.btn_close.setFixedSize(16, 16)
        self.btn_close.clicked.connect(self.close)

        root.addWidget(self.lbl, 1)
        root.addWidget(self.btn_close, 0, Qt.AlignTop)

    def enterEvent(self, event) -> None:
        # Pause auto-close when hovering
        try:
            if self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        # Resume auto-close
        try:
            self._timer.start(self._timeout_ms)
        except Exception:
            pass
        super().leaveEvent(event)

    def closeEvent(self, event) -> None:
        try:
            if self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass
        try:
            self.closed.emit(self)
        except Exception:
            pass
        super().closeEvent(event)


class ToastManager(QObject):
    """
    Toast manager that stacks multiple toasts on top of a given parent window.
    (Overlay trong phạm vi cửa sổ anchor)
    """

    _sig_show = Signal(object)  # ToastPayload

    def __init__(
        self,
        anchor: QWidget,
        corner: str = "bottom_right",  # bottom_right / top_right
        timeout_ms: int = 5000,
        width: int = 360,
        gap: int = 10,
        margin: int = 16,
    ) -> None:
        super().__init__(anchor)
        self.anchor = anchor
        self.corner = corner
        self.timeout_ms = int(timeout_ms)
        self.width = int(width)
        self.gap = int(gap)
        self.margin = int(margin)

        self._toasts: List[ToastWidget] = []
        # Giới hạn số toast hiển thị đồng thời
        self.max_visible = 3
        self._sig_show.connect(self._on_show_payload)
        self.anchor.installEventFilter(self)

    def show_player_join(self, player_name: str, gold: Union[int, float, str]) -> None:
        payload = ToastPayload(player_name=player_name, gold=gold, message_type="join")
        self._on_show_payload(payload)

    def show_player_join_threadsafe(self, player_name: str, gold: Union[int, float, str]) -> None:
        payload = ToastPayload(player_name=player_name, gold=gold, message_type="join")
        self._sig_show.emit(payload)

    def show_player_left(self, player_name: str, gold: Union[int, float, str]) -> None:
        payload = ToastPayload(player_name=player_name, gold=gold, message_type="leave")
        self._on_show_payload(payload)

    def show_player_left_threadsafe(self, player_name: str, gold: Union[int, float, str]) -> None:
        payload = ToastPayload(player_name=player_name, gold=gold, message_type="leave")
        self._sig_show.emit(payload)

    def _on_show_payload(self, payload: ToastPayload) -> None:
        if self.anchor is None or not self.anchor.isVisible():
            return

        toast = ToastWidget(
            parent=self.anchor,
            payload=payload,
            timeout_ms=self.timeout_ms,
            width=self.width,
        )
        toast.closed.connect(self._on_toast_closed)

        self._toasts.insert(0, toast)
        toast.show()
        toast.raise_()

        # Giữ lại tối đa max_visible toast (mới nhất ở trên)
        self._enforce_limit()
        self._reposition()

    def _on_toast_closed(self, toast: ToastWidget) -> None:
        try:
            if toast in self._toasts:
                self._toasts.remove(toast)
        except Exception:
            pass
        self._reposition()

    def _enforce_limit(self) -> None:
        """
        Đảm bảo chỉ giữ lại tối đa max_visible toast.
        Các toast cũ hơn (ở cuối danh sách) sẽ tự đóng.
        """
        try:
            max_visible = int(getattr(self, "max_visible", 0) or 0)
        except Exception:
            max_visible = 0

        if max_visible <= 0:
            return

        if len(self._toasts) <= max_visible:
            return

        # Toast mới nhất nằm ở đầu danh sách (_toasts[0])
        # -> các toast dư nằm từ index max_visible trở đi
        extras = list(self._toasts[max_visible:])
        for t in extras:
            try:
                # close() sẽ gọi _on_toast_closed và tự remove + reposition
                t.close()
            except Exception:
                pass

    def _reposition(self) -> None:
        if not self._toasts or self.anchor is None:
            return

        rect = self.anchor.rect()
        if self.corner == "top_right":
            x = rect.width() - self.width - self.margin
            y = self.margin
            for t in self._toasts:
                t.move(QPoint(max(self.margin, x), y))
                y += t.height() + self.gap
        else:
            x = rect.width() - self.width - self.margin
            y = rect.height() - self.margin
            for t in self._toasts:
                y -= t.height()
                t.move(QPoint(max(self.margin, x), max(self.margin, y)))
                y -= self.gap

    def eventFilter(self, watched, event) -> bool:
        try:
            if watched is self.anchor and event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show):
                self._reposition()
        except Exception:
            pass
        return super().eventFilter(watched, event)


class DesktopToastManager(QObject):
    """
    Toast hiển thị theo tọa độ màn hình (desktop), luôn nổi góc phải dưới.
    Không phụ thuộc vào cửa sổ tool/tab nào.
    """

    _sig_show = Signal(object)  # ToastPayload

    def __init__(
        self,
        timeout_ms: int = 5000,
        width: int = 360,
        gap: int = 10,
        margin: int = 16,
    ) -> None:
        super().__init__(None)
        self.timeout_ms = int(timeout_ms)
        self.width = int(width)
        self.gap = int(gap)
        self.margin = int(margin)

        self._toasts: List[ToastWidget] = []
        # Giới hạn số toast hiển thị đồng thời
        self.max_visible = 3
        self._sig_show.connect(self._on_show_payload)

    def show_player_join(self, player_name: str, gold: Union[int, float, str]) -> None:
        payload = ToastPayload(player_name=player_name, gold=gold, message_type="join")
        self._on_show_payload(payload)

    def show_player_join_threadsafe(self, player_name: str, gold: Union[int, float, str]) -> None:
        payload = ToastPayload(player_name=player_name, gold=gold, message_type="join")
        self._sig_show.emit(payload)

    def show_player_left(self, player_name: str, gold: Union[int, float, str]) -> None:
        payload = ToastPayload(player_name=player_name, gold=gold, message_type="leave")
        self._on_show_payload(payload)

    def show_player_left_threadsafe(self, player_name: str, gold: Union[int, float, str]) -> None:
        payload = ToastPayload(player_name=player_name, gold=gold, message_type="leave")
        self._sig_show.emit(payload)

    def _screen_rect(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        # availableGeometry: loại trừ taskbar
        return screen.availableGeometry()

    def _on_show_payload(self, payload: ToastPayload) -> None:
        rect = self._screen_rect()
        if rect is None:
            return

        toast = ToastWidget(
            parent=None,  # TOP-LEVEL
            payload=payload,
            timeout_ms=self.timeout_ms,
            width=self.width,
        )
        toast.closed.connect(self._on_toast_closed)

        self._toasts.insert(0, toast)
        toast.show()
        toast.raise_()

        # Giữ lại tối đa max_visible toast
        self._enforce_limit()
        self._reposition()

    def _on_toast_closed(self, toast: ToastWidget) -> None:
        try:
            if toast in self._toasts:
                self._toasts.remove(toast)
        except Exception:
            pass
        self._reposition()
        
    def _enforce_limit(self) -> None:
        """
        Đảm bảo chỉ giữ lại tối đa max_visible toast trên desktop.
        """
        try:
            max_visible = int(getattr(self, "max_visible", 0) or 0)
        except Exception:
            max_visible = 0

        if max_visible <= 0:
            return
        if len(self._toasts) <= max_visible:
            return

        extras = list(self._toasts[max_visible:])
        for t in extras:
            try:
                t.close()
            except Exception:
                pass

    def _reposition(self) -> None:
        rect = self._screen_rect()
        if rect is None or not self._toasts:
            return

        x = rect.x() + rect.width() - self.width - self.margin
        y = rect.y() + rect.height() - self.margin

        for t in self._toasts:
            y -= t.height()
            t.move(QPoint(x, y))
            y -= self.gap
