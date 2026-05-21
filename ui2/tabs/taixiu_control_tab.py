from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Mapping, Optional, Sequence

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QSpinBox,
    QFrame,
    QCheckBox,
    QGridLayout,
    QPlainTextEdit,
)

from core.config import load_config
from ui2.ai.taixiu_pattern_stats import summarize_patterns


class TaiXiuControlTab(QWidget):
    request_play_tai_xiu = Signal(str, dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._profiles = ["P1", "P2", "P3"]
        self._global_busy = False
        self._auto_last_key_by_target: Dict[str, str] = {}
        self._logs: Deque[str] = deque(maxlen=120)

        self._build_ui()
        self._load_defaults()
        self._apply_styles()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        root.addWidget(self._build_header())
        root.addWidget(self._build_manual_box())
        root.addWidget(self._build_auto_box())
        root.addWidget(self._build_monitor_box(), 1)

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("txc_header")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        title = QLabel("TÀI XỈU AUTO / KIỂM THỬ")
        title.setObjectName("txc_title")
        title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel("Manual test • Auto trigger theo cầu • Theo dõi trạng thái")
        subtitle.setObjectName("txc_subtitle")
        subtitle.setAlignment(Qt.AlignCenter)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        return frame

    def _build_manual_box(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("txc_panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("MANUAL CONTROL")
        title.setObjectName("txc_section_title")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self.cbo_manual_target = QComboBox()
        self.cbo_manual_target.addItems(self._profiles)
        self.cbo_manual_bet = QComboBox()
        self.spn_manual_delay = QSpinBox()
        self.spn_manual_delay.setRange(0, 5000)
        self.spn_manual_delay.setSuffix(" ms")

        for w in (self.cbo_manual_target, self.cbo_manual_bet, self.spn_manual_delay):
            w.setFixedHeight(34)

        grid.addWidget(QLabel("Profile"), 0, 0)
        grid.addWidget(self.cbo_manual_target, 0, 1)
        grid.addWidget(QLabel("Bet"), 0, 2)
        grid.addWidget(self.cbo_manual_bet, 0, 3)
        grid.addWidget(QLabel("Delay"), 0, 4)
        grid.addWidget(self.spn_manual_delay, 0, 5)
        layout.addLayout(grid)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_manual_tai = QPushButton("TÀI")
        self.btn_manual_tai.setObjectName("txc_btn_tai")
        self.btn_manual_xiu = QPushButton("XỈU")
        self.btn_manual_xiu.setObjectName("txc_btn_xiu")
        self.btn_manual_tai_all = QPushButton("TÀI ALL")
        self.btn_manual_tai_all.setObjectName("txc_btn_tai")
        self.btn_manual_xiu_all = QPushButton("XỈU ALL")
        self.btn_manual_xiu_all.setObjectName("txc_btn_xiu")

        for btn in (self.btn_manual_tai, self.btn_manual_xiu, self.btn_manual_tai_all, self.btn_manual_xiu_all):
            btn.setFixedHeight(36)

        self.btn_manual_tai.clicked.connect(lambda: self._emit_manual_one("tai"))
        self.btn_manual_xiu.clicked.connect(lambda: self._emit_manual_one("xiu"))
        self.btn_manual_tai_all.clicked.connect(lambda: self._emit_play_all("tai", source="manual"))
        self.btn_manual_xiu_all.clicked.connect(lambda: self._emit_play_all("xiu", source="manual"))

        btn_row.addWidget(self.btn_manual_tai)
        btn_row.addWidget(self.btn_manual_xiu)
        btn_row.addSpacing(12)
        btn_row.addWidget(self.btn_manual_tai_all)
        btn_row.addWidget(self.btn_manual_xiu_all)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.lbl_manual_status = QLabel("Status: Sẵn sàng")
        self.lbl_manual_status.setObjectName("txc_status_line")
        layout.addWidget(self.lbl_manual_status)
        return frame

    def _build_auto_box(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("txc_panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("AUTO CONTROL")
        title.setObjectName("txc_section_title")
        layout.addWidget(title)

        top_row = QGridLayout()
        top_row.setHorizontalSpacing(8)
        top_row.setVerticalSpacing(8)

        self.chk_auto_enabled = QCheckBox("Bật AUTO")
        self.chk_auto_enabled.setObjectName("txc_auto_check")
        self.cbo_auto_target = QComboBox()
        self.cbo_auto_target.addItems(["P1", "P2", "P3", "ALL"])
        self.cbo_auto_action = QComboBox()
        self.cbo_auto_action.addItems(["Theo cầu", "Ngược cầu"])
        self.cbo_auto_bet = QComboBox()
        self.spn_auto_delay = QSpinBox()
        self.spn_auto_delay.setRange(0, 5000)
        self.spn_auto_delay.setSuffix(" ms")

        for w in (self.cbo_auto_target, self.cbo_auto_action, self.cbo_auto_bet, self.spn_auto_delay):
            w.setFixedHeight(34)

        top_row.addWidget(self.chk_auto_enabled, 0, 0, 1, 2)
        top_row.addWidget(QLabel("Áp dụng cho"), 1, 0)
        top_row.addWidget(self.cbo_auto_target, 1, 1)
        top_row.addWidget(QLabel("Hành động"), 1, 2)
        top_row.addWidget(self.cbo_auto_action, 1, 3)
        top_row.addWidget(QLabel("Bet"), 2, 0)
        top_row.addWidget(self.cbo_auto_bet, 2, 1)
        top_row.addWidget(QLabel("Delay"), 2, 2)
        top_row.addWidget(self.spn_auto_delay, 2, 3)
        layout.addLayout(top_row)

        rules_frame = QFrame()
        rules_frame.setObjectName("txc_inner_box")
        rules_layout = QGridLayout(rules_frame)
        rules_layout.setContentsMargins(10, 10, 10, 10)
        rules_layout.setHorizontalSpacing(8)
        rules_layout.setVerticalSpacing(8)

        rules_title = QLabel("RULE KÍCH HOẠT")
        rules_title.setObjectName("txc_inner_title")
        rules_layout.addWidget(rules_title, 0, 0, 1, 4)

        self.chk_rule_streak = QCheckBox("Bệt")
        self.spn_rule_streak = QSpinBox()
        self.spn_rule_streak.setRange(3, 20)
        self.spn_rule_streak.setValue(5)

        self.chk_rule_alt = QCheckBox("1:1")
        self.spn_rule_alt = QSpinBox()
        self.spn_rule_alt.setRange(4, 20)
        self.spn_rule_alt.setValue(6)

        self.chk_rule_22 = QCheckBox("2:2")
        self.spn_rule_22 = QSpinBox()
        self.spn_rule_22.setRange(4, 20)
        self.spn_rule_22.setValue(4)

        self.chk_rule_33 = QCheckBox("3:3")
        self.spn_rule_33 = QSpinBox()
        self.spn_rule_33.setRange(6, 24)
        self.spn_rule_33.setValue(6)

        for spin in (self.spn_rule_streak, self.spn_rule_alt, self.spn_rule_22, self.spn_rule_33):
            spin.setFixedHeight(30)

        rules = [
            (self.chk_rule_streak, self.spn_rule_streak),
            (self.chk_rule_alt, self.spn_rule_alt),
            (self.chk_rule_22, self.spn_rule_22),
            (self.chk_rule_33, self.spn_rule_33),
        ]
        for idx, (chk, spin) in enumerate(rules, start=1):
            rules_layout.addWidget(chk, idx, 0)
            rules_layout.addWidget(QLabel("Kích hoạt từ"), idx, 1)
            rules_layout.addWidget(spin, idx, 2)
            rules_layout.addWidget(QLabel("tay"), idx, 3)

        layout.addWidget(rules_frame)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.btn_save_auto = QPushButton("LƯU CẤU HÌNH AUTO")
        self.btn_save_auto.setObjectName("txc_btn_neutral")
        self.btn_disable_auto = QPushButton("TẮT AUTO")
        self.btn_disable_auto.setObjectName("txc_btn_warn")

        self.btn_save_auto.setFixedHeight(36)
        self.btn_disable_auto.setFixedHeight(36)
        self.btn_save_auto.clicked.connect(self._save_auto_config)
        self.btn_disable_auto.clicked.connect(self._disable_auto)

        action_row.addWidget(self.btn_save_auto)
        action_row.addWidget(self.btn_disable_auto)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        return frame

    def _build_monitor_box(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("txc_panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("AUTO MONITOR / LOG")
        title.setObjectName("txc_section_title")
        layout.addWidget(title)

        self.lbl_monitor = QLabel("AUTO: Tắt")
        self.lbl_monitor.setObjectName("txc_monitor_title")
        layout.addWidget(self.lbl_monitor)

        self.lbl_monitor_rule = QLabel("Rule hiện tại: Chưa cấu hình")
        self.lbl_monitor_rule.setObjectName("txc_status_line")
        layout.addWidget(self.lbl_monitor_rule)

        self.lbl_monitor_state = QLabel("Chờ dữ liệu realtime...")
        self.lbl_monitor_state.setObjectName("txc_status_line")
        self.lbl_monitor_state.setWordWrap(True)
        layout.addWidget(self.lbl_monitor_state)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setObjectName("txc_log")
        layout.addWidget(self.log_box, 1)
        return frame

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            '''
            QWidget { color:#ECEFF4; font-size:13px; }
            QFrame#txc_header, QFrame#txc_panel, QFrame#txc_inner_box {
                background:#232734; border:1px solid #31374A; border-radius:12px;
            }
            QLabel#txc_title { font-size:20px; font-weight:800; color:#F8FAFC; }
            QLabel#txc_subtitle, QLabel#txc_status_line { color:#C9D2DE; }
            QLabel#txc_section_title { font-size:14px; font-weight:800; color:#F8FAFC; }
            QLabel#txc_inner_title, QLabel#txc_monitor_title { font-size:13px; font-weight:700; color:#F8FAFC; }
            QPushButton, QComboBox, QSpinBox, QPlainTextEdit {
                background:#1B1F2A; border:1px solid #31374A; border-radius:8px; padding:4px 6px;
            }
            QPlainTextEdit#txc_log { color:#DCE6F2; }
            QPushButton { font-weight:700; padding:6px 12px; }
            QPushButton#txc_btn_tai { background:#176B50; border:1px solid #1E8967; }
            QPushButton#txc_btn_tai:hover { background:#1E8967; }
            QPushButton#txc_btn_xiu { background:#A93232; border:1px solid #C94444; }
            QPushButton#txc_btn_xiu:hover { background:#C94444; }
            QPushButton#txc_btn_neutral { background:#305A94; border:1px solid #4474B8; }
            QPushButton#txc_btn_warn { background:#6B4B16; border:1px solid #C58B1D; }
            QCheckBox#txc_auto_check { font-weight:700; color:#F8FAFC; }
            '''
        )

    def _default_bets(self) -> List[str]:
        return ["1000", "10000", "50000", "100000", "500000", "1000000", "10000000"]

    def _load_defaults(self) -> None:
        bets = self._load_bet_values()
        delay_ms = self._load_default_delay()

        self.cbo_manual_bet.clear()
        self.cbo_manual_bet.addItems(bets)
        self.spn_manual_delay.setValue(delay_ms)

        self.cbo_auto_bet.clear()
        self.cbo_auto_bet.addItems(bets)
        self.spn_auto_delay.setValue(delay_ms)

        self.chk_rule_streak.setChecked(True)
        self._refresh_monitor_labels()

    def _load_bet_values(self) -> List[str]:
        try:
            cfg = load_config()
            game_ui = cfg.get("game_ui", {}) or {}
            taixiu = game_ui.get("taixiu", {}) or {}
            bets = taixiu.get("tx_bet_values") or []
            bets = [str(x).strip() for x in bets if str(x).strip()]
            if not bets:
                bets = self._default_bets()
            return sorted(bets, key=lambda s: int(s))
        except Exception:
            return self._default_bets()

    def _load_default_delay(self) -> int:
        try:
            cfg = load_config()
            ui = cfg.get("ui", {}) or {}
            tx = ui.get("taixiu", {}) or {}
            return int(tx.get("delay_ms", 100))
        except Exception:
            return 100

    def _set_global_busy(self, busy: bool) -> None:
        self._global_busy = busy
        for btn in (self.btn_manual_tai, self.btn_manual_xiu, self.btn_manual_tai_all, self.btn_manual_xiu_all):
            btn.setEnabled(not busy)

    def _emit_manual_one(self, side: str) -> bool:
        if self._global_busy:
            return False
        profile_id = self.cbo_manual_target.currentText().strip()
        bet = self.cbo_manual_bet.currentText().strip()
        delay_ms = int(self.spn_manual_delay.value())
        if not profile_id or not bet:
            self.lbl_manual_status.setText("Status: Thiếu profile hoặc bet")
            return False

        self._set_global_busy(True)
        label_side = "TÀI" if side == "tai" else "XỈU"
        self.lbl_manual_status.setText(f"Status: MANUAL {label_side} | {profile_id} | Bet {bet}")
        self._append_log(f"MANUAL -> {profile_id} | {label_side} | bet={bet} | delay={delay_ms}")

        self.request_play_tai_xiu.emit(profile_id, {"side": side, "bet": bet, "delay_ms": delay_ms})
        QTimer.singleShot(2000, self._release_busy)
        return True

    def _emit_play_all(self, side: str, source: str = "manual") -> bool:
        if self._global_busy:
            return False

        bet = self.cbo_auto_bet.currentText().strip() if source == "auto" else self.cbo_manual_bet.currentText().strip()
        delay_ms = int(self.spn_auto_delay.value()) if source == "auto" else int(self.spn_manual_delay.value())
        if not bet:
            self.lbl_manual_status.setText("Status: Chưa chọn bet")
            return False

        self._set_global_busy(True)
        label_side = "TÀI" if side == "tai" else "XỈU"
        src = "AUTO" if source == "auto" else "MANUAL"
        self.lbl_manual_status.setText(f"Status: {src} {label_side} ALL | Bet {bet}")
        self._append_log(f"{src} -> ALL | {label_side} | bet={bet} | delay={delay_ms}")

        delay_between_profiles = 150
        for index, profile_id in enumerate(self._profiles):
            QTimer.singleShot(
                index * delay_between_profiles,
                lambda pid=profile_id, s=side, b=bet, d=delay_ms: self.request_play_tai_xiu.emit(
                    pid, {"side": s, "bet": b, "delay_ms": d}
                ),
            )

        total_release_ms = len(self._profiles) * delay_between_profiles + 2000
        QTimer.singleShot(total_release_ms, self._release_busy)
        return True

    def _release_busy(self) -> None:
        self._set_global_busy(False)

    def _save_auto_config(self) -> None:
        self.chk_auto_enabled.setChecked(True)
        self._refresh_monitor_labels()
        self._append_log("AUTO armed")

    def _disable_auto(self) -> None:
        self.chk_auto_enabled.setChecked(False)
        self._refresh_monitor_labels()
        self._append_log("AUTO disabled")

    def _refresh_monitor_labels(self) -> None:
        enabled = self.chk_auto_enabled.isChecked()
        target = self.cbo_auto_target.currentText().strip()
        action = self.cbo_auto_action.currentText().strip()
        self.lbl_monitor.setText(f"AUTO: {'ĐANG BẬT' if enabled else 'ĐANG TẮT'} | Target: {target} | Action: {action}")
        self.lbl_monitor_rule.setText(f"Rule hiện tại: {self._build_rule_summary()}")

    def _build_rule_summary(self) -> str:
        parts: List[str] = []
        mapping = [
            ("Bệt", self.chk_rule_streak, self.spn_rule_streak),
            ("1:1", self.chk_rule_alt, self.spn_rule_alt),
            ("2:2", self.chk_rule_22, self.spn_rule_22),
            ("3:3", self.chk_rule_33, self.spn_rule_33),
        ]
        for name, chk, spin in mapping:
            if chk.isChecked():
                parts.append(f"{name} >= {spin.value()}")
        return " | ".join(parts) if parts else "Chưa chọn rule"

    def on_auto_snapshot(self, latest_round: object, final_rows: object) -> None:
        # Cơ chế cũ đã bỏ.
        # Auto hiện chỉ kích hoạt từ main.py sau khi final + delay 20 giây.
        return
        
    def on_auto_final_ready(self, trigger_sid: str, final_rows: object) -> None:
        try:
            self._refresh_monitor_labels()

            if not self.chk_auto_enabled.isChecked():
                return
            if not trigger_sid or final_rows is None:
                return

            final_items = [self._row_to_dict(x) for x in list(final_rows)]
            final_items = [x for x in final_items if x]

            valid_final_items = []
            for item in final_items:
                side = str(item.get("result_side") or "").strip().lower()
                sid = str(item.get("sid") or "").strip()
                if side in {"tai", "xiu"} and sid:
                    valid_final_items.append(item)

            if not valid_final_items:
                self.lbl_monitor_state.setText("AUTO final: chưa có dữ liệu final hợp lệ")
                self._append_log("AUTO final bỏ qua: chưa có dữ liệu final hợp lệ")
                return

            latest_final = valid_final_items[-1]
            latest_final_sid = str(latest_final.get("sid") or "").strip()
            latest_final_side = str(latest_final.get("result_side") or "").strip().lower()

            if latest_final_side not in {"tai", "xiu"}:
                self.lbl_monitor_state.setText("AUTO final: result_side final không hợp lệ")
                self._append_log("AUTO final bỏ qua: result_side final không hợp lệ")
                return

            mode_text = self.cbo_auto_action.currentText().strip().lower()
            if "ngược" in mode_text:
                action_side = self._opposite_side(latest_final_side)
            else:
                action_side = latest_final_side

            if action_side not in {"tai", "xiu"}:
                self.lbl_monitor_state.setText("AUTO final: không xác định được cửa đánh")
                self._append_log("AUTO final bỏ qua: không xác định được cửa đánh")
                return

            target = self.cbo_auto_target.currentText().strip()
            bet = self.cbo_auto_bet.currentText().strip()

            auto_key = f"{target}|{trigger_sid}|{latest_final_sid}|{action_side}|{bet}"
            if self._auto_last_key_by_target.get(target) == auto_key:
                self._append_log(f"Bỏ qua trùng AUTO key: {auto_key}")
                return

            reason = (
                f"trigger_sid={trigger_sid} | latest_final_sid={latest_final_sid} | "
                f"latest_final_side={latest_final_side} | action={action_side}"
            )

            self.lbl_monitor_state.setText(
                f"Final trigger {trigger_sid} -> đánh {'TÀI' if action_side == 'tai' else 'XỈU'} | target={target}"
            )
            self._append_log(f"FINAL READY -> {reason}")
            self._append_log(
                f"SCHEDULE FIRE -> {target} | {action_side.upper()} | bet={bet}"
            )

            ok = (
                self._emit_play_all(action_side, source="auto")
                if target == "ALL"
                else self._emit_auto_one(target, action_side)
            )

            if ok:
                self._auto_last_key_by_target[target] = auto_key
                self.lbl_monitor_state.setText(
                    f"Đã kích hoạt sau final: {target} | {'TÀI' if action_side == 'tai' else 'XỈU'} | "
                    f"theo final sid {latest_final_sid}"
                )
            else:
                self._append_log("AUTO final không phát được lệnh cược (busy hoặc thiếu bet)")
        except Exception as e:
            self.lbl_monitor_state.setText(f"AUTO final lỗi: {e}")
            self._append_log(f"AUTO final lỗi: {e}")

    def _emit_auto_one(self, profile_id: str, side: str) -> bool:
        if self._global_busy:
            return False
        bet = self.cbo_auto_bet.currentText().strip()
        delay_ms = int(self.spn_auto_delay.value())
        if not bet:
            self.lbl_monitor_state.setText("AUTO lỗi: Chưa chọn bet")
            return False
        self._set_global_busy(True)
        label_side = "TÀI" if side == "tai" else "XỈU"
        self.lbl_manual_status.setText(f"Status: AUTO {label_side} | {profile_id} | Bet {bet}")
        self.request_play_tai_xiu.emit(profile_id, {"side": side, "bet": bet, "delay_ms": delay_ms})
        QTimer.singleShot(2000, self._release_busy)
        return True

    def _row_to_dict(self, row: object) -> Mapping[str, object]:
        if isinstance(row, dict):
            return row
        try:
            return dict(row)
        except Exception:
            return {}

    def _is_rule_enabled(self, pattern_key: str, length: int) -> bool:
        mapping = {
            "streak": (self.chk_rule_streak, self.spn_rule_streak),
            "alt_1_1": (self.chk_rule_alt, self.spn_rule_alt),
            "block_2_2": (self.chk_rule_22, self.spn_rule_22),
            "block_3_3": (self.chk_rule_33, self.spn_rule_33),
        }
        item = mapping.get(pattern_key)
        if not item:
            return False
        chk, spin = item
        return chk.isChecked() and int(length) >= int(spin.value())

    def _predict_action_side(self, pattern_key: str, pattern_side: Optional[str], final_sides: Sequence[str]) -> Optional[str]:
        if not final_sides:
            return None
        last = final_sides[-1]
        if pattern_key == "streak":
            return pattern_side or last
        if pattern_key == "alt_1_1":
            return self._opposite_side(last)
        if pattern_key == "block_2_2":
            return self._predict_block_side(final_sides, 2)
        if pattern_key == "block_3_3":
            return self._predict_block_side(final_sides, 3)
        return None

    def _predict_block_side(self, sides: Sequence[str], block_size: int) -> Optional[str]:
        if not sides:
            return None
        last = sides[-1]
        tail = 1
        for idx in range(len(sides) - 2, -1, -1):
            if sides[idx] == last:
                tail += 1
            else:
                break
        if tail < block_size:
            return last
        return self._opposite_side(last)

    def _opposite_side(self, side: Optional[str]) -> Optional[str]:
        if side == "tai":
            return "xiu"
        if side == "xiu":
            return "tai"
        return None

    def _append_log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._logs.appendleft(f"[{stamp}] {text}")
        self.log_box.setPlainText("\n".join(self._logs))

    def dat_trang_thai(self, text: str) -> None:
        self.lbl_manual_status.setText(f"Status: {text}")
        self._set_global_busy(False)

    def dat_trang_thai_profile(self, profile_id: str, text: str) -> None:
        self.lbl_manual_status.setText(f"{profile_id}: {text}")
        self._set_global_busy(False)
