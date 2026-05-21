from typing import Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGroupBox,
    QPushButton,
    QLabel,
    QCheckBox,
    QMessageBox,
    QTextEdit,
    QComboBox,
    QGraphicsOpacityEffect,
    QRadioButton,
    QButtonGroup,
)

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap

from core.logger import log
from engine.card import Card

from .dashboard_constants import (
    FULL_DECK,
    INDEX_TO_CHI,
    classify_chis,
    hand_type_color,
    _load_opp_pixmap,
)


def build_ui_impl(self) -> None:
    root = QHBoxLayout(self)


    # Refs cho nút để DashboardTab có thể đổi trạng thái (active/busy/done)
    # Khởi tạo trước khi dùng để tránh AttributeError khi build UI.
    if not hasattr(self, "apply_buttons") or self.apply_buttons is None:
        self.apply_buttons = {}
    if not hasattr(self, "scan_buttons") or self.scan_buttons is None:
        self.scan_buttons = {}
    if not hasattr(self, "reset_buttons") or self.reset_buttons is None:
        self.reset_buttons = {}
    if not hasattr(self, "btn_scan_opp"):
        self.btn_scan_opp = None


    left = QVBoxLayout()
    right = QVBoxLayout()
    root.addLayout(left, 1)
    root.addLayout(right, 2)

    # Browser group
    browser_group = QGroupBox("Browser_Profile")
    browser_layout = QVBoxLayout(browser_group)
    for pid in self.profiles:
        row = QHBoxLayout()

        name_label = QLabel(pid)
        row.addWidget(name_label)

        state_label = QLabel("🟡 Chưa scan")
        state_label.setStyleSheet("color:#aaaaaa; font-size:11px;")
        row.addWidget(state_label)
        self.profile_state_labels[pid] = state_label

        open_btn = QPushButton("Mở")
        open_btn.clicked.connect(lambda _, p=pid: self.open_browser(p))
        row.addWidget(open_btn)

        reset_btn = QPushButton("↻")
        self.reset_buttons[pid] = reset_btn
        reset_btn.setToolTip("Reset kết nối DevTools với trình duyệt profile này")
        reset_btn.clicked.connect(lambda _, p=pid: self.reset_browser(p))
        row.addWidget(reset_btn)

        close_btn = QPushButton("Đóng")
        close_btn.clicked.connect(lambda _, p=pid: self.close_browser(p))
        row.addWidget(close_btn)

        browser_layout.addLayout(row)

    left.addWidget(browser_group)


    # OPP controls (luôn hiện)
    opp_ctrl_group = QGroupBox("Đối thủ (OPP)")
    opp_ctrl_layout = QVBoxLayout(opp_ctrl_group)

    btn_scan_opp = QPushButton("Quét bài Đối Thủ (OPP)")
    self.btn_scan_opp = btn_scan_opp
    btn_scan_opp.setToolTip("Dùng bài của P1/P2/P3 để suy ra bài đối thủ")
    btn_scan_opp.setStyleSheet(
        "background-color:#c62828;"
        "color:white;"
        "font-weight:bold;"
    )
    btn_scan_opp.clicked.connect(self.on_scan_opponent_clicked)
    opp_ctrl_layout.addWidget(btn_scan_opp)

    # --- Mode riêng cho OPP: Tiền / Max ---
    opp_mode_row = QHBoxLayout()
    opp_mode_row.addStretch()
    
    opp_mode_label = QLabel("Kiểu xếp OPP:")
    opp_mode_row.addWidget(opp_mode_label)

    self.opp_mode_money = QRadioButton("Tiền")
    self.opp_mode_max = QRadioButton("Max")
    self.opp_mode_money.setChecked(True)

    self.opp_mode_group = QButtonGroup(self)
    self.opp_mode_group.addButton(self.opp_mode_money, 0)
    self.opp_mode_group.addButton(self.opp_mode_max, 1)

    self.opp_mode_money.toggled.connect(self.on_opp_mode_radio_changed)
    self.opp_mode_max.toggled.connect(self.on_opp_mode_radio_changed)

    opp_mode_row.addWidget(self.opp_mode_money)
    opp_mode_row.addWidget(self.opp_mode_max)
    
    opp_mode_row.addStretch()
    opp_ctrl_layout.addLayout(opp_mode_row)

    left.addWidget(opp_ctrl_group)


    # Toggle hiển thị phần quét thủ công (ít dùng khi WS auto)
    btn_toggle_manual_scan = QPushButton("Hiện quét thủ công")
    btn_toggle_manual_scan.setToolTip("Ẩn/hiện cụm nút Quét Bài P1/P2/P3/ALL để giao diện gọn hơn")
    btn_toggle_manual_scan.setVisible(False)  # Ẩn vĩnh viễn nút toggle quét thủ công
    left.addWidget(btn_toggle_manual_scan)

    # Scan (WebSocket) group
    scan_group = QGroupBox("Quét bài")
    scan_layout = QVBoxLayout(scan_group)

    # Mặc định ẩn vì đa số dùng WS auto (gọn UI)
    scan_group.setVisible(False)

    def _toggle_manual_scan() -> None:
        try:
            is_vis = scan_group.isVisible()
            scan_group.setVisible(not is_vis)
            btn_toggle_manual_scan.setText("Ẩn quét thủ công" if not is_vis else "Hiện quét thủ công")
        except Exception:
            pass

    btn_toggle_manual_scan.clicked.connect(_toggle_manual_scan)

    row_scan = QHBoxLayout()
    btn_scan_p1 = QPushButton("Quét Bài P1")
    self.scan_buttons["P1"] = btn_scan_p1
    btn_scan_p1.clicked.connect(lambda: self.load_ws_cards(["P1"]))
    row_scan.addWidget(btn_scan_p1)

    btn_scan_p2 = QPushButton("Quét Bài P2")
    self.scan_buttons["P2"] = btn_scan_p2
    btn_scan_p2.clicked.connect(lambda: self.load_ws_cards(["P2"]))
    row_scan.addWidget(btn_scan_p2)

    btn_scan_p3 = QPushButton("Quét Bài P3")
    self.scan_buttons["P3"] = btn_scan_p3
    btn_scan_p3.clicked.connect(lambda: self.load_ws_cards(["P3"]))
    row_scan.addWidget(btn_scan_p3)

    scan_layout.addLayout(row_scan)

    btn_scan_all = QPushButton("Quét Bài ALL")
    self.scan_buttons["ALL"] = btn_scan_all
    btn_scan_all.clicked.connect(lambda: self.load_ws_cards(self.profiles))
    scan_layout.addWidget(btn_scan_all)


    left.addWidget(scan_group)

    # Engine group – chọn kiểu xếp bài + gợi ý/áp dụng
    engine_group = QGroupBox("Engine – Gợi ý & áp dụng")
    engine_layout = QVBoxLayout(engine_group)

    # 1) Hàng chọn Engine Mode (radio Tiền / Max) – áp dụng cho P1/P2/P3
    mode_row = QHBoxLayout()
    mode_row.addStretch()
    
    mode_label = QLabel("Kiểu xếp bài:")
    mode_row.addWidget(mode_label)
    self.engine_mode_money = QRadioButton("Tiền")
    self.engine_mode_max = QRadioButton("Max")
    self.engine_mode_money.setChecked(True)

    self.engine_mode_group = QButtonGroup(self)
    self.engine_mode_group.addButton(self.engine_mode_money, 0)
    self.engine_mode_group.addButton(self.engine_mode_max, 1)

    self.engine_mode_money.toggled.connect(self.on_engine_mode_radio_changed)
    self.engine_mode_max.toggled.connect(self.on_engine_mode_radio_changed)

    mode_row.addWidget(self.engine_mode_money)
    mode_row.addWidget(self.engine_mode_max)
    mode_row.addStretch()
    engine_layout.addLayout(mode_row)

    # 2) Nhóm ĐỐI THỦ – có viền riêng
    opp_group = QGroupBox("Đối thủ")
    opp_layout = QHBoxLayout(opp_group)

    self.engine_opp_label = QLabel("Thiếu bài (0/13)")
    self.engine_opp_label.setTextFormat(Qt.RichText)
    opp_layout.addWidget(self.engine_opp_label)

    engine_layout.addWidget(opp_group)

    # 3) Bảng gợi ý cho từng profile P1/P2/P3
    # engine_summary_labels giữ như cũ (DashboardTab đã có)

    
    # Cấu hình tốc độ kéo thả khi Áp dụng (ms). Chỉ ảnh hưởng Action/Apply.
    # if not hasattr(self, "ui_apply_delay_ms"):
        # self.ui_apply_delay_ms = QSpinBox()
        # self.ui_apply_delay_ms.setRange(0, 500)
        # self.ui_apply_delay_ms.setValue(10)  # mặc định 10ms
        # self.ui_apply_delay_ms.setSuffix(" ms")
        # self.ui_apply_delay_ms.setToolTip("Delay giữa mỗi lần kéo (ms). Tăng nếu game lag/animation.")
    # speed_row = QHBoxLayout()
    # speed_row.addWidget(QLabel("Delay kéo:"))
    # speed_row.addWidget(self.ui_apply_delay_ms)
    # speed_row.addStretch()
    # engine_layout.addLayout(speed_row)

    for pid in self.profiles:
        row = QHBoxLayout()

        lbl_pid = QLabel(pid)
        lbl_pid.setStyleSheet("font-weight: bold;")
        row.addWidget(lbl_pid)

        summary_label = QLabel("Thiếu bài (0/13)")
        summary_label.setTextFormat(Qt.RichText)
        summary_label.setMinimumWidth(260)
        row.addWidget(summary_label, 1)

        self.engine_summary_labels[pid] = summary_label

        btn_apply = QPushButton(f"Áp dụng lên {pid}")
        self.apply_buttons[pid] = btn_apply
        btn_apply.clicked.connect(lambda _, p=pid: self.apply_suggestion_for(p))
        row.addWidget(btn_apply)

        engine_layout.addLayout(row)

    left.addWidget(engine_group)

    left.addStretch()

    # Bên phải: OPP + P1/P2/P3
    top_right = QHBoxLayout()
    bottom_right = QHBoxLayout()
    right.addLayout(top_right, 2)
    right.addLayout(bottom_right, 2)

    # OPP group
    opp_group = QGroupBox("Đối thủ (OPP)")
    opp_group.setStyleSheet(
        "QGroupBox{border:2px solid #ff5555; margin-top: 6px;} "
        "QGroupBox::title{left:10px;}"
    )
    opp_layout = QVBoxLayout(opp_group)

    self.player_boxes["OPP"] = opp_group

    self.player_card_labels["OPP"] = {
        "chi3": [],
        "chi2": [],
        "chi1": [],
    }
    self.player_chi_labels["OPP"] = {
        "chi3": QLabel("Chi 3: Chưa có bài"),
        "chi2": QLabel("Chi 2: Chưa có bài"),
        "chi1": QLabel("Chi 1: Chưa có bài"),
    }

    opp_panel = QWidget()
    v_opp = QVBoxLayout(opp_panel)
    v_opp.addStretch()

    # Chi 3
    row3 = QHBoxLayout()
    for _ in range(3):
        lbl = QLabel()
        lbl.setFixedSize(34, 48)
        lbl.setStyleSheet("background-color:#111111;border:1px solid #444;")
        lbl.setAlignment(Qt.AlignCenter)
        row3.addWidget(lbl)
        self.player_card_labels["OPP"]["chi3"].append(lbl)
    row3.addStretch()
    v_opp.addLayout(row3)
    v_opp.addWidget(self.player_chi_labels["OPP"]["chi3"])

    # Chi 2
    row2 = QHBoxLayout()
    for _ in range(5):
        lbl = QLabel()
        lbl.setFixedSize(34, 48)
        lbl.setStyleSheet("background-color:#111111;border:1px solid #444;")
        lbl.setAlignment(Qt.AlignCenter)
        row2.addWidget(lbl)
        self.player_card_labels["OPP"]["chi2"].append(lbl)
    row2.addStretch()
    v_opp.addLayout(row2)
    v_opp.addWidget(self.player_chi_labels["OPP"]["chi2"])

    # Chi 1
    row1 = QHBoxLayout()
    for _ in range(5):
        lbl = QLabel()
        lbl.setFixedSize(34, 48)
        lbl.setStyleSheet("background-color:#111111;border:1px solid #444;")
        lbl.setAlignment(Qt.AlignCenter)
        row1.addWidget(lbl)
        self.player_card_labels["OPP"]["chi1"].append(lbl)
    row1.addStretch()
    v_opp.addLayout(row1)
    v_opp.addWidget(self.player_chi_labels["OPP"]["chi1"])

    opp_layout.addWidget(opp_panel)

    top_right.addWidget(opp_group, 1)

    # P1/P2/P3 group
    def create_player_group(rowname: str, color: str) -> QGroupBox:
        group = QGroupBox(rowname)
        group.setStyleSheet(
            f"QGroupBox{{border:2px solid {color}; margin-top: 6px;}} "
            f"QGroupBox::title{{left:10px;}}"
        )
        layout = QVBoxLayout(group)

        self.player_boxes[rowname] = group

        self.player_card_labels[rowname] = {
            "chi3": [],
            "chi2": [],
            "chi1": [],
        }
        self.player_chi_labels[rowname] = {
            "chi3": QLabel("Chi 3: Chưa có bài"),
            "chi2": QLabel("Chi 2: Chưa có bài"),
            "chi1": QLabel("Chi 1: Chưa có bài"),
        }

        panel = QWidget()
        v = QVBoxLayout(panel)
        v.addStretch()

        # Chi 3
        row3 = QHBoxLayout()
        for _ in range(3):
            lbl = QLabel()
            lbl.setFixedSize(34, 48)
            lbl.setStyleSheet("background-color:#111111;border:1px solid #444;")
            lbl.setAlignment(Qt.AlignCenter)
            row3.addWidget(lbl)
            self.player_card_labels[rowname]["chi3"].append(lbl)
        row3.addStretch()
        v.addLayout(row3)
        v.addWidget(self.player_chi_labels[rowname]["chi3"])

        # Chi 2
        row2 = QHBoxLayout()
        for _ in range(5):
            lbl = QLabel()
            lbl.setFixedSize(34, 48)
            lbl.setStyleSheet("background-color:#111111;border:1px solid #444;")
            lbl.setAlignment(Qt.AlignCenter)
            row2.addWidget(lbl)
            self.player_card_labels[rowname]["chi2"].append(lbl)
        row2.addStretch()
        v.addLayout(row2)
        v.addWidget(self.player_chi_labels[rowname]["chi2"])

        # Chi 1
        row1 = QHBoxLayout()
        for _ in range(5):
            lbl = QLabel()
            lbl.setFixedSize(34, 48)
            lbl.setStyleSheet("background-color:#111111;border:1px solid #444;")
            lbl.setAlignment(Qt.AlignCenter)
            row1.addWidget(lbl)
            self.player_card_labels[rowname]["chi1"].append(lbl)
        row1.addStretch()
        v.addLayout(row1)
        v.addWidget(self.player_chi_labels[rowname]["chi1"])

        layout.addWidget(panel)
        return group

    p1_group = create_player_group("P1", "#00bfff")
    p2_group = create_player_group("P2", "#aaaaaa")
    p3_group = create_player_group("P3", "#aaaaaa")

    top_right.addWidget(p1_group, 1)
    bottom_right.addWidget(p2_group, 1)
    bottom_right.addWidget(p3_group, 1)

    self.setLayout(root)


