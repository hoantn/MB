from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QButtonGroup,
)

from ui2.tabs.dashboard.dashboard_constants import _load_opp_pixmap

try:
    from engine.card import Card
except Exception:
    Card = None


class StrategyView(QWidget):
    """
    Strategy V2 View (gọn):
    - bỏ 2 khung text phía trên list gợi ý
    - list gợi ý dùng itemWidget (rich text)
    - selection rõ: vạch màu trái + nền nhẹ + chữ đậm (không tạo 2 viền)
    """

    profile_changed = Signal(str)          # emits "P1"/"P2"/"P3"
    ngu_label_clicked = Signal(int)        # index in NGU list
    p_label_clicked = Signal(int)          # index in P list
    apply_all_clicked = Signal()           # click ALL apply
    break_sap_lang_clicked = Signal()      # click global sap-lang combo apply
    p_retry_clicked = Signal()            # click reset gợi ý cho P ACTIVE

    CARD_W = 67
    CARD_H = 84

    _ACCENT_7 = ["#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#00c7be", "#007aff", "#af52de"]

    def __init__(self, profiles: List[str], parent=None):
        super().__init__(parent)
        self.profiles = profiles or ["P1", "P2", "P3"]
        self.active_profile = self.profiles[0]

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ================= TOP: cards =================
        top = QHBoxLayout()
        top.setSpacing(8)

        # NGU
        self.box_ngu_cards = QGroupBox("ĐỐI THỦ")
        ngu_lay = QVBoxLayout(self.box_ngu_cards)
        ngu_lay.setContentsMargins(8, 8, 8, 8)
        ngu_lay.setSpacing(6)

        self.lbl_ngu_status = QLabel("Chờ đủ 3P để suy ĐỐI THỦ…")
        self.lbl_ngu_status.setStyleSheet("color:#aaaaaa; font-size:11px;")
        ngu_lay.addWidget(self.lbl_ngu_status)

        self._ngu_row_chi3 = self._make_card_row("Chi 3", 3, with_special=True)
        self._ngu_row_chi2 = self._make_card_row("Chi 2", 5)
        self._ngu_row_chi1 = self._make_card_row("Chi 1", 5)
        ngu_lay.addLayout(self._ngu_row_chi3["layout"])
        ngu_lay.addLayout(self._ngu_row_chi2["layout"])
        ngu_lay.addLayout(self._ngu_row_chi1["layout"])
        top.addWidget(self.box_ngu_cards, 1)

        # P ACTIVE
        self.box_p_cards = QGroupBox("P1 (ACTIVE)")
        p_lay = QVBoxLayout(self.box_p_cards)
        p_lay.setContentsMargins(8, 8, 8, 8)
        p_lay.setSpacing(6)

        # Hàng status + nút reset
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(4)

        self.lbl_p_status = QLabel("Chờ bài…")
        self.lbl_p_status.setStyleSheet("color:#aaaaaa; font-size:11px;")
        status_row.addWidget(self.lbl_p_status, 1)  # label chiếm hết bên trái

        # thêm hàng status vào layout của box
        p_lay.addLayout(status_row)

        # các hàng bài Chi 3 / Chi 2 / Chi 1 như cũ
        self._p_row_chi3 = self._make_card_row("Chi 3", 3, with_special=True)
        self._p_row_chi2 = self._make_card_row("Chi 2", 5)
        self._p_row_chi1 = self._make_card_row("Chi 1", 5)
        p_lay.addLayout(self._p_row_chi3["layout"])
        p_lay.addLayout(self._p_row_chi2["layout"])
        p_lay.addLayout(self._p_row_chi1["layout"])

        top.addWidget(self.box_p_cards, 1)


        root.addLayout(top, 1)
        self.lbl_ngu_special = self._ngu_row_chi3.get("special")
        self.lbl_p_special = self._p_row_chi3.get("special")

        # màu hiện tại (sẽ set từ StrategyTab theo label)
        self._ngu_special_color = "#facc15"
        self._p_special_color = "#facc15"

        # ================= BOTTOM: symmetric blocks =================
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        # Left: NGU list
        self.box_ngu = QGroupBox("ĐỐI THỦ")
        ngu_sel = QVBoxLayout(self.box_ngu)
        ngu_sel.setContentsMargins(8, 8, 8, 8)
        ngu_sel.setSpacing(6)

        self.list_ngu = QListWidget()
        self.list_ngu.setMinimumHeight(160)
        self.list_ngu.setStyleSheet(self._list_style())
        self.list_ngu.itemClicked.connect(lambda _it: self._emit_list_ngu())
        self.list_ngu.currentRowChanged.connect(lambda _r: self._sync_item_selection_style(self.list_ngu))
        ngu_sel.addWidget(self.list_ngu, 1)
        bottom.addWidget(self.box_ngu, 1)

        # Right: P list + actions
        self.box_p = QGroupBox("P (ACTIVE)")
        p_sel_root = QVBoxLayout(self.box_p)
        p_sel_root.setContentsMargins(8, 8, 8, 8)
        p_sel_root.setSpacing(6)
        
        # Header khung gợi ý: nút reset nằm ở đây
        header_row = QHBoxLayout()
        header_row.setSpacing(4)
        # (nếu muốn có text tiêu đề, có thể thêm label bên trái – không bắt buộc)
        # lbl = QLabel("GỢI Ý")
        # lbl.setStyleSheet("font-weight:900;")
        # header_row.addWidget(lbl, 1)

        # nút reset gợi ý P ACTIVE (đẶT TRONG KHUNG GỢI Ý)
        self.btn_p_retry = QPushButton("⟳")
        self.btn_p_retry.setObjectName("btnRetryP")
        self.btn_p_retry.setFixedSize(QSize(30, 25))
        self.btn_p_retry.setToolTip("Quét lại gợi ý cho profile đang chọn")
        self.btn_p_retry.setVisible(True)  # mặc định hiện, render sẽ điều khiển
        self.btn_p_retry.clicked.connect(self.p_retry_clicked.emit)
        header_row.addWidget(self.btn_p_retry, 0, Qt.AlignLeft)

        p_sel_root.addLayout(header_row)        
        # Hàng chính: list gợi ý + cột action (XẾP BÀI, P1/P2/P3, ALL)
        row = QHBoxLayout()
        row.setSpacing(10)

        self.list_p = QListWidget()
        self.list_p.setMinimumHeight(160)
        self.list_p.setStyleSheet(self._list_style())
        self.list_p.itemClicked.connect(lambda _it: self._emit_list_p())
        self.list_p.currentRowChanged.connect(lambda _r: self._sync_item_selection_style(self.list_p))
        row.addWidget(self.list_p, 1)

        act = QVBoxLayout()
        act.setSpacing(8)

        self.btn_hup = QPushButton("XẾP BÀI")
        self.btn_hup.setEnabled(False)
        self.btn_hup.setMinimumWidth(170)
        self.btn_hup.setMinimumHeight(44)
        # dùng theme.py (QSS role="primary") để tự đổi theo Sáng/Tối
        self.btn_hup.setProperty("role", "primary")
        self.btn_hup.setStyleSheet("border-radius:12px; font-weight:900;")
        act.addWidget(self.btn_hup, 0, Qt.AlignRight)

        prof_row = QHBoxLayout()
        prof_row.setSpacing(6)
        self.profile_group = QButtonGroup(self)
        self.profile_group.setExclusive(True)

        for pid in self.profiles:
            b = self._make_pill_button(pid, checkable=True)
            b.clicked.connect(lambda _=False, p=pid: self.profile_changed.emit(p))
            self.profile_group.addButton(b)
            prof_row.addWidget(b)

        act.addLayout(prof_row)

        # ALL button (apply all profiles)
        self.btn_all = self._make_pill_button("ALL", checkable=False)
        self.btn_all.setMinimumHeight(28)
        self.btn_all.clicked.connect(self.apply_all_clicked.emit)
        act.addWidget(self.btn_all, 0, Qt.AlignRight)

        self.btn_break_sap_lang = QPushButton("Bẻ Sập Làng")
        self.btn_break_sap_lang.setVisible(False)
        self.btn_break_sap_lang.setMinimumWidth(130)
        self.btn_break_sap_lang.setMinimumHeight(30)
        self.btn_break_sap_lang.setStyleSheet(
            "QPushButton{border-radius:14px; padding:0 12px; font-weight:900;"
            "background:#f59e0b; color:#111827;}"
            "QPushButton:hover{background:#fbbf24;}"
        )
        self.btn_break_sap_lang.clicked.connect(self.break_sap_lang_clicked.emit)
        act.addWidget(self.btn_break_sap_lang, 0, Qt.AlignRight)

        act.addStretch(1)
        row.addLayout(act, 0)
        p_sel_root.addLayout(row, 1)

        bottom.addWidget(self.box_p, 1)
        root.addLayout(bottom)

        self.set_active_profile(self.active_profile)

    # ---------------- styles ----------------
    def _list_style(self) -> str:
        # item spacing gọn hơn: padding=0; itemWidget margins nhỏ.
        return (
            "QListWidget{border-radius:10px;}"
            "QListWidget::item{padding:0px; border:0px;}"
        )

    def _make_pill_button(self, text: str, checkable: bool) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(bool(checkable))
        b.setMinimumHeight(28)
        if checkable:
            b.setStyleSheet(
                "QPushButton{border-radius:14px; padding:0 10px;}"
                "QPushButton:checked{background: palette(highlight); color: palette(highlighted-text); font-weight:900;}"
            )
        else:
            b.setStyleSheet(
                "QPushButton{border-radius:14px; padding:0 12px;}"
            )
        return b

    def set_break_sap_lang_available(self, available: bool, leader: str = "") -> None:
        self.btn_break_sap_lang.setVisible(bool(available))
        if available and leader:
            self.btn_break_sap_lang.setText(f"Bẻ Sập Làng ({leader})")
        else:
            self.btn_break_sap_lang.setText("Bẻ Sập Làng")

    # ---------------- cards ----------------
    def _make_card_label(self) -> QLabel:
        lab = QLabel()
        lab.setObjectName("richLabel")
        lab.setFixedSize(self.CARD_W, self.CARD_H)
        lab.setStyleSheet("border:1px solid palette(dark); border-radius:6px;")
        lab.setAlignment(Qt.AlignCenter)
        return lab
        
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # cập nhật lại font-size cho label đặc biệt mỗi lần cửa sổ thay đổi
        self._update_special_font_sizes()

    def _make_card_row(self, title: str, n: int, with_special: bool = False):
        row = QHBoxLayout()
        row.setSpacing(6)

        tag = QLabel(title)
        tag.setFixedWidth(46)
        tag.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        tag.setStyleSheet("font-weight:900;")
        row.addWidget(tag, 0)

        labs = []
        for _ in range(n):
            lab = self._make_card_label()
            labs.append(lab)
            row.addWidget(lab, 0)

        special_label = None
        from PySide6.QtWidgets import QSizePolicy

        if with_special:
            special_label = QLabel("")
            special_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            special_label.setStyleSheet("font-weight:900;")
            special_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            special_label.setMinimumWidth(120)   # tránh bị bóp = 0
            row.addWidget(special_label, 1)      # 👈 quan trọng: stretch = 1
        row.addStretch(1)
        return {"layout": row, "labels": labs, "special": special_label}

    def _set_pix(self, lab: QLabel, code: str) -> None:
        if not code:
            lab.setPixmap(QPixmap())
            lab.setText("")
            lab.setToolTip("")
            return

        pix: Optional[QPixmap] = _load_opp_pixmap(code, lab.width(), lab.height())
        if pix is not None:
            lab.setPixmap(pix.scaled(lab.width(), lab.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            lab.setText("")
            lab.setToolTip(code)
        else:
            lab.setPixmap(QPixmap())
            lab.setText(code)
            lab.setToolTip(code)

    def _sort_codes_for_display(self, codes: List[str]) -> List[str]:
        if not codes or Card is None:
            return list(codes or [])
        try:
            cards = [Card.from_code(c) for c in codes if c and c not in ("--", "??")]
            ranks = [getattr(c, "rank", None) for c in cards]
            if len(cards) == 5 and set(ranks) == {"A", "2", "3", "4", "5"}:
                wheel_order = {"A": 0, "2": 1, "3": 2, "4": 3, "5": 4}
                cards = sorted(cards, key=lambda c: wheel_order.get(getattr(c, "rank", ""), 99))
            else:
                cards = sorted(cards, key=lambda c: getattr(c, "rank_index", 0))
            return [c.to_code() for c in cards]
        except Exception:
            return list(codes or [])

    # ---------------- signals ----------------
    def _emit_list_ngu(self) -> None:
        idx = self.list_ngu.currentRow()
        if idx is None or idx < 0:
            return
        self.ngu_label_clicked.emit(int(idx))

    def _emit_list_p(self) -> None:
        idx = self.list_p.currentRow()
        if idx is None or idx < 0:
            return
        self.p_label_clicked.emit(int(idx))

    
    def _set_rich_item_widget_html(self, w: QWidget, html: str) -> None:
        try:
            lab = w.findChild(QLabel, "richLabel")
            if lab is not None:
                lab.setText(html or "")
        except Exception:
            pass

    def update_p_label(self, row: int, html: str) -> None:
        try:
            item = self.list_p.item(row)
            if item is None:
                return
            w = self.list_p.itemWidget(item)
            if w is None:
                return
            self._set_rich_item_widget_html(w, html)
        except Exception:
            pass

    def update_ngu_label(self, row: int, html: str) -> None:
        try:
            item = self.list_ngu.item(row)
            if item is None:
                return
            w = self.list_ngu.itemWidget(item)
            if w is None:
                return
            self._set_rich_item_widget_html(w, html)
        except Exception:
            pass
# ---------------- list rich-item helpers ----------------
    def _make_rich_item_widget(self, html: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        # gọn hơn nữa nhưng vẫn dễ nhìn
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(0)

        lab = QLabel()
        lab.setObjectName("richLabel")
        lab.setTextFormat(Qt.RichText)
        lab.setWordWrap(True)
        lab.setText(html or "")
        lab.setStyleSheet("font-weight:600;")
        lay.addWidget(lab)

        w._mb_label = lab  # type: ignore[attr-defined]
        return w

    def _sync_item_selection_style(self, lw: QListWidget) -> None:
        sel = lw.currentRow()
        for i in range(lw.count()):
            it = lw.item(i)
            w = lw.itemWidget(it)
            if w is None:
                continue

            lab = getattr(w, "_mb_label", None)
            color = self._ACCENT_7[i % len(self._ACCENT_7)]

            if i == sel:
                # selection rõ ràng: vạch trái + nền nhẹ (KHÔNG border trong -> không bị 2 viền)
                w.setStyleSheet(
                    f"background-color: palette(alternate-base);"
                    f"border-left: 4px solid {color};"
                    f"border-radius: 8px;"
                )
                if isinstance(lab, QLabel):
                    lab.setStyleSheet("font-weight:900;")
            else:
                w.setStyleSheet("background: transparent; border-left: 4px solid transparent; border-radius: 8px;")
                if isinstance(lab, QLabel):
                    lab.setStyleSheet("font-weight:600;")


    # ---------------- public API ----------------
    def set_active_profile(self, pid: str) -> None:
        if pid not in self.profiles:
            return
        self.active_profile = pid
        self.box_p_cards.setTitle(f"{pid} (ACTIVE)")
        self.box_p.setTitle(f"{pid} (ACTIVE)")
        for b in self.profile_group.buttons():
            if b.text() == pid:
                b.setChecked(True)

        # đổi profile -> ẩn nút reset, render sẽ quyết định có hiện lại hay không
        if hasattr(self, "set_p_retry_visible"):
            self.set_p_retry_visible(False)

    def set_p_status(self, text: str) -> None:
        self.lbl_p_status.setText(text or "")
        
    def set_p_retry_visible(self, visible: bool) -> None:
        """Hiện/ẩn nút reset gợi ý cho P ACTIVE.

        - visible = True: chỉ nên bật khi P đã có đủ 13 lá nhưng không có gợi ý.
        - visible = False: ẩn trong các trường hợp khác.
        """
        if hasattr(self, "btn_p_retry") and self.btn_p_retry is not None:
            self.btn_p_retry.setVisible(bool(visible))

    def set_ngu_status(self, text: str) -> None:
        self.lbl_ngu_status.setText(text or "")

    # kept for compatibility – no longer shown
    def set_engine_ngu(self, text: str) -> None:
        return

    def set_engine_p(self, text: str) -> None:
        return

    def set_ngu_labels(self, items: List[dict], default_index: int = 0) -> None:
        self.list_ngu.blockSignals(True)
        try:
            # Reuse existing rows when possible to avoid QListWidget.clear()+setItemWidget spikes.
            if self.list_ngu.count() == len(items) and len(items) > 0:
                for i, it in enumerate(items):
                    html = str(it.get("label_html") or it.get("label") or "")
                    item = self.list_ngu.item(i)
                    if item is None:
                        continue
                    w = self.list_ngu.itemWidget(item)
                    if w is None:
                        continue
                    self._set_rich_item_widget_html(w, html)
            else:
                self.list_ngu.clear()
                for it in items:
                    html = str(it.get("label_html") or it.get("label") or "")
                    item = QListWidgetItem()
                    h = 44 if bool(it.get("is_special")) else 32
                    item.setSizeHint(QSize(0, h))
                    self.list_ngu.addItem(item)
                    self.list_ngu.setItemWidget(item, self._make_rich_item_widget(html))
            if items and 0 <= default_index < len(items):
                self.list_ngu.setCurrentRow(default_index)
        finally:
            self.list_ngu.blockSignals(False)
        self._sync_item_selection_style(self.list_ngu)


    def set_p_labels(self, items: List[dict], default_index: int = 0) -> None:
        self.list_p.blockSignals(True)
        try:
            # Reuse existing rows when possible to avoid QListWidget.clear()+setItemWidget spikes.
            if self.list_p.count() == len(items) and len(items) > 0:
                for i, it in enumerate(items):
                    html = str(it.get("label_html") or it.get("label") or "")
                    item = self.list_p.item(i)
                    if item is None:
                        continue
                    w = self.list_p.itemWidget(item)
                    if w is None:
                        continue
                    self._set_rich_item_widget_html(w, html)
            else:
                self.list_p.clear()
                for it in items:
                    html = str(it.get("label_html") or it.get("label") or "")
                    item = QListWidgetItem()
                    h = 44 if bool(it.get("is_special")) else 32
                    item.setSizeHint(QSize(0, h))
                    self.list_p.addItem(item)
                    self.list_p.setItemWidget(item, self._make_rich_item_widget(html))
            if items and 0 <= default_index < len(items):
                self.list_p.setCurrentRow(default_index)
        finally:
            self.list_p.blockSignals(False)
        self._sync_item_selection_style(self.list_p)

        self.btn_hup.setEnabled(bool(items))

    def set_cards_p_normalized(self, codes_13: List[str]) -> None:
        self._set_cards_block(self._p_row_chi1, self._p_row_chi2, self._p_row_chi3, codes_13)

    def set_cards_ngu_normalized(self, codes_13: List[str]) -> None:
        self._set_cards_block(self._ngu_row_chi1, self._ngu_row_chi2, self._ngu_row_chi3, codes_13)

    def _set_cards_block(self, row_chi1, row_chi2, row_chi3, codes_13: List[str]) -> None:
        c = list(codes_13 or [])
        chi1 = self._sort_codes_for_display(c[0:5])
        chi2 = self._sort_codes_for_display(c[5:10])
        chi3 = self._sort_codes_for_display(c[10:13])

        for i, lab in enumerate(row_chi3["labels"]):
            self._set_pix(lab, chi3[i] if i < len(chi3) else "")
        for i, lab in enumerate(row_chi2["labels"]):
            self._set_pix(lab, chi2[i] if i < len(chi2) else "")
        for i, lab in enumerate(row_chi1["labels"]):
            self._set_pix(lab, chi1[i] if i < len(chi1) else "")
    # =================== Special label for Chi 3 (responsive) ===================
    def _compute_special_font_size(self) -> int:
        # responsive: dựa trên width của view
        w = max(400, self.width() or 0)
        # ví dụ: 1000px -> ~22px, clamp 14..32
        size = int(w * 0.022)
        return max(14, min(32, size))

    def _apply_special_style(self, lab: QLabel, color: str) -> None:
        if not lab:
            return
        font_size = self._compute_special_font_size()
        # lưu lại để dùng lại khi resize
        lab._mb_font_size = font_size  # type: ignore[attr-defined]
        lab._mb_color = color          # type: ignore[attr-defined]
        lab.setStyleSheet(
            f"font-weight:900; color:{color}; font-size:{font_size}px;"
        )

    def _update_special_font_sizes(self) -> None:
        for lab in (self.lbl_ngu_special, self.lbl_p_special):
            if not lab or not lab.text():
                continue
            # lấy lại màu đã lưu, nếu có
            color = getattr(lab, "_mb_color", "#facc15")
            self._apply_special_style(lab, color)

    def set_p_special_text(self, text: str, color: Optional[str] = None) -> None:
        if not self.lbl_p_special:
            return
        self.lbl_p_special.setText(text or "")
        if not text:
            return
        if color is not None:
            self._p_special_color = color
        self._apply_special_style(self.lbl_p_special, self._p_special_color)

    def set_ngu_special_text(self, text: str, color: Optional[str] = None) -> None:
        if not self.lbl_ngu_special:
            return
        self.lbl_ngu_special.setText(text or "")
        if not text:
            return
        if color is not None:
            self._ngu_special_color = color
        self._apply_special_style(self.lbl_ngu_special, self._ngu_special_color)
