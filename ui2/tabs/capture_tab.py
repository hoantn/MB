from typing import Optional
import copy

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QSpinBox,
    QGroupBox,
    QFormLayout,
    QMessageBox,
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from browser.manager import BrowserManager
from capture.capture_manager import CaptureManager
from capture.region import set_game_region, get_game_region, set_slot, get_slots
from core.logger import log
from ui2.widgets.image_preview import ImagePreview
from core.config import load_config, save_config

class CaptureTab(QWidget):
    """Capture / DevTools tab.

    - Chỉ dùng DevTools capture (BrowserManager + CaptureManager).
    - Nút chụp full → hiển thị ảnh ở Preview.
    - Người dùng drag vùng game trên Preview → Apply game region.
    - Chỉnh slot cho 13 lá bằng số (x, y, width, height) → Apply slot.
    """

    def __init__(
        self,
        browser_manager: BrowserManager,
        capture_manager: CaptureManager,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.browser_manager = browser_manager
        self.capture_manager = capture_manager

        self.current_profile = "P1"
        self.current_full_pixmap: Optional[QPixmap] = None
        self.current_selection = None  # (x, y, w, h) in image coordinates

        # State: chọn 12 tọa độ Bet theo thứ tự
        self._bet_pick_mode: bool = False
        self._bet_pick_bets: list[str] = []
        self._bet_pick_index: int = 0
        self._bet_pick_target: str = "room"
        
        # State: chọn điểm EXIT (1 hoặc 2)
        self._exit_pick_mode: bool = False
        self._exit_pick_index: int = 1  # 1 = thoát phòng 1, 2 = thoát phòng 2
        
        # State: chọn tọa độ Tài/Xỉu
        self._taixiu_pick_mode: bool = False
        self._taixiu_pick_side: str = ""
        self._taixiu_pick_kind: str = ""
        
        self._build_ui()
        self._load_existing_region()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Top controls
        top = QHBoxLayout()
        top.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["P1", "P2", "P3"])
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        top.addWidget(self.profile_combo)

        capture_btn = QPushButton("Chụp full từ DevTools")
        capture_btn.clicked.connect(self.capture_full)
        top.addWidget(capture_btn)

        apply_region_btn = QPushButton("Áp dụng vùng game từ selection")
        apply_region_btn.clicked.connect(self.apply_region_from_selection)
        top.addWidget(apply_region_btn)

        fix_btn = QPushButton("Fix nhanh tọa độ kéo")
        fix_btn.clicked.connect(self.fix_coordinates_clicked)
        top.addWidget(fix_btn)
        
        # Fix 12 tọa độ Bet (vào phòng) cho profile hiện tại
        fix_bets_btn = QPushButton("Fix tọa độ vào phòng")
        fix_bets_btn.setToolTip("Chọn lần lượt 12 nút Bet cho profile hiện tại trên ảnh Preview")
        fix_bets_btn.clicked.connect(self.fix_enter_bets_clicked)
        top.addWidget(fix_bets_btn)
        
        fix_tx_bets_btn = QPushButton("Fix chip Tài/Xỉu")
        fix_tx_bets_btn.setToolTip("Chọn lần lượt các chip cược cho Tài/Xỉu của profile hiện tại")
        fix_tx_bets_btn.clicked.connect(self.fix_taixiu_bets_clicked)
        top.addWidget(fix_tx_bets_btn)

        fix_tai_btn = QPushButton("Fix nút Tài")
        fix_tai_btn.setToolTip("Chọn tọa độ nút Tài trên ảnh Preview cho profile hiện tại")
        fix_tai_btn.clicked.connect(self.fix_tai_clicked)
        top.addWidget(fix_tai_btn)

        fix_xiu_btn = QPushButton("Fix nút Xỉu")
        fix_xiu_btn.setToolTip("Chọn tọa độ nút Xỉu trên ảnh Preview cho profile hiện tại")
        fix_xiu_btn.clicked.connect(self.fix_xiu_clicked)
        top.addWidget(fix_xiu_btn)
        
        fix_confirm_btn = QPushButton("Fix nút Đặt cược")
        fix_confirm_btn.setToolTip("Chọn tọa độ nút ĐẶT CƯỢC trên ảnh Preview cho profile hiện tại")
        fix_confirm_btn.clicked.connect(self.fix_confirm_clicked)
        top.addWidget(fix_confirm_btn)   
        
        fix_exit1_btn = QPushButton("Fix tọa độ thoát phòng 1")
        fix_exit1_btn.setToolTip("Chọn tọa độ nút Thoát phòng #1 trên ảnh Preview cho profile hiện tại")
        fix_exit1_btn.clicked.connect(self.fix_exit_room1_clicked)
        top.addWidget(fix_exit1_btn)

        fix_exit2_btn = QPushButton("Fix tọa độ thoát phòng 2")
        fix_exit2_btn.setToolTip("Chọn tọa độ nút Thoát phòng #2 trên ảnh Preview cho profile hiện tại")
        fix_exit2_btn.clicked.connect(self.fix_exit_room2_clicked)
        top.addWidget(fix_exit2_btn)
        
        sync_btn = QPushButton("Đồng bộ config")
        sync_btn.setToolTip("Copy tọa độ P1 sang P2, P3 (bet vào phòng, thoát phòng, 13 lá)")
        sync_btn.clicked.connect(self.sync_config_from_p1)
        top.addWidget(sync_btn)

        top.addStretch()
        root.addLayout(top)

        # Preview
        self.preview = ImagePreview(self)
        self.preview.selectionChanged.connect(self._on_selection_changed)
        root.addWidget(self.preview, stretch=3)

        # Slot editor
        slot_group = QGroupBox("Slot 1-13 (tọa độ tương đối trong vùng game)")
        slot_form = QFormLayout(slot_group)

        self.slot_index_spin = QSpinBox()
        self.slot_index_spin.setRange(1, 13)

        self.slot_x_spin = QSpinBox()
        self.slot_x_spin.setRange(0, 10000)
        self.slot_y_spin = QSpinBox()
        self.slot_y_spin.setRange(0, 10000)
        self.slot_w_spin = QSpinBox()
        self.slot_w_spin.setRange(1, 10000)
        self.slot_h_spin = QSpinBox()
        self.slot_h_spin.setRange(1, 10000)

        slot_form.addRow("Slot index:", self.slot_index_spin)
        slot_form.addRow("X:", self.slot_x_spin)
        slot_form.addRow("Y:", self.slot_y_spin)
        slot_form.addRow("Width:", self.slot_w_spin)
        slot_form.addRow("Height:", self.slot_h_spin)

        load_slot_btn = QPushButton("Load slot hiện tại")
        load_slot_btn.clicked.connect(self.load_slot_config)
        save_slot_btn = QPushButton("Lưu slot")
        save_slot_btn.clicked.connect(self.save_slot_config)

        btn_row = QHBoxLayout()
        btn_row.addWidget(load_slot_btn)
        btn_row.addWidget(save_slot_btn)
        btn_row.addStretch()
        slot_form.addRow(btn_row)

        root.addWidget(slot_group, stretch=1)

    # ------------------------------------------------------------------ Events / helpers

    def _on_profile_changed(self, pid: str) -> None:
        self.current_profile = pid
        self._load_existing_region()
        self._load_existing_slots()
        
    def fix_coordinates_clicked(self) -> None:
        """
        Nút Fix tọa độ:
        - Lần đầu: khởi tạo toạ độ design 1280x720 từ config hiện tại.
        - Các lần sau: dùng design + canvas Cocos để cập nhật lại region + slots.
        """
        pid = self.current_profile
        if not pid:
            QMessageBox.warning(self, "Fix tọa độ", "Chưa chọn profile.")
            return

        ok, msg = self.capture_manager.fix_coordinates(pid)
        if ok:
            QMessageBox.information(self, "Fix tọa độ", msg)
        else:
            QMessageBox.warning(self, "Fix tọa độ", msg)
            
    def fix_enter_bets_clicked(self) -> None:
        """
        Nút 'Fix tọa độ vào phòng' cho profile hiện tại.

        Quy trình:
        - YÊU CẦU đã có ảnh full trên Preview (chụp từ DevTools).
        - Lấy danh sách 12 mức cược từ config.game_ui.bet_buttons.
        - Bật chế độ _bet_pick_mode: mỗi lần user chọn selection trên Preview
          sẽ ghi nhận tâm vùng đó cho 1 mức cược, lần lượt theo danh sách.
        """
        pid = self.current_profile
        if not pid:
            QMessageBox.warning(self, "Fix tọa độ", "Chưa chọn profile.")
            return

        if self.current_full_pixmap is None:
            QMessageBox.warning(
                self,
                "Fix tọa độ vào phòng",
                "Chưa có ảnh Preview.\nHãy bấm 'Chụp full từ DevTools' trước.",
            )
            return

        try:
            cfg = load_config()
            game_ui = cfg.get("game_ui", {})
            bet_cfg = game_ui.get("bet_buttons", {})
            if not bet_cfg:
                QMessageBox.warning(
                    self,
                    "Fix tọa độ vào phòng",
                    "Chưa có cấu hình 'bet_buttons' trong config.json.",
                )
                return

            # Lấy danh sách 12 mức cược, sort theo số
            bets = sorted(bet_cfg.keys(), key=lambda s: int(s))
            if not bets:
                QMessageBox.warning(
                    self,
                    "Fix tọa độ vào phòng",
                    "Không tìm thấy mức cược nào trong game_ui.bet_buttons.",
                )
                return

            self._bet_pick_bets = bets
            self._bet_pick_index = 0
            self._bet_pick_target = "room"
            self._bet_pick_mode = True

            first_bet = self._bet_pick_bets[0]
            QMessageBox.information(
                self,
                "Fix tọa độ vào phòng",
                (
                    f"Profile {pid}: sẽ chọn lần lượt {len(self._bet_pick_bets)} mức cược.\n\n"
                    f"Bước 1: hãy drag một vùng quanh nút Bet {first_bet} trên ảnh Preview.\n"
                    "Khi thả chuột, tọa độ tâm sẽ được lưu lại."
                ),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Fix tọa độ vào phòng",
                f"Lỗi khi chuẩn bị danh sách mức cược: {e}",
            )
            self._bet_pick_mode = False
            self._bet_pick_bets = []
            self._bet_pick_index = 0
            
    def fix_taixiu_bets_clicked(self) -> None:
        pid = self.current_profile
        if not pid:
            QMessageBox.warning(self, "Fix chip Tài/Xỉu", "Chưa chọn profile.")
            return

        if self.current_full_pixmap is None:
            QMessageBox.warning(
                self,
                "Fix chip Tài/Xỉu",
                "Chưa có ảnh Preview.\nHãy bấm 'Chụp full từ DevTools' trước.",
            )
            return

        try:
            cfg = load_config()
            game_ui = cfg.setdefault("game_ui", {})
            taixiu = game_ui.setdefault("taixiu", {})

            bets = taixiu.get("tx_bet_values") or []
            bets = [str(x).strip() for x in bets if str(x).strip()]
            bets = sorted(bets, key=lambda s: int(s))
            if not bets:
                QMessageBox.warning(
                    self,
                    "Fix chip Tài/Xỉu",
                    "Không tìm thấy mức cược nào trong game_ui.bet_buttons.",
                )
                return

            self._bet_pick_bets = bets
            self._bet_pick_index = 0
            self._bet_pick_target = "taixiu"
            self._bet_pick_mode = True
            self._exit_pick_mode = False
            self._taixiu_pick_mode = False

            QMessageBox.information(
                self,
                "Fix chip Tài/Xỉu",
                f"Profile {pid}: hãy chọn lần lượt {len(bets)} chip cược dùng cho Tài/Xỉu.\nBắt đầu từ Bet {bets[0]}.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Fix chip Tài/Xỉu", f"Lỗi: {e}")

    def fix_tai_clicked(self) -> None:
        self._start_taixiu_pick("tai")

    def fix_xiu_clicked(self) -> None:
        self._start_taixiu_pick("xiu")
        
    def fix_confirm_clicked(self) -> None:
        self._start_taixiu_pick("confirm")
        
    def _start_taixiu_pick(self, kind: str) -> None:
        pid = self.current_profile
        if not pid:
            QMessageBox.warning(self, "Fix nút Tài/Xỉu", "Chưa chọn profile.")
            return

        if self.current_full_pixmap is None:
            QMessageBox.warning(
                self,
                "Fix nút Tài/Xỉu",
                "Chưa có ảnh Preview.\nHãy bấm 'Chụp full từ DevTools' trước.",
            )
            return

        self._bet_pick_mode = False
        self._exit_pick_mode = False
        self._taixiu_pick_kind = kind
        self._taixiu_pick_side = kind
        self._taixiu_pick_mode = True

        if kind == "tai":
            label = "TÀI"
        elif kind == "xiu":
            label = "XỈU"
        else:
            label = "ĐẶT CƯỢC"

        QMessageBox.information(
            self,
            "Fix nút Tài/Xỉu",
            f"Profile {pid}: hãy drag một vùng nhỏ quanh nút {label} trên ảnh Preview.",
        )
        
    def fix_exit_room1_clicked(self) -> None:
        """
        Nút 'Fix tọa độ ra phòng' cho profile hiện tại.

        Quy trình:
        - YÊU CẦU đã có ảnh full trên Preview (chụp từ DevTools).
        - Bật chế độ _exit_pick_mode: lần drag selection tiếp theo trên Preview
          sẽ được dùng làm tọa độ nút EXIT.
        """
        pid = self.current_profile
        if not pid:
            QMessageBox.warning(self, "Fix tọa độ ra phòng", "Chưa chọn profile.")
            return

        if self.current_full_pixmap is None:
            QMessageBox.warning(
                self,
                "Fix tọa độ ra phòng",
                "Chưa có ảnh Preview.\nHãy bấm 'Chụp full từ DevTools' trước.",
            )
            return

        # Không cho chạy đồng thời với chế độ chọn Bet
        self._bet_pick_mode = False
        self._exit_pick_index = 1
        self._exit_pick_mode = True

        QMessageBox.information(
            self,
            "Fix tọa độ ra phòng",
            (
                f"Profile {pid}: hãy drag một vùng nhỏ bao quanh nút THOÁT PHÒNG "
                "trên ảnh Preview.\n"
                "Khi thả chuột, tâm vùng chọn sẽ được lưu làm điểm click EXIT."
            ),
        )
    def fix_exit_room2_clicked(self) -> None:
        """
        Nút 'Fix tọa độ thoát phòng 2' cho profile hiện tại.

        Quy trình:
        - YÊU CẦU đã có ảnh full trên Preview (chụp từ DevTools).
        - Bật chế độ _exit_pick_mode: lần drag selection tiếp theo trên Preview
          sẽ được dùng làm tọa độ nút EXIT.
        """
        pid = self.current_profile
        if not pid:
            QMessageBox.warning(self, "Fix tọa độ thoát phòng 2", "Chưa chọn profile.")
            return

        if self.current_full_pixmap is None:
            QMessageBox.warning(
                self,
                "Fix tọa độ thoát phòng 2",
                "Chưa có ảnh Preview.\nHãy bấm 'Chụp full từ DevTools' trước.",
            )
            return

        # Không cho chạy đồng thời với chế độ chọn Bet
        self._bet_pick_mode = False
        self._exit_pick_index = 2
        self._exit_pick_mode = True

        QMessageBox.information(
            self,
            "Fix tọa độ thoát phòng 2",
            (
                f"Profile {pid}: hãy drag một vùng nhỏ bao quanh nút THOÁT PHÒNG "
                "trên ảnh Preview.\n"
                "Khi thả chuột, tâm vùng chọn sẽ được lưu làm điểm click EXIT."
            ),
        )   

    def fix_exit_room_clicked(self) -> None:
        """Backward-compatible alias: Fix tọa độ thoát phòng 1."""
        self.fix_exit_room1_clicked()     
        
    def sync_config_from_p1(self) -> None:
        """
        Đồng bộ config toạ độ từ P1 sang P2, P3:

        - profiles.[P].window: width, height, scale_percent (scale + kích thước cửa sổ)
        - game_ui.bet_buttons_profile:
            copy toàn bộ 12 mức cược vào phòng của P1
        - game_ui.exit_button_profile:
            copy toạ độ nút EXIT của P1
        - capture.regions:
            copy vùng game của P1
        - capture.slots:
            copy 13 slot lá bài của P1
        - capture.design:
            copy phần design (region + slots design 1280x720) của P1
        """
        # Bắt buộc đang đứng ở P1 để tránh nhầm nguồn
        if self.current_profile != "P1":
            QMessageBox.warning(
                self,
                "Đồng bộ config",
                "Hãy chọn profile P1 trước khi đồng bộ sang P2, P3.",
            )
            return

        # Xác nhận vì thao tác này GHI ĐÈ config P2, P3
        ret = QMessageBox.question(
            self,
            "Đồng bộ config",
            (
                "Copy toàn bộ toạ độ từ P1 sang P2, P3:\n\n"
                "- Cửa sổ (width, height, % scale)\n"
                "- 12 nút Bet (vào phòng)\n"
                "- Nút Thoát phòng\n"
                "- Vùng game\n"
                "- 13 slot lá bài\n"
                "- Design (region + slots 1280x720)\n\n"
                "Thao tác này sẽ ghi đè config hiện tại của P2 và P3.\n\n"
                "Bạn có chắc chắn muốn tiếp tục?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        try:
            cfg = load_config()

            # ----------------- profiles.window: scale + size -----------------
            profiles = cfg.setdefault("profiles", {})
            src_profile_p1 = profiles.get("P1") or {}
            src_window = src_profile_p1.get("window")

            # ----------------- game_ui: bet + exit per-profile -----------------
            game_ui = cfg.setdefault("game_ui", {})
            taixiu = game_ui.setdefault("taixiu", {})

            tx_bet_profile = taixiu.setdefault(
                "tx_bet_points_profile",
                {"P1": {}, "P2": {}, "P3": {}},
            )
            tx_tai_profile = taixiu.setdefault(
                "tai_button_profile",
                {"P1": None, "P2": None, "P3": None},
            )
            tx_xiu_profile = taixiu.setdefault(
                "xiu_button_profile",
                {"P1": None, "P2": None, "P3": None},
            )
            tx_confirm_profile = taixiu.setdefault(
                "confirm_button_profile",
                {"P1": None, "P2": None, "P3": None},
            )

            src_tx_bets = copy.deepcopy(tx_bet_profile.get("P1", {}))
            src_tai = copy.deepcopy(tx_tai_profile.get("P1"))
            src_xiu = copy.deepcopy(tx_xiu_profile.get("P1"))
            src_confirm = copy.deepcopy(tx_confirm_profile.get("P1"))
            
            bet_profile = game_ui.setdefault("bet_buttons_profile", {})
            exit_profile = game_ui.setdefault("exit_button_profile", {})

            src_bets = bet_profile.get("P1")
            src_exit = exit_profile.get("P1")
            exit_profile2 = game_ui.setdefault("exit_button2_profile", {})
            src_exit2 = exit_profile2.get("P1")

            # ----------------- capture: region + slots + design -----------------
            capture_cfg = cfg.setdefault("capture", {})
            regions = capture_cfg.setdefault("regions", {})
            slots = capture_cfg.setdefault("slots", {})
            design_cfg = capture_cfg.setdefault("design", {})

            src_region = regions.get("P1")
            src_slots = slots.get("P1")
            src_design = design_cfg.get("P1")

            if not any([src_window, src_bets, src_exit, src_exit2, src_region, src_slots, src_design]):
                QMessageBox.warning(
                    self,
                    "Đồng bộ config",
                    "Không tìm thấy đủ config của P1 (window / bet / exit / region / slots / design) để đồng bộ.",
                )
                return

            targets = ["P2", "P3"]
            for pid in targets:
                # 1) Cửa sổ: width, height, scale_percent
                dst_profile = profiles.get(pid)
                if dst_profile is not None and isinstance(src_window, dict):
                    dst_profile["window"] = copy.deepcopy(src_window)

                # 2) Bet vào phòng (12 mức)
                if isinstance(src_bets, dict):
                    bet_profile[pid] = copy.deepcopy(src_bets)

                # 3) Nút Thoát phòng
                if isinstance(src_exit, dict):
                    exit_profile[pid] = copy.deepcopy(src_exit)
                    
                if isinstance(src_exit2, dict):
                    exit_profile2[pid] = copy.deepcopy(src_exit2)

                # 4) Vùng game (tọa độ sau khi resize)
                if isinstance(src_region, dict):
                    regions[pid] = copy.deepcopy(src_region)

                # 5) 13 slot lá bài (tọa độ sau khi resize)
                if isinstance(src_slots, dict):
                    slots[pid] = copy.deepcopy(src_slots)

                # 6) Design (region + slots 1280x720)
                if isinstance(src_design, dict):
                    design_cfg[pid] = copy.deepcopy(src_design)
                    
                if isinstance(src_tx_bets, dict):
                    tx_bet_profile[pid] = copy.deepcopy(src_tx_bets)

                if isinstance(src_tai, dict):
                    tx_tai_profile[pid] = copy.deepcopy(src_tai)

                if isinstance(src_xiu, dict):
                    tx_xiu_profile[pid] = copy.deepcopy(src_xiu)
                if isinstance(src_confirm, dict):
                    tx_confirm_profile[pid] = copy.deepcopy(src_confirm)
            save_config(cfg)

            QMessageBox.information(
                self,
                "Đồng bộ config",
                "Đã copy toạ độ từ P1 sang P2 và P3:\n"
                "- Cửa sổ (width, height, % scale)\n"
                "- 12 nút Bet vào phòng\n"
                "- Nút Thoát phòng\n"
                "- Vùng game\n"
                "- 13 slot lá bài\n"
                "- Design (region + slots 1280x720)\n"
                "- Chip Tài/Xỉu\n"
                "- Nút Tài / Xỉu\n"
                "- Nút Đặt cược\n",
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Đồng bộ config",
                f"Lỗi khi đồng bộ config: {e}",
            )

    def _load_existing_region(self) -> None:
        region = get_game_region(self.current_profile)
        if not region:
            self.current_selection = None
            return
        # current_selection sử dụng 4 trường x, y, width, height
        self.current_selection = (
            int(region.get("x", 0)),
            int(region.get("y", 0)),
            int(region.get("width", 0)),
            int(region.get("height", 0)),
        )

    def _load_existing_slots(self) -> None:
        # Không bắt buộc vẽ overlay, chỉ load khi user bấm "Load slot"
        pass

    def _on_selection_changed(self, x: int, y: int, w: int, h: int) -> None:
        # ImagePreview đã emit theo tọa độ ẢNH rồi
        self.current_selection = (int(x), int(y), int(w), int(h))

        log.info(
            "Preview selection (IMAGE coords) for %s: x=%s, y=%s, w=%s, h=%s",
            self.current_profile,
            x, y, w, h,
        )

        # 👉 cập nhật editor khi ở chế độ chỉnh slot bình thường
        if not self._bet_pick_mode and not self._exit_pick_mode and not self._taixiu_pick_mode:
            if w > 0 and h > 0:
                self.slot_x_spin.setValue(int(x))
                self.slot_y_spin.setValue(int(y))
                self.slot_w_spin.setValue(int(w))
                self.slot_h_spin.setValue(int(h))

        if self._bet_pick_mode:
            self._handle_bet_pick_from_selection()
            return

        if self._taixiu_pick_mode:
            self._handle_taixiu_side_pick_from_selection()
            return

        if self._exit_pick_mode:
            self._handle_exit_pick_from_selection()
            return
            
    def _handle_bet_pick_from_selection(self) -> None:
        """
        Được gọi mỗi khi có selection mới trong chế độ _bet_pick_mode.
        - Lấy tâm selection hiện tại.
        - Gán cho mức cược hiện tại trong _bet_pick_bets[_bet_pick_index].
        - Nếu target = room  -> lưu vào game_ui.bet_buttons_profile
        - Nếu target = taixiu -> lưu vào game_ui.taixiu.tx_bet_points_profile
        """
        if not self._bet_pick_mode:
            return
        if not self.current_selection:
            return
        if not self._bet_pick_bets or self._bet_pick_index >= len(self._bet_pick_bets):
            self._bet_pick_mode = False
            return

        pid = self.current_profile
        bet_key = self._bet_pick_bets[self._bet_pick_index]

        x, y, w, h = self.current_selection
        cx = int(x + w / 2)
        cy = int(y + h / 2)

        try:
            cfg = load_config()
            game_ui = cfg.setdefault("game_ui", {})

            if self._bet_pick_target == "taixiu":
                taixiu = game_ui.setdefault("taixiu", {})
                profile_bets = taixiu.setdefault(
                    "tx_bet_points_profile",
                    {"P1": {}, "P2": {}, "P3": {}},
                )
            else:
                profile_bets = game_ui.setdefault(
                    "bet_buttons_profile",
                    {"P1": {}, "P2": {}, "P3": {}},
                )

            per_profile = profile_bets.setdefault(pid, {})
            per_profile[str(bet_key)] = {"x": cx, "y": cy}
            save_config(cfg)

            msg = (
                f"Profile {pid} – đã lưu tọa độ cho Bet {bet_key}:\n"
                f"x={cx}, y={cy}"
            )

            self._bet_pick_index += 1
            if self._bet_pick_index >= len(self._bet_pick_bets):
                self._bet_pick_mode = False
                msg += f"\n\nĐÃ HOÀN THÀNH chọn {len(self._bet_pick_bets)} mức cược cho {pid}."
            else:
                next_bet = self._bet_pick_bets[self._bet_pick_index]
                msg += f"\n\nTiếp theo: hãy drag vùng quanh nút Bet {next_bet} rồi thả chuột."

            box_title = "Fix chip Tài/Xỉu" if self._bet_pick_target == "taixiu" else "Fix tọa độ vào phòng"
            QMessageBox.information(self, box_title, msg)

        except Exception as e:
            box_title = "Fix chip Tài/Xỉu" if self._bet_pick_target == "taixiu" else "Fix tọa độ vào phòng"
            QMessageBox.critical(
                self,
                box_title,
                f"Lỗi khi lưu tọa độ Bet {bet_key} cho {pid}: {e}",
            )
            
    def _handle_taixiu_side_pick_from_selection(self) -> None:
        if not self._taixiu_pick_mode:
            return
        if not self.current_selection:
            return

        pid = self.current_profile
        kind = (self._taixiu_pick_kind or self._taixiu_pick_side or "").strip().lower()

        if kind not in ("tai", "xiu", "confirm"):
            self._taixiu_pick_mode = False
            self._taixiu_pick_side = ""
            self._taixiu_pick_kind = ""
            QMessageBox.warning(self, "Fix nút Tài/Xỉu", "Loại nút không hợp lệ.")
            return

        x, y, w, h = self.current_selection
        cx = int(x + w / 2)
        cy = int(y + h / 2)

        try:
            cfg = load_config()
            game_ui = cfg.setdefault("game_ui", {})
            taixiu = game_ui.setdefault("taixiu", {})

            if kind == "tai":
                key = "tai_button_profile"
                label = "TÀI"
            elif kind == "xiu":
                key = "xiu_button_profile"
                label = "XỈU"
            else:
                key = "confirm_button_profile"
                label = "ĐẶT CƯỢC"

            profile_map = taixiu.setdefault(key, {"P1": None, "P2": None, "P3": None})
            profile_map[pid] = {"x": cx, "y": cy}

            save_config(cfg)

            self._taixiu_pick_mode = False
            self._taixiu_pick_side = ""
            self._taixiu_pick_kind = ""

            QMessageBox.information(
                self,
                "Fix nút Tài/Xỉu",
                f"Đã lưu nút {label} cho {pid}: x={cx}, y={cy}",
            )

        except Exception as e:
            self._taixiu_pick_mode = False
            self._taixiu_pick_side = ""
            self._taixiu_pick_kind = ""
            QMessageBox.critical(
                self,
                "Fix nút Tài/Xỉu",
                f"Lỗi khi lưu nút {kind} cho {pid}: {e}",
            )
            
    def _handle_exit_pick_from_selection(self) -> None:
        """
        Được gọi khi có selection mới ở chế độ _exit_pick_mode.
        - Lấy tâm selection hiện tại.
        - Lưu vào config.game_ui.exit_button_profile[profile_id].
        """
        if not self._exit_pick_mode:
            return
        if not self.current_selection:
            return

        pid = self.current_profile
        x, y, w, h = self.current_selection
        cx = int(x + w / 2)
        cy = int(y + h / 2)

        try:
            cfg = load_config()
            game_ui = cfg.setdefault("game_ui", {})

            # phân biệt EXIT #1 / EXIT #2
            if int(getattr(self, "_exit_pick_index", 1)) == 2:
                exit_profiles = game_ui.setdefault("exit_button2_profile", {})
                box_title = "Fix tọa độ thoát phòng 2"
            else:
                exit_profiles = game_ui.setdefault("exit_button_profile", {})
                box_title = "Fix tọa độ thoát phòng 1"

            exit_profiles[pid] = {"x": cx, "y": cy}
            save_config(cfg)

            self._exit_pick_mode = False

            QMessageBox.information(
                self,
                box_title,
                f"Profile {pid} – đã lưu tọa độ EXIT #{self._exit_pick_index}:\n"
                f"x={cx}, y={cy}",
            )

        except Exception as e:
            self._exit_pick_mode = False
            QMessageBox.critical(
                self,
                f"Fix tọa độ thoát phòng {self._exit_pick_index}",
                f"Lỗi khi lưu tọa độ EXIT cho {pid}: {e}",
            )

    # ------------------------------------------------------------------ Actions

    def capture_full(self) -> None:
        pid = self.current_profile
        img = self.capture_manager.capture_full(pid)
        if img is None:
            QMessageBox.warning(self, "Lỗi", f"Không capture được từ profile {pid}.")
            return

        # PIL -> QPixmap
        from PIL.ImageQt import ImageQt

        qimage = ImageQt(img.convert("RGB"))
        pix = QPixmap.fromImage(qimage)
        self.current_full_pixmap = pix
        self.preview.setImage(pix)

    def apply_region_from_selection(self) -> None:
        if not self.current_selection:
            QMessageBox.warning(self, "Chưa có selection", "Hãy drag vùng game trên Preview trước.")
            return

        x, y, w, h = self.current_selection
        region = {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}
        set_game_region(self.current_profile, region)
        QMessageBox.information(
            self,
            "Đã lưu vùng game",
            f"Profile {self.current_profile}: x={x}, y={y}, w={w}, h={h}",
        )

    def load_slot_config(self) -> None:
        pid = self.current_profile
        idx = str(self.slot_index_spin.value())
        slots_cfg = get_slots(pid)
        slot = slots_cfg.get(idx)
        if not slot:
            QMessageBox.information(self, "Slot trống", f"Chưa có config cho slot {idx} của {pid}.")
            return

        self.slot_x_spin.setValue(int(slot.get("x", 0)))
        self.slot_y_spin.setValue(int(slot.get("y", 0)))
        self.slot_w_spin.setValue(int(slot.get("width", 50)))
        self.slot_h_spin.setValue(int(slot.get("height", 70)))

    def save_slot_config(self) -> None:
        pid = self.current_profile
        idx = int(self.slot_index_spin.value())
        rect = {
            "x": int(self.slot_x_spin.value()),
            "y": int(self.slot_y_spin.value()),
            "width": int(self.slot_w_spin.value()),
            "height": int(self.slot_h_spin.value()),
        }
        set_slot(pid, idx, rect)
        QMessageBox.information(
            self,
            "Đã lưu slot",
            f"Profile {pid}, slot {idx}: {rect}",
        )
