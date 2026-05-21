from __future__ import annotations

from typing import Optional, List, Dict, Any

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QSplitter,
    QGroupBox,
    QTextEdit,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer

from core.logger import log
from db import player_queries as pq


class PlayersTab(QWidget):
    """
    Tab "Người chơi":
      - List tổng hợp đối thủ đã gặp (group theo UID)
      - Filter/search cơ bản
      - Click -> xem lịch sử 20 lần gần nhất
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # paging
        self._page_size = 200
        self._page_index = 0

        self._selected_uid: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ===== Filters bar =====
        bar = QHBoxLayout()
        bar.setSpacing(8)

        bar.addWidget(QLabel("Search:"))
        self.edt_search = QLineEdit()
        self.edt_search.setPlaceholderText("UID hoặc tên...")
        self.edt_search.textChanged.connect(self._on_filters_changed_debounced)
        bar.addWidget(self.edt_search, 2)

        bar.addWidget(QLabel("Profile:"))
        self.cb_profile = QComboBox()
        self.cb_profile.addItem("All", userData=None)
        self.cb_profile.addItem("P1", userData="P1")
        self.cb_profile.addItem("P2", userData="P2")
        self.cb_profile.addItem("P3", userData="P3")
        self.cb_profile.currentIndexChanged.connect(self._on_filters_changed)
        bar.addWidget(self.cb_profile)

        bar.addWidget(QLabel("Bet:"))
        self.cb_bet = QComboBox()
        self.cb_bet.addItem("All", userData=None)
        self.cb_bet.currentIndexChanged.connect(self._on_filters_changed)
        bar.addWidget(self.cb_bet)

        bar.addWidget(QLabel("Time:"))
        self.cb_time = QComboBox()
        self.cb_time.addItem("All", userData="ALL")
        self.cb_time.addItem("24h", userData="24H")
        self.cb_time.addItem("7d", userData="7D")
        self.cb_time.addItem("30d", userData="30D")
        self.cb_time.currentIndexChanged.connect(self._on_filters_changed)
        bar.addWidget(self.cb_time)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.reload)
        bar.addWidget(self.btn_refresh)

        root.addLayout(bar)

        # ===== Split view =====
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # left: list
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(6)

        self.lbl_stats = QLabel("0 người chơi")
        self.lbl_stats.setStyleSheet("font-weight:600;")
        left_l.addWidget(self.lbl_stats)

        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels(
            ["UID", "Tên", "Gặp", "Gần nhất", "Vàng", "Top Bet", "Top Profile"]
        )
        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.itemSelectionChanged.connect(self._on_row_selected)

        left_l.addWidget(self.tbl, 1)

        # paging
        paging = QHBoxLayout()
        self.btn_prev = QPushButton("Prev")
        self.btn_next = QPushButton("Next")
        self.lbl_page = QLabel("Page 1")
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_next.clicked.connect(self._next_page)
        paging.addWidget(self.btn_prev)
        paging.addWidget(self.btn_next)
        paging.addWidget(self.lbl_page)
        paging.addStretch(1)
        left_l.addLayout(paging)

        splitter.addWidget(left)

        # right: details
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(8)

        g_info = QGroupBox("Chi tiết người chơi")
        g_info_l = QVBoxLayout(g_info)

        self.lbl_uid = QLabel("UID: -")
        self.lbl_name = QLabel("Tên: -")
        self.lbl_meta = QLabel("Thông tin: -")
        self.lbl_uid.setStyleSheet("font-weight:600;")
        g_info_l.addWidget(self.lbl_uid)
        g_info_l.addWidget(self.lbl_name)
        g_info_l.addWidget(self.lbl_meta)

        right_l.addWidget(g_info)

        g_top = QGroupBox("Top bet / top profile")
        g_top_l = QVBoxLayout(g_top)
        self.lbl_top = QLabel("-")
        g_top_l.addWidget(self.lbl_top)
        right_l.addWidget(g_top)

        g_hist = QGroupBox("Lịch sử 20 lần gần nhất")
        g_hist_l = QVBoxLayout(g_hist)
        self.tbl_hist = QTableWidget(0, 5)
        self.tbl_hist.setHorizontalHeaderLabels(["Time", "Profile", "Bet", "Room", "Vàng"])
        self.tbl_hist.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_hist.setAlternatingRowColors(True)
        self.tbl_hist.verticalHeader().setVisible(False)
        self.tbl_hist.horizontalHeader().setStretchLastSection(True)
        g_hist_l.addWidget(self.tbl_hist, 1)
        right_l.addWidget(g_hist, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, 1)

        # debounce timer for search
        self._debounce = QTimer(self)
        self._debounce.setInterval(250)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._on_filters_changed)

        # load initial
        self._reload_bets()
        self.reload()

    # ==========================
    # Filters / paging
    # ==========================

    def _reload_bets(self) -> None:
        try:
            bets = pq.list_distinct_bets()
        except Exception:
            bets = []
        self.cb_bet.blockSignals(True)
        try:
            self.cb_bet.clear()
            self.cb_bet.addItem("All", userData=None)
            for b in bets:
                self.cb_bet.addItem(str(b), userData=int(b))
        finally:
            self.cb_bet.blockSignals(False)

    def _on_filters_changed_debounced(self) -> None:
        self._debounce.stop()
        self._debounce.start()

    def _on_filters_changed(self) -> None:
        self._page_index = 0
        self.reload()

    def _prev_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self.reload()

    def _next_page(self) -> None:
        self._page_index += 1
        self.reload()

    # ==========================
    # Data loading
    # ==========================

    def reload(self) -> None:
        search = self.edt_search.text().strip() or None
        profile_id = self.cb_profile.currentData()
        bet = self.cb_bet.currentData()
        time_filter = self.cb_time.currentData() or "ALL"

        limit = self._page_size
        offset = self._page_index * self._page_size

        try:
            rows = pq.list_players_aggregated(
                search=search,
                profile_id=profile_id,
                bet=bet,
                time_filter=time_filter,
                limit=limit,
                offset=offset,
            )
        except Exception:
            log.exception("PlayersTab: list_players_aggregated failed")
            rows = []

        self._fill_table(rows)

        self.lbl_page.setText(f"Page {self._page_index + 1}")
        self.btn_prev.setEnabled(self._page_index > 0)
        self.btn_next.setEnabled(len(rows) == self._page_size)

        self.lbl_stats.setText(f"{len(rows)} người chơi (page size={self._page_size})")

        # refresh bet list sometimes (optional)
        # self._reload_bets()

    def _fill_table(self, rows: List[pq.PlayerRow]) -> None:
        self.tbl.setRowCount(0)
        for r in rows:
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)

            def _set(col: int, text: str) -> None:
                it = QTableWidgetItem(text)
                it.setData(Qt.UserRole, r.uid)  # store uid for selection
                self.tbl.setItem(row, col, it)

            _set(0, r.uid)
            _set(1, r.name_last)
            _set(2, str(r.meet_times))
            _set(3, r.last_seen)
            _set(4, "" if r.last_gold is None else str(r.last_gold))
            _set(5, "" if r.top_bet is None else str(r.top_bet))
            _set(6, "" if r.top_profile is None else str(r.top_profile))

        self.tbl.resizeColumnsToContents()

        # clear details if no selection
        if self.tbl.rowCount() == 0:
            self._clear_details()

    def _clear_details(self) -> None:
        self._selected_uid = None
        self.lbl_uid.setText("UID: -")
        self.lbl_name.setText("Tên: -")
        self.lbl_meta.setText("Thông tin: -")
        self.lbl_top.setText("-")
        self.tbl_hist.setRowCount(0)

    # ==========================
    # Selection -> details
    # ==========================

    def _on_row_selected(self) -> None:
        items = self.tbl.selectedItems()
        if not items:
            return
        uid = items[0].data(Qt.UserRole)
        if not uid:
            return
        uid = str(uid)
        if uid == self._selected_uid:
            return
        self._selected_uid = uid
        self._load_details(uid)

    def _load_details(self, uid: str) -> None:
        try:
            hist = pq.get_player_history(uid, limit=20)
        except Exception:
            log.exception("PlayersTab: get_player_history failed uid=%r", uid)
            hist = []

        # best effort name
        name = "-"
        if hist:
            name = str(hist[0].get("seen_name") or "-")

        # meta summary from history
        if hist:
            last_seen = str(hist[0].get("last_seen_at") or "")
            last_gold = hist[0].get("seen_gold")
        else:
            last_seen = ""
            last_gold = None

        # compute meet_times roughly from current page? better: count from DB quickly
        # For Phase 1, use top profiles/bets + history count.
        try:
            top_bets = pq.get_top_bets(uid, limit=3)
            top_profiles = pq.get_top_profiles(uid, limit=3)
        except Exception:
            top_bets, top_profiles = [], []

        top_text_parts: List[str] = []
        if top_bets:
            top_text_parts.append("Top Bet: " + ", ".join([f"{b}({c})" for b, c in top_bets]))
        if top_profiles:
            top_text_parts.append("Top Profile: " + ", ".join([f"{p}({c})" for p, c in top_profiles]))
        self.lbl_top.setText("\n".join(top_text_parts) if top_text_parts else "-")

        self.lbl_uid.setText(f"UID: {uid}")
        self.lbl_name.setText(f"Tên: {name}")
        gold_txt = "-" if last_gold is None else str(last_gold)
        self.lbl_meta.setText(f"Gần nhất: {last_seen} | Vàng gần nhất: {gold_txt}")

        self._fill_history(hist)

    def _fill_history(self, hist: List[Dict[str, Any]]) -> None:
        self.tbl_hist.setRowCount(0)
        for h in hist:
            row = self.tbl_hist.rowCount()
            self.tbl_hist.insertRow(row)

            def _set(col: int, text: str) -> None:
                self.tbl_hist.setItem(row, col, QTableWidgetItem(text))

            _set(0, str(h.get("last_seen_at") or ""))
            _set(1, str(h.get("profile_id") or ""))
            _set(2, "" if h.get("bet") is None else str(h.get("bet")))
            _set(3, "" if h.get("room_id") is None else str(h.get("room_id")))
            _set(4, "" if h.get("seen_gold") is None else str(h.get("seen_gold")))

        self.tbl_hist.resizeColumnsToContents()
