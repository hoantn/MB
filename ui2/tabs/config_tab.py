# ui2/tabs/config_tab.py
from __future__ import annotations

from typing import Any, Dict
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QCheckBox,
    QPushButton,
    QDialog,
    QComboBox,
    QLineEdit,
    QLabel,
    QFrame,
    QScrollArea,
    QColorDialog, 
    QMessageBox,
)

from PySide6.QtGui import QColor

from core.config import (
    load_config,
    save_config,
    apply_game_to_config,
    copy_config_coords_to_game,
)

from core.logger import log
from core.tool_instance import TOOL_MAX, TOOL_MIN, get_bridge_port, get_profile_ports
from ui2.theme import (
    get_available_themes,
    get_current_theme_name,
    get_theme_default_colors,
    get_theme_effective_colors,
)
from ui2.runtime.task_runner import UiTaskResult, UiTaskRunner


class ConfigTab(QWidget):
    def __init__(self, parent=None, *, slot: int = 1, embedded: bool = False) -> None:
        super().__init__(parent)
        self._slot = max(1, int(slot or 1))
        self._embedded = bool(embedded)
        self._tasks = UiTaskRunner(self)
        self._tasks.rejected.connect(self._on_task_rejected)

        self._build_ui()
        self._load_from_config()

    # ------------------------------------------------------------ UI BUILD
    def _show_success(self, text: str) -> None:
        QMessageBox.information(self, "Thành công", text)

    def _show_error(self, text: str) -> None:
        QMessageBox.critical(self, "Lỗi", text)

    def _on_task_rejected(self, res: UiTaskResult) -> None:
        self._show_error(res.error)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Keep controls at their usable height when the main tool is compact.
        # Scrolling is preferable to squeezing spin boxes and checkboxes flat.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer.addWidget(self.scroll)

        content = QWidget()
        self.scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # ---- Group: Tool instance / ports ----
        grp_tool = QGroupBox("Tool / Cong ket noi")
        lay_tool = QFormLayout(grp_tool)

        self.cmb_tool = QComboBox()
        self.cmb_tool.addItems([f"Tool {i}" for i in range(TOOL_MIN, TOOL_MAX + 1)])
        self.lbl_tool_ports = QLabel("")
        self.lbl_tool_ports.setWordWrap(True)
        self.lbl_tool_ports.setStyleSheet("color:#666;")
        self.cmb_tool.currentIndexChanged.connect(self._refresh_tool_ports_label)

        lay_tool.addRow("Tool dang chay:", self.cmb_tool)
        lay_tool.addRow("Bo port:", self.lbl_tool_ports)

        # ---- Group: Game / Tọa độ ----
        grp_game = QGroupBox("Game / Tọa độ")
        lay_game = QHBoxLayout(grp_game)

        self.cmb_game = QComboBox()
        # hardcode theo yêu cầu bạn (sau này có thể scan folder)
        self.cmb_game.addItems(["go88", "rikvip", "b52", "789", "iwin"])

        self.btn_apply_game = QPushButton("Chuyển game")
        self.btn_copy_coords = QPushButton("Copy tọa độ gốc")

        # gợi ý: phân biệt vai trò bằng property để ăn QSS nếu có
        self.btn_apply_game.setProperty("role", "primary")
        self.btn_copy_coords.setProperty("role", "info")

        lay_game.addWidget(QLabel("Chọn game:"))
        lay_game.addWidget(self.cmb_game, 1)
        lay_game.addWidget(self.btn_apply_game)
        lay_game.addWidget(self.btn_copy_coords)

        # ---- Group: Quản lý phòng game ----
        grp_room = QGroupBox("Quản lý phòng game")
        lay_room = QFormLayout(grp_room)

        self.spin_delay_join = QSpinBox()
        self.spin_delay_join.setRange(0, 30000)
        self.spin_delay_join.setSingleStep(100)
        self.spin_delay_join.setSuffix(" ms")

        self.spin_delay_create = QSpinBox()
        self.spin_delay_create.setRange(0, 30000)
        self.spin_delay_create.setSingleStep(100)
        self.spin_delay_create.setSuffix(" ms")

        self.spin_exit_double_click = QSpinBox()
        self.spin_exit_double_click.setRange(0, 3000)
        self.spin_exit_double_click.setSingleStep(10)
        self.spin_exit_double_click.setSuffix(" ms")

        lay_room.addRow("Thời gian vào phòng:", self.spin_delay_join)
        lay_room.addRow("Thời gian tạo phòng:", self.spin_delay_create)
        lay_room.addRow("Thời gian giữa 2 lần click thoát phòng:", self.spin_exit_double_click)

        # ---- Group: Thông báo vào/ra phòng ----
        grp_notify = QGroupBox("Thông báo vào phòng / ra phòng")
        lay_notify = QVBoxLayout(grp_notify)

        self.chk_notify_enter_exit = QCheckBox("Hiển thị thông báo khi người chơi vào/ra phòng")
        lay_notify.addWidget(self.chk_notify_enter_exit)

        # NEW: đưa checkbox mini xuống dưới notify (theo yêu cầu)
        self.chk_room_mini = QCheckBox("Dùng 'Phòng Game' dạng cửa sổ mini tách biệt")
        lay_notify.addWidget(self.chk_room_mini)

        lay_notify.addStretch(1)

        # ---- Group: Quản lý xếp bài ----
        grp_apply = QGroupBox("Quản lý xếp bài (kéo bài)")
        lay_apply = QFormLayout(grp_apply)

        self.spin_delay_between_drag = QSpinBox()
        self.spin_delay_between_drag.setRange(0, 1000)
        self.spin_delay_between_drag.setSingleStep(5)
        self.spin_delay_between_drag.setSuffix(" ms")

        self.spin_drag_duration = QSpinBox()
        self.spin_drag_duration.setRange(0, 2000)
        self.spin_drag_duration.setSingleStep(10)
        self.spin_drag_duration.setSuffix(" ms")

        lay_apply.addRow("Thời gian nghỉ giữa 2 lần kéo:", self.spin_delay_between_drag)
        lay_apply.addRow("Thời gian chờ sau mỗi lần kéo:", self.spin_drag_duration)

        # ---- Group: Giao diện / Màu sắc ----
        grp_theme = QGroupBox("Giao diện / Màu sắc")
        lay_theme = QHBoxLayout(grp_theme)

        self.btn_theme_colors = QPushButton("Config màu giao diện...")
        # dùng role="info" để ăn QSS semantic info button (viền xanh)
        self.btn_theme_colors.setProperty("role", "info")

        lay_theme.addWidget(self.btn_theme_colors)
        lay_theme.addStretch(1)

        # ---- Group: Tool window geometry ----
        grp_tool_window = QGroupBox("Cửa sổ Tool")
        lay_tool_window = QHBoxLayout(grp_tool_window)

        self.btn_save_tool_window_geometry = QPushButton("Đặt kích thước và vị trí hiện tại làm mặc định")
        self.btn_reset_tool_window_geometry = QPushButton("Khôi phục mặc định")
        self.btn_save_tool_window_geometry.setProperty("role", "primary")
        self.btn_reset_tool_window_geometry.setProperty("role", "info")

        lay_tool_window.addWidget(self.btn_save_tool_window_geometry)
        lay_tool_window.addWidget(self.btn_reset_tool_window_geometry)
        lay_tool_window.addStretch(1)

        # ---- Buttons ----
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.btn_save = QPushButton("Lưu cấu hình")
        self.btn_reload = QPushButton("Tải lại")

        btn_row.addWidget(self.btn_reload)
        btn_row.addWidget(self.btn_save)

        # ---- Assemble ----
        root.addWidget(grp_tool)
        root.addWidget(grp_game)

        # ---- Row: Room (left) + Apply (right) ----
        row_room_apply = QHBoxLayout()
        row_room_apply.setSpacing(10)
        row_room_apply.addWidget(grp_room, 1)
        row_room_apply.addWidget(grp_apply, 1)
        root.addLayout(row_room_apply)

        root.addWidget(grp_notify)
        grp_browser = QGroupBox("Trình duyệt")
        lay_browser = QVBoxLayout(grp_browser)
        self.chk_manage_chrome_by_tool = QCheckBox("Mở quản lý Chrome theo Tool")
        lay_browser.addWidget(self.chk_manage_chrome_by_tool)
        lay_browser.addStretch(1)
        root.addWidget(grp_browser)
        root.addWidget(grp_theme)
        root.addWidget(grp_tool_window)

        if self._embedded:
            grp_tool.hide()
            grp_notify.hide()
            grp_theme.hide()
            try:
                lay_room.labelForField(self.spin_exit_double_click).hide()
            except Exception:
                pass
            self.spin_exit_double_click.hide()

        root.addLayout(btn_row)
        root.addStretch(1)

        self.btn_apply_game.clicked.connect(self._on_apply_game_clicked)
        self.btn_copy_coords.clicked.connect(self._on_copy_coords_clicked)

        self.btn_save.clicked.connect(self._on_save_clicked)
        self.btn_reload.clicked.connect(self._load_from_config)
        self.btn_theme_colors.clicked.connect(self._open_theme_color_dialog)
        self.btn_save_tool_window_geometry.clicked.connect(self._on_save_tool_window_geometry_clicked)
        self.btn_reset_tool_window_geometry.clicked.connect(self._on_reset_tool_window_geometry_clicked)

    # ------------------------------------------------------------ LOAD/SAVE

    def _load_from_config(self) -> None:
        """Đọc config.json và đổ vào UI."""
        try:
            cfg: Dict[str, Any] = load_config(self._slot)
        except Exception as e:
            log.error("ConfigTab._load_from_config: %s", e)
            return

        ui = cfg.get("ui") or {}
        tool_index = int(ui.get("tool_index", 1) or 1)
        tool_index = max(TOOL_MIN, min(TOOL_MAX, tool_index))
        self.cmb_tool.setCurrentIndex(tool_index - 1)
        self._refresh_tool_ports_label()

        active_game = (ui.get("active_game") or "").strip().lower()
        if active_game:
            idx = self.cmb_game.findText(active_game)
            if idx >= 0:
                self.cmb_game.setCurrentIndex(idx)
        ui_room = ui.get("room") or {}
        ui_apply = ui.get("apply") or {}
        ui_browser = ui.get("browser") or {}

        delay_join_ms = int(ui_room.get("delay_join_ms", 500) or 0)
        delay_create_ms = int(ui_room.get("delay_create_ms", 800) or 0)
        exit_double_click_ms = int(ui_room.get("exit_double_click_ms", 130) or 0)
        notify_enter_exit = bool(ui_room.get("notify_enter_exit", True))
        mini_as_window = bool(ui_room.get("mini_as_window", False))
        manage_chrome_by_tool = bool(ui_browser.get("manage_chrome_by_tool", False))

        delay_between_drag_ms = int(ui_apply.get("delay_between_drag_ms", 10) or 0)
        drag_duration_ms = int(ui_apply.get("drag_duration_ms", 120) or 0)

        self.spin_delay_join.setValue(delay_join_ms)
        self.spin_delay_create.setValue(delay_create_ms)
        self.spin_exit_double_click.setValue(exit_double_click_ms)
        self.chk_notify_enter_exit.setChecked(notify_enter_exit)
        self.chk_room_mini.setChecked(mini_as_window)
        self.chk_manage_chrome_by_tool.setChecked(manage_chrome_by_tool)
        
        self.spin_delay_between_drag.setValue(delay_between_drag_ms)
        self.spin_drag_duration.setValue(drag_duration_ms)

    def _on_save_clicked(self) -> None:
        """Lưu config từ UI về config.json."""
        try:
            cfg: Dict[str, Any] = load_config(self._slot)
        except Exception as e:
            log.error("ConfigTab._on_save_clicked load: %s", e)
            self._show_error(f"Lưu cấu hình thất bại:\n{e}")
            return

        ui = cfg.setdefault("ui", {})
        ui_room = ui.setdefault("room", {})
        ui_apply = ui.setdefault("apply", {})
        ui_browser = ui.setdefault("browser", {})
        old_tool_index = int(ui.get("tool_index", 1) or 1)
        new_tool_index = int(self.cmb_tool.currentIndex()) + 1
        if not self._embedded:
            ui["tool_index"] = new_tool_index

        ui_room["delay_join_ms"] = int(self.spin_delay_join.value())
        ui_room["delay_create_ms"] = int(self.spin_delay_create.value())
        if not self._embedded:
            ui_room["exit_double_click_ms"] = int(self.spin_exit_double_click.value())
            ui_room["notify_enter_exit"] = bool(self.chk_notify_enter_exit.isChecked())
            ui_room["mini_as_window"] = bool(self.chk_room_mini.isChecked())

        ui_apply["delay_between_drag_ms"] = int(self.spin_delay_between_drag.value())
        ui_apply["drag_duration_ms"] = int(self.spin_drag_duration.value())
        ui_browser["manage_chrome_by_tool"] = bool(self.chk_manage_chrome_by_tool.isChecked())

        try:
            save_config(cfg, self._slot)
        except Exception as e:
            log.error("ConfigTab._on_save_clicked save: %s", e)
            return

        # Không popup ồn ào, chỉ log – nếu muốn bạn có thể thêm toast/messagebox
        log.info("ConfigTab: config saved.")
        self._show_success("Đã lưu cấu hình thành công.")
        if not self._embedded and new_tool_index != old_tool_index:
            QMessageBox.information(
                self,
                "Can khoi dong lai",
                "Da doi Tool. Hay tat/mo lai app va trinh duyet de bridge/socket dung dung port.",
            )

    def _refresh_tool_ports_label(self) -> None:
        tool_index = int(self.cmb_tool.currentIndex()) + 1
        ports = get_profile_ports(tool_index)
        self.lbl_tool_ports.setText(
            f"Bridge: {get_bridge_port(tool_index)} | "
            f"P1: {ports.get('P1')} | P2: {ports.get('P2')} | P3: {ports.get('P3')}"
        )
        
    def _on_apply_game_clicked(self) -> None:
        game = (self.cmb_game.currentText() or "").strip().lower()
        self.btn_apply_game.setEnabled(False)

        def _done(result) -> None:
            ok, msg = result
            if ok:
                log.info("ConfigTab: %s", msg)
                # Load lại để UI khác đọc config mới nếu cần
                self._show_success(msg)
                self._load_from_config()
            else:
                log.error("ConfigTab: %s", msg)
                self._show_error(msg)

        self._tasks.run(
            key=f"{self._slot}:apply_game",
            name=f"Tool {self._slot} áp dụng game",
            fn=lambda: apply_game_to_config(game, self._slot),
            on_success=_done,
            on_error=self._show_error,
            on_finished=lambda _res: self.btn_apply_game.setEnabled(True),
            timeout_ms=10_000,
        )

    def _on_copy_coords_clicked(self) -> None:
        game = (self.cmb_game.currentText() or "").strip().lower()
        self.btn_copy_coords.setEnabled(False)

        def _done(result) -> None:
            ok, msg = result
            if ok:
                log.info("ConfigTab: %s", msg)
                self._show_success(msg)
            else:
                log.error("ConfigTab: %s", msg)
                self._show_error(msg)

        self._tasks.run(
            key=f"{self._slot}:copy_coords",
            name=f"Tool {self._slot} copy tọa độ",
            fn=lambda: copy_config_coords_to_game(game, self._slot),
            on_success=_done,
            on_error=self._show_error,
            on_finished=lambda _res: self.btn_copy_coords.setEnabled(True),
            timeout_ms=10_000,
        )

    def _on_save_tool_window_geometry_clicked(self) -> None:
        """Persist the current MainWindow geometry for the active tool instance."""
        owner = self.window()
        if not hasattr(owner, "save_current_tool_window_geometry"):
            self._show_error("Không tìm thấy chức năng lưu vị trí cửa sổ Tool.")
            return
        try:
            ok, message = owner.save_current_tool_window_geometry()
        except Exception as e:
            log.exception("ConfigTab: save tool window geometry failed")
            self._show_error(f"Không thể lưu vị trí cửa sổ Tool:\n{e}")
            return
        if ok:
            self._show_success(message)
        else:
            self._show_error(message)

    def _on_reset_tool_window_geometry_clicked(self) -> None:
        """Remove the active tool instance override and apply the fallback layout."""
        owner = self.window()
        if not hasattr(owner, "reset_tool_window_geometry"):
            self._show_error("Không tìm thấy chức năng khôi phục cửa sổ Tool.")
            return
        try:
            ok, message = owner.reset_tool_window_geometry()
        except Exception as e:
            log.exception("ConfigTab: reset tool window geometry failed")
            self._show_error(f"Không thể khôi phục cửa sổ Tool:\n{e}")
            return
        if ok:
            self._show_success(message)
        else:
            self._show_error(message)

    # ------------------------------------------------------------ Theme color dialog

    def _open_theme_color_dialog(self) -> None:
        dlg = ThemeColorConfigDialog(self)
        dlg.exec()


