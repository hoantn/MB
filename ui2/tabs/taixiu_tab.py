from __future__ import annotations

import os
import sqlite3
from typing import Dict, List, Optional

from ui2.ai.taixiu_pattern_stats import summarize_patterns
from ui2.ai.taixiu_overview_ai import build_taixiu_overview

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QScrollArea,
    QAbstractItemView,
)


def _default_db_path() -> str:
    here = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(project_root, "taixiu_history.sqlite3")


class TaiXiuTab(QWidget):
    auto_snapshot_ready = Signal(object, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._db_path = _default_db_path()
        self._current_mode = None
        self._last_pattern_signature = None

        self._build_ui()
        self._apply_styles()
        self._rebuild_layout(force=True)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_from_db)
        self._timer.start(1500)

        self.refresh_from_db()

    # ==========================================================
    # BUILD UI
    # ==========================================================
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(self.scroll)

        self.page = QWidget()
        self.scroll.setWidget(self.page)

        self.page_layout = QVBoxLayout(self.page)
        self.page_layout.setContentsMargins(16, 16, 16, 16)
        self.page_layout.setSpacing(14)

        self.page_layout.addWidget(self._build_top_bar())
        self.page_layout.addWidget(self._build_state_panel())
        self.page_layout.addWidget(self._build_decision_panel())
        self.page_layout.addWidget(self._build_evidence_wrap(), 1)
        self.page_layout.addWidget(self._build_status_bar())

    def _build_top_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("tx_top_bar")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(2)

        self.lbl_title = QLabel("TÀI XỈU • AUTO MODE")
        self.lbl_title.setObjectName("tx_title")

        self.lbl_subtitle = QLabel("Nhìn nhanh • quyết định nhanh • ít nhiễu")
        self.lbl_subtitle.setObjectName("tx_subtitle")

        left.addWidget(self.lbl_title)
        left.addWidget(self.lbl_subtitle)

        layout.addLayout(left, 1)

        self.lbl_live = QLabel("● LIVE")
        self.lbl_live.setObjectName("tx_live_badge")
        self.lbl_live.setAlignment(Qt.AlignCenter)

        self.btn_refresh = QPushButton("LÀM MỚI")
        self.btn_refresh.setObjectName("tx_refresh_btn")
        self.btn_refresh.clicked.connect(self.refresh_from_db)

        layout.addWidget(self.lbl_live, 0)
        layout.addWidget(self.btn_refresh, 0)

        return frame

    def _build_state_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("tx_state_panel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        self.state_top_row = QHBoxLayout()
        self.state_top_row.setSpacing(10)

        self.state_round_chip = self._make_info_chip("PHIÊN", "-")
        self.state_status_chip = self._make_info_chip("TRẠNG THÁI", "-")
        self.state_total_chip = self._make_info_chip("TỔNG", "-")

        self.state_top_row.addWidget(self.state_round_chip["frame"])
        self.state_top_row.addWidget(self.state_status_chip["frame"])
        self.state_top_row.addWidget(self.state_total_chip["frame"])

        layout.addLayout(self.state_top_row)

        self.lbl_result = QLabel("-")
        self.lbl_result.setObjectName("tx_result_hero")
        self.lbl_result.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_result)

        self.dice_row = QHBoxLayout()
        self.dice_row.setSpacing(10)

        self.lbl_die_1 = self._make_die_label("-")
        self.lbl_die_2 = self._make_die_label("-")
        self.lbl_die_3 = self._make_die_label("-")

        self.dice_row.addStretch(1)
        self.dice_row.addWidget(self.lbl_die_1)
        self.dice_row.addWidget(self.lbl_die_2)
        self.dice_row.addWidget(self.lbl_die_3)
        self.dice_row.addStretch(1)

        layout.addLayout(self.dice_row)

        return frame

    def _build_decision_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("tx_decision_panel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        self.lbl_decision_title = QLabel("GỢI Ý HÀNH ĐỘNG")
        self.lbl_decision_title.setObjectName("tx_block_title")
        self.lbl_decision_title.setAlignment(Qt.AlignCenter)

        self.lbl_decision = QLabel("→ ĐANG PHÂN TÍCH")
        self.lbl_decision.setObjectName("tx_decision_hero")
        self.lbl_decision.setAlignment(Qt.AlignCenter)

        self.lbl_reason_1 = QLabel("-")
        self.lbl_reason_1.setObjectName("tx_reason_line")
        self.lbl_reason_1.setWordWrap(True)

        self.lbl_reason_2 = QLabel("-")
        self.lbl_reason_2.setObjectName("tx_reason_line")
        self.lbl_reason_2.setWordWrap(True)

        self.lbl_reason_3 = QLabel("-")
        self.lbl_reason_3.setObjectName("tx_reason_line")
        self.lbl_reason_3.setWordWrap(True)

        layout.addWidget(self.lbl_decision_title)
        layout.addWidget(self.lbl_decision)
        layout.addWidget(self.lbl_reason_1)
        layout.addWidget(self.lbl_reason_2)
        layout.addWidget(self.lbl_reason_3)

        return frame

    def _build_evidence_wrap(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("tx_evidence_wrap")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.evidence_host = QVBoxLayout()
        self.evidence_host.setContentsMargins(0, 0, 0, 0)
        self.evidence_host.setSpacing(0)

        layout.addLayout(self.evidence_host)

        self.evidence_panel = self._build_evidence_panel()
        self.history_panel = self._build_history_panel()

        return frame

    def _build_evidence_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("tx_evidence_panel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(8)

        self.lbl_evidence_title = QLabel("BẰNG CHỨNG NHANH")
        self.lbl_evidence_title.setObjectName("tx_block_title")

        self.lbl_seq_hint = QLabel("trái: cũ  →  phải: mới")
        self.lbl_seq_hint.setObjectName("tx_small_hint")

        top.addWidget(self.lbl_evidence_title)
        top.addStretch(1)
        top.addWidget(self.lbl_seq_hint)

        layout.addLayout(top)

        self.sequence_box = QFrame()
        self.sequence_box.setObjectName("tx_sequence_box")
        self.sequence_layout = QHBoxLayout(self.sequence_box)
        self.sequence_layout.setContentsMargins(12, 10, 12, 10)
        self.sequence_layout.setSpacing(8)
        layout.addWidget(self.sequence_box)

        self.pattern_row = QHBoxLayout()
        self.pattern_row.setSpacing(10)

        self.card_pattern = self._make_metric_card("CẦU", "KHÔNG RÕ")
        self.card_money = self._make_metric_card("TIỀN", "Tài 0% | Xỉu 0%")
        self.card_warning = self._make_metric_card("CẢNH BÁO", "-")

        self.pattern_row.addWidget(self.card_pattern["frame"])
        self.pattern_row.addWidget(self.card_money["frame"])
        self.pattern_row.addWidget(self.card_warning["frame"])

        layout.addLayout(self.pattern_row)

        self.ai_box = QFrame()
        self.ai_box.setObjectName("tx_ai_box")
        ai_layout = QVBoxLayout(self.ai_box)
        ai_layout.setContentsMargins(12, 10, 12, 10)
        ai_layout.setSpacing(6)

        self.lbl_ai_quick = QLabel("-")
        self.lbl_ai_quick.setObjectName("tx_ai_line")
        self.lbl_ai_quick.setWordWrap(True)

        self.lbl_ai_extra = QLabel("-")
        self.lbl_ai_extra.setObjectName("tx_ai_line")
        self.lbl_ai_extra.setWordWrap(True)

        ai_layout.addWidget(self.lbl_ai_quick)
        ai_layout.addWidget(self.lbl_ai_extra)

        layout.addWidget(self.ai_box)

        self.db_box = QFrame()
        self.db_box.setObjectName("tx_db_box")
        db_layout = QVBoxLayout(self.db_box)
        db_layout.setContentsMargins(12, 10, 12, 10)
        db_layout.setSpacing(6)

        self.lbl_db_path = QLabel(f"DB: {self._db_path}")
        self.lbl_db_path.setObjectName("tx_db_label")
        self.lbl_db_path.setWordWrap(True)

        db_layout.addWidget(self.lbl_db_path)
        layout.addWidget(self.db_box)

        return frame

    def _build_history_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("tx_history_panel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)

        self.lbl_hist_title = QLabel("LỊCH SỬ GẦN NHẤT")
        self.lbl_hist_title.setObjectName("tx_block_title")

        self.lbl_hist_hint = QLabel("15 phiên mới nhất")
        self.lbl_hist_hint.setObjectName("tx_small_hint")

        top.addWidget(self.lbl_hist_title)
        top.addStretch(1)
        top.addWidget(self.lbl_hist_hint)

        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(
            ["Phiên", "Xúc xắc", "Tổng", "Kết quả", "Tiền"]
        )
        self._setup_table(self.history_table)

        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)

        layout.addLayout(top)
        layout.addWidget(self.history_table, 1)

        return frame

    def _build_status_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("tx_status_bar")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)

        self.global_status_label = QLabel("DB OK  •  15 rounds  •  cập nhật 1.5s")
        self.global_status_label.setObjectName("tx_status_label")
        self.global_status_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.global_status_label)
        return frame

    # ==========================================================
    # SMALL BUILDERS
    # ==========================================================
    def _make_info_chip(self, title: str, value: str) -> Dict[str, object]:
        frame = QFrame()
        frame.setObjectName("tx_info_chip")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("tx_chip_title")
        lbl_title.setAlignment(Qt.AlignCenter)

        lbl_value = QLabel(value)
        lbl_value.setObjectName("tx_chip_value")
        lbl_value.setAlignment(Qt.AlignCenter)

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_value)

        return {"frame": frame, "value": lbl_value}

    def _make_die_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("tx_die")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedSize(56, 56)
        return lbl

    def _make_metric_card(self, title: str, value: str) -> Dict[str, object]:
        frame = QFrame()
        frame.setObjectName("tx_metric_card")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("tx_metric_title")

        lbl_value = QLabel(value)
        lbl_value.setObjectName("tx_metric_value")
        lbl_value.setWordWrap(True)

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_value, 1)

        return {"frame": frame, "value": lbl_value}

    def _make_sequence_token(self, side: str) -> QLabel:
        lbl = QLabel()
        lbl.setFixedSize(18, 18)

        if side == "tai":
            lbl.setStyleSheet("""
                background: #111111;
                border: 2px solid #E5E7EB;
                border-radius: 9px;
            """)
        elif side == "xiu":
            lbl.setStyleSheet("""
                background: #F8FAFC;
                border: 2px solid #0F172A;
                border-radius: 9px;
            """)
        else:
            lbl.setStyleSheet("""
                background: #475569;
                border: 2px solid #64748B;
                border-radius: 9px;
            """)

        return lbl

    def _setup_table(self, table: QTableWidget) -> None:
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setShowGrid(True)
        table.setSortingEnabled(False)
        table.setFocusPolicy(Qt.NoFocus)

    # ==========================================================
    # RESPONSIVE
    # ==========================================================
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rebuild_layout()

    def _rebuild_layout(self, force: bool = False) -> None:
        width = max(self.width(), self.scroll.viewport().width())
        mode = "wide" if width >= 1220 else "stack"

        if not force and mode == self._current_mode:
            return
        self._current_mode = mode

        while self.evidence_host.count():
            item = self.evidence_host.takeAt(0)
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)

        if mode == "wide":
            row = QHBoxLayout()
            row.setSpacing(14)
            row.addWidget(self.evidence_panel, 46)
            row.addWidget(self.history_panel, 54)
            self.evidence_host.addLayout(row)
        else:
            col = QVBoxLayout()
            col.setSpacing(14)
            col.addWidget(self.evidence_panel)
            col.addWidget(self.history_panel, 1)
            self.evidence_host.addLayout(col)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)

    # ==========================================================
    # STYLE
    # ==========================================================
    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget {
                background: #0B1220;
                color: #E5E7EB;
                font-family: "Segoe UI";
                font-size: 13px;
            }

            QScrollArea {
                border: none;
                background: #0B1220;
            }

            QFrame#tx_top_bar,
            QFrame#tx_state_panel,
            QFrame#tx_decision_panel,
            QFrame#tx_evidence_panel,
            QFrame#tx_history_panel,
            QFrame#tx_status_bar {
                background: #111827;
                border: 1px solid #1F2937;
                border-radius: 18px;
            }

            QFrame#tx_info_chip,
            QFrame#tx_sequence_box,
            QFrame#tx_metric_card,
            QFrame#tx_ai_box,
            QFrame#tx_db_box {
                background: #0F172A;
                border: 1px solid #233047;
                border-radius: 14px;
            }

            QLabel#tx_title {
                color: #F8FAFC;
                font-size: 25px;
                font-weight: 1000;
            }

            QLabel#tx_subtitle {
                color: #94A3B8;
                font-size: 12px;
                font-weight: 700;
            }

            QLabel#tx_live_badge {
                background: #991B1B;
                color: #FFFFFF;
                border: 1px solid #EF4444;
                border-radius: 10px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 1000;
                min-width: 80px;
            }

            QPushButton#tx_refresh_btn {
                background: #1D4ED8;
                color: #FFFFFF;
                border: none;
                border-radius: 10px;
                padding: 9px 14px;
                font-size: 12px;
                font-weight: 1000;
            }

            QPushButton#tx_refresh_btn:hover {
                background: #2563EB;
            }

            QPushButton#tx_refresh_btn:pressed {
                background: #1E40AF;
            }

            QLabel#tx_chip_title,
            QLabel#tx_metric_title,
            QLabel#tx_db_label,
            QLabel#tx_small_hint,
            QLabel#tx_status_label {
                color: #94A3B8;
                font-size: 11px;
                font-weight: 800;
            }

            QLabel#tx_chip_value {
                color: #F8FAFC;
                font-size: 18px;
                font-weight: 1000;
            }

            QLabel#tx_result_hero {
                color: #F8FAFC;
                background: #0F172A;
                border: 1px solid #334155;
                border-radius: 20px;
                padding: 18px 20px;
                font-size: 52px;
                font-weight: 1000;
            }

            QLabel#tx_die {
                background: #F8FAFC;
                color: #0F172A;
                border: 2px solid #CBD5E1;
                border-radius: 14px;
                font-size: 22px;
                font-weight: 1000;
            }

            QLabel#tx_block_title {
                color: #F8FAFC;
                font-size: 15px;
                font-weight: 1000;
            }

            QLabel#tx_decision_hero {
                color: #FFFFFF;
                background: #0F172A;
                border: 2px solid #334155;
                border-radius: 18px;
                padding: 16px 18px;
                font-size: 34px;
                font-weight: 1000;
            }

            QLabel#tx_reason_line {
                color: #E5E7EB;
                font-size: 14px;
                font-weight: 700;
            }

            QLabel#tx_metric_value,
            QLabel#tx_ai_line {
                color: #F8FAFC;
                font-size: 14px;
                font-weight: 800;
            }

            QTableWidget {
                background: #0F172A;
                alternate-background-color: #111C32;
                border: 1px solid #233047;
                border-radius: 14px;
                color: #E5E7EB;
                gridline-color: #233047;
                selection-background-color: #1E40AF;
                font-size: 13px;
            }

            QHeaderView::section {
                background: #111827;
                color: #CBD5E1;
                border: none;
                border-bottom: 1px solid #233047;
                padding: 8px 6px;
                font-size: 12px;
                font-weight: 1000;
            }
        """)

    # ==========================================================
    # DB
    # ==========================================================
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def refresh_from_db(self) -> None:
        try:
            if not os.path.exists(self._db_path):
                self.global_status_label.setText("Chưa thấy file DB")
                return

            conn = self._connect()
            try:
                latest_round = conn.execute("""
                    SELECT *
                    FROM tx_rounds
                    ORDER BY last_seen_at DESC
                    LIMIT 1
                """).fetchone()

                history_rows = conn.execute("""
                    SELECT *
                    FROM tx_rounds
                    ORDER BY last_seen_at DESC
                    LIMIT 15
                """).fetchall()

                final_round_rows = conn.execute("""
                    SELECT sid, result_side, total, last_seen_at
                    FROM (
                        SELECT sid, result_side, total, last_seen_at
                        FROM tx_rounds
                        WHERE is_final = 1
                          AND LOWER(COALESCE(result_side, '')) IN ('tai', 'xiu')
                        ORDER BY last_seen_at DESC
                        LIMIT 500
                    ) t
                    ORDER BY last_seen_at ASC
                """).fetchall()
            finally:
                conn.close()

            self._update_state_ui(latest_round)
            self._update_history_ui(history_rows)
            self._update_ai_ui(final_round_rows)
            self._update_pattern_ui(final_round_rows)
            self.auto_snapshot_ready.emit(latest_round, final_round_rows)

            self.global_status_label.setText(
                f"DB OK  •  15 rounds  •  final={len(final_round_rows)}  •  cập nhật 1.5s"
            )
        except Exception as e:
            self.global_status_label.setText(f"Lỗi đọc DB: {e}")

    # ==========================================================
    # UPDATE UI
    # ==========================================================
    def _update_state_ui(self, row: Optional[sqlite3.Row]) -> None:
        if row is None:
            self.state_round_chip["value"].setText("-")
            self.state_status_chip["value"].setText("-")
            self.state_total_chip["value"].setText("-")

            self.lbl_result.setText("-")
            self.lbl_die_1.setText("-")
            self.lbl_die_2.setText("-")
            self.lbl_die_3.setText("-")
            self._style_result_box("neutral")
            return

        sid = str(row["sid"] or "-")
        is_final = int(row["is_final"] or 0)
        total = row["total"]
        result_side = str(row["result_side"] or "").lower()

        d1, d2, d3 = row["dice_1"], row["dice_2"], row["dice_3"]

        self.state_round_chip["value"].setText(sid)
        self.state_status_chip["value"].setText("ĐÃ CHỐT" if is_final == 1 else "ĐANG CƯỢC")
        self.state_total_chip["value"].setText(str(total) if total is not None else "-")

        self.lbl_die_1.setText(str(d1) if d1 is not None else "-")
        self.lbl_die_2.setText(str(d2) if d2 is not None else "-")
        self.lbl_die_3.setText(str(d3) if d3 is not None else "-")

        if result_side == "tai":
            self.lbl_result.setText("⚫ TÀI")
            self._style_result_box("tai")
        elif result_side == "xiu":
            self.lbl_result.setText("⚪ XỈU")
            self._style_result_box("xiu")
        else:
            self.lbl_result.setText(str(total) if total is not None else "-")
            self._style_result_box("neutral")

    def _update_history_ui(self, rows: List[sqlite3.Row]) -> None:
        self.history_table.setRowCount(len(rows))

        for row_idx, r in enumerate(rows):
            dice = "-"
            if r["dice_1"] is not None and r["dice_2"] is not None and r["dice_3"] is not None:
                dice = f"{r['dice_1']}-{r['dice_2']}-{r['dice_3']}"

            side = str(r["result_side"] or "").lower()
            if side == "tai":
                result_text = "⚫ TÀI"
            elif side == "xiu":
                result_text = "⚪ XỈU"
            else:
                result_text = "-"

            bet_text = (
                f"T {self._format_money(int(r['tai_total_bet'] or 0))}"
                f" | X {self._format_money(int(r['xiu_total_bet'] or 0))}"
            )

            values = [
                str(r["sid"]),
                dice,
                str(r["total"] if r["total"] is not None else "-"),
                result_text,
                bet_text,
            ]

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 3:
                    self._style_history_result(item, side)

                self.history_table.setItem(row_idx, col_idx, item)

    def _update_ai_ui(self, final_rows: List[sqlite3.Row]) -> None:
        try:
            overview = build_taixiu_overview(final_rows)
        except Exception as e:
            self.lbl_ai_quick.setText(f"AI lỗi: {e}")
            self.lbl_ai_extra.setText("Kiểm tra module taixiu_overview_ai.py")
            self.card_warning["value"].setText("AI lỗi")
            self._set_decision("neutral", "→ ĐANG PHÂN TÍCH")
            self._set_reasons(["-"])
            return

        bias_text = overview.today_bias_text or "-"
        hi1 = overview.highlight_lines[0] if len(overview.highlight_lines) > 0 else "-"
        hi2 = overview.highlight_lines[1] if len(overview.highlight_lines) > 1 else "-"
        warning = overview.warning_lines[0] if len(overview.warning_lines) > 0 else "Chưa có cảnh báo nổi bật."

        self.lbl_ai_quick.setText(f"• {bias_text}")
        self.lbl_ai_extra.setText(hi1 if hi1 and hi1 != "-" else hi2 if hi2 and hi2 != "-" else "-")
        self.card_warning["value"].setText(warning)

        decision_mode, decision_text, reasons = self._build_decision_from_overview(
            overview=overview,
            quick_text=self.lbl_ai_quick.text(),
            extra_text=self.lbl_ai_extra.text(),
            warning_text=warning,
        )
        self._set_decision(decision_mode, decision_text)
        self._set_reasons(reasons)

    def _update_pattern_ui(self, final_rows: List[sqlite3.Row]) -> None:
        sides = [str(r["result_side"] or "").lower() for r in final_rows]
        pattern_info = summarize_patterns(sides, limit=200)

        signature = (
            pattern_info.current_pattern.key,
            pattern_info.current_pattern.display_name,
            pattern_info.current_pattern.length,
            pattern_info.current_pattern.strength_label,
            pattern_info.recent_sequence_text,
            pattern_info.total_rounds_used,
            tuple((item.key, item.count) for item in pattern_info.stat_items),
        )
        if signature == self._last_pattern_signature:
            return
        self._last_pattern_signature = signature

        current_name = pattern_info.current_pattern.display_name or "KHÔNG RÕ"
        self.card_pattern["value"].setText(current_name)
        self._style_pattern_card(current_name)

        count_map = {item.key: item.count for item in pattern_info.stat_items}
        self.card_warning["value"].setText(self.card_warning["value"].text())

        sides_recent = sides[-12:] if sides else []
        self._render_recent_sequence(sides_recent)

    # ==========================================================
    # DECISION HELPERS
    # ==========================================================
    def _build_decision_from_overview(
        self,
        overview,
        quick_text: str,
        extra_text: str,
        warning_text: str,
    ):
        # default
        mode = "neutral"
        decision_text = "→ KHÔNG ĐÁNH"
        reasons: List[str] = []

        lower_all = " ".join([
            str(getattr(overview, "today_bias_text", "") or ""),
            quick_text or "",
            extra_text or "",
            warning_text or "",
        ]).lower()

        if "tài" in lower_all and "xỉu" not in lower_all:
            mode = "tai"
            decision_text = "→ ĐÁNH TÀI"
        elif "xỉu" in lower_all and "tài" not in lower_all:
            mode = "xiu"
            decision_text = "→ ĐÁNH XỈU"
        else:
            mode = "neutral"
            decision_text = "→ KHÔNG ĐÁNH"

        pattern_text = self.card_pattern["value"].text().strip()
        money_text = self.card_money["value"].text().strip()
        warning_clean = warning_text.strip() if warning_text else "-"

        if pattern_text and pattern_text != "KHÔNG RÕ":
            reasons.append(f"- {pattern_text}")
        if money_text and money_text != "-":
            reasons.append(f"- {money_text}")
        if warning_clean and warning_clean != "-" and "chưa có cảnh báo" not in warning_clean.lower():
            reasons.append(f"- {warning_clean}")

        if not reasons:
            reasons = ["- Chưa đủ tín hiệu rõ", "- Ưu tiên chờ thêm", "- Không nên vào lệnh vội"]

        return mode, decision_text, reasons[:3]

    def _set_decision(self, mode: str, text: str) -> None:
        self.lbl_decision.setText(text)

        if mode == "tai":
            self.lbl_decision.setStyleSheet("""
                color: #FFFFFF;
                background: #111111;
                border: 2px solid #E5E7EB;
                border-radius: 18px;
                padding: 16px 18px;
                font-size: 34px;
                font-weight: 1000;
            """)
        elif mode == "xiu":
            self.lbl_decision.setStyleSheet("""
                color: #0F172A;
                background: #F8FAFC;
                border: 2px solid #CBD5E1;
                border-radius: 18px;
                padding: 16px 18px;
                font-size: 34px;
                font-weight: 1000;
            """)
        else:
            self.lbl_decision.setStyleSheet("""
                color: #F8FAFC;
                background: #0F172A;
                border: 2px solid #334155;
                border-radius: 18px;
                padding: 16px 18px;
                font-size: 34px;
                font-weight: 1000;
            """)

    def _set_reasons(self, reasons: List[str]) -> None:
        lines = reasons[:3] + ["-"] * max(0, 3 - len(reasons[:3]))
        self.lbl_reason_1.setText(lines[0])
        self.lbl_reason_2.setText(lines[1])
        self.lbl_reason_3.setText(lines[2])

    # ==========================================================
    # VISUAL HELPERS
    # ==========================================================
    def _style_result_box(self, mode: str) -> None:
        if mode == "tai":
            self.lbl_result.setStyleSheet("""
                color: #FFFFFF;
                background: #111111;
                border: 2px solid #E5E7EB;
                border-radius: 20px;
                padding: 18px 20px;
                font-size: 52px;
                font-weight: 1000;
            """)
        elif mode == "xiu":
            self.lbl_result.setStyleSheet("""
                color: #0F172A;
                background: #F8FAFC;
                border: 2px solid #CBD5E1;
                border-radius: 20px;
                padding: 18px 20px;
                font-size: 52px;
                font-weight: 1000;
            """)
        else:
            self.lbl_result.setStyleSheet("""
                color: #F8FAFC;
                background: #0F172A;
                border: 1px solid #334155;
                border-radius: 20px;
                padding: 18px 20px;
                font-size: 52px;
                font-weight: 1000;
            """)

    def _style_pattern_card(self, current_name: str) -> None:
        name_upper = str(current_name or "").upper()
        color = "#F8FAFC"
        bg = "#0F172A"
        border = "#334155"

        if "BỆT TÀI" in name_upper:
            color = "#FFFFFF"
            bg = "#111111"
            border = "#E5E7EB"
        elif "BỆT XỈU" in name_upper:
            color = "#0F172A"
            bg = "#F8FAFC"
            border = "#CBD5E1"
        elif "1:1" in name_upper:
            color = "#DBEAFE"
            bg = "#102A43"
            border = "#60A5FA"
        elif "2:2" in name_upper:
            color = "#FEF3C7"
            bg = "#3F2A12"
            border = "#F59E0B"
        elif "3:3" in name_upper:
            color = "#F3E8FF"
            bg = "#312E81"
            border = "#A78BFA"

        self.card_pattern["value"].setStyleSheet(f"""
            background: {bg};
            color: {color};
            border: 1px solid {border};
            border-radius: 12px;
            padding: 10px 12px;
            font-size: 20px;
            font-weight: 1000;
        """)

    def _style_history_result(self, item: QTableWidgetItem, side: str) -> None:
        if side == "tai":
            item.setForeground(QColor("#FFFFFF"))
            item.setBackground(QColor("#111111"))
        elif side == "xiu":
            item.setForeground(QColor("#0F172A"))
            item.setBackground(QColor("#F8FAFC"))

    def _render_recent_sequence(self, sides: List[str]) -> None:
        while self.sequence_layout.count():
            item = self.sequence_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not sides:
            return

        for side in sides:
            self.sequence_layout.addWidget(self._make_sequence_token(side))
        self.sequence_layout.addStretch(1)

        tai_count = sum(1 for s in sides if s == "tai")
        xiu_count = sum(1 for s in sides if s == "xiu")
        total = tai_count + xiu_count

        if total > 0:
            tai_pct = int((tai_count / total) * 100)
            xiu_pct = 100 - tai_pct
            self.card_money["value"].setText(f"Tài {tai_pct}% | Xỉu {xiu_pct}%")
        else:
            self.card_money["value"].setText("Tài 0% | Xỉu 0%")

    def _format_money(self, value: int) -> str:
        v = int(value or 0)
        if v >= 1_000_000_000:
            return f"{v / 1_000_000_000:.1f}B"
        if v >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if v >= 1_000:
            return f"{v / 1_000:.1f}K"
        return str(v)

    # ==========================================================
    # compatibility
    # ==========================================================
    def dat_trang_thai(self, text: str) -> None:
        self.global_status_label.setText(text)

    def dat_trang_thai_profile(self, profile_id: str, text: str) -> None:
        pass