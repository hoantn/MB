from __future__ import annotations
from core.logger import log

from dataclasses import dataclass
from typing import List, Optional, Dict
from io import BytesIO

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QComboBox, QSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
    QDialog, QMessageBox,
    QListWidget, QListWidgetItem, QStackedWidget, QSizePolicy, QSplitter
)
from PySide6.QtGui import QPixmap, QMouseEvent, QGuiApplication

from browser.manager import BrowserManager
from core.config import load_config, save_config

# ---------------- DATA MODELS ----------------

@dataclass
class NguoiChoiPhong:
    ghe: int
    uid: str
    ten: str
    vang: Optional[int] = None


@dataclass
class TrangThaiPhong:
    room_id: Optional[int]
    bet: Optional[int]
    so_nguoi_hien_tai: int
    so_nguoi_toi_da: int
    nguoi_choi: List[NguoiChoiPhong]
    my_uid: Optional[str] = None


# ---------------- CLICK COPY LABEL ----------------

class ClickCopyLabel(QLabel):
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            text = (self.text() or "").strip()
            if text and text != "-":
                QGuiApplication.clipboard().setText(text)
        super().mousePressEvent(event)


# ---------------- PANEL PHÒNG CHO MỖI PROFILE ----------------

class PanelPhongProfile(QWidget):

    yeu_cau_tao_phong_auto = Signal(str, dict)
    yeu_cau_vao_phong_auto = Signal(str, dict)
    yeu_cau_tim_khach_auto = Signal(str, dict)
    yeu_cau_dung_tac_vu = Signal(str)
    yeu_cau_lam_moi_phong = Signal(str)
    yeu_cau_vao_cung_phong = Signal(str, str)  # (profile_hien_tai, profile_muc_tieu)
    yeu_cau_goi_team = Signal(str)  # host profile_id

    def __init__(self, profile_id: str, parent=None):
        super().__init__(parent)
        self.profile_id = profile_id

        # ----- LABEL MY UID (CLICK COPY) -----
        self.nhan_my_uid = ClickCopyLabel("-")
        self.nhan_my_uid.setToolTip("Nhấn để sao chép UID")

        self.nhan_room = QLabel("-")
        self.nhan_bet = QLabel("-")
        self.nhan_so_nguoi = QLabel("-")

        # ----- DANH SÁCH NGƯỜI CHƠI: TÊN - VÀNG - UID -----
        self.bang_nguoi_choi = QTableWidget(0, 4)
        self.bang_nguoi_choi.setHorizontalHeaderLabels(["Tên", "Vàng", "UID", "Gặp"])
        self.bang_nguoi_choi.setEditTriggers(QTableWidget.NoEditTriggers)
        self.bang_nguoi_choi.setSelectionBehavior(QTableWidget.SelectRows)
        self.bang_nguoi_choi.horizontalHeader().setStretchLastSection(True)
        self.bang_nguoi_choi.cellClicked.connect(self._on_player_clicked)

        # Map UID -> row để update realtime không rebuild table (tối ưu repaint)
        self._uid_to_row: Dict[str, int] = {}
        self._row_to_uid: List[str] = []

        # ----- LÀM MỚI TRẠNG THÁI PHÒNG -----
        self.nut_lam_moi = QPushButton("Làm mới")
        self.nut_lam_moi.setToolTip("Yêu cầu cập nhật trạng thái phòng (snapshot mới nhất)")
        self.nut_lam_moi.setMaximumWidth(120)
        self.nut_lam_moi.clicked.connect(self._lam_moi_trang_thai_phong)

        # ----- TẠO PHÒNG -----
        self.combo_bet_tao = QComboBox()
        self._init_bet_combo(self.combo_bet_tao)

        # ----- THỜI GIAN NGHỈ GIỮA 2 CHU KỲ (ANTI-SPAM) -----
        cfg = load_config()
        ui_room = (cfg.setdefault('ui', {}) ).setdefault('room', {})
        delay_create_ms = int(ui_room.get('delay_create_ms', 500) or 0)
        delay_join_ms = int(ui_room.get('delay_join_ms', 500) or 0)
        self.spin_delay_create = QSpinBox()
        self.spin_delay_create.setRange(0, 30000)
        self.spin_delay_create.setSingleStep(100)
        self.spin_delay_create.setSuffix(' ms')
        self.spin_delay_create.setValue(delay_create_ms)

        self.nut_tao_toggle = QPushButton("Tạo phòng")
        self.nhan_trang_thai_tao = QLabel("Đang dừng.")
        self.nut_tao_toggle.clicked.connect(self._xu_ly_tao)


        # ----- JOIN PHÒNG THEO UID -----
        self.edit_target_uid = QLineEdit()
        self.edit_target_uid.setMaximumWidth(260)

        # Nút vào cùng phòng theo UID của profile khác
        others = [p for p in ('P1','P2','P3') if p != self.profile_id]
        self.btn_follow_a = QPushButton(others[0])
        self.btn_follow_b = QPushButton(others[1])
        for b in (self.btn_follow_a, self.btn_follow_b):
            b.setMaximumWidth(44)
            b.setToolTip('Vào cùng phòng theo UID của ' + b.text())
            b.setStyleSheet('QPushButton{padding:4px 6px;font-weight:600;}')
        self.btn_follow_a.clicked.connect(lambda: self.yeu_cau_vao_cung_phong.emit(self.profile_id, self.btn_follow_a.text()))
        self.btn_follow_b.clicked.connect(lambda: self.yeu_cau_vao_cung_phong.emit(self.profile_id, self.btn_follow_b.text()))

        self.combo_bet_join = QComboBox()
        self._init_bet_combo(self.combo_bet_join)

        self.spin_delay_join = QSpinBox()
        self.spin_delay_join.setRange(0, 30000)
        self.spin_delay_join.setSingleStep(100)
        self.spin_delay_join.setSuffix(' ms')
        self.spin_delay_join.setValue(delay_join_ms)

        self.nut_join_toggle = QPushButton("Vào phòng")
        self.nhan_trang_thai_join = QLabel("Đang dừng.")
        self.nut_join_toggle.clicked.connect(self._xu_ly_join)

        # ----- TÌM KHÁCH (GIỐNG TẠO PHÒNG, KHÁC ĐK THÀNH CÔNG) -----
        self.nut_find_toggle = QPushButton("Tìm khách")
        self.nhan_trang_thai_find = QLabel("Đang dừng.")
        self.nut_find_toggle.clicked.connect(self._xu_ly_find_guest)

        # Style giống create/join (xanh)
        self.nut_find_toggle.setStyleSheet(
            "QPushButton{background-color:#2e7d32;color:white;font-weight:600;padding:6px 10px;border-radius:4px;}"
        )

        self._dang_find = False

        # ----- STYLE (nhẹ, không phụ thuộc theme) -----
        self.nut_tao_toggle.setStyleSheet(
            "QPushButton{background-color:#2e7d32;color:white;font-weight:600;padding:6px 10px;border-radius:4px;}"
        )
        self.nut_join_toggle.setStyleSheet(
            "QPushButton{background-color:#2e7d32;color:white;font-weight:600;padding:6px 10px;border-radius:4px;}"
        )
        self.nut_lam_moi.setStyleSheet("QPushButton{padding:4px 10px;}")

        self._dang_tao = False
        self._dang_join = False

        self._build_ui()

    # ---------------- HELPERS ----------------

    def _goi_team(self):
        self.yeu_cau_goi_team.emit(self.profile_id)

    def _init_bet_combo(self, combo: QComboBox):
        bets = [
            100, 500, 1000, 2000, 5000, 10000, 20000,
            50000, 100000, 200000, 500000, 1000000
        ]
        combo.clear()
        for v in bets:
            combo.addItem(f"{v:,}", v)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ===== Header (giống mẫu 2) =====
        header = QWidget()
        h = QVBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)

        self.lbl_title = QLabel(f"Chi tiết phòng ({self.profile_id})")
        ft = self.lbl_title.font()
        ft.setBold(True)
        ft.setPointSize(ft.pointSize() + 1)
        self.lbl_title.setFont(ft)

        title_row.addWidget(self.lbl_title)
        title_row.addStretch(1)
        h.addLayout(title_row)

        # Summary line: Room | Bet | Players
        sum_row = QHBoxLayout()
        sum_row.setContentsMargins(0, 0, 0, 0)
        sum_row.setSpacing(12)

        sum_row.addWidget(QLabel("Phòng:"))
        sum_row.addWidget(self.nhan_room)
        sum_row.addSpacing(12)

        sum_row.addWidget(QLabel("Cược:"))
        sum_row.addWidget(self.nhan_bet)
        sum_row.addSpacing(12)

        sum_row.addWidget(QLabel("Người:"))
        sum_row.addWidget(self.nhan_so_nguoi)
        sum_row.addStretch(1)
        sum_row.addWidget(self.nut_lam_moi, 0)

        h.addLayout(sum_row)

        myuid_row = QHBoxLayout()
        myuid_row.setContentsMargins(0, 0, 0, 0)
        myuid_row.addWidget(QLabel("UID của tôi:"))
        myuid_row.addWidget(self.nhan_my_uid)
        myuid_row.addStretch(1)
        h.addLayout(myuid_row)

        root.addWidget(header)

        # ===== Players table =====
        g_players = QGroupBox("Danh sách người chơi")
        v_players = QVBoxLayout(g_players)
        v_players.setContentsMargins(8, 8, 8, 8)
        v_players.addWidget(self.bang_nguoi_choi)
        root.addWidget(g_players, 1)  # stretch

        # ===== Actions (Create / Join / Stop) =====
        g_actions = QGroupBox("Thao tác")
        v = QVBoxLayout(g_actions)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # Row: Create (swap: chọn tọa độ trước, bet sau)
        row_create = QHBoxLayout()
        row_create.setSpacing(8)
        row_create.addStretch(1)
        row_create.addWidget(QLabel("Tạo phòng:"))
        row_create.addWidget(self.combo_bet_tao, 0)
        # row_create.addWidget(QLabel('Nghỉ:'), 0)
        # row_create.addWidget(self.spin_delay_create, 0)
        row_create.addWidget(self.nut_tao_toggle, 0)
        # NEW: nút gọi team
        others = [p for p in ('P1','P2','P3') if p != self.profile_id]
        self.btn_call_team = QPushButton(f"Gọi ({others[0]} - {others[1]}) vào phòng")
        self.btn_call_team.setStyleSheet(
            "QPushButton{background-color:#1565c0;color:white;font-weight:600;padding:6px 10px;border-radius:4px;}"
        )
        self.btn_call_team.clicked.connect(self._goi_team)

        row_create.addWidget(self.btn_call_team, 0)
        v.addLayout(row_create)

        v.addWidget(self.nhan_trang_thai_tao)

        # Row: Join
        row_join = QHBoxLayout()
        row_join.setSpacing(8)
        row_join.addWidget(QLabel("UID mục tiêu:"))
        row_join.addWidget(self.btn_follow_a, 0)
        row_join.addWidget(self.btn_follow_b, 0)
        row_join.addWidget(self.edit_target_uid, 0)
        row_join.addStretch(1)
        row_join.addWidget(QLabel("Cược:"))
        row_join.addWidget(self.combo_bet_join, 0)
        # row_join.addWidget(QLabel('Nghỉ:'), 0)
        # row_join.addWidget(self.spin_delay_join, 0)
        row_join.addWidget(self.nut_join_toggle, 0)
        v.addLayout(row_join)

        v.addWidget(self.nhan_trang_thai_join)

        # Row: Find guest (NEW) - đặt dưới "Vào phòng"
        row_find = QHBoxLayout()
        row_find.setSpacing(8)
        row_find.addStretch(1)
        row_find.addWidget(QLabel("Tìm khách:"))
        row_find.addWidget(self.nut_find_toggle, 0)
        v.addLayout(row_find)

        v.addWidget(self.nhan_trang_thai_find)
        
        # Row: Stop (dừng mọi tác vụ)
        row_stop = QHBoxLayout()
        row_stop.addStretch(1)
        self.nut_stop = QPushButton("Dừng")
        self.nut_stop.setStyleSheet(
            "QPushButton{background-color:#c62828;color:white;font-weight:700;padding:6px 14px;border-radius:4px;}"
        )
        self.nut_stop.clicked.connect(self._stop_all_tasks)
        row_stop.addWidget(self.nut_stop)
        v.addLayout(row_stop)

        root.addWidget(g_actions)

    # ---------------- EVENTS ----------------


    def set_refreshing(self, refreshing: bool) -> None:
        """Bật/tắt trạng thái đang làm mới phòng (UI only)."""
        try:
            self.nut_lam_moi.setEnabled(not refreshing)
            self.nut_lam_moi.setText("Đang làm mới..." if refreshing else "Làm mới")
        except Exception:
            pass

    def _lam_moi_trang_thai_phong(self) -> None:
        """Yêu cầu Engine làm mới trạng thái phòng cho profile hiện tại."""
        try:
            self.set_refreshing(True)
            self.yeu_cau_lam_moi_phong.emit(self.profile_id)
        except Exception as e:
            log.exception("RoomTab _lam_moi_trang_thai_phong crashed: %s", e)

    def _stop_all_tasks(self) -> None:
        """Dừng cả tạo phòng và vào phòng cho profile hiện tại (UI + Engine)."""
        try:
            self._dang_tao = False
            self._dang_join = False
            self._dang_find = False
            self.nut_tao_toggle.setText("Tạo phòng")
            self.nut_join_toggle.setText("Vào phòng")
            self.nhan_trang_thai_tao.setText("Đang dừng.")
            self.nhan_trang_thai_join.setText("Đang dừng.")
            self.nut_find_toggle.setText("Tìm khách")
            self.nhan_trang_thai_find.setText("Đang dừng.")
            self.yeu_cau_dung_tac_vu.emit(self.profile_id)
        except Exception as e:
            log.exception("RoomTab _stop_all_tasks crashed: %s", e)

    def _on_player_clicked(self, row, col):
        # Chỉ copy khi click vào cột UID
        if col != 2:
            return
        try:
            item = self.bang_nguoi_choi.item(row, col)
            if item:
                uid = (item.text() or "").strip()
                if uid:
                    QGuiApplication.clipboard().setText(uid)
        except Exception as e:
            log.exception("RoomTab _on_player_clicked crashed: %s", e)

    def _xu_ly_tao(self):
        if not self._dang_tao:
            bet = self.combo_bet_tao.currentData()
            delay_ms = int(self.spin_delay_create.value())
            params = {"bet": bet, "delay_ms": delay_ms}
            self._save_room_delay('delay_create_ms', delay_ms)
            self._dang_tao = True
            self.nut_tao_toggle.setText("Dừng tạo")
            self.nhan_trang_thai_tao.setText("Đang tạo phòng...")
            self.yeu_cau_tao_phong_auto.emit(self.profile_id, params)
        else:
            self._dang_tao = False
            self.nut_tao_toggle.setText("Tạo phòng")
            self.nhan_trang_thai_tao.setText("Đang dừng.")
            self.yeu_cau_dung_tac_vu.emit(self.profile_id)

    def _xu_ly_join(self):
        if not self._dang_join:
            uid = self.edit_target_uid.text().strip()
            bet = self.combo_bet_join.currentData()
            delay_ms = int(self.spin_delay_join.value())
            params = {"target_uid": uid, "bet": bet, "delay_ms": delay_ms}
            self._save_room_delay('delay_join_ms', delay_ms)
            self._dang_join = True
            self.nut_join_toggle.setText("Dừng vào")
            self.nhan_trang_thai_join.setText(f"Đang tìm/vào (UID {uid})...")
            self.yeu_cau_vao_phong_auto.emit(self.profile_id, params)
        else:
            self._dang_join = False
            self.nut_join_toggle.setText("Vào phòng")
            self.nhan_trang_thai_join.setText("Đang dừng.")
            self.yeu_cau_dung_tac_vu.emit(self.profile_id)

    def _xu_ly_find_guest(self):
        if not self._dang_find:
            bet = self.combo_bet_tao.currentData()
            delay_ms = int(self.spin_delay_create.value())  # dùng y hệt tạo phòng
            params = {"bet": bet, "delay_ms": delay_ms}
            self._save_room_delay('delay_create_ms', delay_ms)  # dùng y hệt tạo phòng

            self._dang_find = True
            self.nut_find_toggle.setText("Dừng tìm")
            self.nhan_trang_thai_find.setText("Đang tìm khách (bàn có sẵn 1 người)...")
            self.yeu_cau_tim_khach_auto.emit(self.profile_id, params)
        else:
            self._dang_find = False
            self.nut_find_toggle.setText("Tìm khách")
            self.nhan_trang_thai_find.setText("Đang dừng.")
            self.yeu_cau_dung_tac_vu.emit(self.profile_id)
        
    def _save_room_delay(self, key: str, value: int) -> None:
        """Lưu cấu hình thời gian nghỉ vào config.json (an toàn, best-effort)."""
        try:
            cfg = load_config()
            ui_room = (cfg.setdefault("ui", {})).setdefault("room", {})
            ui_room[key] = int(value)
            save_config(cfg)
        except Exception:
            # không làm crash UI
            pass

    def start_join_with_uid(self, uid: str, bet: Optional[int] = None) -> None:
        """Bấm nút P2/P3: tự điền UID (và đồng bộ cược nếu có) rồi bắt đầu vào phòng (nếu chưa chạy)."""
        try:
            if not uid:
                return

            # 1) Điền UID mục tiêu
            self.edit_target_uid.setText(uid)

            # 2) Đồng bộ mức cược theo profile mục tiêu (nếu có)
            if bet is not None:
                try:
                    idx = self.combo_bet_join.findData(int(bet))
                    if idx >= 0:
                        self.combo_bet_join.setCurrentIndex(idx)
                except Exception:
                    pass

            # 3) Bắt đầu vào phòng (nếu chưa chạy)
            if not self._dang_join:
                self._xu_ly_join()
        except Exception as e:
            log.exception("RoomTab start_join_with_uid crashed: %s", e)


