from typing import List, Dict
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

from core.config import load_config, save_config

# =========================
# Theme names
# =========================
THEME_DARK = "Tối"
THEME_LIGHT = "Sáng"

# =========================
# Semantic colors (KHÔNG đổi giữa themes)
# =========================
SEM_PRIMARY = "#2EA043"   # Action chính / focus
SEM_SUCCESS = "#238636"   # OK / Connected
SEM_WARNING = "#D29922"   # Pending
SEM_DANGER  = "#F85149"   # Error / Stop
SEM_INFO    = "#58A6FF"   # Info / PX / Reconnect


# =========================
# Public API
# =========================
def get_available_themes() -> List[str]:
    return [THEME_DARK, THEME_LIGHT]


def get_current_theme_name() -> str:
    cfg = load_config()
    ui_cfg = cfg.get("ui", {})
    name = ui_cfg.get("theme", THEME_DARK)
    return name if name in get_available_themes() else THEME_DARK


def set_current_theme_name(name: str) -> None:
    if name not in get_available_themes():
        name = THEME_DARK
    cfg = load_config()
    cfg.setdefault("ui", {})["theme"] = name
    save_config(cfg)


def apply_app_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    apply_theme_by_name(app, get_current_theme_name())


def get_theme_default_colors(name: str) -> Dict[str, str]:
    """
    Trả về bảng màu mặc định (không bị ảnh hưởng bởi config.json).
    Dùng cho nút 'Reset theme này về mặc định'.
    """
    return _default_theme_colors(name).copy()


def get_theme_effective_colors(name: str) -> Dict[str, str]:
    """
    Trả về bảng màu đang được sử dụng (config.json nếu có, fallback mặc định + brightness).
    """
    return _load_theme_colors(name).copy()


# =========================
# Internal helpers
# =========================
def _c(hex_: str) -> QColor:
    return QColor(hex_)


def _default_theme_colors(name: str) -> Dict[str, str]:
    dark = (name == THEME_DARK)
    if dark:
        # Dark: giống palette mặc định trước đây
        return {
            "bg": "#1E1E1E",
            "panel": "#252526",
            "sidebar": "#2D2D30",
            "input_bg": "#1C1C1C",
            "border": "#3C3C3C",
            "divider": "#333333",
            "text": "#E6E6E6",
            "text2": "#B0B0B0",
            "muted": "#8A8A8A",
            "btn_bg": "#2D2D30",
            "btn_hover": "#333333",
        }
    # Light
    return {
        "bg": "#E5E7EB",
        "panel": "#E5E7EB",
        "sidebar": "#F9FAFB",
        "input_bg": "#f6f7f8",
        "border": "#D1D5DB",
        "divider": "#E5E7EB",
        "text": "#111827",
        "text2": "#374151",
        "muted": "#6B7280",
        "btn_bg": "#CCCCCC",
        "btn_hover": "#D1D5DB",
    }


def _get_brightness_for_theme(name: str) -> float:
    """
    Lấy hệ số sáng/tối cho theme (0.5–1.5). 1.0 = giữ nguyên.
    """
    try:
        cfg = load_config()
        ui_cfg = cfg.get("ui", {})
        tb = ui_cfg.get("theme_brightness", {})
        value = tb.get(name, 1.0)
        value = float(value)
    except Exception:
        value = 1.0

    # Giới hạn cho an toàn, tránh quá tối hoặc quá sáng
    if value < 0.5:
        value = 0.5
    if value > 1.5:
        value = 1.5
    return value


def _apply_brightness_hex(hex_color: str, factor: float) -> str:
    """
    Scale độ sáng (lightness) trên không gian HSL cho 1 màu hex.
    """
    c = QColor(hex_color)
    if not c.isValid():
        return hex_color

    h = c.hslHueF()
    s = c.hslSaturationF()
    l = c.lightnessF()
    a = c.alphaF()

    new_l = max(0.0, min(1.0, l * factor))
    c.setHslF(h, s, new_l, a)
    return c.name()  # #RRGGBB


def _load_theme_colors(name: str) -> Dict[str, str]:
    """
    Đọc bảng màu từ config.json (ui.theme_colors[name]),
    merge với mặc định và áp dụng brightness.
    """
    default = _default_theme_colors(name)

    try:
        cfg = load_config()
        ui_cfg = cfg.get("ui", {})
        all_colors = ui_cfg.get("theme_colors", {})
        colors = all_colors.get(name)
    except Exception:
        colors = None

    merged: Dict[str, str] = default.copy()
    if isinstance(colors, dict):
        for key, value in colors.items():
            if isinstance(value, str) and value:
                merged[key] = value

    factor = _get_brightness_for_theme(name)
    if abs(factor - 1.0) > 0.01:
        for key, value in list(merged.items()):
            if isinstance(value, str) and value.startswith("#") and len(value) in (4, 7):
                merged[key] = _apply_brightness_hex(value, factor)

    return merged


def apply_theme_by_name(app: QApplication, name: str) -> None:
    pal = QPalette()
    if name == THEME_LIGHT:
        _apply_light_palette(pal)
    else:
        _apply_dark_palette(pal)

    app.setPalette(pal)
    app.setStyleSheet(_build_qss(name))