def set_profile_state_impl(self, pid: str, state: str) -> None:
    """
    Cập nhật trạng thái profile + màu label + highlight box.

    state: "idle" | "scanned" | "preview" | "applied"
    """
    self.profile_state[pid] = state
    label = self.profile_state_labels.get(pid)
    box = self.player_boxes.get(pid)

    if label is None:
        return

    if state == "idle":
        text = "🟡 Chưa scan"
        color = "#aaaaaa"
        active = False
    elif state == "scanned":
        text = "🔵 Đã scan"
        color = "#00bfff"
        active = False
    elif state == "preview":
        text = "🟢 Đang xem gợi ý"
        color = "#00ff88"
        active = True
    elif state == "applied":
        text = "✅ Đã áp dụng"
        color = "#00ff88"
        active = True
    else:
        text = state
        color = "#ffffff"
        active = False

    label.setText(text)
    label.setStyleSheet(f"color:{color}; font-size:11px;")

    if box is not None:
        if active:
            box.setStyleSheet(
                box.styleSheet()
                + "QGroupBox{background-color:rgba(0,255,136,20);}"
            )
            self._pulse_profile_box(pid)
        else:
            box.setStyleSheet(
                box.styleSheet().split("QGroupBox{background-color", 1)[0]
            )


def pulse_profile_box_impl(self, pid: str) -> None:
    box = self.player_boxes.get(pid)
    if box is None:
        return

    # Hủy animation cũ nếu có
    old_anim = self._box_animations.get(pid)
    if old_anim is not None:
        old_anim.stop()

    effect = box.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(box)
        box.setGraphicsEffect(effect)

    anim = QPropertyAnimation(effect, b"opacity", self)
    anim.setDuration(200)
    anim.setStartValue(0.4)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    self._box_animations[pid] = anim
    anim.start()


