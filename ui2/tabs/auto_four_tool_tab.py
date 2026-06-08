"""
ui2/tabs/auto_four_tool_tab.py

Tab "Auto Play" quản lý 4 tool slot đồng thời.

Layout 3 cột:
  [Sidebar 4 tool] | [Header + Inner tabs: Tổng quan | Phòng | Chiến Thuật] | [Activity log]

Tool 1 reuse existing StrategyTab từ MainWindow (tránh đụng WS queue global).
Tool 2-4 dùng ToolContext riêng với per-tool WS bridge, queue, card_store.
"""
from __future__ import annotations

import queue
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QStackedWidget, QTextEdit, QFrame, QScrollArea,
    QSizePolicy, QTabWidget,
)
from PySide6.QtGui import QFont, QColor

from core.logger import log


# ============================================================
# ToolSlotCard — card nhỏ bên sidebar đại diện 1 tool
# ============================================================

class ToolSlotCard(QWidget):
    """Card hiển thị trạng thái 1 tool.
    clicked: chọn tool (click lên card body)
    toggle_requested: bật/tắt bridge (click nút ▶/■)
    """

    clicked = Signal(int)           # slot (1-4) — chọn tool
    toggle_requested = Signal(int)  # slot (1-4) — bật/tắt bridge

    def __init__(self, slot: int, parent=None):
        super().__init__(parent)
        self.slot = slot
        self._active = False
        self._running = False
        self._selected = False

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(72)
        self.setCursor(Qt.PointingHandCursor)
        self._build_ui()
        self._refresh_style()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # Indicator dot
        self._dot = QLabel("●")
        self._dot.setFixedWidth(14)
        font_dot = QFont()
        font_dot.setPointSize(10)
        self._dot.setFont(font_dot)

        # Text block
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._lbl_name = QLabel(f"Tool {self.slot}")
        font_name = QFont()
        font_name.setBold(True)
        font_name.setPointSize(9)
        self._lbl_name.setFont(font_name)

        self._lbl_status = QLabel("Chưa khởi động")
        font_status = QFont()
        font_status.setPointSize(8)
        self._lbl_status.setFont(font_status)

        text_col.addWidget(self._lbl_name)
        text_col.addWidget(self._lbl_status)

        # Start/Stop button
        self._btn = QPushButton("▶ Bắt đầu")
        self._btn.setFixedWidth(90)
        self._btn.setFixedHeight(28)
        self._btn.clicked.connect(self._on_btn_clicked)

        root.addWidget(self._dot)
        root.addLayout(text_col, 1)
        root.addWidget(self._btn)

    def _refresh_style(self):
        dot_color = "#22c55e" if self._running else "#6b7280"
        self._dot.setStyleSheet(f"color: {dot_color};")

        border = "2px solid #3b82f6" if self._selected else "1px solid #3C3C3C"
        bg = "#1f2937" if self._selected else "transparent"
        self.setStyleSheet(
            f"ToolSlotCard {{ border: {border}; border-radius: 6px;"
            f" background: {bg}; }}"
        )

        btn_text = "■ Dừng" if self._running else "▶ Bắt đầu"
        btn_bg = "#dc2626" if self._running else "#2563eb"
        self._btn.setText(btn_text)
        self._btn.setStyleSheet(
            f"QPushButton {{ background: {btn_bg}; color: white;"
            f" border-radius: 4px; border: none; font-size: 8pt; }}"
            f"QPushButton:hover {{ background: {'#b91c1c' if self._running else '#1d4ed8'}; }}"
        )

    def set_selected(self, selected: bool):
        self._selected = selected
        self._refresh_style()

    def set_running(self, running: bool):
        self._running = running
        self._refresh_style()

    def set_status_text(self, text: str):
        self._lbl_status.setText(text)

    def _on_btn_clicked(self):
        # Nút bắt/dừng: không chọn tool, chỉ toggle bridge
        self.toggle_requested.emit(self.slot)

    def mousePressEvent(self, event):
        self.clicked.emit(self.slot)
        super().mousePressEvent(event)


# ============================================================
# AutoFourToolTab — tab chính
# ============================================================

