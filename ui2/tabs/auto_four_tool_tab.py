"""
ui2/tabs/auto_four_tool_tab.py

Tab "Auto Play" quản lý 4 tool slot.
Layout 3 cột: [Sidebar 250px] | [Detail flexible] | [Activity 310px]

Tổng quan   → nhúng ctx.room_tab  (RoomControlTab đang hoạt động)
Chiến Thuật → nhúng ctx.strategy_tab (StrategyTab đang hoạt động)
"""
from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QStackedWidget, QFrame, QTextEdit,
    QSizePolicy, QSpinBox,
)

from core.logger import log

# ── Màu demo ──────────────────────────────────────────────────────
_BG     = "#0f1216"
_PANEL  = "#171b20"
_PANEL2 = "#1d2229"
_PANEL3 = "#12161b"
_LINE   = "#303741"
_LINE2  = "#242a32"
_TEXT   = "#edf1f5"
_MUTED  = "#929ca8"
_GREEN  = "#2fb171"
_GREEN2 = "#1e704b"
_BLUE   = "#4e8bd9"
_AMBER  = "#e3a53b"
_RED    = "#dc5b62"


def _lbl(text: str, style: str = "") -> QLabel:
    w = QLabel(text)
    if style:
        w.setStyleSheet(style)
    return w


def _circle(size: int, color: str) -> QLabel:
    """QLabel hình tròn thuần CSS — thay thế QLabel('●')."""
    w = QLabel()
    w.setFixedSize(size, size)
    r = size // 2
    w.setStyleSheet(f"background:{color}; border-radius:{r}px;")
    return w


# ═══════════════════════════════════════════════════════════════════
# ToggleSwitch — iOS-style toggle khớp demo HTML (.switch)
# ═══════════════════════════════════════════════════════════════════