# ---------------- ENGINE → UI UPDATE ----------------

    def dat_trang_thai_tao(self, text: str, dang_chay: Optional[bool] = None) -> None:
        """Engine gọi để cập nhật trạng thái khối TẠO PHÒNG."""
        self.nhan_trang_thai_tao.setText(text)
        # tô màu để nhận biết trạng thái thành công
        if text.strip().startswith("ĐÃ TẠO"):
            self.nhan_trang_thai_tao.setStyleSheet("color: rgb(0, 170, 0); font-weight: 600;")
        else:
            self.nhan_trang_thai_tao.setStyleSheet("")

        if dang_chay is not None:
            self._dang_tao = bool(dang_chay)
            self.nut_tao_toggle.setText("Dừng tạo" if dang_chay else "Tạo phòng")

    def dat_trang_thai_join(self, text: str, dang_chay: Optional[bool] = None) -> None:
        """Engine gọi để cập nhật trạng thái khối VÀO PHÒNG."""
        self.nhan_trang_thai_join.setText(text)
        # tô màu để nhận biết trạng thái thành công
        if text.strip().startswith("ĐÃ VÀO"):
            self.nhan_trang_thai_join.setStyleSheet("color: rgb(0, 170, 0); font-weight: 600;")
        else:
            self.nhan_trang_thai_join.setStyleSheet("")
        if dang_chay is not None:
            self._dang_join = bool(dang_chay)
            self.nut_join_toggle.setText("Dừng vào" if dang_chay else "Vào phòng")
            
    def dat_trang_thai_find(self, text: str, dang_chay: Optional[bool] = None) -> None:
        """Engine gọi để cập nhật trạng thái khối TÌM KHÁCH."""
        self.nhan_trang_thai_find.setText(text)
        if text.strip().startswith("ĐÃ TÌM"):
            self.nhan_trang_thai_find.setStyleSheet("color: rgb(0, 170, 0); font-weight: 600;")
        else:
            self.nhan_trang_thai_find.setStyleSheet("")
        if dang_chay is not None:
            self._dang_find = bool(dang_chay)
            self.nut_find_toggle.setText("Dừng tìm" if dang_chay else "Tìm khách")

    def cap_nhat_trang_thai_phong(self, st: TrangThaiPhong, target_uid=None) -> None:
        """Update snapshot phòng (tối ưu: update từng row theo uid, không rebuild toàn bảng)."""
        try:
            self.nhan_my_uid.setText(st.my_uid or "-")
            self.nhan_room.setText("-" if st.room_id is None else str(st.room_id))
            self.nhan_bet.setText("-" if st.bet is None else str(st.bet))
            self.nhan_so_nguoi.setText(f"{st.so_nguoi_hien_tai}/{st.so_nguoi_toi_da}")

            ds = st.nguoi_choi or []
            desired_uids: List[str] = [str(p.uid or "").strip() for p in ds if str(p.uid or "").strip()]
            desired_set = set(desired_uids)

            # 1) Remove rows for uids no longer present (từ cuối lên để không lệch index)
            r = len(self._row_to_uid) - 1
            while r >= 0:
                uid = self._row_to_uid[r]
                if uid not in desired_set:
                    self.bang_nguoi_choi.removeRow(r)
                    self._row_to_uid.pop(r)
                    self._uid_to_row.pop(uid, None)
                    # reindex mapping for rows after removed
                    for i in range(r, len(self._row_to_uid)):
                        self._uid_to_row[self._row_to_uid[i]] = i
                r -= 1

            # 2) Ensure rows exist and follow the desired order (swap/move minimal)
            def _swap_rows(a: int, b: int) -> None:
                if a == b:
                    return
                # swap items
                for c in range(self.bang_nguoi_choi.columnCount()):
                    ia = self.bang_nguoi_choi.takeItem(a, c)
                    ib = self.bang_nguoi_choi.takeItem(b, c)
                    self.bang_nguoi_choi.setItem(a, c, ib)
                    self.bang_nguoi_choi.setItem(b, c, ia)
                # swap uid tracking
                ua, ub = self._row_to_uid[a], self._row_to_uid[b]
                self._row_to_uid[a], self._row_to_uid[b] = ub, ua
                self._uid_to_row[ua], self._uid_to_row[ub] = b, a

            # add missing uids (append)
            for uid in desired_uids:
                if uid and uid not in self._uid_to_row:
                    row = self.bang_nguoi_choi.rowCount()
                    self.bang_nguoi_choi.insertRow(row)
                    self._uid_to_row[uid] = row
                    self._row_to_uid.append(uid)
                    # init empty items once
                    self.bang_nguoi_choi.setItem(row, 0, QTableWidgetItem(""))
                    self.bang_nguoi_choi.setItem(row, 1, QTableWidgetItem(""))
                    self.bang_nguoi_choi.setItem(row, 2, QTableWidgetItem(uid))
                    self.bang_nguoi_choi.setItem(row, 3, QTableWidgetItem("0"))

            # reorder via swaps (O(n^2) worst-case but n<=4 nên rất nhẹ)
            for desired_row, uid in enumerate(desired_uids):
                cur_row = self._uid_to_row.get(uid)
                if cur_row is None:
                    continue
                if cur_row != desired_row:
                    _swap_rows(cur_row, desired_row)

            # 3) Update cell contents only if changed
            for desired_row, p in enumerate(ds):
                uid = str(p.uid or "").strip()
                if not uid:
                    continue
                row = self._uid_to_row.get(uid)
                if row is None:
                    continue

                ten = str(p.ten or "").strip()
                vang_text = "" if p.vang is None else str(p.vang)

                it0 = self.bang_nguoi_choi.item(row, 0)
                if it0 is None:
                    it0 = QTableWidgetItem("")
                    self.bang_nguoi_choi.setItem(row, 0, it0)
                if it0.text() != ten:
                    it0.setText(ten)

                it1 = self.bang_nguoi_choi.item(row, 1)
                if it1 is None:
                    it1 = QTableWidgetItem("")
                    self.bang_nguoi_choi.setItem(row, 1, it1)
                if it1.text() != vang_text:
                    it1.setText(vang_text)

                it2 = self.bang_nguoi_choi.item(row, 2)
                if it2 is None:
                    it2 = QTableWidgetItem(uid)
                    self.bang_nguoi_choi.setItem(row, 2, it2)
                if it2.text() != uid:
                    it2.setText(uid)

            # 4) Update "Gặp" (meet_times) bằng batch query (nhẹ)
            for uid in desired_uids:
                row = self._uid_to_row.get(uid)
                if row is None:
                    continue
                it3 = self.bang_nguoi_choi.item(row, 3)
                if it3 is None:
                    it3 = QTableWidgetItem("")
                    self.bang_nguoi_choi.setItem(row, 3, it3)
                if it3.text():
                    it3.setText("")

        except Exception as e:
            log.exception(
                "RoomTab cap_nhat_trang_thai_phong crashed (profile=%s, room_id=%s): %s",
                self.profile_id,
                getattr(st, "room_id", None),
                e,
            )