class AutoFourToolTab(QWidget):
    """
    Tab quản lý 4 tool auto play.

    Tất cả 4 slot đều dùng ToolContext riêng.
    Slot 1 dùng global ws_card_store để nhận cards từ bridge hiện có (main.py).
    Slot 2-4 dùng per-tool WSCardStore + per-tool WS bridge.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # ToolContext cho cả 4 slot — index 0 = slot 1, ... index 3 = slot 4
        self._contexts: List = []
        self._current_slot = 1

        # Tạo ToolContext cho slot 1-4
        self._init_tool_contexts()

        # Build UI
        self._cards: List[ToolSlotCard] = []
        self._strategy_stack = QStackedWidget()
        self._room_stack = QStackedWidget()
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumWidth(220)
        self._log_edit.setPlaceholderText("Activity log...")

        self._build_ui()
        self._select_slot(1)

        # Timer poll events cho slot 2-4 (slot 1 được poll bởi main.py)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_tool_events)
        self._poll_timer.start()

    # ------------------------------------------------------------------
    # Khởi tạo ToolContext cho tất cả 4 slot
    # ------------------------------------------------------------------

    def _init_tool_contexts(self):
        from core.config import ensure_slot_configs
        from core.tool_context import ToolContext
        from ui2.bridge.ws_card_store import ws_card_store as global_card_store

        # Đảm bảo config-tool2,3,4.json tồn tại
        ensure_slot_configs()

        for slot in range(1, 5):
            try:
                if slot == 1:
                    # Slot 1 dùng global card_store để nhận cards từ bridge đang chạy ở main.py
                    # Không start bridge riêng (tránh port conflict với bridge Tool 1 hiện có)
                    ctx = ToolContext(slot, card_store=global_card_store)
                else:
                    ctx = ToolContext(slot)
                ctx.build_widgets(parent=self)
                self._contexts.append(ctx)
            except Exception:
                log.exception("[AutoFourToolTab] Lỗi khởi tạo ToolContext slot=%d", slot)
                self._contexts.append(None)

    # ------------------------------------------------------------------
    # Build layout
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # --- LEFT: sidebar ---
        sidebar = self._build_sidebar()
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(210)
        splitter.addWidget(sidebar)

        # --- CENTER: inner tabs ---
        center = self._build_center()
        splitter.addWidget(center)

        # --- RIGHT: activity log ---
        log_panel = self._build_log_panel()
        log_panel.setMinimumWidth(160)
        log_panel.setMaximumWidth(240)
        splitter.addWidget(log_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        root.addWidget(splitter)

    def _build_sidebar(self) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.NoFrame)
        frame.setStyleSheet("background: #252526; border-right: 1px solid #3C3C3C;")

        vlay = QVBoxLayout(frame)
        vlay.setContentsMargins(6, 8, 6, 8)
        vlay.setSpacing(6)

        header = QLabel("Quản lý Tool")
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        header.setFont(font)
        header.setStyleSheet("color: #B0B0B0; padding-bottom: 4px;")
        vlay.addWidget(header)

        for slot in range(1, 5):
            card = ToolSlotCard(slot, self)
            card.clicked.connect(self._on_card_select)
            card.toggle_requested.connect(self._on_card_toggle)
            self._cards.append(card)
            vlay.addWidget(card)

        vlay.addStretch()
        return frame

    def _build_center(self) -> QWidget:
        frame = QWidget()
        vlay = QVBoxLayout(frame)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        # Header: tên tool đang chọn
        self._center_header = QLabel("Tool 1")
        font_h = QFont()
        font_h.setBold(True)
        font_h.setPointSize(10)
        self._center_header.setFont(font_h)
        self._center_header.setStyleSheet(
            "color: #E6E6E6; background: #252526;"
            " padding: 6px 12px; border-bottom: 1px solid #3C3C3C;"
        )
        vlay.addWidget(self._center_header)

        # Inner tab widget
        self._inner_tabs = QTabWidget()
        self._inner_tabs.setDocumentMode(True)
        self._inner_tabs.setStyleSheet(
            "QTabWidget::pane { border: none; }"
            "QTabBar::tab { background: #2D2D30; color: #B0B0B0;"
            " padding: 5px 14px; border: none; }"
            "QTabBar::tab:selected { background: #1E1E1E; color: #E6E6E6;"
            " border-bottom: 2px solid #3b82f6; }"
        )

        # Tab Tổng quan
        overview_stack = self._build_overview_stack()
        self._inner_tabs.addTab(overview_stack, "Tổng quan")

        # Tab Phòng — QStackedWidget chứa 4 RoomControlTab
        self._inner_tabs.addTab(self._room_stack, "Phòng")
        self._build_room_stack()

        # Tab Chiến Thuật — QStackedWidget chứa 4 StrategyTab
        self._inner_tabs.addTab(self._strategy_stack, "Chiến Thuật")
        self._build_strategy_stack()

        vlay.addWidget(self._inner_tabs, 1)
        return frame

    def _build_overview_stack(self) -> QStackedWidget:
        """Tổng quan đơn giản: tên tool + tool_index + bridge port."""
        stack = QStackedWidget()
        for slot in range(1, 5):
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setAlignment(Qt.AlignTop)
            lay.setContentsMargins(16, 16, 16, 16)
            lay.setSpacing(8)

            if slot == 1:
                tool_index = 1
                port = 9527
            else:
                ctx = self._contexts[slot - 2]
                tool_index = ctx.tool_index if ctx else slot
                port = ctx._bridge_port if ctx else (9526 + slot)

            lbl = QLabel(f"<b>Tool {slot}</b>")
            lbl.setStyleSheet("color: #E6E6E6; font-size: 14pt;")
            lay.addWidget(lbl)

            info = QLabel(
                f"Tool index: {tool_index}\n"
                f"Bridge port: {port}\n"
                f"Config: {'config.json' if slot == 1 else f'config-tool{slot}.json'}"
            )
            info.setStyleSheet("color: #B0B0B0; font-size: 9pt;")
            lay.addWidget(info)
            lay.addStretch()

            stack.addWidget(w)
        return stack

    def _build_room_stack(self):
        """Nhúng RoomControlTab của 4 slot vào room_stack."""
        for i, ctx in enumerate(self._contexts):
            slot = i + 1
            if ctx is not None and ctx.room_tab is not None:
                self._room_stack.addWidget(ctx.room_tab)
            else:
                placeholder = QLabel(f"Phòng Tool {slot} (lỗi khởi tạo)")
                placeholder.setAlignment(Qt.AlignCenter)
                self._room_stack.addWidget(placeholder)

    def _build_strategy_stack(self):
        """Nhúng StrategyTab của 4 slot vào strategy_stack."""
        for i, ctx in enumerate(self._contexts):
            slot = i + 1
            if ctx is not None and ctx.strategy_tab is not None:
                self._strategy_stack.addWidget(ctx.strategy_tab)
            else:
                placeholder = QLabel(f"Chiến Thuật Tool {slot} (lỗi khởi tạo)")
                placeholder.setAlignment(Qt.AlignCenter)
                self._strategy_stack.addWidget(placeholder)

    def _build_log_panel(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.NoFrame)
        frame.setStyleSheet("background: #1C1C1C; border-left: 1px solid #3C3C3C;")

        vlay = QVBoxLayout(frame)
        vlay.setContentsMargins(6, 8, 6, 8)
        vlay.setSpacing(4)

        header = QLabel("Activity")
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        header.setFont(font)
        header.setStyleSheet("color: #B0B0B0;")
        vlay.addWidget(header)

        self._log_edit.setStyleSheet(
            "QTextEdit { background: #1C1C1C; color: #B0B0B0;"
            " border: none; font-size: 8pt; font-family: Consolas, monospace; }"
        )
        self._log_edit.setMaximumWidth(10000)  # reset max trong panel
        vlay.addWidget(self._log_edit, 1)

        return frame

    # ------------------------------------------------------------------
    # Chọn tool / Toggle bridge
    # ------------------------------------------------------------------

    def _on_card_select(self, slot: int):
        """Click card body → chọn hiển thị tool đó."""
        self._select_slot(slot)

    def _on_card_toggle(self, slot: int):
        """Click nút ▶/■ → bật hoặc dừng bridge của tool."""
        card = self._cards[slot - 1]
        if card._running:
            self.stop_tool(slot)
        else:
            self.start_tool(slot)

    def _select_slot(self, slot: int):
        self._current_slot = slot
        idx = slot - 1  # 0-based index trong stacks

        # Cập nhật selection highlight
        for card in self._cards:
            card.set_selected(card.slot == slot)

        # Switch stacks
        self._strategy_stack.setCurrentIndex(idx)
        self._room_stack.setCurrentIndex(idx)

        # Cũng switch overview_stack nếu cần (lấy từ inner_tabs)
        overview_stack = self._inner_tabs.widget(0)  # tab index 0 = Tổng quan
        if isinstance(overview_stack, QStackedWidget):
            overview_stack.setCurrentIndex(idx)

        # Update header
        self._center_header.setText(f"Tool {slot}")

    # ------------------------------------------------------------------
    # Start / Stop từng tool
    # ------------------------------------------------------------------

    def start_tool(self, slot: int):
        """Khởi động WS bridge cho tool slot."""
        ctx = self._contexts[slot - 1]

        if slot == 1:
            # Slot 1: bridge đã được main.py khởi động, chỉ đánh dấu running
            self._log(1, "Tool 1 dùng bridge mặc định (main.py)")
            self._cards[0].set_running(True)
            self._cards[0].set_status_text("Đang chạy")
            return

        if ctx is None:
            self._log(slot, f"Tool {slot}: context lỗi, không thể start")
            return

        try:
            ctx.start()
            self._cards[slot - 1].set_running(True)
            self._cards[slot - 1].set_status_text(f"Port {ctx._bridge_port}")
            self._log(slot, f"Tool {slot} bridge port {ctx._bridge_port} started")
        except OSError as e:
            self._cards[slot - 1].set_status_text("Lỗi port")
            self._log(slot, f"Tool {slot} lỗi start: {e}")

    def stop_tool(self, slot: int):
        """Dừng WS bridge cho tool slot."""
        if slot == 1:
            self._log(1, "Tool 1 không dừng được từ đây")
            return

        ctx = self._contexts[slot - 1]
        if ctx:
            ctx.stop()
        self._cards[slot - 1].set_running(False)
        self._cards[slot - 1].set_status_text("Đã dừng")
        self._log(slot, f"Tool {slot} dừng")

    def start_all(self):
        """Khởi động tất cả tools (2-4). Tool 1 do main.py quản lý."""
        for slot in range(2, 5):
            self.start_tool(slot)

    def stop_all(self):
        """Dừng tất cả tools 2-4."""
        for slot in range(2, 5):
            self.stop_tool(slot)

    # ------------------------------------------------------------------
    # Event polling
    # ------------------------------------------------------------------

    def _poll_tool_events(self):
        """Poll event queue cho slot 2-4 (slot 1 do main.py xử lý qua WS_EVENT_QUEUE global)."""
        for ctx in self._contexts:
            if ctx is None or ctx.slot == 1:
                continue  # Slot 1 bridge & queue được quản lý bởi main.py
            n = 0
            while n < 30:
                try:
                    evt = ctx.event_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    ctx.dispatch_event(evt)
                except Exception:
                    log.exception("[AutoFourToolTab] dispatch_event lỗi slot=%d", ctx.slot)
                n += 1

    # ------------------------------------------------------------------
    # Activity log
    # ------------------------------------------------------------------

    def _log(self, slot: int, msg: str):
        """Ghi vào activity log."""
        try:
            self._log_edit.append(f"[T{slot}] {msg}")
            # Giới hạn 500 dòng để tránh OOM
            doc = self._log_edit.document()
            if doc.blockCount() > 500:
                cursor = self._log_edit.textCursor()
                cursor.movePosition(cursor.Start)
                cursor.select(cursor.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()
        except Exception:
            pass

    def log_from_context(self, slot: int, msg: str):
        """API công khai để ToolContext / RoomEngine ghi log."""
        self._log(slot, msg)