def update_opponent_impl(self) -> None:
    known = set()
    for pid in self.profiles:
        for c in self.card_codes_flat[pid]:
            if c and c not in ("??", "--"):
                known.add(c)

    remaining = [c for c in FULL_DECK if c not in known]
    opp_codes: List[Optional[str]] = ["??"] * 13
    for i in range(min(13, len(remaining))):
        opp_codes[i] = remaining[i]

    self.card_codes_flat["OPP"] = opp_codes
    self.preview_chis["OPP"] = None
    self.card_conf_flat["OPP"] = [1.0 if c and c != "??" else 0.0 for c in opp_codes]



def normalize_cards_for_view(cards):
    """Chuẩn hoá thứ tự lá trong 1 chi để dễ nhìn (thấp -> cao).

    Lưu ý: chỉ dùng cho HIỂN THỊ; không thay đổi mapping slot gốc của WS.
    """
    if not cards:
        return []

    try:
        ranks = [c.rank for c in cards]
        if len(cards) == 5 and set(ranks) == {"A", "2", "3", "4", "5"}:
            wheel_order = {"A": 0, "2": 1, "3": 2, "4": 3, "5": 4}
            return sorted(cards, key=lambda c: (wheel_order.get(c.rank, 99), getattr(c, "suit", "")))
        return sorted(cards, key=lambda c: (getattr(c, "rank_index", 0), getattr(c, "suit", "")))
    except Exception:
        return list(cards)