# ---------------- TAB ROOM ----------------

class RoomControlTab(QWidget):

    request_auto_create_room = Signal(str, dict)
    request_auto_join_room = Signal(str, dict)
    request_stop_room_task = Signal(str)
    request_refresh_room = Signal(str)
    request_auto_find_guest_room = Signal(str, dict)

    def __init__(self, browser_manager: BrowserManager, parent=None):
        super().__init__(parent)
        self.browser_manager = browser_manager

        # Panels theo profile
        self.panels: Dict[str, PanelPhongProfile] = {}

        # Master–Detail state
        self._pid_to_index: Dict[str, int] = {}
        self._last_room_state: Dict[str, Optional[TrangThaiPhong]] = {"P1": None, "P2": None, "P3": None}
        self._task_state: Dict[str, Dict[str, bool]] = {
            "P1": {"create": False, "join": False},
            "P2": {"create": False, "join": False},
            "P3": {"create": False, "join": False},
        }

        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        # ----- Left: profile nav -----
        self.profile_nav = QListWidget()
        self.profile_nav.setObjectName("room_profile_nav")
        # Cho phép kéo thay đổi width: dùng min/max thay vì fixedWidth
        self.profile_nav.setMinimumWidth(40)
        self.profile_nav.setMaximumWidth(400)
        self.profile_nav.setSpacing(4)
        self.profile_nav.setSelectionMode(QListWidget.SingleSelection)

        # ----- Right: detail stack -----
        self.detail_stack = QStackedWidget()
        self.detail_stack.setObjectName("room_detail_stack")
        self.detail_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # ----- Splitter ngang giữa nav và detail -----
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("room_main_splitter")
        splitter.addWidget(self.profile_nav)
        splitter.addWidget(self.detail_stack)
        # hệ số co giãn: bên phải chiếm phần còn lại
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # kích thước khởi tạo, tương đương 240px cho nav
        splitter.setSizes([90, 800])

        root.addWidget(splitter)

        # Build panels + nav items
        for pid in ("P1", "P2", "P3"):
            p = PanelPhongProfile(pid)
            self.panels[pid] = p
            idx = self.detail_stack.addWidget(p)
            self._pid_to_index[pid] = idx

            # Relay UI signals -> RoomEngine (giữ nguyên API)
            p.yeu_cau_tao_phong_auto.connect(self.request_auto_create_room)
            p.yeu_cau_vao_phong_auto.connect(self.request_auto_join_room)
            p.yeu_cau_tim_khach_auto.connect(self.request_auto_find_guest_room)
            p.yeu_cau_dung_tac_vu.connect(self.request_stop_room_task)
            p.yeu_cau_lam_moi_phong.connect(self.request_refresh_room)
            p.yeu_cau_vao_cung_phong.connect(self._on_ui_vao_cung_phong)
            p.yeu_cau_goi_team.connect(self._on_ui_goi_team)

            item = QListWidgetItem(self._format_nav_text(pid))
            try:
                # Icon nhẹ, không phụ thuộc file ảnh
                if pid == "P1":
                    item.setIcon(self.style().standardIcon(self.style().SP_ComputerIcon))
                elif pid == "P2":
                    item.setIcon(self.style().standardIcon(self.style().SP_DriveHDIcon))
                else:
                    item.setIcon(self.style().standardIcon(self.style().SP_DirIcon))
            except Exception:
                pass
            item.setData(Qt.UserRole, pid)
            self.profile_nav.addItem(item)

        self.profile_nav.currentRowChanged.connect(self._on_nav_changed)

        # Default select P1
        self.profile_nav.setCurrentRow(0)
        self._on_nav_changed(0)

    def _on_nav_changed(self, row: int) -> None:
        try:
            if row < 0:
                return
            item = self.profile_nav.item(row)
            if not item:
                return
            pid = item.data(Qt.UserRole)
            if not pid:
                return
            idx = self._pid_to_index.get(str(pid))
            if idx is None:
                return
            self.detail_stack.setCurrentIndex(idx)
        except Exception as e:
            log.exception("RoomTab _on_nav_changed crashed: %s", e)


    def _on_ui_vao_cung_phong(self, pid_hien_tai: str, pid_muc_tieu: str) -> None:
        """UI yêu cầu 'vào cùng phòng' theo UID của profile mục tiêu."""
        try:
            st = self._last_room_state.get(pid_muc_tieu)
            uid = None
            if st is not None:
                uid = getattr(st, "my_uid", None)
            uid = (uid or "").strip() if isinstance(uid, str) else str(uid or "").strip()
            bet = None
            if st is not None:
                bet = getattr(st, "bet", None)

            panel = self.panels.get(pid_hien_tai)
            if not panel:
                return
            if not uid or uid == "-":
                # Không có UID để follow
                QMessageBox.information(self, "Thông báo", f"Chưa có UID của {pid_muc_tieu}. Hãy vào/tạo phòng để có UID trước.")
                return
            panel.start_join_with_uid(uid, bet)
        except Exception as e:
            log.exception("RoomTab _on_ui_vao_cung_phong crashed: %s", e)
            
    def _on_ui_goi_team(self, host_pid: str) -> None:
        """
        Host gọi toàn bộ profile còn lại vào phòng.
        Reuse start_join_with_uid -> không đụng engine.
        """
        try:
            st = self._last_room_state.get(host_pid)

            uid = None
            bet = None

            if st is not None:
                uid = getattr(st, "my_uid", None)
                bet = getattr(st, "bet", None)

            uid = (uid or "").strip() if isinstance(uid, str) else str(uid or "").strip()

            # ⭐ Popup nếu host chưa có UID
            if not uid or uid == "-":
                QMessageBox.information(
                    self,
                    "Thông báo",
                    f"{host_pid} chưa có UID.\nHãy tạo/vào phòng trước."
                )
                return

            # Followers
            others = [p for p in ("P1","P2","P3") if p != host_pid]

            for follower in others:
                panel = self.panels.get(follower)
                if not panel:
                    continue

                panel.start_join_with_uid(uid, bet)

        except Exception as e:
            log.exception("RoomTab _on_ui_goi_team crashed: %s", e)

    def _format_nav_text(self, pid: str) -> str:
        st = self._last_room_state.get(pid)
        tasks = self._task_state.get(pid) or {"create": False, "join": False}

        # Task tag (ưu tiên hiển thị)
        tag = ""
        if tasks.get("create"):
            tag = "TẠO"
        elif tasks.get("join"):
            tag = "VÀO"

        if not st:
            base = f"{pid}"
            return f"{base}   [{tag}]" if tag else base

        bet = "-" if st.bet is None else str(st.bet)
        room_id = "-" if st.room_id is None else str(st.room_id)
        so = f"{st.so_nguoi_hien_tai}/{st.so_nguoi_toi_da}"

        base = f"{pid}  Phòng:{room_id}  Cược:{bet}  {so}"
        return f"{base}  [{tag}]" if tag else base

    def _refresh_nav_item(self, pid: str) -> None:
        try:
            for i in range(self.profile_nav.count()):
                it = self.profile_nav.item(i)
                if not it:
                    continue
                if it.data(Qt.UserRole) == pid:
                    it.setText(self._format_nav_text(pid))
                    break
        except Exception as e:
            log.exception("RoomTab _refresh_nav_item(%s) crashed: %s", pid, e)

    # ------------- ENGINE → UI UPDATE -------------
    def cap_nhat_trang_thai_phong(self, pid: str, st: TrangThaiPhong, target_uid=None):
        panel = self.panels.get(pid)
        if not panel:
            log.warning("RoomTab cap_nhat_trang_thai_phong: panel %s không tồn tại", pid)
            return
        try:
            panel.cap_nhat_trang_thai_phong(st, target_uid)
            if hasattr(panel, "set_refreshing"):
                panel.set_refreshing(False)
            self._last_room_state[pid] = st
            self._refresh_nav_item(pid)
        except Exception as e:
            log.exception(
                "RoomControlTab cap_nhat_trang_thai_phong crashed (pid=%s, room_id=%s): %s",
                pid,
                getattr(st, "room_id", None),
                e,
            )

    def dat_trang_thai_tao(self, profile_id: str, text: str, dang_chay: Optional[bool] = None) -> None:
        panel = self.panels.get(profile_id)
        if not panel:
            log.warning("RoomTab dat_trang_thai_tao: panel %s không tồn tại", profile_id)
            return
        try:
            panel.dat_trang_thai_tao(text, dang_chay)
            if dang_chay is not None:
                self._task_state[profile_id]["create"] = bool(dang_chay)
                if bool(dang_chay):
                    self._task_state[profile_id]["join"] = False
                self._refresh_nav_item(profile_id)
        except Exception as e:
            log.exception(
                "RoomControlTab dat_trang_thai_tao crashed (pid=%s): %s",
                profile_id,
                e,
            )

    def dat_trang_thai_join(self, profile_id: str, text: str, dang_chay: Optional[bool] = None) -> None:
        panel = self.panels.get(profile_id)
        if not panel:
            log.warning("RoomTab dat_trang_thai_join: panel %s không tồn tại", profile_id)
            return
        try:
            panel.dat_trang_thai_join(text, dang_chay)
            if dang_chay is not None:
                self._task_state[profile_id]["join"] = bool(dang_chay)
                if bool(dang_chay):
                    self._task_state[profile_id]["create"] = False
                self._refresh_nav_item(profile_id)
        except Exception as e:
            log.exception(
                "RoomControlTab dat_trang_thai_join crashed (pid=%s): %s",
                profile_id,
                e,
            )
    def dat_trang_thai_find(self, profile_id: str, text: str, dang_chay: Optional[bool] = None) -> None:
        panel = self.panels.get(profile_id)
        if not panel:
            log.warning("RoomTab dat_trang_thai_find: panel %s không tồn tại", profile_id)
            return
        try:
            panel.dat_trang_thai_find(text, dang_chay)
            # (không bắt buộc) nếu bạn muốn tag nav thì thêm task_state, còn không thì bỏ
            self._refresh_nav_item(profile_id)
        except Exception as e:
            log.exception("RoomControlTab dat_trang_thai_find crashed (pid=%s): %s", profile_id, e)