# =========================
# Dark palette
# =========================
def _apply_dark_palette(p: QPalette) -> None:
    colors = _load_theme_colors(THEME_DARK)

    bg        = _c(colors["bg"])
    panel     = _c(colors["panel"])
    sidebar   = _c(colors["sidebar"])
    input_bg  = _c(colors["input_bg"])
    border    = _c(colors["border"])

    text      = _c(colors["text"])
    text2     = _c(colors["text2"])
    muted     = _c(colors["muted"])

    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, text)

    p.setColor(QPalette.Base, input_bg)
    p.setColor(QPalette.AlternateBase, sidebar)

    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.PlaceholderText, muted)

    p.setColor(QPalette.Button, sidebar)
    p.setColor(QPalette.ButtonText, text)

    p.setColor(QPalette.Highlight, _c(SEM_PRIMARY))
    p.setColor(QPalette.HighlightedText, _c("#0B0F0D"))

    p.setColor(QPalette.Link, _c(SEM_INFO))
    p.setColor(QPalette.BrightText, _c(SEM_DANGER))

    p.setColor(QPalette.Disabled, QPalette.Text, _c("#666666"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, _c("#666666"))

    p.setColor(QPalette.Dark, border)
    p.setColor(QPalette.Mid, _c("#333333"))
    p.setColor(QPalette.Light, _c("#4A4A4A"))


# =========================
# Light palette (anti-glare)
# =========================
def _apply_light_palette(p: QPalette) -> None:
    colors = _load_theme_colors(THEME_LIGHT)

    bg        = _c(colors["bg"])
    panel     = _c(colors["panel"])
    sidebar   = _c(colors["sidebar"])
    input_bg  = _c(colors["input_bg"])
    border    = _c(colors["border"])

    text      = _c(colors["text"])
    text2     = _c(colors["text2"])
    muted     = _c(colors["muted"])

    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, text)

    p.setColor(QPalette.Base, input_bg)
    p.setColor(QPalette.AlternateBase, sidebar)

    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.PlaceholderText, muted)

    p.setColor(QPalette.Button, _c("#E5E7EB"))
    p.setColor(QPalette.ButtonText, text)

    p.setColor(QPalette.Highlight, _c(SEM_PRIMARY))
    p.setColor(QPalette.HighlightedText, _c("#f6f7f8"))

    p.setColor(QPalette.Link, _c(SEM_INFO))
    p.setColor(QPalette.BrightText, _c(SEM_DANGER))

    p.setColor(QPalette.Disabled, QPalette.Text, _c("#9CA3AF"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, _c("#9CA3AF"))

    p.setColor(QPalette.Dark, border)
    p.setColor(QPalette.Mid, _c("#E5E7EB"))
    p.setColor(QPalette.Light, _c("#f6f7f8"))


# =========================
# QSS – nơi IDE “ăn tiền”
# =========================
def _build_qss(theme: str) -> str:
    dark = (theme == THEME_DARK)
    colors = _load_theme_colors(theme)

    bg        = colors["bg"]
    panel     = colors["panel"]
    sidebar   = colors["sidebar"]
    border    = colors["border"]
    divider   = colors["divider"]

    text      = colors["text"]
    text2     = colors["text2"]
    muted     = colors["muted"]

    input_bg  = colors["input_bg"]
    btn_bg    = colors["btn_bg"]
    btn_hover = colors["btn_hover"]

    return f"""
    QWidget {{
        background-color: {bg};
        color: {text};
        selection-background-color: {SEM_PRIMARY};
        selection-color: {"#0B0F0D" if dark else "#f6f7f8"};
    }}

    QGroupBox {{
        background-color: {panel};
        border: 1px solid {border};
        border-radius: 6px;
        margin-top: 10px;
        padding: 6px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 6px;
        color: {text2};
    }}

    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
        background-color: {input_bg};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 6px;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
    QSpinBox:focus, QComboBox:focus {{
        border: 1px solid {SEM_PRIMARY};
    }}

    QPushButton {{
        background-color: {btn_bg};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 6px 10px;
    }}
    QPushButton:hover {{
        background-color: {btn_hover};
        border: 1px solid {SEM_PRIMARY};
    }}
    QPushButton:disabled {{
        color: {muted};
        border: 1px solid {divider};
    }}

    QListWidget, QTreeView, QTableView {{
        background-color: {panel};
        border: 1px solid {border};
        border-radius: 6px;
    }}

    QHeaderView::section {{
        background-color: {sidebar};
        border: 1px solid {border};
        padding: 6px;
        color: {text2};
    }}

    /* Semantic roles */
    QPushButton[role="primary"] {{
        background-color: {SEM_PRIMARY};
        border: 1px solid {SEM_PRIMARY};
        color: {"#0B0F0D" if dark else "#f6f7f8"};
    }}
    QPushButton[role="success"] {{
        background-color: {SEM_SUCCESS};
        border: 1px solid {SEM_SUCCESS};
        color: {"#0B0F0D" if dark else "#f6f7f8"};
    }}
    QPushButton[role="danger"] {{
        background-color: {SEM_DANGER};
        border: 1px solid {SEM_DANGER};
        color: #f6f7f8;
    }}
    QPushButton[role="info"] {{
        border: 1px solid {SEM_INFO};
        color: {SEM_INFO};
        background-color: transparent;
    }}
    """
