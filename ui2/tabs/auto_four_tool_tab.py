"""
ui2/tabs/auto_four_tool_tab.py

Tab "Auto Play" quản lý nhiều tool slot.
Layout 3 cột: [Sidebar 250px] | [Detail flexible] | [Activity 310px]

Tổng quan   → nhúng ctx.room_tab  (RoomControlTab đang hoạt động)
Chiến Thuật → nhúng ctx.strategy_tab (StrategyTab đang hoạt động)
"""
from __future__ import annotations

import queue
import time
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QStackedWidget, QFrame, QTextEdit,
    QSizePolicy, QSpinBox, QScrollArea, QDialog, QFormLayout,
    QDialogButtonBox, QLineEdit,
)

from core.config import AUTO_TOOL_SLOTS, load_config, save_config
from core.logger import log
from core.gold_threshold_notifier import ToolSlotGoldThresholdNotifier
from ui2.runtime.task_runner import UiTaskResult, UiTaskRunner

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


def _format_money(value) -> str:
    try:
        v = float(value)
    except Exception:
        return "-"
    sign = "-" if v < 0 else ""
    v = abs(v)
    units = ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K"))
    for base, suffix in units:
        if v >= base:
            x = v / base
            text = f"{x:.1f}".rstrip("0").rstrip(".")
            return f"{sign}{text}{suffix}"
    return f"{sign}{int(v)}"


def _parse_money_input(text: str) -> Optional[int]:
    raw = str(text or "").strip().replace(",", "").replace(" ", "")
    if not raw:
        return None
    mult = 1
    suffix = raw[-1:].lower()
    if suffix in ("k", "m", "b"):
        raw = raw[:-1]
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[suffix]
    try:
        return int(float(raw) * mult)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
# ToggleSwitch — iOS-style toggle khớp demo HTML (.switch)
# ═══════════════════════════════════════════════════════════════════