class ToggleSwitch(QWidget):
    """Toggle switch vẽ bằng paintEvent — knob di chuyển trái/phải."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._on = False
        self.setFixedSize(32, 17)
        self.setCursor(Qt.PointingHandCursor)

    def setChecked(self, v: bool):
        if self._on != v:
            self._on = v
            self.update()

    def isChecked(self) -> bool:
        return self._on

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, _event):
        from PySide6.QtGui import QPainter, QColor, QPen, QBrush
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2

        if self._on:
            track_c  = QColor("#174f38")
            border_c = QColor("#2fb171")
            knob_c   = QColor("#68d6a0")
            knob_x   = w - h + 2
        else:
            track_c  = QColor("#242a31")
            border_c = QColor("#4a535e")
            knob_c   = QColor("#87919d")
            knob_x   = 2

        pen = QPen(border_c)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(QBrush(track_c))
        p.drawRoundedRect(0.5, 0.5, w - 1, h - 1, r, r)

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(knob_c))
        ks = h - 4
        p.drawEllipse(knob_x, 2, ks, ks)
        p.end()


# ═══════════════════════════════════════════════════════════════════
# ToolSlotCard — card sidebar
# ═══════════════════════════════════════════════════════════════════

class ToolSlotCard(QFrame):
    """Card 1 tool trong sidebar. Click body = chọn, click switch = toggle bridge."""

    selected_changed = Signal(int)   # slot
    toggle_requested = Signal(int)   # slot

    _COL_OFF  = "#69737e"
    _COL_RUN  = "#2fb171"
    _COL_WAIT = "#e3a53b"
    _COL_ERR  = "#dc5b62"

    def __init__(self, slot: int, parent=None):
        super().__init__(parent)
        self.slot = slot
        self._selected = False
        self._running = False
        self._p_dots: dict[str, QLabel] = {}
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(90)
        self.setCursor(Qt.PointingHandCursor)
        self._build()
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(9, 9, 9, 9)
        root.setSpacing(6)

        # Row 1: dot(8px) + name + toggle switch
        top = QHBoxLayout()
        top.setSpacing(7)

        self._dot = _circle(8, self._COL_OFF)

        self._lbl_name = QLabel(f"Tool {self.slot}")
        f = QFont(); f.setBold(True); f.setPointSize(10)
        self._lbl_name.setFont(f)
        self._lbl_name.setStyleSheet(f"color:{_TEXT};")

        self._switch = ToggleSwitch(self)
        self._switch.clicked.connect(lambda: self.toggle_requested.emit(self.slot))

        top.addWidget(self._dot)
        top.addWidget(self._lbl_name, 1)
        top.addWidget(self._switch)

        # Row 2: meta
        self._lbl_meta = QLabel("Chưa khởi động")
        self._lbl_meta.setStyleSheet(
            f"color:{_MUTED}; font-size:11px;"
            " white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"
        )

        # Row 3: mini P1/P2/P3  — label bên trái, dot 5px bên phải
        grid_row = QHBoxLayout()
        grid_row.setSpacing(4)
        for pid in ("P1", "P2", "P3"):
            cell = QWidget()
            cell.setFixedHeight(26)
            cell.setStyleSheet(
                f"background:{_PANEL3}; border:1px solid {_LINE2}; border-radius:3px;"
            )
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(5, 2, 5, 2)
            cl.setSpacing(0)
            plbl = QLabel(pid)
            plbl.setStyleSheet("color:#b9c1ca; font-size:10px; font-weight:800;")
            dot_p = _circle(5, self._COL_OFF)
            cl.addWidget(plbl)
            cl.addStretch()
            cl.addWidget(dot_p)
            self._p_dots[pid] = dot_p
            grid_row.addWidget(cell)
        grid_row.addStretch()

        root.addLayout(top)
        root.addWidget(self._lbl_meta)
        root.addLayout(grid_row)

    def set_selected(self, v: bool):
        self._selected = v
        self._refresh()

    def set_running(self, v: bool):
        self._running = v
        self._switch.setChecked(v)
        self._refresh()

    def set_meta(self, text: str):
        self._lbl_meta.setText(text)

    def set_profile_status(self, pid: str, status: str):
        dot = self._p_dots.get(pid)
        if not dot:
            return
        color = {
            "run":  self._COL_RUN,
            "wait": self._COL_WAIT,
            "err":  self._COL_ERR,
        }.get(status, self._COL_OFF)
        dot.setStyleSheet(f"background:{color}; border-radius:2px;")

    def _refresh(self):
        # Dot trạng thái (circle thuần màu)
        col = self._COL_RUN if self._running else self._COL_OFF
        self._dot.setStyleSheet(f"background:{col}; border-radius:4px;")

        # Card border: active = sọc xanh bên trái + bg sáng hơn
        # Dùng QFrame selector để không ảnh hưởng child widgets
        if self._selected:
            self.setStyleSheet(
                f"ToolSlotCard {{"
                f"border-top:1px solid {_BLUE};"
                f"border-right:1px solid {_BLUE};"
                f"border-bottom:1px solid {_BLUE};"
                f"border-left:3px solid {_BLUE};"
                f"border-radius:5px; background:#1b2633;"
                f"}}"
            )
        else:
            self.setStyleSheet(
                f"ToolSlotCard {{"
                f"border:1px solid {_LINE}; border-radius:5px; background:{_PANEL};"
                f"}}"
            )

    def mousePressEvent(self, event):
        self.selected_changed.emit(self.slot)
        super().mousePressEvent(event)


# ═══════════════════════════════════════════════════════════════════
# AutoFourToolTab — tab chính
# ═══════════════════════════════════════════════════════════════════

class AutoFourToolTab(QWidget):
    """Tab quản lý 4 tool auto play — layout khớp demo HTML."""

    # Signal thread-safe: background thread emit → _log chạy trên UI thread
    _bg_log = Signal(int, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{_BG}; color:{_TEXT};")

        self._contexts: List = []
        self._current_slot = 1
        self._cards: List[ToolSlotCard] = []
        self._overview_stack  = QStackedWidget()
        self._strategy_stack  = QStackedWidget()
        self._browser_stack   = QStackedWidget()
        self._log_html: List[str] = []

        # Log filter: "sel" | "all" | "err"
        self._log_filter = "sel"

        self._bg_log.connect(self._log)
        self._init_tool_contexts()
        self._start_slot_bridges()

        try:
            self._build_ui()
            self._select_slot(1)
        except Exception:
            log.exception("[AutoFourToolTab] _build_ui lỗi")
            err = QLabel("Lỗi khởi tạo — xem log console")
            err.setStyleSheet(f"color:{_RED}; padding:20px;")
            QVBoxLayout(self).addWidget(err)
            return

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_tool_events)
        self._poll_timer.start()

    # ── Init contexts ──────────────────────────────────────────────

    def _init_tool_contexts(self):
        from core.config import ensure_slot_configs
        from core.tool_context import ToolContext
        ensure_slot_configs()
        for slot in range(1, 5):
            try:
                # Mỗi slot có WSCardStore riêng — KHÔNG chia sẻ global_cs.
                # Slot 1 nhận event qua relay từ main.py._handle_bridge_event.
                # Slots 2-4 nhận event qua per-tool bridge riêng.
                # Tránh double-processing: nếu slot 1 dùng global_cs,
                # cả 2 strategy_tab (main.py + ctx) cùng poll global_cs → double compute.
                ctx = ToolContext(slot, card_store=None)
                ctx.build_widgets(parent=self)
                self._contexts.append(ctx)
            except Exception:
                log.exception("[AutoFourToolTab] ToolContext slot=%d lỗi", slot)
                self._contexts.append(None)

    def _start_slot_bridges(self):
        """Khởi động WS bridge cho slot 2-4 ngay khi tab init.

        Bridge phải luôn chạy khi browser mở, bất kể auto play có bật hay không,
        vì extension cần fetch proxy-creds từ bridge ngay khi onAuthRequired.
        Slot 1 do main.py quản lý, không cần start ở đây.
        """
        for slot in range(2, 5):
            ctx = self._contexts[slot - 1]
            if ctx is None:
                continue
            if ctx._ws_server is not None:
                continue
            try:
                ctx.start()
                log.info("[AutoFourToolTab] bridge slot=%d started (eager)", slot)
            except OSError as e:
                log.warning("[AutoFourToolTab] bridge slot=%d port busy: %s", slot, e)

    # ── Build UI ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        body = QSplitter(Qt.Horizontal)
        body.setHandleWidth(1)
        body.setStyleSheet(f"QSplitter::handle {{ background:{_LINE}; }}")

        sidebar = self._build_sidebar()
        sidebar.setFixedWidth(250)
        body.addWidget(sidebar)
        body.addWidget(self._build_detail())
        body.addWidget(self._build_activity())

        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)

        root.addWidget(body, 1)

    # ── Topbar ─────────────────────────────────────────────────────

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background:#15191e; border-bottom:1px solid {_LINE};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        brand = QLabel("MB CONTROL")
        brand.setStyleSheet(f"color:{_TEXT}; font-size:14px; font-weight:900;")
        lay.addWidget(brand)
        tag = QLabel("/ AUTO PLAY")
        tag.setStyleSheet(f"color:{_GREEN}; font-size:14px; font-weight:900;")
        lay.addWidget(tag)

        sep = QFrame(); sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color:{_LINE};"); lay.addWidget(sep)

        lay.addWidget(_lbl("Số ván", f"color:{_MUTED};"))
        self._spn_rounds = QSpinBox()
        self._spn_rounds.setRange(1, 9999); self._spn_rounds.setValue(999)
        self._spn_rounds.setFixedWidth(68)
        self._spn_rounds.setStyleSheet(
            f"QSpinBox {{ background:{_PANEL3}; color:{_TEXT}; border:1px solid {_LINE};"
            " border-radius:4px; padding:0 4px; height:28px; }}"
        )
        lay.addWidget(self._spn_rounds)

        lay.addWidget(_lbl("Delay", f"color:{_MUTED};"))
        spn_style = self._spn_rounds.styleSheet()
        self._spn_dmin = QSpinBox()
        self._spn_dmin.setRange(0, 120); self._spn_dmin.setValue(5)
        self._spn_dmin.setFixedWidth(52)
        self._spn_dmin.setStyleSheet(spn_style)
        self._spn_dmax = QSpinBox()
        self._spn_dmax.setRange(0, 120); self._spn_dmax.setValue(10)
        self._spn_dmax.setFixedWidth(52)
        self._spn_dmax.setStyleSheet(spn_style)
        lay.addWidget(self._spn_dmin)
        lay.addWidget(_lbl("–", f"color:{_MUTED};"))
        lay.addWidget(self._spn_dmax)
        lay.addWidget(_lbl("giây", f"color:{_MUTED};"))

        lay.addStretch()

        self._btn_start_all = self._topbtn("Chạy tất cả", _GREEN2, _GREEN)
        self._btn_stop_all  = self._topbtn("Dừng tất cả", "#532e32", "#98444b")
        self._btn_start_all.clicked.connect(self.start_all)
        self._btn_stop_all.clicked.connect(self.stop_all)
        lay.addWidget(self._btn_start_all)
        lay.addWidget(self._btn_stop_all)
        return bar

    def _topbtn(self, text: str, bg: str, border: str) -> QPushButton:
        b = QPushButton(text)
        b.setFixedHeight(30)
        b.setStyleSheet(
            f"QPushButton {{ background:{bg}; color:#fff; border:1px solid {border};"
            " border-radius:4px; padding:0 12px; font-weight:700; }}"
        )
        return b

    # ── Sidebar ────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        frame = QWidget()
        frame.setStyleSheet(f"background:#12161a; border-right:1px solid {_LINE};")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(7)

        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("Danh sách Tool", f"color:{_TEXT}; font-weight:800;"))
        hdr.addStretch()
        hdr.addWidget(_lbl("4 cụm / 12P", f"color:{_MUTED}; font-size:11px;"))
        lay.addLayout(hdr)

        for slot in range(1, 5):
            card = ToolSlotCard(slot, self)
            card.selected_changed.connect(self._select_slot)
            card.toggle_requested.connect(self._on_toggle)
            self._cards.append(card)
            lay.addWidget(card)

        lay.addStretch()

        # System health footer
        foot = QWidget()
        foot.setStyleSheet(
            f"background:{_PANEL}; border:1px solid {_LINE}; border-radius:5px;"
        )
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(9, 8, 9, 8)
        fl.setSpacing(4)

        fh = QHBoxLayout()
        fh.addWidget(_lbl("Sức khoẻ hệ thống", f"color:{_TEXT}; font-weight:800;"))
        fh.addStretch()
        health_tag = _lbl("Ổn định",
            f"background:#183b2d; color:#86e0b2;"
            f" border:1px solid #32664f; border-radius:3px;"
            f" padding:2px 5px; font-size:11px;")
        fh.addWidget(health_tag)
        fl.addLayout(fh)
        fl.addWidget(_lbl("Hệ thống: 4/4 sẵn sàng", f"color:{_TEXT}; font-size:11px;"))
        fl.addWidget(_lbl("Profiles: 12 hồ sơ", f"color:{_MUTED}; font-size:11px;"))
        lay.addWidget(foot)
        return frame

    # ── Detail panel ───────────────────────────────────────────────

    def _build_detail(self) -> QWidget:
        frame = QWidget()
        frame.setStyleSheet(f"background:{_BG};")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header row
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{_BG}; border-bottom:1px solid {_LINE};")
        hdr.setFixedHeight(62)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 8, 10, 8)
        hl.setSpacing(10)

        # Left: dot + title + badge + sub
        info_col = QVBoxLayout(); info_col.setSpacing(3)
        top_row = QHBoxLayout(); top_row.setSpacing(8)
        self._hdr_dot   = _lbl("●", f"color:{_GREEN}; font-size:10px;")
        self._hdr_title = _lbl("Tool 1", f"color:{_TEXT}; font-size:17px; font-weight:900;")
        self._hdr_badge = _lbl("Chưa khởi động",
            f"background:{_PANEL2}; color:{_MUTED}; border:1px solid {_LINE};"
            " border-radius:4px; padding:3px 7px; font-weight:700; font-size:11px;")
        top_row.addWidget(self._hdr_dot)
        top_row.addWidget(self._hdr_title)
        top_row.addWidget(self._hdr_badge)
        top_row.addStretch()
        self._hdr_sub = _lbl("Chọn tool để xem chi tiết",
            f"color:{_MUTED}; font-size:11px;")
        info_col.addLayout(top_row)
        info_col.addWidget(self._hdr_sub)

        # Right: 5 action buttons (khớp demo)
        act_row = QHBoxLayout(); act_row.setSpacing(6)
        self._btn_open_browsers  = self._detailbtn("Mở 3 trình duyệt",  "#343b45")
        self._btn_reconnect_all  = self._detailbtn("Kết nối lại ALL",    "#254c7d", _BLUE)
        self._btn_reset_proxy    = self._detailbtn("Reset Proxy ALL",    "#5d4218", _AMBER)
        self._btn_clear_profiles = self._detailbtn("Xoá ALL Profile",    "#622b31", _RED)
        self._btn_open_browsers.clicked.connect(self._on_open_browsers)
        self._btn_reconnect_all.clicked.connect(self._on_reconnect_all)
        self._btn_reset_proxy.clicked.connect(self._on_reset_proxy)
        self._btn_clear_profiles.clicked.connect(self._on_clear_profiles)
        for b in (self._btn_open_browsers, self._btn_reconnect_all,
                  self._btn_reset_proxy, self._btn_clear_profiles):
            act_row.addWidget(b)

        hl.addLayout(info_col, 1)
        hl.addLayout(act_row)
        lay.addWidget(hdr)

        # Inner tab bar (2 tabs — khớp demo)
        tab_bar = QWidget()
        tab_bar.setFixedHeight(36)
        tab_bar.setStyleSheet(f"background:#13171c; border-bottom:1px solid {_LINE};")
        tbl = QHBoxLayout(tab_bar)
        tbl.setContentsMargins(10, 0, 10, 0)
        tbl.setSpacing(0)
        self._btn_overview  = self._innertab("Phòng",   True)
        self._btn_strategy  = self._innertab("Chiến Thuật", False)
        self._btn_browser   = self._innertab("Trình duyệt", False)
        self._btn_overview.clicked.connect(lambda: self._switch_inner(0))
        self._btn_strategy.clicked.connect(lambda: self._switch_inner(1))
        self._btn_browser.clicked.connect(lambda:  self._switch_inner(2))
        tbl.addWidget(self._btn_overview)
        tbl.addWidget(self._btn_strategy)
        tbl.addWidget(self._btn_browser)
        tbl.addStretch()

        # Quick exit room: P1/P2/P3 toggle + button (right side of tab bar)
        _toggle_style = (
            "QPushButton { background:#1d2229; color:#697581; border:1px solid #2e3740;"
            " border-radius:3px; padding:0 7px; font-weight:700; font-size:11px; }"
            f"QPushButton:checked {{ background:{_BLUE}; color:#fff; border-color:{_BLUE}; }}"
            "QPushButton:pressed { opacity:0.85; }"
        )
        self._chk_exit_p1 = QPushButton("P1"); self._chk_exit_p1.setCheckable(True); self._chk_exit_p1.setChecked(True)
        self._chk_exit_p2 = QPushButton("P2"); self._chk_exit_p2.setCheckable(True); self._chk_exit_p2.setChecked(True)
        self._chk_exit_p3 = QPushButton("P3"); self._chk_exit_p3.setCheckable(True); self._chk_exit_p3.setChecked(True)
        for tog in (self._chk_exit_p1, self._chk_exit_p2, self._chk_exit_p3):
            tog.setFixedHeight(22)
            tog.setStyleSheet(_toggle_style)
            tbl.addWidget(tog)
        tbl.addSpacing(6)
        self._btn_exit_room = QPushButton("Thoát Phòng")
        self._btn_exit_room.setFixedHeight(22)
        self._btn_exit_room.setStyleSheet(
            "QPushButton { background:#622b31; color:#fff; border:1px solid #a04040;"
            " border-radius:3px; padding:0 9px; font-weight:700; font-size:11px; }"
            "QPushButton:pressed { background:#7a3540; }"
        )
        self._btn_exit_room.clicked.connect(self._on_quick_exit_room)
        tbl.addWidget(self._btn_exit_room)
        tbl.addSpacing(6)

        lay.addWidget(tab_bar)

        # Stacked panes
        self._inner_stack = QStackedWidget()
        self._inner_stack.setStyleSheet(f"background:{_BG};")

        # Pane 0: Tổng quan = ctx.room_tab (RoomControlTab)
        self._inner_stack.addWidget(self._overview_stack)
        self._build_overview_pages()

        # Pane 1: Chiến Thuật = ctx.strategy_tab (StrategyTab)
        self._inner_stack.addWidget(self._strategy_stack)
        self._build_strategy_pages()

        # Pane 2: Trình duyệt = ctx.profiles_tab (ProfilesTabV2)
        self._inner_stack.addWidget(self._browser_stack)
        self._build_browser_pages()

        lay.addWidget(self._inner_stack, 1)
        return frame

    def _detailbtn(self, text: str, bg: str, border: str = "transparent") -> QPushButton:
        b = QPushButton(text)
        b.setFixedHeight(29)
        b.setStyleSheet(
            f"QPushButton {{ background:{bg}; color:#fff; border:1px solid {border};"
            " border-radius:4px; padding:0 9px; font-weight:700; }}"
            f"QPushButton:pressed {{ background:{bg}; opacity:0.8; }}"
        )
        return b

    def _innertab(self, text: str, active: bool) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.setChecked(active)
        b.setFixedHeight(36)
        b.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_MUTED}; border:none;"
            f" border-bottom:2px solid transparent; padding:0 14px;"
            f" font-weight:700; font-size:12px; margin-bottom:-1px; }}"
            f"QPushButton:checked {{ color:{_TEXT}; border-bottom-color:{_BLUE}; }}"
        )
        return b

    # ── Pane builders ──────────────────────────────────────────────

    def _build_overview_pages(self):
        """Pane Tổng quan = nhúng ctx.room_tab (RoomControlTab đang hoạt động)."""
        for slot in range(1, 5):
            ctx = self._contexts[slot - 1]
            if ctx is not None and ctx.room_tab is not None:
                self._overview_stack.addWidget(ctx.room_tab)
            else:
                ph = QLabel(f"Room Tool {slot} — lỗi khởi tạo")
                ph.setAlignment(Qt.AlignCenter)
                ph.setStyleSheet(f"color:{_MUTED};")
                self._overview_stack.addWidget(ph)

    def _build_strategy_pages(self):
        """Pane Chiến Thuật = nhúng ctx.strategy_tab (StrategyTab đang hoạt động)."""
        for slot in range(1, 5):
            ctx = self._contexts[slot - 1]
            if ctx is not None and ctx.strategy_tab is not None:
                self._strategy_stack.addWidget(ctx.strategy_tab)
            else:
                ph = QLabel(f"Chiến Thuật Tool {slot} — lỗi khởi tạo")
                ph.setAlignment(Qt.AlignCenter)
                ph.setStyleSheet(f"color:{_MUTED};")
                self._strategy_stack.addWidget(ph)

    def _build_browser_pages(self):
        """Pane Trình duyệt = nhúng ctx.profiles_tab (ProfilesTabV2 per-slot)."""
        from PySide6.QtWidgets import QScrollArea
        for slot in range(1, 5):
            ctx = self._contexts[slot - 1]
            if ctx is not None and ctx.profiles_tab is not None:
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QScrollArea.NoFrame)
                scroll.setWidget(ctx.profiles_tab)
                self._browser_stack.addWidget(scroll)
            else:
                ph = QLabel(f"Trình duyệt Tool {slot} — lỗi khởi tạo")
                ph.setAlignment(Qt.AlignCenter)
                ph.setStyleSheet(f"color:{_MUTED};")
                self._browser_stack.addWidget(ph)

    # ── Activity log ───────────────────────────────────────────────

    def _build_activity(self) -> QWidget:
        frame = QWidget()
        frame.setFixedWidth(310)
        frame.setStyleSheet(f"background:#12161a; border-left:1px solid {_LINE};")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header
        ah = QWidget()
        ah.setStyleSheet(f"background:#12161a; border-bottom:1px solid {_LINE};")
        ahl = QVBoxLayout(ah)
        ahl.setContentsMargins(10, 8, 10, 8)
        ahl.setSpacing(6)

        hrow = QHBoxLayout()
        hrow.addWidget(_lbl("Hoạt động", f"color:{_TEXT}; font-weight:800;"))
        hrow.addStretch()
        btn_clr = QPushButton("Xoá log")
        btn_clr.setFixedHeight(24)
        btn_clr.setStyleSheet(
            f"QPushButton {{ background:{_PANEL2}; color:{_MUTED}; border:1px solid {_LINE};"
            " border-radius:4px; padding:0 8px; font-size:11px; }}"
        )
        btn_clr.clicked.connect(self._clear_log)
        hrow.addWidget(btn_clr)
        ahl.addLayout(hrow)

        # 3 sub-tabs (khớp demo)
        tabs_row = QHBoxLayout(); tabs_row.setSpacing(4)
        self._btn_log_sel = self._logtab("Tool đang chọn", True)
        self._btn_log_all = self._logtab("Tất cả", False)
        self._btn_log_err = self._logtab("Chỉ lỗi", False)
        self._btn_log_sel.clicked.connect(lambda: self._switch_log_filter("sel"))
        self._btn_log_all.clicked.connect(lambda: self._switch_log_filter("all"))
        self._btn_log_err.clicked.connect(lambda: self._switch_log_filter("err"))
        for b in (self._btn_log_sel, self._btn_log_all, self._btn_log_err):
            tabs_row.addWidget(b)
        ahl.addLayout(tabs_row)
        lay.addWidget(ah)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet(
            f"QTextEdit {{ background:#12161a; color:#bbc4cd; border:none;"
            " font-size:11px; font-family:'Segoe UI',Arial,sans-serif; padding:4px 8px; }}"
        )
        lay.addWidget(self._log_view, 1)
        return frame

    def _logtab(self, text: str, active: bool) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True); b.setChecked(active)
        b.setFixedHeight(26)
        b.setStyleSheet(
            f"QPushButton {{ background:{_PANEL}; color:{_MUTED};"
            f" border:1px solid {_LINE}; border-radius:4px; padding:0 8px; font-size:11px; }}"
            f"QPushButton:checked {{ background:#253343; color:#e5edf5;"
            f" border-color:#46627e; }}"
        )
        return b

    # ── Switch inner tab ───────────────────────────────────────────

    def _switch_inner(self, idx: int):
        self._inner_stack.setCurrentIndex(idx)
        self._btn_overview.setChecked(idx == 0)
        self._btn_strategy.setChecked(idx == 1)
        self._btn_browser.setChecked(idx == 2)

    def _switch_log_filter(self, f: str):
        self._log_filter = f
        self._btn_log_sel.setChecked(f == "sel")
        self._btn_log_all.setChecked(f == "all")
        self._btn_log_err.setChecked(f == "err")
        self._redraw_log()

    # ── Select tool ────────────────────────────────────────────────

    def _select_slot(self, slot: int):
        self._current_slot = slot
        idx = slot - 1
        for card in self._cards:
            card.set_selected(card.slot == slot)
        self._overview_stack.setCurrentIndex(idx)
        self._strategy_stack.setCurrentIndex(idx)
        self._browser_stack.setCurrentIndex(idx)

        ctx = self._contexts[idx]
        running = self._cards[idx]._running
        self._hdr_title.setText(f"Tool {slot}")
        self._hdr_dot.setStyleSheet(
            f"color:{'#2fb171' if running else '#69737e'}; font-size:10px;"
        )
        if running:
            self._hdr_badge.setText("Đang chạy")
            self._hdr_badge.setStyleSheet(
                "background:#173b2c; color:#86e0b2; border:1px solid #32664f;"
                " border-radius:4px; padding:3px 7px; font-weight:700; font-size:11px;"
            )
        else:
            self._hdr_badge.setText("Chưa khởi động")
            self._hdr_badge.setStyleSheet(
                f"background:{_PANEL2}; color:{_MUTED}; border:1px solid {_LINE};"
                " border-radius:4px; padding:3px 7px; font-weight:700; font-size:11px;"
            )
        tool_idx = ctx.tool_index if ctx else slot
        cfg_file = "config.json" if slot == 1 else f"config-tool{slot}.json"
        self._hdr_sub.setText(
            f"Tool index {tool_idx} — {cfg_file} — bridge port {9526 + tool_idx}"
        )
        # Cập nhật log display theo filter
        self._redraw_log()

    # ── Toggle bridge ──────────────────────────────────────────────

    def _on_toggle(self, slot: int):
        if self._cards[slot - 1]._running:
            self.stop_tool(slot)
        else:
            self.start_tool(slot)
        if self._current_slot == slot:
            self._select_slot(slot)

    def _get_auto_params(self):
        """Lấy rounds + delay từ topbar spinboxes."""
        rounds = int(self._spn_rounds.value())
        dmin = int(self._spn_dmin.value()) * 1000
        dmax = int(self._spn_dmax.value()) * 1000
        return rounds, min(dmin, dmax), max(dmin, dmax)

    def _ensure_bridge(self, slot: int) -> bool:
        """Start bridge cho slot (nếu chưa chạy). Trả về True nếu OK."""
        if slot == 1:
            return True  # bridge main.py luôn chạy
        ctx = self._contexts[slot - 1]
        if ctx is None:
            self._log(slot, "Context lỗi, không start bridge", "err")
            return False
        if ctx._ws_server is not None:
            return True  # bridge đã đang chạy
        try:
            ctx.start()
            return True
        except OSError as e:
            self._cards[slot - 1].set_meta("Lỗi port")
            self._log(slot, f"Lỗi start bridge: {e}", "err")
            return False

    def start_tool(self, slot: int):
        ctx = self._contexts[slot - 1]
        rounds, delay_min, delay_max = self._get_auto_params()

        if not self._ensure_bridge(slot):
            return

        # Bật auto play trên strategy_tab của slot này
        if ctx is not None and ctx.strategy_tab is not None:
            ctx.strategy_tab.set_auto_play(True, rounds, delay_min, delay_max)

        self._cards[slot - 1].set_running(True)
        self._cards[slot - 1].set_meta(f"Auto Play: {rounds} ván")
        self._log(slot, f"Auto Play BẬT — {rounds} ván, delay {delay_min//1000}-{delay_max//1000}s", "ok")

    def stop_tool(self, slot: int):
        ctx = self._contexts[slot - 1]

        # Tắt auto play trên strategy_tab
        if ctx is not None and ctx.strategy_tab is not None:
            ctx.strategy_tab.set_auto_play(False)

        # Không dừng bridge khi tắt auto play — bridge phải chạy liên tục để
        # extension vẫn fetch được proxy-creds khi browser đang mở.

        self._cards[slot - 1].set_running(False)
        self._cards[slot - 1].set_meta("Auto Play: tắt")
        self._log(slot, "Auto Play ĐÃ TẮT", "warn")

    def start_all(self):
        for slot in range(1, 5):
            self.start_tool(slot)

    def stop_all(self):
        for slot in range(1, 5):
            self.stop_tool(slot)

    # ── Action button handlers ─────────────────────────────────────

    def _on_open_browsers(self):
        slot = self._current_slot
        ctx = self._contexts[slot - 1]
        if ctx is None:
            return

        # Extension fetch proxy-creds từ bridge ngay khi load.
        # Nếu bridge chưa start thì fetch sẽ fail → không có proxy.
        if not self._ensure_bridge(slot):
            self._log(slot, "Bridge không start được, extension sẽ không kết nối được!", "err")
            return

        self._log(slot, "Đang mở 3 trình duyệt...", "info")

        def _work():
            for pid in ("P1", "P2", "P3"):
                try:
                    ctx.browser_manager.open_browser(pid)
                    self._bg_log.emit(slot, f"{pid}: trình duyệt đã mở", "ok")
                except Exception as e:
                    self._bg_log.emit(slot, f"Lỗi mở browser {pid}: {e}", "err")

        threading.Thread(target=_work, daemon=True, name=f"open-browsers-slot{slot}").start()

    def _on_reconnect_all(self):
        slot = self._current_slot
        ctx = self._contexts[slot - 1]
        if ctx is None:
            self._log(slot, "Không có context", "err")
            return
        self._log(slot, "Đang kết nối lại DevTools P1/P2/P3...", "info")

        def _work():
            for pid in ("P1", "P2", "P3"):
                try:
                    ctx.browser_manager._clear_cached_browser_state(pid)
                    ctx.browser_manager.ensure_tab(pid)
                    self._bg_log.emit(slot, f"{pid}: kết nối lại DevTools OK", "ok")
                except Exception as e:
                    self._bg_log.emit(slot, f"{pid}: lỗi kết nối lại: {e}", "err")

        threading.Thread(target=_work, daemon=True, name=f"reconnect-slot{slot}").start()

    def _on_quick_exit_room(self):
        slot = self._current_slot
        ctx = self._contexts[slot - 1]
        if ctx is None or ctx.gateway is None:
            self._log(slot, "Không có gateway để thoát phòng", "err")
            return
        pids = []
        if self._chk_exit_p1.isChecked(): pids.append("P1")
        if self._chk_exit_p2.isChecked(): pids.append("P2")
        if self._chk_exit_p3.isChecked(): pids.append("P3")
        if not pids:
            self._log(slot, "Chưa chọn profile để thoát phòng", "warn")
            return
        for pid in pids:
            try:
                ctx.gateway.gui_lenh_thoat_phong(pid)
                self._log(slot, f"Đã gửi lệnh thoát phòng → {pid}", "ok")
            except Exception as e:
                self._log(slot, f"Lỗi thoát phòng {pid}: {e}", "err")

    def _on_reset_proxy(self):
        slot = self._current_slot
        ctx = self._contexts[slot - 1]
        if ctx is None:
            self._log(slot, "Không có context", "err")
            return
        self._log(slot, "Đang đổi IP proxy P1/P2/P3...", "info")

        def _work():
            from core.proxyno1_provider import proxyno1_change_ip_for_profile
            for pid in ("P1", "P2", "P3"):
                try:
                    ok, msg = proxyno1_change_ip_for_profile(pid, slot=slot)
                    level = "ok" if ok else "err"
                    self._bg_log.emit(slot, f"{pid}: {msg}", level)
                except Exception as e:
                    self._bg_log.emit(slot, f"{pid}: lỗi reset proxy: {e}", "err")

        threading.Thread(target=_work, daemon=True, name=f"reset-proxy-slot{slot}").start()

    def _on_clear_profiles(self):
        slot = self._current_slot
        ctx = self._contexts[slot - 1]
        if ctx is None:
            self._log(slot, "Không có context", "err")
            return
        from PySide6.QtWidgets import QMessageBox
        resp = QMessageBox.question(
            self,
            "Xác nhận xoá Profile",
            f"Xoá toàn bộ dữ liệu runtime (P1/P2/P3) của Tool {slot}?\n"
            "Trình duyệt sẽ bị đóng. Hành động này không thể hoàn tác.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        self._log(slot, "Đang xoá profile runtime P1/P2/P3...", "warn")

        def _work():
            for pid in ("P1", "P2", "P3"):
                try:
                    ok = ctx.browser_manager.delete_profile_user_data(pid)
                    if ok:
                        self._bg_log.emit(slot, f"{pid}: đã xoá profile runtime", "warn")
                    else:
                        self._bg_log.emit(slot, f"{pid}: xoá thất bại (browser còn sống?)", "err")
                except Exception as e:
                    self._bg_log.emit(slot, f"{pid}: lỗi xoá: {e}", "err")

        threading.Thread(target=_work, daemon=True, name=f"clear-profiles-slot{slot}").start()

    # ── Event polling ──────────────────────────────────────────────

    def _poll_tool_events(self):
        # Slot 1: main.py relay event vào ctx.event_queue (xem _handle_bridge_event).
        # Slot 2-4: per-tool bridge tự push event vào ctx.event_queue.
        for ctx in self._contexts:
            if ctx is None:
                continue
            n = 0
            while n < 30:
                try:
                    evt = ctx.event_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    ctx.dispatch_event(evt)
                except Exception:
                    log.exception("[AutoFourToolTab] dispatch slot=%d", ctx.slot)
                n += 1

    # ── Log ────────────────────────────────────────────────────────

    _LOG_COLORS = {"ok": _GREEN, "warn": _AMBER, "err": _RED, "info": "#66727f"}

    def _log(self, slot: int, msg: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        dot = self._LOG_COLORS.get(level, "#66727f")
        row = {
            "slot": slot, "level": level, "ts": ts,
            "html": (
                f'<div style="padding:6px 3px 6px 18px;border-bottom:1px solid {_LINE2};'
                f'color:#bbc4cd;position:relative;">'
                f'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;'
                f'background:{dot};margin-right:6px;vertical-align:middle;"></span>'
                f'<span style="color:#697581;">[{ts}]</span> '
                f'<b style="color:{_TEXT};">[T{slot}]</b> {msg}</div>'
            )
        }
        self._log_html.append(row)
        if len(self._log_html) > 500:
            self._log_html = self._log_html[-400:]
        self._redraw_log()

    def _redraw_log(self):
        f = self._log_filter
        sel = self._current_slot
        rows = []
        for r in self._log_html:
            if f == "sel" and r["slot"] != sel and r["slot"] != 0:
                continue
            if f == "err" and r["level"] not in ("err", "warn"):
                continue
            rows.append(r["html"])
        self._log_view.setHtml(
            f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:11px;">'
            + "".join(rows) + "</div>"
        )
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_log(self):
        self._log_html.clear()
        self._log_view.clear()

    def log_from_context(self, slot: int, msg: str, level: str = "info"):
        self._log(slot, msg, level)