class ThemeColorConfigDialog(QDialog):
    """
    Popup cấu hình màu giao diện cho từng theme (Tối / Sáng).
    """

    COLOR_KEYS = [
        ("bg", "Nền chính"),
        ("panel", "Panel / Khung"),
        ("sidebar", "Sidebar / Header / Danh sách"),
        ("input_bg", "Nền ô nhập"),
        ("border", "Viền"),
        ("divider", "Đường kẻ (divider)"),
        ("text", "Chữ chính"),
        ("text2", "Chữ phụ"),
        ("muted", "Chữ mờ / gợi ý"),
        ("btn_bg", "Nền nút"),
        ("btn_hover", "Nền nút (hover)"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Config màu giao diện")
        self.setModal(True)
        self.resize(520, 520)

        self._current_theme: str = get_current_theme_name()
        self._rows: Dict[str, Dict[str, Any]] = {}

        self._build_ui()
        self._load_for_theme(self._current_theme)

    def _build_ui(self) -> None:
        from PySide6.QtWidgets import QVBoxLayout, QFormLayout, QHBoxLayout

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Theme selector
        top_row = QHBoxLayout()
        lbl_theme = QLabel("Theme:")
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(get_available_themes())
        idx = self.cmb_theme.findText(self._current_theme)
        if idx >= 0:
            self.cmb_theme.setCurrentIndex(idx)
        self.cmb_theme.currentTextChanged.connect(self._on_theme_changed)

        top_row.addWidget(lbl_theme)
        top_row.addWidget(self.cmb_theme)
        top_row.addStretch(1)

        root.addLayout(top_row)

        # Color table
        grp_colors = QGroupBox("Bảng màu")
        lay_colors = QFormLayout(grp_colors)
        lay_colors.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        for key, label in self.COLOR_KEYS:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            preview = QFrame()
            preview.setFixedSize(32, 18)
            preview.setFrameShape(QFrame.StyledPanel)
            preview.setFrameShadow(QFrame.Sunken)

            edit = QLineEdit()
            edit.setMaxLength(7)
            edit.setPlaceholderText("#RRGGBB")

            btn_pick = QPushButton("...")
            btn_pick.setFixedWidth(30)

            row_layout.addWidget(preview)
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(btn_pick)

            lay_colors.addRow(label + ":", row_widget)

            self._rows[key] = {
                "preview": preview,
                "edit": edit,
                "button": btn_pick,
            }

            btn_pick.clicked.connect(lambda _=False, k=key: self._on_pick_color(k))

        root.addWidget(grp_colors)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.btn_reset_theme = QPushButton("Reset theme này")
        self.btn_cancel = QPushButton("Đóng")
        self.btn_save_apply = QPushButton("Lưu & Áp dụng")

        btn_row.addWidget(self.btn_reset_theme)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_save_apply)

        root.addLayout(btn_row)

        self.btn_reset_theme.clicked.connect(self._on_reset_clicked)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save_apply.clicked.connect(self._on_save_and_apply)

    # ---------------------- helpers ----------------------

    def _set_row_color(self, key: str, hex_color: str) -> None:
        row = self._rows.get(key)
        if not row:
            return
        if not hex_color:
            return

        if not hex_color.startswith("#"):
            hex_color = "#" + hex_color
        if len(hex_color) != 7:
            # bỏ qua màu không hợp lệ, tránh crash
            return

        edit: QLineEdit = row["edit"]
        preview: QFrame = row["preview"]

        edit.setText(hex_color)
        preview.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #444;")

    def _collect_colors_from_ui(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for key, _ in self.COLOR_KEYS:
            row = self._rows.get(key)
            if not row:
                continue
            edit: QLineEdit = row["edit"]
            text = edit.text().strip()
            if not text:
                continue
            if not text.startswith("#"):
                text = "#" + text
            if len(text) != 7:
                # bỏ qua nếu không đúng #RRGGBB
                continue
            result[key] = text
        return result

    # ---------------------- load/save ----------------------

    def _load_for_theme(self, theme_name: str) -> None:
        self._current_theme = theme_name
        try:
            # Lấy hiệu lực hiện tại: config nếu có, fallback default
            colors = get_theme_effective_colors(theme_name)
        except Exception:
            colors = get_theme_default_colors(theme_name)

        for key, _label in self.COLOR_KEYS:
            hex_color = colors.get(key)
            if hex_color:
                self._set_row_color(key, hex_color)

    def _save_current_theme(self) -> None:
        try:
            cfg: Dict[str, Any] = load_config()
        except Exception as e:
            log.error("ThemeColorConfigDialog._save_current_theme load: %s", e)
            return

        ui = cfg.setdefault("ui", {})
        theme_colors = ui.setdefault("theme_colors", {})

        # merge với default để tránh thiếu key
        default_colors = get_theme_default_colors(self._current_theme)
        user_colors = self._collect_colors_from_ui()
        merged = default_colors.copy()
        merged.update(user_colors)

        theme_colors[self._current_theme] = merged

        try:
            save_config(cfg)
        except Exception as e:
            log.error("ThemeColorConfigDialog._save_current_theme save: %s", e)

    # ---------------------- slots ----------------------

    def _on_theme_changed(self, name: str) -> None:
        # đổi theme đang cấu hình, load lại bảng màu
        self._load_for_theme(name)

    def _on_pick_color(self, key: str) -> None:
        from PySide6.QtWidgets import QColorDialog

        row = self._rows.get(key)
        if not row:
            return

        edit: QLineEdit = row["edit"]
        current = edit.text().strip() or "#000000"
        if not current.startswith("#") or len(current) != 7:
            current = "#000000"

        initial = QColor(current)
        color = QColorDialog.getColor(initial, self, "Chọn màu")
        if not color.isValid():
            return

        hex_color = color.name()  # dạng #RRGGBB
        self._set_row_color(key, hex_color)

    def _on_reset_clicked(self) -> None:
        # Reset theme hiện tại về mặc định
        default_colors = get_theme_default_colors(self._current_theme)
        for key, _label in self.COLOR_KEYS:
            hex_color = default_colors.get(key)
            if hex_color:
                self._set_row_color(key, hex_color)

    def _on_save_and_apply(self) -> None:
        from PySide6.QtWidgets import QApplication
        from ui2.theme import apply_theme_by_name

        self._save_current_theme()

        # Áp dụng lại theme đang sử dụng (không tự đổi theme của user)
        app = QApplication.instance()
        if app is not None:
            try:
                current_theme = get_current_theme_name()
                apply_theme_by_name(app, current_theme)
            except Exception as e:
                log.error("ThemeColorConfigDialog._on_save_and_apply apply theme: %s", e)

        self.accept()
