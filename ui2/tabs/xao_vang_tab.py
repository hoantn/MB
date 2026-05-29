from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.config import load_config
from core.logger import log


MAX_CHIP_CLICKS_PER_PROFILE = 6


class XaoVangTab(QWidget):
    """Fast balanced Tai/Xiu betting panel based on real chip clicks."""

    request_play_tai_xiu = Signal(str, dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._profiles = ["P1", "P2", "P3"]
        self._selected_profile = "P1"
        self._selected_side = "tai"
        self._selected_bet = ""
        self._chip_values: List[int] = []
        self._valid_bets: List[str] = []
        self._global_busy = False
        self._auto_enabled = False
        self._auto_remaining = 0
        self._auto_index = 0
        self._auto_seen_sids: set[str] = set()
        self._logs: Deque[str] = deque(maxlen=80)
        self._profile_buttons: Dict[str, QPushButton] = {}
        self._side_buttons: Dict[str, QPushButton] = {}
        self._bet_buttons: Dict[str, QPushButton] = {}
        self._summary_side_labels: Dict[str, QLabel] = {}
        self._summary_bet_labels: Dict[str, QLabel] = {}
        self._summary_chip_labels: Dict[str, QLabel] = {}

        self._build_ui()
        self._load_defaults()
        self._apply_styles()
        self._refresh_selection()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QLabel("Xào Vàng")
        header.setObjectName("xv_title")
        root.addWidget(header)

        panel = QFrame()
        panel.setObjectName("xv_panel")
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(12, 12, 12, 12)
        panel_lay.setSpacing(10)

        control_band = QGridLayout()
        control_band.setHorizontalSpacing(12)
        control_band.setVerticalSpacing(8)

        profile_section, profile_row = self._build_button_section("P chính")
        for profile_id in self._profiles:
            btn = self._make_choice_button(profile_id)
            btn.clicked.connect(lambda checked=False, pid=profile_id: self._select_profile(pid))
            self._profile_buttons[profile_id] = btn
            profile_row.addWidget(btn)

        side_section, side_row = self._build_button_section("Cửa P chính")
        for side, text in (("tai", "TÀI"), ("xiu", "XỈU")):
            btn = self._make_choice_button(text)
            btn.setObjectName(f"xv_side_{side}")
            btn.clicked.connect(lambda checked=False, s=side: self._select_side(s))
            self._side_buttons[side] = btn
            side_row.addWidget(btn)

        bet_section, self.bet_row = self._build_button_section("Số vàng cần xào")

        control_band.addLayout(profile_section, 0, 0)
        control_band.addWidget(self._make_separator(), 0, 1)
        control_band.addLayout(side_section, 0, 2)
        control_band.addWidget(self._make_separator(), 0, 3)
        control_band.addLayout(bet_section, 0, 4)
        control_band.setColumnStretch(0, 1)
        control_band.setColumnStretch(2, 1)
        control_band.setColumnStretch(4, 3)
        panel_lay.addLayout(control_band)

        delay_row = QHBoxLayout()
        delay_row.setSpacing(8)
        delay_label = QLabel("Delay")
        delay_label.setObjectName("xv_small_label")
        self.spn_manual_delay = QSpinBox()
        self.spn_manual_delay.setRange(0, 5000)
        self.spn_manual_delay.setSuffix(" ms")
        delay_row.addWidget(delay_label)
        delay_row.addWidget(self.spn_manual_delay)
        delay_row.addStretch(1)
        panel_lay.addLayout(delay_row)

        self.summary_panel = QFrame()
        self.summary_panel.setObjectName("xv_summary")
        summary_grid = QGridLayout(self.summary_panel)
        summary_grid.setContentsMargins(0, 0, 0, 0)
        summary_grid.setHorizontalSpacing(0)
        summary_grid.setVerticalSpacing(0)

        for row, profile_id in enumerate(self._profiles):
            lbl_profile = QLabel(profile_id)
            lbl_profile.setObjectName("xv_summary_profile")
            lbl_side = QLabel("-")
            lbl_side.setObjectName("xv_summary_side")
            lbl_bet = QLabel("-")
            lbl_bet.setObjectName("xv_summary_bet")
            lbl_chips = QLabel("-")
            lbl_chips.setObjectName("xv_summary_chips")
            summary_grid.addWidget(lbl_profile, row, 0)
            summary_grid.addWidget(lbl_side, row, 1)
            summary_grid.addWidget(lbl_bet, row, 2)
            summary_grid.addWidget(lbl_chips, row, 3)
            self._summary_side_labels[profile_id] = lbl_side
            self._summary_bet_labels[profile_id] = lbl_bet
            self._summary_chip_labels[profile_id] = lbl_chips
        panel_lay.addWidget(self.summary_panel)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.lbl_balance = QLabel("Chọn gói chip hợp lệ")
        self.lbl_balance.setObjectName("xv_balance")
        self.btn_execute = QPushButton("ĐÁNH XÀO VÀNG")
        self.btn_execute.setObjectName("xv_execute")
        self.btn_execute.setMinimumHeight(42)
        self.btn_execute.clicked.connect(self._emit_xao_vang)
        footer.addWidget(self.lbl_balance, 1)
        footer.addWidget(self.btn_execute)
        panel_lay.addLayout(footer)

        auto_row = QHBoxLayout()
        auto_row.setSpacing(8)
        self.btn_auto_toggle = QPushButton("AUTO XÀO: TẮT")
        self.btn_auto_toggle.setCheckable(True)
        self.btn_auto_toggle.setObjectName("xv_auto_toggle")
        self.btn_auto_toggle.clicked.connect(self._toggle_auto)
        auto_count_label = QLabel("Số phiên")
        auto_count_label.setObjectName("xv_small_label")
        self.spn_auto_rounds = QSpinBox()
        self.spn_auto_rounds.setRange(1, 999)
        self.spn_auto_rounds.setValue(10)
        self.lbl_auto_status = QLabel("Auto: tắt")
        self.lbl_auto_status.setObjectName("xv_auto_status")
        auto_row.addWidget(self.btn_auto_toggle)
        auto_row.addWidget(auto_count_label)
        auto_row.addWidget(self.spn_auto_rounds)
        auto_row.addWidget(self.lbl_auto_status, 1)
        panel_lay.addLayout(auto_row)

        self.lbl_status = QLabel("Status: Sẵn sàng")
        panel_lay.addWidget(self.lbl_status)
        root.addWidget(panel)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setObjectName("xv_log")
        root.addWidget(self.log_box, 1)

    def _build_button_section(self, title: str):
        layout = QVBoxLayout()
        layout.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("xv_section_label")
        row = QHBoxLayout()
        row.setSpacing(8)
        layout.addWidget(label)
        layout.addLayout(row)
        return layout, row

    def _make_choice_button(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setMinimumHeight(36)
        return btn

    def _make_separator(self) -> QFrame:
        line = QFrame()
        line.setObjectName("xv_vline")
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Plain)
        return line

    def _load_defaults(self) -> None:
        self._chip_values = self._load_chip_values()
        self._valid_bets = self._build_valid_xao_bets(self._chip_values)
        self._selected_bet = self._pick_default_bet(self._valid_bets)
        self._build_bet_buttons(self._valid_bets)
        self.spn_manual_delay.setValue(self._load_default_delay())

    def _load_chip_values(self) -> List[int]:
        """Read chips that are actually configured for every profile."""
        try:
            cfg = load_config()
            taixiu = ((cfg.get("game_ui") or {}).get("taixiu") or {})
            configured = {self._parse_int(x) for x in (taixiu.get("tx_bet_values") or [])}
            configured = {x for x in configured if x > 0}
            points_by_profile = taixiu.get("tx_bet_points_profile") or {}

            common: Optional[set[int]] = None
            for profile_id in self._profiles:
                profile_points = points_by_profile.get(profile_id) or {}
                values = {self._parse_int(x) for x in profile_points.keys()}
                values = {x for x in values if x > 0}
                common = values if common is None else common.intersection(values)

            chips = configured.intersection(common or set()) if configured else (common or set())
            return sorted(chips, reverse=True)
        except Exception:
            return []

    def _build_valid_xao_bets(self, chips: List[int]) -> List[str]:
        if not chips:
            return []

        candidates = set()
        for chip in chips:
            candidates.add(chip)
            candidates.add(chip * 2)
            candidates.add(chip * 5)
            candidates.add(chip * 10)

        valid = []
        for amount in sorted(candidates):
            if amount <= 0 or amount % 2 != 0:
                continue
            main_chips = self._decompose_amount(amount, chips)
            counter_chips = self._decompose_amount(amount // 2, chips)
            if main_chips and counter_chips:
                valid.append(str(amount))
        return valid

    def _pick_default_bet(self, bets: List[str]) -> str:
        for preferred in ("2000", "100000", "20000", "10000"):
            if preferred in bets:
                return preferred
        return bets[0] if bets else ""

    def _load_default_delay(self) -> int:
        try:
            return int((((load_config().get("ui") or {}).get("taixiu") or {}).get("delay_ms", 100)))
        except Exception:
            return 100

    def _build_bet_buttons(self, bets: List[str]) -> None:
        self._clear_layout(self.bet_row)
        self._bet_buttons.clear()
        for bet in bets:
            btn = self._make_choice_button(self._format_bet_short(bet))
            btn.clicked.connect(lambda checked=False, value=bet: self._select_bet(value))
            self._bet_buttons[bet] = btn
            self.bet_row.addWidget(btn)
        self.bet_row.addStretch(1)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _set_global_busy(self, busy: bool) -> None:
        self._global_busy = bool(busy)
        buttons = [
            *self._profile_buttons.values(),
            *self._side_buttons.values(),
            *self._bet_buttons.values(),
            self.btn_execute,
        ]
        for btn in buttons:
            btn.setEnabled(not busy)

    def _select_profile(self, profile_id: str) -> None:
        self._selected_profile = profile_id
        self._refresh_selection()

    def _select_side(self, side: str) -> None:
        self._selected_side = side
        self._refresh_selection()

    def _select_bet(self, bet: str) -> None:
        self._selected_bet = bet
        self._refresh_selection()

    def _opposite_side(self, side: str) -> str:
        return "xiu" if side == "tai" else "tai"

    def _decompose_amount(self, amount: int, chips: Optional[List[int]] = None) -> Optional[List[int]]:
        chip_values = sorted(chips or self._chip_values, reverse=True)
        if amount <= 0 or not chip_values:
            return None

        best_plan: Optional[List[int]] = None

        def search(index: int, remain: int, picked: List[int]) -> None:
            nonlocal best_plan
            if remain == 0:
                if best_plan is None or len(picked) < len(best_plan):
                    best_plan = list(picked)
                return
            if index >= len(chip_values):
                return
            if len(picked) >= MAX_CHIP_CLICKS_PER_PROFILE:
                return
            if best_plan is not None and len(picked) >= len(best_plan):
                return

            chip = chip_values[index]
            max_count = min(remain // chip, MAX_CHIP_CLICKS_PER_PROFILE - len(picked))
            for count in range(max_count, -1, -1):
                next_remain = remain - chip * count
                next_picked = picked + ([chip] * count)
                search(index + 1, next_remain, next_picked)

        search(0, amount, [])
        return best_plan

    def _current_plan(self, main_profile: Optional[str] = None) -> Dict[str, Dict[str, object]]:
        if not self._selected_bet:
            return {}
        selected_profile = main_profile or self._selected_profile
        main_bet = self._parse_int(self._selected_bet)
        counter_bet = main_bet // 2
        main_chips = self._decompose_amount(main_bet)
        counter_chips = self._decompose_amount(counter_bet)
        if not main_chips or not counter_chips:
            return {}

        opposite = self._opposite_side(self._selected_side)
        plan: Dict[str, Dict[str, object]] = {}
        for profile_id in self._profiles:
            if profile_id == selected_profile:
                plan[profile_id] = {"side": self._selected_side, "bet": str(main_bet), "chips": main_chips}
            else:
                plan[profile_id] = {"side": opposite, "bet": str(counter_bet), "chips": counter_chips}
        return plan

    def _refresh_selection(self) -> None:
        for profile_id, btn in self._profile_buttons.items():
            btn.setChecked(profile_id == self._selected_profile)
        for side, btn in self._side_buttons.items():
            btn.setChecked(side == self._selected_side)
        for bet, btn in self._bet_buttons.items():
            btn.setChecked(bet == self._selected_bet)

        plan = self._current_plan()
        self.btn_execute.setEnabled(bool(plan) and not self._global_busy)
        if not plan:
            self.lbl_balance.setText("Chưa có gói chip hợp lệ")
            self.lbl_status.setText("Status: Chưa cấu hình đủ chip Tài/Xỉu cho 3P")
            return

        totals = {"tai": 0, "xiu": 0}
        for profile_id in self._profiles:
            side = str(plan[profile_id]["side"])
            bet = str(plan[profile_id]["bet"])
            chips = list(plan[profile_id]["chips"])
            totals[side] += self._parse_int(bet)
            side_label = self._summary_side_labels[profile_id]
            side_label.setText(self._side_text(side))
            side_label.setProperty("side", side)
            side_label.style().unpolish(side_label)
            side_label.style().polish(side_label)
            self._summary_bet_labels[profile_id].setText(self._format_money(bet))
            self._summary_chip_labels[profile_id].setText(self._format_chip_plan(chips))
        self.lbl_balance.setText(
            f"Tài {self._format_money(totals['tai'])} / Xỉu {self._format_money(totals['xiu'])} - cân cửa"
        )
        self.lbl_status.setText("Status: Sẵn sàng")

    def _emit_xao_vang(self) -> bool:
        return self._emit_plan_for_profile(self._selected_profile, source="manual")

    def _emit_plan_for_profile(self, main_profile: str, source: str, sid: str = "") -> bool:
        if self._global_busy:
            return False
        plan = self._current_plan(main_profile)
        delay_ms = int(self.spn_manual_delay.value())
        if not plan:
            self.lbl_status.setText("Status: Chưa có gói chip hợp lệ")
            return False

        self._set_global_busy(True)
        main_text = f"{main_profile} {self._side_text(self._selected_side)} {self._format_money(self._selected_bet)}"
        sid_text = f" | sid={sid}" if sid else ""
        self._append_log(f"Xào Vàng {source} | {main_text} | delay={delay_ms}{sid_text}")
        max_clicks = 0
        for index, profile_id in enumerate(self._profiles):
            item = plan[profile_id]
            chips = list(item["chips"])
            max_clicks = max(max_clicks, len(chips))
            QTimer.singleShot(
                index * 150,
                lambda pid=profile_id, payload=dict(item), d=delay_ms: self.request_play_tai_xiu.emit(
                    pid,
                    {
                        "side": payload["side"],
                        "bet": payload["bet"],
                        "chips": payload["chips"],
                        "delay_ms": d,
                    },
                ),
            )
        release_ms = len(self._profiles) * 150 + max(2000, (max_clicks + 2) * max(delay_ms, 50))
        QTimer.singleShot(release_ms, self._release_busy)
        return True

    def _toggle_auto(self) -> None:
        if self.btn_auto_toggle.isChecked():
            self._auto_enabled = True
            self._auto_remaining = int(self.spn_auto_rounds.value())
            self._auto_index = 0
            self._auto_seen_sids.clear()
            self.btn_auto_toggle.setText("AUTO XÀO: BẬT")
            self.lbl_auto_status.setText(f"Auto: bật | còn {self._auto_remaining} phiên | chờ socket")
            self._append_log(f"Auto bật | số phiên={self._auto_remaining}")
            log.info(
                "XaoVang auto enabled | rounds=%s side=%s bet=%s",
                self._auto_remaining,
                self._selected_side,
                self._selected_bet,
            )
        else:
            self._disable_auto("người dùng tắt")

    def _disable_auto(self, reason: str) -> None:
        self._auto_enabled = False
        self._auto_remaining = 0
        self.btn_auto_toggle.setChecked(False)
        self.btn_auto_toggle.setText("AUTO XÀO: TẮT")
        self.lbl_auto_status.setText(f"Auto: tắt | {reason}")
        self._append_log(f"Auto tắt | {reason}")
        log.info("XaoVang auto disabled | reason=%s", reason)

    def trigger_auto_for_sid(self, sid: str) -> bool:
        sid_str = str(sid or "").strip()
        if not self._auto_enabled or self._auto_remaining <= 0:
            log.debug(
                "XaoVang auto skip | sid=%s enabled=%s remaining=%s",
                sid_str,
                self._auto_enabled,
                self._auto_remaining,
            )
            return False
        if not sid_str or sid_str in self._auto_seen_sids:
            log.debug("XaoVang auto skip duplicate/empty sid | sid=%s", sid_str)
            return False
        if self._global_busy:
            self.lbl_auto_status.setText(f"Auto: bận, bỏ qua sid {sid_str}")
            self._append_log(f"Auto bỏ qua sid={sid_str} vì đang bận")
            log.info("XaoVang auto skip busy | sid=%s", sid_str)
            return False

        main_profile = self._profiles[self._auto_index % len(self._profiles)]
        ok = self._emit_plan_for_profile(main_profile, source="auto", sid=sid_str)
        if not ok:
            log.info("XaoVang auto fire failed | sid=%s main=%s", sid_str, main_profile)
            return False

        log.info(
            "XaoVang auto fired | sid=%s main=%s remaining_before=%s",
            sid_str,
            main_profile,
            self._auto_remaining,
        )
        self._auto_seen_sids.add(sid_str)
        self._auto_index += 1
        self._auto_remaining -= 1
        if self._auto_remaining <= 0:
            self._disable_auto(f"đã đủ phiên, sid cuối {sid_str}")
        else:
            next_profile = self._profiles[self._auto_index % len(self._profiles)]
            self.lbl_auto_status.setText(
                f"Auto: đã xào {main_profile} | còn {self._auto_remaining} phiên | tiếp {next_profile}"
            )
        return True

    def _release_busy(self) -> None:
        self._set_global_busy(False)

    def dat_trang_thai(self, text: str) -> None:
        self.lbl_status.setText(f"Status: {text}")
        self._set_global_busy(False)

    def dat_trang_thai_profile(self, profile_id: str, text: str) -> None:
        self.lbl_status.setText(f"{profile_id}: {text}")
        self._set_global_busy(False)

    def _append_log(self, text: str) -> None:
        self._logs.appendleft(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
        self.log_box.setPlainText("\n".join(self._logs))

    def _side_text(self, side: str) -> str:
        return "TÀI" if side == "tai" else "XỈU"

    def _parse_int(self, value) -> int:
        try:
            return int(str(value).replace(".", "").replace(",", "").strip())
        except Exception:
            return 0

    def _format_money(self, value) -> str:
        return f"{self._parse_int(value):,}".replace(",", ".")

    def _format_bet_short(self, value: str) -> str:
        amount = self._parse_int(value)
        if amount >= 1_000_000:
            return f"{amount // 1_000_000}M"
        if amount >= 1_000:
            return f"{amount // 1_000}K"
        return str(amount)

    def _format_chip_plan(self, chips: List[int]) -> str:
        counts: Dict[int, int] = {}
        for chip in chips:
            counts[chip] = counts.get(chip, 0) + 1
        parts = []
        for chip in sorted(counts.keys(), reverse=True):
            text = self._format_bet_short(str(chip))
            count = counts[chip]
            parts.append(text if count == 1 else f"{text} x{count}")
        return " + ".join(parts)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QLabel#xv_title { font-size:20px; font-weight:900; color:#F8FAFC; }
            QLabel#xv_section_label, QLabel#xv_small_label {
                color:#9AA6B2; font-size:12px; font-weight:800; text-transform:uppercase;
            }
            QFrame#xv_panel {
                background:#171C23; border:1px solid #303846; border-radius:8px;
            }
            QFrame#xv_vline {
                background:#2A3544; max-width:1px; min-width:1px;
            }
            QPushButton, QSpinBox, QPlainTextEdit {
                background:#11161D; border:1px solid #303846; border-radius:7px; padding:4px 8px;
                color:#EDF2F7;
            }
            QPushButton {
                font-weight:900; min-width:58px;
            }
            QPushButton:checked {
                background:#21324D; border-color:#4B7CC7; color:#FFFFFF;
            }
            QPushButton#xv_side_tai:checked {
                background:#174C2D; border-color:#16A34A; color:#9DF2B7;
            }
            QPushButton#xv_side_xiu:checked {
                background:#5A1F24; border-color:#DC2626; color:#FFB0AA;
            }
            QPushButton#xv_execute {
                background:#F2B84B; border-color:#F2B84B; color:#15110A;
                padding:8px 18px; min-width:180px;
            }
            QPushButton#xv_execute:disabled {
                background:#50472F; border-color:#5B5137; color:#9A8E72;
            }
            QPushButton#xv_auto_toggle {
                background:#17202B; border-color:#3A4B61; color:#DCEBFA;
                min-width:130px;
            }
            QPushButton#xv_auto_toggle:checked {
                background:#17543A; border-color:#2BC56D; color:#BDF8D0;
            }
            QLabel#xv_auto_status { color:#BDD6EF; font-weight:800; }
            QFrame#xv_summary {
                background:#10151C; border:1px solid #303846; border-radius:8px;
            }
            QLabel#xv_summary_profile, QLabel#xv_summary_side,
            QLabel#xv_summary_bet, QLabel#xv_summary_chips {
                min-height:42px; padding:0 12px; border-bottom:1px solid rgba(255,255,255,.06);
                font-weight:900;
            }
            QLabel#xv_summary_side[side="tai"] { color:#75E59A; }
            QLabel#xv_summary_side[side="xiu"] { color:#FF928D; }
            QLabel#xv_summary_bet { color:#FFD16B; }
            QLabel#xv_summary_chips { color:#B9C3D0; }
            QLabel#xv_balance { color:#9AA6B2; font-weight:700; }
            QPlainTextEdit#xv_log {
                background:#10151C; border:1px solid #303846; border-radius:8px; padding:8px;
            }
            """
        )