class _SlotAutoLogSink:
    """Adapter so each embedded StrategyTab writes Auto logs to this slot panel."""

    def __init__(self, owner: "AutoFourToolTab", slot: int) -> None:
        self.owner = owner
        self.slot = int(slot)

    def append_log(self, text: str) -> None:
        try:
            self.owner.log_from_context(self.slot, str(text), "info")
        except Exception:
            pass

    def set_auto_state(self, enabled: bool, remaining: int) -> None:
        try:
            if self.owner._cards:
                card = self.owner._cards[self.slot - 1]
                card.set_meta("Auto Play: đang bật" if enabled else "Auto Play: tắt")
        except Exception:
            pass


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
    _COL_SAME = "#4e8bd9"
    _COL_WAIT = "#e3a53b"
    _COL_ERR  = "#dc5b62"

    def __init__(self, slot: int, parent=None):
        super().__init__(parent)
        self.slot = slot
        self._selected = False
        self._running = False
        self._p_dots: dict[str, QLabel] = {}
        self._p_cells: dict[str, QWidget] = {}
        self._p_gold_labels: dict[str, QLabel] = {}
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(112)
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
        self._lbl_profit = QLabel("-")
        self._lbl_profit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._lbl_profit.setStyleSheet(f"color:{_MUTED}; font-size:11px; font-weight:800;")
        top.addWidget(self._lbl_profit)
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
            cell.setFixedHeight(38)
            cell.setStyleSheet(
                f"background:{_PANEL3}; border:1px solid {_LINE2}; border-radius:3px;"
            )
            self._p_cells[pid] = cell
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(5, 2, 5, 2)
            cl.setSpacing(1)
            top_line = QHBoxLayout()
            top_line.setSpacing(2)
            plbl = QLabel(pid)
            plbl.setStyleSheet("color:#b9c1ca; font-size:10px; font-weight:800;")
            dot_p = _circle(5, self._COL_OFF)
            top_line.addWidget(plbl)
            top_line.addStretch()
            top_line.addWidget(dot_p)
            gold_lbl = QLabel("-")
            gold_lbl.setAlignment(Qt.AlignCenter)
            gold_lbl.setStyleSheet("color:#9ba7b3; font-size:9px; font-weight:700;")
            cl.addLayout(top_line)
            cl.addWidget(gold_lbl)
            self._p_dots[pid] = dot_p
            self._p_gold_labels[pid] = gold_lbl
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
        cell = self._p_cells.get(pid)
        if not dot or not cell:
            return
        color, bg, tip = {
            "connected": (self._COL_RUN, "#13241d", f"{pid}: đã kết nối"),
            "same_table": (self._COL_SAME, "#142235", f"{pid}: cùng bàn với P khác"),
            "split_table": (self._COL_ERR, "#2a171a", f"{pid}: khác bàn với P khác"),
            "wait": (self._COL_WAIT, "#271f11", f"{pid}: đang chờ"),
            "err": (self._COL_ERR, "#2a171a", f"{pid}: lỗi"),
        }.get(status, (self._COL_OFF, _PANEL3, f"{pid}: chưa kết nối"))
        cell.setStyleSheet(
            f"background:{bg}; border:1px solid {color}; border-radius:3px;"
        )
        cell.setToolTip(tip)
        dot.setStyleSheet(f"background:{color}; border-radius:2px;")

    def set_gold_state(self, p_gold: dict[str, Optional[int]], profit: Optional[int]):
        for pid in ("P1", "P2", "P3"):
            lbl = self._p_gold_labels.get(pid)
            if lbl is not None:
                lbl.setText(_format_money((p_gold or {}).get(pid)))
        if profit is None:
            self._lbl_profit.setText("-")
            self._lbl_profit.setStyleSheet(f"color:{_MUTED}; font-size:11px; font-weight:800;")
            return
        color = _GREEN if profit > 0 else (_RED if profit < 0 else _MUTED)
        sign = "+" if profit > 0 else ""
        self._lbl_profit.setText(f"{sign}{_format_money(profit)}")
        self._lbl_profit.setStyleSheet(f"color:{color}; font-size:11px; font-weight:900;")

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
    """Tab quản lý nhiều tool auto play — layout khớp demo HTML."""

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
        self._config_stack    = QStackedWidget()
        self._xao_vang_stack  = QStackedWidget()
        self._log_html: List[str] = []

        # Log filter: "sel" | "all" | "err"
        self._log_filter = "sel"
        self._tasks = UiTaskRunner(self)
        self._poll_cursor = 0
        self._log_redraw_pending = False
        self._profile_signal_cache: dict[tuple[int, str], str] = {}
        self._gold_cache: dict[tuple[int, str], Optional[int]] = {}
        self._capital_cache: dict[int, dict[str, Optional[int]]] = {}

        self._bg_log.connect(self._log)
        self._tasks.rejected.connect(self._on_task_rejected)
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

        self._signal_timer = QTimer(self)
        self._signal_timer.setInterval(500)
        self._signal_timer.timeout.connect(self._refresh_profile_room_signals)
        self._signal_timer.start()

    # ── Init contexts ──────────────────────────────────────────────

    def _init_tool_contexts(self):
        from core.config import ensure_slot_configs
        from core.tool_context import ToolContext
        ensure_slot_configs(AUTO_TOOL_SLOTS)
        for slot in range(1, AUTO_TOOL_SLOTS + 1):
            try:
                # Mỗi slot có WSCardStore riêng — KHÔNG chia sẻ global_cs.
                # Slot 1 nhận event qua relay từ main.py._handle_bridge_event.
                # Slots 2+ nhận event qua per-tool bridge riêng.
                # Tránh double-processing: nếu slot 1 dùng global_cs,
                # cả 2 strategy_tab (main.py + ctx) cùng poll global_cs → double compute.
                ctx = ToolContext(slot, card_store=None)
                ctx.build_widgets(parent=self)
                if ctx.strategy_tab is not None:
                    try:
                        base_notifier = getattr(self.parent(), "gold_threshold_notifier", None)
                        slot_notifier = (
                            ToolSlotGoldThresholdNotifier(base_notifier, slot)
                            if base_notifier is not None
                            else None
                        )
                        ctx.strategy_tab.set_runtime_services(
                            room_engine=ctx.room_engine,
                            layout_store=ctx.layout_store,
                            game_controller=ctx.game_controller,
                            auto_play_log_sink=_SlotAutoLogSink(self, slot),
                            auto_settings_notifier=slot_notifier,
                        )
                        if slot_notifier is not None and getattr(ctx, "room_engine", None) is not None:
                            ctx.room_engine.sig_gold_monitor_changed.connect(slot_notifier.check)
                    except Exception:
                        log.exception("[AutoFourToolTab] attach Strategy runtime slot=%d failed", slot)
                self._contexts.append(ctx)
            except Exception:
                log.exception("[AutoFourToolTab] ToolContext slot=%d lỗi", slot)
                self._contexts.append(None)

    def _start_slot_bridges(self):
        """Khởi động WS bridge cho slot 2+ ngay khi tab init.

        Bridge phải luôn chạy khi browser mở, bất kể auto play có bật hay không,
        vì extension cần fetch proxy-creds từ bridge ngay khi onAuthRequired.
        Slot 1 do main.py quản lý, không cần start ở đây.
        """
        for slot in range(2, AUTO_TOOL_SLOTS + 1):
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
        body.addWidget(self._build_room_panel())

        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 1)
        body.setSizes([250, 700, 440])

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

        spin_style = (
            f"QSpinBox {{ background:{_PANEL3}; color:{_TEXT}; border:1px solid {_LINE};"
            " border-radius:4px; padding:0 4px; height:28px; }}"
        )

        lay.addWidget(_lbl("Delay", f"color:{_MUTED};"))
        self._spn_dmin = QSpinBox()
        self._spn_dmin.setRange(0, 120); self._spn_dmin.setValue(8)
        self._spn_dmin.setFixedWidth(52)
        self._spn_dmin.setStyleSheet(spin_style)
        self._spn_dmax = QSpinBox()
        self._spn_dmax.setRange(0, 120); self._spn_dmax.setValue(18)
        self._spn_dmax.setFixedWidth(52)
        self._spn_dmax.setStyleSheet(spin_style)
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
        frame.setStyleSheet("background:#12161a;")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(7)

        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("Danh sách Tool", f"color:{_TEXT}; font-weight:800;"))
        self._lbl_total_profit = QLabel("-")
        self._lbl_total_profit.setAlignment(Qt.AlignCenter)
        self._lbl_total_profit.setStyleSheet(f"color:{_MUTED}; font-size:11px; font-weight:900;")
        hdr.addWidget(self._lbl_total_profit, 1)
        hdr.addStretch()
        hdr.addWidget(_lbl(f"{AUTO_TOOL_SLOTS} cụm / {AUTO_TOOL_SLOTS * 3}P", f"color:{_MUTED}; font-size:11px;"))
        lay.addLayout(hdr)

        for slot in range(1, AUTO_TOOL_SLOTS + 1):
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
        fl.addWidget(_lbl(f"Hệ thống: {AUTO_TOOL_SLOTS}/{AUTO_TOOL_SLOTS} sẵn sàng", f"color:{_TEXT}; font-size:11px;"))
        fl.addWidget(_lbl(f"Profiles: {AUTO_TOOL_SLOTS * 3} hồ sơ", f"color:{_MUTED}; font-size:11px;"))
        lay.addWidget(foot)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(frame)
        scroll.setStyleSheet(f"background:#12161a; border-right:1px solid {_LINE};")
        return scroll

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

        # Right: action buttons for the selected tool.
        act_row = QHBoxLayout(); act_row.setSpacing(6)
        self._btn_open_browsers  = self._detailbtn("Mở 3 trình duyệt",  "#343b45")
        self._btn_reconnect_all  = self._detailbtn("Kết nối lại ALL",    "#254c7d", _BLUE)
        self._btn_reset_proxy    = self._detailbtn("Reset Proxy ALL",    "#5d4218", _AMBER)
        self._btn_set_capital    = self._detailbtn("Mốc vốn", "#263646", _BLUE)
        self._btn_open_browsers.clicked.connect(self._on_open_browsers)
        self._btn_reconnect_all.clicked.connect(self._on_reconnect_all)
        self._btn_reset_proxy.clicked.connect(self._on_reset_proxy)
        self._btn_set_capital.clicked.connect(self._on_set_capital_from_gold)
        for b in (self._btn_open_browsers, self._btn_reconnect_all, self._btn_reset_proxy, self._btn_set_capital):
            act_row.addWidget(b)

        hl.addLayout(info_col, 1)
        hl.addLayout(act_row)
        lay.addWidget(hdr)

        # Inner tab bar
        tab_bar = QWidget()
        tab_bar.setFixedHeight(36)
        tab_bar.setStyleSheet(f"background:#13171c; border-bottom:1px solid {_LINE};")
        tbl = QHBoxLayout(tab_bar)
        tbl.setContentsMargins(10, 0, 10, 0)
        tbl.setSpacing(0)
        self._btn_strategy  = self._innertab("Chiến Thuật", True)
        self._btn_xao_vang  = self._innertab("Xào Vàng", False)
        self._btn_browser   = self._innertab("Trình duyệt", False)
        self._btn_config    = self._innertab("Cấu hình", False)
        self._btn_strategy.clicked.connect(lambda: self._switch_inner(0))
        self._btn_xao_vang.clicked.connect(lambda: self._switch_inner(1))
        self._btn_browser.clicked.connect(lambda:  self._switch_inner(2))
        self._btn_config.clicked.connect(lambda:   self._switch_inner(3))
        tbl.addWidget(self._btn_strategy)
        tbl.addWidget(self._btn_xao_vang)
        tbl.addWidget(self._btn_browser)
        tbl.addWidget(self._btn_config)
        tbl.addStretch()

        lay.addWidget(tab_bar)

        # Stacked panes
        self._inner_stack = QStackedWidget()
        self._inner_stack.setStyleSheet(f"background:{_BG};")

        # Pane 0: Chiến Thuật = ctx.strategy_tab (StrategyTab)
        self._inner_stack.addWidget(self._strategy_stack)
        self._build_strategy_pages()

        # Pane 1: Xào Vàng = ctx.xao_vang_tab (XaoVangTab per-slot)
        self._inner_stack.addWidget(self._xao_vang_stack)
        self._build_xao_vang_pages()

        # Pane 2: Trình duyệt = ctx.profiles_tab (ProfilesTabV2)
        self._inner_stack.addWidget(self._browser_stack)
        self._build_browser_pages()

        # Pane 3: Cấu hình = ctx.config_tab (ConfigTab per-slot)
        self._inner_stack.addWidget(self._config_stack)
        self._build_config_pages()

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

    def _set_detail_actions_enabled(self, enabled: bool) -> None:
        for btn in (
            getattr(self, "_btn_open_browsers", None),
            getattr(self, "_btn_reconnect_all", None),
            getattr(self, "_btn_reset_proxy", None),
            getattr(self, "_btn_set_capital", None),
        ):
            if btn is not None:
                btn.setEnabled(bool(enabled))

    def _load_capital(self, slot: int) -> dict[str, Optional[int]]:
        slot = int(slot or 1)
        if slot in self._capital_cache:
            return dict(self._capital_cache[slot])
        data: dict[str, Optional[int]] = {"P1": None, "P2": None, "P3": None}
        try:
            cfg = load_config(slot)
            raw = ((cfg.get("ui") or {}).get("auto_play_capital") or {})
            for pid in ("P1", "P2", "P3"):
                val = raw.get(pid)
                data[pid] = int(val) if val is not None else None
        except Exception:
            pass
        self._capital_cache[slot] = dict(data)
        return data

    def _save_capital(self, slot: int, values: dict[str, Optional[int]]) -> None:
        slot = int(slot or 1)
        clean = {
            pid: (int(values[pid]) if values.get(pid) is not None else None)
            for pid in ("P1", "P2", "P3")
        }
        cfg = load_config(slot)
        ui = cfg.setdefault("ui", {})
        ui["auto_play_capital"] = clean
        save_config(cfg, slot)
        self._capital_cache[slot] = dict(clean)

    def _current_gold_by_profile(self, ctx) -> dict[str, Optional[int]]:
        golds: dict[str, Optional[int]] = {"P1": None, "P2": None, "P3": None}
        room_engine = getattr(ctx, "room_engine", None)
        if room_engine is not None and hasattr(room_engine, "get_profile_gold_state"):
            try:
                state = room_engine.get_profile_gold_state() or {}
                for pid in ("P1", "P2", "P3"):
                    val = (state.get(pid) or {}).get("gold")
                    golds[pid] = int(val) if val is not None else None
            except Exception:
                pass
        return golds

    def _profit_for_slot(self, slot: int, golds: dict[str, Optional[int]]) -> Optional[int]:
        capital = self._load_capital(slot)
        if any(capital.get(pid) is None for pid in ("P1", "P2", "P3")):
            return None
        if any((golds or {}).get(pid) is None for pid in ("P1", "P2", "P3")):
            return None
        try:
            return sum(int(golds[pid]) - int(capital[pid]) for pid in ("P1", "P2", "P3"))
        except Exception:
            return None

    def _update_total_profit_label(self) -> None:
        lbl = getattr(self, "_lbl_total_profit", None)
        if lbl is None:
            return
        total = 0
        count = 0
        for slot in range(1, AUTO_TOOL_SLOTS + 1):
            profit = self._gold_cache.get((slot, "profit"))
            if profit is None:
                continue
            try:
                total += int(profit)
                count += 1
            except Exception:
                continue
        if count <= 0:
            lbl.setText("-")
            lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px; font-weight:900;")
            return
        color = _GREEN if total > 0 else (_RED if total < 0 else _MUTED)
        sign = "+" if total > 0 else ""
        lbl.setText(f"Tổng {sign}{_format_money(total)}")
        lbl.setStyleSheet(f"color:{color}; font-size:11px; font-weight:900;")

    def _on_task_rejected(self, res: UiTaskResult) -> None:
        try:
            slot = int(str(res.key).split(":", 1)[0])
        except Exception:
            slot = self._current_slot
        self._log(slot, f"{res.name}: {res.error}", "warn")

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
        for slot in range(1, AUTO_TOOL_SLOTS + 1):
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
        for slot in range(1, AUTO_TOOL_SLOTS + 1):
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
        for slot in range(1, AUTO_TOOL_SLOTS + 1):
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

    def _build_xao_vang_pages(self):
        """Pane Xao Vang = ctx.xao_vang_tab (XaoVangTab per-slot)."""
        for slot in range(1, AUTO_TOOL_SLOTS + 1):
            ctx = self._contexts[slot - 1]
            if ctx is not None and getattr(ctx, "xao_vang_tab", None) is not None:
                self._xao_vang_stack.addWidget(ctx.xao_vang_tab)
            else:
                ph = QLabel(f"Xao Vang Tool {slot} - loi khoi tao")
                ph.setAlignment(Qt.AlignCenter)
                ph.setStyleSheet(f"color:{_MUTED};")
                self._xao_vang_stack.addWidget(ph)

    def _build_config_pages(self):
        """Pane Cau hinh = ctx.config_tab (ConfigTab per-slot)."""
        for slot in range(1, AUTO_TOOL_SLOTS + 1):
            ctx = self._contexts[slot - 1]
            if ctx is not None and getattr(ctx, "config_tab", None) is not None:
                self._config_stack.addWidget(ctx.config_tab)
            else:
                ph = QLabel(f"Cau hinh Tool {slot} - loi khoi tao")
                ph.setAlignment(Qt.AlignCenter)
                ph.setStyleSheet(f"color:{_MUTED};")
                self._config_stack.addWidget(ph)

    def _build_room_panel(self) -> QWidget:
        frame = QWidget()
        frame.setMinimumWidth(520)
        frame.setStyleSheet(f"background:#12161a; border-left:1px solid {_LINE};")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(44)
        header.setStyleSheet(f"background:#12161a; border-bottom:1px solid {_LINE};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(6)

        hl.addWidget(_lbl("Phòng", f"color:{_TEXT}; font-weight:900; font-size:13px;"))
        hl.addStretch()

        toggle_style = (
            f"QPushButton {{ background:{_PANEL2}; color:{_MUTED}; border:1px solid {_LINE};"
            " border-radius:13px; padding:0 12px; font-weight:800; height:26px; }}"
            f"QPushButton:checked {{ background:{_BLUE}; color:#fff; border-color:{_BLUE}; }}"
        )
        self._chk_exit_p1 = QPushButton("P1")
        self._chk_exit_p2 = QPushButton("P2")
        self._chk_exit_p3 = QPushButton("P3")
        for btn in (self._chk_exit_p1, self._chk_exit_p2, self._chk_exit_p3):
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setStyleSheet(toggle_style)
            hl.addWidget(btn)
        self._chk_exit_p1.setChecked(True)
        self._chk_exit_p2.setChecked(True)
        self._chk_exit_p3.setChecked(True)

        self._btn_exit_room = QPushButton("Thoát Phòng")
        self._btn_exit_room.setFixedHeight(28)
        self._btn_exit_room.setStyleSheet(
            f"QPushButton {{ background:#7a2e35; color:#fff; border:1px solid {_RED};"
            " border-radius:4px; padding:0 10px; font-weight:800; }}"
        )
        self._btn_exit_room.clicked.connect(self._on_quick_exit_room)
        hl.addWidget(self._btn_exit_room)

        lay.addWidget(header)
        self._overview_stack.setStyleSheet(f"background:{_BG};")
        self._build_overview_pages()
        lay.addWidget(self._overview_stack, 1)
        return frame

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
        self._btn_strategy.setChecked(idx == 0)
        self._btn_xao_vang.setChecked(idx == 1)
        self._btn_browser.setChecked(idx == 2)
        self._btn_config.setChecked(idx == 3)

    def _switch_log_filter(self, f: str):
        self._log_filter = f
        if hasattr(self, "_btn_log_sel"):
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
        self._xao_vang_stack.setCurrentIndex(idx)
        self._browser_stack.setCurrentIndex(idx)
        self._config_stack.setCurrentIndex(idx)

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
        """Lấy delay từ topbar spinboxes."""
        dmin = int(self._spn_dmin.value()) * 1000
        dmax = int(self._spn_dmax.value()) * 1000
        return min(dmin, dmax), max(dmin, dmax)

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
        delay_min, delay_max = self._get_auto_params()

        if not self._ensure_bridge(slot):
            return

        # Bật auto play trên strategy_tab của slot này
        if ctx is not None and ctx.strategy_tab is not None:
            ctx.strategy_tab.set_auto_play(True, delay_min_ms=delay_min, delay_max_ms=delay_max)

        self._cards[slot - 1].set_running(True)
        self._cards[slot - 1].set_meta("Auto Play: đang bật")
        self._log(slot, f"Auto Play BẬT — chạy liên tục, delay {delay_min//1000}-{delay_max//1000}s", "ok")

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
        for slot in range(1, AUTO_TOOL_SLOTS + 1):
            self.start_tool(slot)

    def stop_all(self):
        for slot in range(1, AUTO_TOOL_SLOTS + 1):
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
                    if hasattr(ctx.browser_manager, "reload_config"):
                        ctx.browser_manager.reload_config()
                    ctx.browser_manager.open_browser(pid)
                    try:
                        managed = bool(ctx.browser_manager._is_managed_chrome_by_tool_enabled())
                        app_mode = bool(ctx.browser_manager._browser_port_has_app_mode(ctx.browser_manager._get_port(pid)))
                        if managed:
                            self._bg_log.emit(slot, f"{pid}: managed Chrome AppMode={'OK' if app_mode else 'FAIL'}", "ok" if app_mode else "warn")
                    except Exception:
                        pass
                    self._bg_log.emit(slot, f"{pid}: trình duyệt đã mở", "ok")
                except Exception as e:
                    self._bg_log.emit(slot, f"Lỗi mở browser {pid}: {e}", "err")

        self._set_detail_actions_enabled(False)
        self._tasks.run(
            key=f"{slot}:open_browsers",
            name=f"Tool {slot} - mo 3 trinh duyet",
            fn=_work,
            on_error=lambda err, s=slot: self._log(s, f"Mo trinh duyet loi: {err}", "err"),
            on_finished=lambda _res: self._set_detail_actions_enabled(True),
            timeout_ms=90_000,
        )

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

        self._set_detail_actions_enabled(False)
        self._tasks.run(
            key=f"{slot}:reconnect_all",
            name=f"Tool {slot} - ket noi lai ALL",
            fn=_work,
            on_error=lambda err, s=slot: self._log(s, f"Ket noi lai ALL loi: {err}", "err"),
            on_finished=lambda _res: self._set_detail_actions_enabled(True),
            timeout_ms=45_000,
        )

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
            lease = None
            try:
                gate = getattr(ctx, "action_gate", None)
                if gate is not None:
                    lease, busy = gate.try_acquire(pid, "room:exit", owner="AutoFourToolTab")
                    if lease is None:
                        self._log(
                            slot,
                            f"{pid} dang ban ({getattr(busy, 'action', 'action')}); bo qua Thoat Phong",
                            "warn",
                        )
                        continue
                ctx.gateway.gui_lenh_thoat_phong(pid)
                self._log(slot, f"Đã gửi lệnh thoát phòng → {pid}", "ok")
            except Exception as e:
                self._log(slot, f"Lỗi thoát phòng {pid}: {e}", "err")
            finally:
                if lease is not None:
                    try:
                        ctx.action_gate.release(lease)
                    except Exception:
                        pass

    def _on_set_capital_from_gold(self):
        slot = self._current_slot
        ctx = self._contexts[slot - 1]
        if ctx is None:
            self._log(slot, "Khong co context de lay moc von", "err")
            return
        golds = self._current_gold_by_profile(ctx)
        saved = self._load_capital(slot)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Moc von Tool {slot}")
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        edits: dict[str, QLineEdit] = {}
        for pid in ("P1", "P2", "P3"):
            edit = QLineEdit()
            val = saved.get(pid)
            if val is None:
                val = golds.get(pid)
            edit.setText("" if val is None else str(int(val)))
            edit.setPlaceholderText("VD: 100000, 100K, 1.5M")
            edits[pid] = edit
            current = _format_money(golds.get(pid))
            form.addRow(f"{pid} (hien tai {current})", edit)
        layout.addLayout(form)

        btn_current = QPushButton("Lay vang hien tai")
        btn_current.setFixedHeight(28)
        btn_current.setStyleSheet(
            f"background:#263646; color:#fff; border:1px solid {_BLUE};"
            " border-radius:4px; padding:0 10px; font-weight:700;"
        )
        layout.addWidget(btn_current)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        def fill_current():
            missing = [pid for pid in ("P1", "P2", "P3") if golds.get(pid) is None]
            if missing:
                self._log(slot, f"Chua co vang hien tai cho {','.join(missing)}", "warn")
                return
            for pid in ("P1", "P2", "P3"):
                edits[pid].setText(str(int(golds[pid])))

        btn_current.clicked.connect(fill_current)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() != QDialog.Accepted:
            return

        values: dict[str, Optional[int]] = {}
        for pid in ("P1", "P2", "P3"):
            val = _parse_money_input(edits[pid].text())
            if val is None:
                self._log(slot, f"Moc von {pid} khong hop le", "warn")
                return
            values[pid] = val

        self._save_capital(slot, values)
        profit = self._profit_for_slot(slot, golds)
        self._log(
            slot,
            "Da lay moc von: "
            + " | ".join(f"{pid}={_format_money(values[pid])}" for pid in ("P1", "P2", "P3")),
            "ok",
        )
        try:
            self._gold_cache[(slot, "profit")] = profit
            self._cards[slot - 1].set_gold_state(golds, profit)
            self._update_total_profit_label()
        except Exception:
            pass

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

        self._set_detail_actions_enabled(False)
        self._tasks.run(
            key=f"{slot}:reset_proxy_all",
            name=f"Tool {slot} - reset proxy ALL",
            fn=_work,
            on_error=lambda err, s=slot: self._log(s, f"Reset Proxy ALL loi: {err}", "err"),
            on_finished=lambda _res: self._set_detail_actions_enabled(True),
            timeout_ms=60_000,
        )

    # ── Event polling ──────────────────────────────────────────────

    def _poll_tool_events(self):
        # Keep UI responsive under 12-tool bursts: process a small time slice
        # per timer tick, never drop events. Remaining queued events stay for
        # the next tick in the same per-tool FIFO queue.
        if not self._contexts:
            return

        deadline = time.perf_counter() + 0.010
        count = len(self._contexts)
        start_idx = int(getattr(self, "_poll_cursor", 0) or 0) % count
        next_idx = start_idx
        processed_any = False

        for offset in range(count):
            idx = (start_idx + offset) % count
            ctx = self._contexts[idx]
            next_idx = (idx + 1) % count
            if ctx is None:
                continue
            n = 0
            while n < 30:
                if time.perf_counter() >= deadline:
                    self._poll_cursor = next_idx
                    if processed_any:
                        self._refresh_profile_room_signals()
                    return
                try:
                    evt = ctx.event_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    ctx.dispatch_event(evt)
                    processed_any = True
                except Exception:
                    log.exception("[AutoFourToolTab] dispatch slot=%d", ctx.slot)
                n += 1
        self._poll_cursor = next_idx
        if processed_any:
            self._refresh_profile_room_signals()

    def _refresh_profile_room_signals(self):
        for slot, ctx in enumerate(self._contexts, start=1):
            if slot - 1 >= len(self._cards):
                continue
            statuses = self._compute_profile_room_signals(ctx)
            card = self._cards[slot - 1]
            for pid, status in statuses.items():
                cache_key = (slot, pid)
                if self._profile_signal_cache.get(cache_key) == status:
                    continue
                self._profile_signal_cache[cache_key] = status
                card.set_profile_status(pid, status)
            golds = self._current_gold_by_profile(ctx)
            changed = False
            for pid, gold in golds.items():
                key = (slot, pid)
                if self._gold_cache.get(key) != gold:
                    self._gold_cache[key] = gold
                    changed = True
            profit = self._profit_for_slot(slot, golds)
            profit_key = (slot, "profit")
            if self._gold_cache.get(profit_key) != profit:
                self._gold_cache[profit_key] = profit
                changed = True
            if changed:
                card.set_gold_state(golds, profit)
        self._update_total_profit_label()

    def _compute_profile_room_signals(self, ctx) -> dict[str, str]:
        pids = ("P1", "P2", "P3")
        result = {pid: "disconnected" for pid in pids}
        room_engine = getattr(ctx, "room_engine", None) if ctx is not None else None
        room_tab = getattr(ctx, "room_tab", None) if ctx is not None else None
        if room_engine is None and room_tab is None:
            return result

        uid_by_pid: dict[str, str] = {}
        table_by_pid: dict[str, frozenset[str]] = {}
        table_members: dict[frozenset[str], set[str]] = {}

        if room_engine is not None and hasattr(room_engine, "get_room_monitor_state"):
            for pid in pids:
                try:
                    state = room_engine.get_room_monitor_state(pid) or {}
                except Exception:
                    continue
                profiles = state.get("profiles") or {}
                for profile, info in profiles.items():
                    uid = str((info or {}).get("uid") or "").strip()
                    if profile in pids and uid:
                        uid_by_pid[profile] = uid

        last_room_state = getattr(room_tab, "_last_room_state", {}) if room_tab is not None else {}
        if isinstance(last_room_state, dict):
            for pid in pids:
                st = last_room_state.get(pid)
                if st is None:
                    continue
                my_uid = str(getattr(st, "my_uid", "") or "").strip()
                if my_uid:
                    uid_by_pid[pid] = my_uid
                players = getattr(st, "nguoi_choi", None) or []
                room_uids = {
                    str(getattr(player, "uid", "") or "").strip()
                    for player in players
                    if str(getattr(player, "uid", "") or "").strip()
                }
                count = int(getattr(st, "so_nguoi_hien_tai", 0) or 0)
                if room_uids or count > 0 or getattr(st, "room_id", None) is not None:
                    result[pid] = "connected"
                if room_uids:
                    key = frozenset(room_uids)
                elif getattr(st, "room_id", None) is not None:
                    key = frozenset({f"room:{getattr(st, 'room_id', None)}"})
                else:
                    key = frozenset()
                if key:
                    table_by_pid[pid] = key
                    members = {
                        profile
                        for profile, uid in uid_by_pid.items()
                        if uid and uid in room_uids
                    }
                    if my_uid:
                        members.add(pid)
                    table_members.setdefault(key, set()).update(members)

        for pid in pids:
            if uid_by_pid.get(pid):
                result[pid] = "connected"

        if room_engine is not None and hasattr(room_engine, "get_room_monitor_state"):
            for pid in pids:
                try:
                    state = room_engine.get_room_monitor_state(pid) or {}
                except Exception:
                    continue
                if not bool(state.get("roster_fresh")):
                    continue
                room_uids = {
                    str(uid).strip()
                    for uid in (state.get("room_uids") or [])
                    if str(uid or "").strip()
                }
                own_uid = uid_by_pid.get(pid)
                if not own_uid or own_uid not in room_uids:
                    continue
                key = frozenset(room_uids)
                table_by_pid[pid] = key
                members = {
                    profile
                    for profile, uid in uid_by_pid.items()
                    if uid and uid in room_uids
                }
                table_members.setdefault(key, set()).update(members)

        same_table_pids: set[str] = set()
        for members in table_members.values():
            if len(members) >= 2:
                same_table_pids.update(members)

        active_table_keys = {key for key in table_by_pid.values() if key}
        for pid in pids:
            if pid in same_table_pids:
                result[pid] = "same_table"
            elif table_by_pid.get(pid) and len(active_table_keys) >= 2:
                result[pid] = "split_table"

        return result

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
        self._schedule_log_redraw()

    def _schedule_log_redraw(self):
        if self._log_redraw_pending:
            return
        self._log_redraw_pending = True
        QTimer.singleShot(80, self._redraw_log)

    def _redraw_log(self):
        self._log_redraw_pending = False
        if not hasattr(self, "_log_view"):
            return
        f = self._log_filter
        sel = self._current_slot
        rows = []
        for r in self._log_html:
            if f == "sel" and r["slot"] != sel and r["slot"] != 0:
                continue
            if f == "err" and r["level"] not in ("err", "warn"):
                continue
            rows.append(r["html"])
        if len(rows) > 250:
            rows = rows[-250:]
        self._log_view.setHtml(
            f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:11px;">'
            + "".join(rows) + "</div>"
        )
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_log(self):
        self._log_html.clear()
        self._log_redraw_pending = False
        if hasattr(self, "_log_view"):
            self._log_view.clear()

    def log_from_context(self, slot: int, msg: str, level: str = "info"):
        self._log(slot, msg, level)