def refresh_player_thumbnails_impl(self, rowname: str) -> None:
    """Vẽ thumbnail lá bài theo preview (nếu có) hoặc bài scan gốc."""
    from PIL.ImageQt import ImageQt  # type: ignore

    img_lists = self.card_images_pil.get(rowname)
    if img_lists is None:
        img_lists = [None] * 13

    # Xóa ảnh cũ
    for chi_name, labels in self.player_card_labels[rowname].items():
        for lbl in labels:
            lbl.clear()

    preview = self.preview_chis.get(rowname)

    if preview is not None:
        codes = self.card_codes_flat.get(rowname, [])
        code_to_img: Dict[str, "Image.Image"] = {}  # type: ignore[name-defined]
        for c, img in zip(codes, img_lists):
            if not c or c in ("--", "??") or img is None:
                continue
            if c not in code_to_img:
                code_to_img[c] = img

        chi1_cards, chi2_cards, chi3_cards = preview
        # Chuẩn hoá thứ tự hiển thị trong từng chi (thấp -> cao)
        chi1_cards = normalize_cards_for_view(chi1_cards)
        chi2_cards = normalize_cards_for_view(chi2_cards)
        chi3_cards = normalize_cards_for_view(chi3_cards)
        mapping = {
            "chi3": chi3_cards,
            "chi2": chi2_cards,
            "chi1": chi1_cards,
        }

        for chi_name, cards in mapping.items():
            labels = self.player_card_labels[rowname][chi_name]
            for i, card in enumerate(cards):
                if i >= len(labels):
                    break
                img = code_to_img.get(card.to_code())
                lbl = labels[i]

                if img is not None:
                    try:
                        qimage = ImageQt(img.convert("RGB"))
                        pix = QPixmap.fromImage(qimage).scaled(
                            lbl.width(),
                            lbl.height(),
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                        lbl.setPixmap(pix)
                        continue
                    except Exception as e:
                        log.error(
                            "Lỗi render thumbnail preview %s %s-%s: %s",
                            rowname,
                            chi_name,
                            i,
                            e,
                        )

                code = card.to_code()
                pix = _load_opp_pixmap(code, lbl.width(), lbl.height())
                if pix is not None:
                    lbl.setPixmap(pix)
        return

    # --- Nhánh không preview: vẽ theo thứ tự INDEX_TO_CHI ---
    for idx, (chi_name, pos) in enumerate(INDEX_TO_CHI):
        if idx >= len(img_lists):
            break
        img = img_lists[idx]

        labels = self.player_card_labels[rowname][chi_name]
        # GUARD tránh out-of-range nếu INDEX_TO_CHI và số label không khớp hoàn toàn
        if pos >= len(labels):
            continue

        lbl = labels[pos]

        if img is not None:
            try:
                qimage = ImageQt(img.convert("RGB"))
                pix = QPixmap.fromImage(qimage).scaled(
                    lbl.width(),
                    lbl.height(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                lbl.setPixmap(pix)
                continue
            except Exception as e:
                log.error("Lỗi render thumbnail %s idx %s: %s", rowname, idx, e)

        # Fallback cho WS: không có ảnh capture nhưng có mã bài → dùng ảnh vision/opp
        codes_row = self.card_codes_flat.get(rowname, [])
        if idx < len(codes_row):
            code = codes_row[idx]
            if code and code not in ("--", "??"):
                pix = _load_opp_pixmap(code, lbl.width(), lbl.height())
                if pix is not None:
                    lbl.setPixmap(pix)


def refresh_all_views_impl(self) -> None:
    """
    Refresh label Chi1/Chi2/Chi3 và thumbnail cho OPP + P1/P2/P3.

    Quy ước:
    - Nếu row chưa có preview -> hiển thị "Chưa có bài" và clear thumbnail.
    - Nếu có preview nhưng thiếu đủ 13 lá -> hiển thị "Chưa đủ 13 lá (preview)".
    - Nếu đủ -> classify_chis + tô màu + icon.
    """
    for row in self.rows:
        labels = self.player_chi_labels[row]
        preview = self.preview_chis.get(row)

        # 1) Chưa có preview => reset UI an toàn
        if preview is None:
            try:
                labels["chi3"].setText("Chi 3: Chưa có bài")
                labels["chi2"].setText("Chi 2: Chưa có bài")
                labels["chi1"].setText("Chi 1: Chưa có bài")
            except Exception:
                pass

            # Clear / refresh thumbnail theo trạng thái hiện tại
            try:
                self._refresh_player_thumbnails(row)
            except Exception:
                pass
            continue

        # 2) Có preview => unpack
        try:
            chi1_cards, chi2_cards, chi3_cards = preview
        except Exception:
            # Preview hỏng cấu trúc => reset an toàn
            try:
                labels["chi3"].setText("Chi 3: Chưa có bài")
                labels["chi2"].setText("Chi 2: Chưa có bài")
                labels["chi1"].setText("Chi 1: Chưa có bài")
            except Exception:
                pass
            try:
                self._refresh_player_thumbnails(row)
            except Exception:
                pass
            continue

        # 3) Chuẩn hoá thứ tự hiển thị trong từng chi (thấp -> cao)
        chi1_cards = normalize_cards_for_view(chi1_cards)
        chi2_cards = normalize_cards_for_view(chi2_cards)
        chi3_cards = normalize_cards_for_view(chi3_cards)

        # 4) Check đủ 13 lá
        cards_all = chi3_cards + chi2_cards + chi1_cards
        if len(cards_all) != 13:
            msg = "<span style='color:#888888;'>Chưa đủ 13 lá (preview)</span>"
            try:
                labels["chi3"].setText(f"Chi 3: {msg}")
                labels["chi2"].setText(f"Chi 2: {msg}")
                labels["chi1"].setText(f"Chi 1: {msg}")
            except Exception:
                pass
            try:
                self._refresh_player_thumbnails(row)
            except Exception:
                pass
            continue

        # 5) Classify + render label màu
        type1, type2, type3 = classify_chis(chi1_cards, chi2_cards, chi3_cards)

        strong = {"Thùng phá sảnh", "Tứ quý", "Cù"}
        medium = {"Thùng", "Sảnh", "Xám"}

        def fmt_label(prefix: str, hand_type: str) -> str:
            color = hand_type_color(hand_type)
            icon = ""
            if hand_type in strong:
                icon = "🔥"
            elif hand_type in medium:
                icon = "★"
            icon_text = f" {icon}" if icon else ""
            return (
                f"{prefix}: "
                f"<span style='color:{color};'><b>{hand_type}{icon_text}</b></span>"
            )

        try:
            labels["chi3"].setText(fmt_label("Chi 3", type3))
            labels["chi2"].setText(fmt_label("Chi 2", type2))
            labels["chi1"].setText(fmt_label("Chi 1", type1))
        except Exception:
            pass

        # 6) Vẽ thumbnail theo preview hiện tại
        try:
            self._refresh_player_thumbnails(row)
        except Exception:
            pass
