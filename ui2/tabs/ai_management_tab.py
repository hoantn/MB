from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.logger import log
from ui2.tabs.strategy2.auto_choice_rules import (
    delete_rule,
    export_rules_json,
    get_ai_learning_settings,
    import_rules,
    list_rules,
    save_ai_learning_settings,
    set_rule_enabled,
)


_BG = "#0f1216"
_PANEL = "#151a20"
_PANEL2 = "#1b222b"
_LINE = "#303946"
_LINE2 = "#222a34"
_TEXT = "#f3f7fb"
_MUTED = "#9aa8b5"
_BLUE = "#4e8bd9"
_GREEN = "#28a766"
_AMBER = "#d89a2b"
_RED = "#d65b65"


def _codes(value: object) -> list[str]:
    return [str(x).strip().upper() for x in str(value or "").split(",") if str(x).strip()]


class AIManagementTab(QWidget):
    """Manage user-saved auto suggestion choices.

    This tab intentionally manages only the persisted AI rule layer. Runtime
    auto selection still lives in StrategyTab/auto_suggestion_picker.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._selected_id: Optional[int] = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget {{ background:{_BG}; color:{_TEXT}; font-size:12px; }}
            QFrame#panel {{ background:{_PANEL}; border:1px solid {_LINE}; border-radius:6px; }}
            QFrame#box {{ background:#10161d; border:1px solid {_LINE2}; border-radius:6px; }}
            QLabel#title {{ font-size:16px; font-weight:900; }}
            QLabel#muted {{ color:{_MUTED}; }}
            QLineEdit, QComboBox, QPlainTextEdit {{
                background:#0c1117; color:{_TEXT}; border:1px solid #3a4452;
                border-radius:5px; padding:5px;
            }}
            QTableWidget {{
                background:#0f151c; color:{_TEXT}; border:0; gridline-color:{_LINE2};
                selection-background-color:#173050; selection-color:{_TEXT};
            }}
            QHeaderView::section {{
                background:#1d232b; color:#b9c7d4; border:0; border-bottom:1px solid {_LINE};
                padding:7px; font-weight:800;
            }}
            QPushButton {{
                background:#222a35; color:white; border:1px solid {_LINE}; border-radius:5px;
                padding:6px 10px; font-weight:800;
            }}
            QPushButton:disabled {{ color:#6f7b86; background:#161c23; }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("panel")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Quản Lý AI")
        title.setObjectName("title")
        sub = QLabel("Quản lý gợi ý [auto] đã lưu trong DB: một rule chung cho mỗi bộ 13 lá, không chia OPP/tự thân.")
        sub.setObjectName("muted")
        title_col.addWidget(title)
        title_col.addWidget(sub)
        h.addLayout(title_col, 1)

        self.lbl_stats = QLabel("-")
        self.lbl_stats.setObjectName("muted")
        h.addWidget(self.lbl_stats)
        self.btn_refresh = self._button("Làm mới", "#222a35")
        self.btn_export = self._button("Xuất backup", "#254c7d", _BLUE)
        self.btn_import = self._button("Nhập backup", "#24533b", _GREEN)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_export.clicked.connect(self._export_json)
        self.btn_import.clicked.connect(self._import_json)
        h.addWidget(self.btn_refresh)
        h.addWidget(self.btn_export)
        h.addWidget(self.btn_import)
        root.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left = QFrame()
        left.setObjectName("panel")
        left.setMinimumWidth(270)
        left.setMaximumWidth(330)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(10, 10, 10, 10)
        left_lay.setSpacing(10)

        left_lay.addWidget(self._section_title("Bộ lọc"))
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Tìm theo 13 lá, label, thế bài...")
        self.cbo_enabled = QComboBox()
        self.cbo_enabled.addItem("Tất cả trạng thái", None)
        self.cbo_enabled.addItem("Đang bật", True)
        self.cbo_enabled.addItem("Đã tắt", False)
        for w in (self.txt_search, self.cbo_enabled):
            left_lay.addWidget(w)
        self.txt_search.returnPressed.connect(self.refresh)
        self.cbo_enabled.currentIndexChanged.connect(self.refresh)

        left_lay.addWidget(self._section_title("Học gần giống"))
        learning_box = QFrame()
        learning_box.setObjectName("box")
        learning_lay = QGridLayout(learning_box)
        learning_lay.setContentsMargins(10, 8, 10, 8)
        learning_lay.setSpacing(8)
        self.chk_similarity = QCheckBox("Dùng rule gần giống")
        self.spn_similarity = QSpinBox()
        self.spn_similarity.setRange(50, 100)
        self.spn_similarity.setSuffix("%")
        self.spn_similarity.setSingleStep(1)
        self.lbl_similarity_note = QLabel(
            "Exact 13 lá vẫn ưu tiên cao nhất. Nếu không có exact, AI chọn rule gần giống có điểm cao nhất."
        )
        self.lbl_similarity_note.setWordWrap(True)
        self.lbl_similarity_note.setObjectName("muted")
        learning_lay.addWidget(self.chk_similarity, 0, 0, 1, 2)
        learning_lay.addWidget(QLabel("Ngưỡng"), 1, 0)
        learning_lay.addWidget(self.spn_similarity, 1, 1)
        learning_lay.addWidget(self.lbl_similarity_note, 2, 0, 1, 2)
        left_lay.addWidget(learning_box)
        self._load_learning_settings()
        self.chk_similarity.toggled.connect(self._save_learning_settings)
        self.spn_similarity.valueChanged.connect(self._save_learning_settings)

        left_lay.addWidget(self._section_title("Tổng quan"))
        stats_box = QFrame()
        stats_box.setObjectName("box")
        grid = QGridLayout(stats_box)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(8)
        self.stat_total = self._metric("0", "Tổng rule")
        self.stat_enabled = self._metric("0", "Đang bật")
        self.stat_disabled = self._metric("0", "Đã tắt")
        self.stat_hits = self._metric("0", "Lần dùng")
        grid.addWidget(self.stat_total, 0, 0)
        grid.addWidget(self.stat_enabled, 0, 1)
        grid.addWidget(self.stat_disabled, 1, 0)
        grid.addWidget(self.stat_hits, 1, 1)
        left_lay.addWidget(stats_box)

        left_lay.addWidget(self._section_title("Ghi chú luồng"))
        note = QLabel(
            "Auto chọn theo thứ tự:\n"
            "1. Rule người dùng đã lưu cho đúng 13 lá.\n"
            "2. Money engine nếu không có rule.\n"
            "3. Fallback gợi ý đầu tiên nếu thiếu dữ liệu.\n\n"
            "Tắt rule sẽ giữ dữ liệu nhưng auto không dùng rule đó."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        left_lay.addWidget(note)
        left_lay.addStretch()
        splitter.addWidget(left)

        center = QFrame()
        center.setObjectName("panel")
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 10, 10, 8)
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel("Dữ liệu học trong DB"), 1)
        self.btn_enable = self._button("Bật", "#24533b", _GREEN)
        self.btn_disable = self._button("Tắt", "#5d4218", _AMBER)
        self.btn_delete = self._button("Xóa", "#87333a", _RED)
        self.btn_enable.clicked.connect(lambda: self._set_selected_enabled(True))
        self.btn_disable.clicked.connect(lambda: self._set_selected_enabled(False))
        self.btn_delete.clicked.connect(self._delete_selected)
        toolbar.addWidget(self.btn_enable)
        toolbar.addWidget(self.btn_disable)
        toolbar.addWidget(self.btn_delete)
        center_lay.addLayout(toolbar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Trạng thái", "Auto chọn", "13 lá", "Lần dùng", "Cập nhật", "Nguồn"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.setColumnWidth(0, 54)
        self.table.setColumnWidth(1, 82)
        self.table.setColumnWidth(2, 175)
        self.table.setColumnWidth(4, 72)
        self.table.setColumnWidth(5, 145)
        self.table.setColumnWidth(6, 130)
        center_lay.addWidget(self.table, 1)
        splitter.addWidget(center)

        right = QFrame()
        right.setObjectName("panel")
        right.setMinimumWidth(360)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(10, 10, 10, 10)
        right_lay.setSpacing(8)
        self.detail_title = QLabel("Chưa chọn rule")
        self.detail_title.setObjectName("title")
        right_lay.addWidget(self.detail_title)
        self.detail_meta = QLabel("-")
        self.detail_meta.setObjectName("muted")
        self.detail_meta.setWordWrap(True)
        right_lay.addWidget(self.detail_meta)

        right_lay.addWidget(self._section_title("Chi tiết 13 lá"))
        self.txt_hand = QPlainTextEdit()
        self.txt_hand.setReadOnly(True)
        self.txt_hand.setFixedHeight(76)
        right_lay.addWidget(self.txt_hand)

        right_lay.addWidget(self._section_title("Bản xếp auto đã lưu"))
        self.txt_split = QPlainTextEdit()
        self.txt_split.setReadOnly(True)
        self.txt_split.setFixedHeight(112)
        right_lay.addWidget(self.txt_split)

        right_lay.addWidget(self._section_title("Thông tin DB"))
        self.txt_db = QPlainTextEdit()
        self.txt_db.setReadOnly(True)
        right_lay.addWidget(self.txt_db, 1)
        splitter.addWidget(right)
        splitter.setSizes([290, 720, 390])

        self._update_action_state()

    def _button(self, text: str, bg: str, border: str = "transparent") -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(
            f"QPushButton {{ background:{bg}; border-color:{border}; }}"
            f"QPushButton:hover {{ border-color:{border if border != 'transparent' else _BLUE}; }}"
        )
        return btn

    def _section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight:900; color:#dbeafe; margin-top:4px;")
        return lbl

    def _metric(self, value: str, label: str) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        v = QLabel(value)
        v.setProperty("metric_value", True)
        v.setStyleSheet("font-size:18px; font-weight:900;")
        l = QLabel(label)
        l.setObjectName("muted")
        lay.addWidget(v)
        lay.addWidget(l)
        box.value_label = v  # type: ignore[attr-defined]
        return box

    def _load_learning_settings(self) -> None:
        settings = get_ai_learning_settings()
        self.chk_similarity.blockSignals(True)
        self.spn_similarity.blockSignals(True)
        self.chk_similarity.setChecked(bool(settings.get("similarity_enabled", True)))
        self.spn_similarity.setValue(int(settings.get("similarity_threshold") or 80))
        self.spn_similarity.setEnabled(self.chk_similarity.isChecked())
        self.chk_similarity.blockSignals(False)
        self.spn_similarity.blockSignals(False)

    def _save_learning_settings(self, *_args) -> None:
        self.spn_similarity.setEnabled(self.chk_similarity.isChecked())
        ok = save_ai_learning_settings(
            similarity_enabled=self.chk_similarity.isChecked(),
            similarity_threshold=self.spn_similarity.value(),
        )
        if not ok:
            QMessageBox.warning(self, "Quản Lý AI", "Không lưu được cấu hình học gần giống.")

    def refresh(self) -> None:
        try:
            enabled_filter = self.cbo_enabled.currentData()
            self._rows = list_rules(
                enabled=enabled_filter if isinstance(enabled_filter, bool) else None,
                search=self.txt_search.text(),
            )
            self._fill_table()
            self._fill_stats()
        except Exception:
            log.exception("[AIManagementTab] refresh failed")
            QMessageBox.warning(self, "Quản Lý AI", "Không đọc được dữ liệu AI trong DB.")

    def _fill_table(self) -> None:
        self.table.setRowCount(len(self._rows))
        for row_idx, row in enumerate(self._rows):
            enabled = bool(int(row.get("enabled") or 0))
            values = [
                row.get("id"),
                "Bật" if enabled else "Tắt",
                row.get("selected_template") or row.get("label") or "-",
                row.get("hand_key") or "-",
                row.get("hit_count") or 0,
                row.get("updated_at") or "-",
                row.get("source") or "-",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, int(row.get("id") or 0))
                if col == 1:
                    item.setForeground(Qt.green if enabled else Qt.yellow)
                self.table.setItem(row_idx, col, item)
        self.table.resizeColumnToContents(0)
        self._restore_or_select_first()

    def _restore_or_select_first(self) -> None:
        if not self._rows:
            self._selected_id = None
            self.table.clearSelection()
            self._show_detail(None)
            self._update_action_state()
            return
        selected_id = self._selected_id
        row_to_select = 0
        if selected_id is not None:
            for i, row in enumerate(self._rows):
                if int(row.get("id") or 0) == int(selected_id):
                    row_to_select = i
                    break
        self.table.selectRow(row_to_select)

    def _fill_stats(self) -> None:
        all_rows = list_rules(limit=100000)
        total = len(all_rows)
        enabled = sum(1 for r in all_rows if int(r.get("enabled") or 0))
        disabled = total - enabled
        hits = sum(int(r.get("hit_count") or 0) for r in all_rows)
        self.stat_total.value_label.setText(str(total))  # type: ignore[attr-defined]
        self.stat_enabled.value_label.setText(str(enabled))  # type: ignore[attr-defined]
        self.stat_disabled.value_label.setText(str(disabled))  # type: ignore[attr-defined]
        self.stat_hits.value_label.setText(str(hits))  # type: ignore[attr-defined]
        self.lbl_stats.setText(f"{enabled}/{total} rule đang bật")

    def _on_selection_changed(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self._selected_id = None
            self._show_detail(None)
            self._update_action_state()
            return
        rule_id = int(items[0].data(Qt.UserRole) or 0)
        self._selected_id = rule_id
        row = next((r for r in self._rows if int(r.get("id") or 0) == rule_id), None)
        self._show_detail(row)
        self._update_action_state()

    def _show_detail(self, row: Optional[dict]) -> None:
        if not row:
            self.detail_title.setText("Chưa chọn rule")
            self.detail_meta.setText("-")
            self.txt_hand.setPlainText("")
            self.txt_split.setPlainText("")
            self.txt_db.setPlainText("")
            return
        enabled = bool(int(row.get("enabled") or 0))
        title = row.get("selected_template") or row.get("label") or "Gợi ý đã lưu"
        self.detail_title.setText(str(title))
        self.detail_meta.setText(
            f"ID #{row.get('id')} | {'Đang bật' if enabled else 'Đã tắt'} | "
            f"dùng {row.get('hit_count') or 0} lần | nguồn: {row.get('source') or '-'}"
        )
        self.txt_hand.setPlainText(str(row.get("hand_key") or "").replace(",", ", "))
        self.txt_split.setPlainText(
            "Chi 3: " + ", ".join(_codes(row.get("chi3_codes"))) + "\n"
            "Chi 2: " + ", ".join(_codes(row.get("chi2_codes"))) + "\n"
            "Chi 1: " + ", ".join(_codes(row.get("chi1_codes"))) + "\n\n"
            "Split key:\n" + str(row.get("selected_split_key") or "")
        )
        self.txt_db.setPlainText(json.dumps(row, ensure_ascii=False, indent=2))

    def _update_action_state(self) -> None:
        has = self._selected_id is not None
        for btn in (self.btn_enable, self.btn_disable, self.btn_delete):
            btn.setEnabled(has)

    def _selected_row(self) -> Optional[dict]:
        if self._selected_id is None:
            return None
        return next((r for r in self._rows if int(r.get("id") or 0) == int(self._selected_id)), None)

    def _set_selected_enabled(self, enabled: bool) -> None:
        row = self._selected_row()
        if not row:
            return
        if not set_rule_enabled(int(row["id"]), enabled):
            QMessageBox.warning(self, "Quản Lý AI", "Không cập nhật được trạng thái rule.")
            return
        self.refresh()

    def _delete_selected(self) -> None:
        row = self._selected_row()
        if not row:
            return
        answer = QMessageBox.question(
            self,
            "Xóa rule AI",
            f"Bạn có chắc muốn xóa rule #{row.get('id')} không?\nThao tác này không thể hoàn tác.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if not delete_rule(int(row["id"])):
            QMessageBox.warning(self, "Quản Lý AI", "Không xóa được rule.")
            return
        self._selected_id = None
        self.refresh()

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Xuất backup AI",
            "auto_choice_rules.json",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(export_rules_json())
            QMessageBox.information(self, "Quản Lý AI", "Đã xuất backup AI.")
        except Exception as exc:
            log.exception("[AIManagementTab] export failed")
            QMessageBox.warning(self, "Quản Lý AI", f"Xuất backup lỗi: {exc}")

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Nhập backup AI", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("File backup không đúng định dạng danh sách.")
            count = import_rules(data)
            QMessageBox.information(self, "Quản Lý AI", f"Đã nhập {count} rule AI.")
            self.refresh()
        except Exception as exc:
            log.exception("[AIManagementTab] import failed")
            QMessageBox.warning(self, "Quản Lý AI", f"Nhập backup lỗi: {exc}")
