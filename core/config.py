import copy
import json
import os
from typing import Any, Dict, Optional, Tuple

from .constants import CONFIG_DIR
from .logger import log

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# NEW: folder chứa tọa độ theo game
GAMES_DIR = os.path.join(CONFIG_DIR, "games")

# NEW: chỉ cho phép copy/merge các block tọa độ này
COORD_KEYS = ("game_ui", "capture")

DEFAULT_CONFIG: Dict[str, Any] = {
    "profiles": {
        "P1": {
            "name": "Profile 1",
            "chrome_path": "",
            "target_url": "",
            "user_data_dir": "",
            "proxy": {"host": "", "port": 0, "username": "", "password": ""},
            "window": {"width": 1280, "height": 720, "scale_percent": 100},
        },
        "P2": {
            "name": "Profile 2",
            "chrome_path": "",
            "target_url": "",
            "user_data_dir": "",
            "proxy": {"host": "", "port": 0, "username": "", "password": ""},
            "window": {"width": 1280, "height": 720, "scale_percent": 100},
        },
        "P3": {
            "name": "Profile 3",
            "chrome_path": "",
            "target_url": "",
            "user_data_dir": "",
            "proxy": {"host": "", "port": 0, "username": "", "password": ""},
            "window": {"width": 1280, "height": 720, "scale_percent": 100},
        },
    },
    "ui": {
        "tool_index": 1,
        "browser_window_positions": {},
        "tool_window_geometries": {},
        "theme": "Tối",
        "theme_colors": {
            "Tối": {
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
            },
            "Sáng": {
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
            },
        },
        "room": {
            "delay_create_ms": 800,
            "delay_join_ms": 500,
            "notify_enter_exit": True,
        },
        "taixiu": {
            "delay_ms": 800
        },
        "apply": {
            "delay_between_drag_ms": 10,
            "drag_duration_ms": 120,
            "double_pass": True,
            "double_pass_gap_ms": 4000,
            "layout606_timeout_retry_count": 1,
            "layout606_timeout_retry_ms": 6500,
            "verify_drag": True,
            "verify_min_confidence": 0.70
        },
        "active_game": "hit",
    },
    "game_ui": {
        "bet_buttons": {},
        "bet_buttons_profile": {"P1": {}, "P2": {}, "P3": {}},
        "exit_button_profile": {"P1": None, "P2": None, "P3": None},
        "exit_button2_profile": {"P1": None, "P2": None, "P3": None},
        "binh_button_profile": {"P1": None, "P2": None, "P3": None},
        "done_button_profile": {"P1": None, "P2": None, "P3": None},
        "taixiu": {
            "tx_bet_values": [
                "1000",
                "10000",
                "50000",
                "100000",
                "500000",
                "1000000",
                "10000000"
            ],
            "tx_bet_points_profile": {"P1": {}, "P2": {}, "P3": {}},
            "tai_button_profile": {"P1": None, "P2": None, "P3": None},
            "xiu_button_profile": {"P1": None, "P2": None, "P3": None},
            "confirm_button_profile": {"P1": None, "P2": None, "P3": None},
        },
    },
    "capture": {
        "regions": {"P1": None, "P2": None, "P3": None},
        "slots": {"P1": {}, "P2": {}, "P3": {}},
    },
    "auto_settings": {
        "telegram": {
            "bot_token": "",
            "chat_id": "",
        },
        "alerts": {
            "gold_min_threshold": {
                "enabled": False,
                "threshold": 0,
            },
            "gold_max_threshold": {
                "enabled": False,
                "threshold": 0,
            },
            "opp_sap_lang_intentional_foul": {
                "enabled": False,
            },
            "missing_3p": {
                "enabled": False,
            },
        },
    },
}


def _config_path(slot: int) -> str:
    """Slot 1 dùng config.json (backward compat), slot 2-4 dùng config-tool{N}.json"""
    if slot == 1:
        return CONFIG_FILE
    return os.path.join(CONFIG_DIR, f"config-tool{slot}.json")


def load_config(slot: int = 1) -> Dict[str, Any]:
    path = _config_path(slot)
    if not os.path.exists(path):
        default = copy.deepcopy(DEFAULT_CONFIG)
        if slot > 1:
            # Ghi tool_index vào config mới tạo cho slot 2-4
            default.setdefault("ui", {})["tool_index"] = slot
        save_config(default, slot)
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        log.error(f"Failed to load config slot={slot}: {e}")
        return copy.deepcopy(DEFAULT_CONFIG)


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    """
    Ghi JSON an toàn: write tmp -> replace.
    Tránh trường hợp crash làm hỏng config.json.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def save_config(config: Dict[str, Any], slot: int = 1) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        _atomic_write_json(_config_path(slot), config)
    except Exception as e:
        log.error(f"Failed to save config slot={slot}: {e}")


def ensure_slot_configs() -> None:
    """Tạo config-tool2,3,4.json nếu chưa tồn tại với tool_index=slot tương ứng."""
    for slot in range(2, 5):
        path = _config_path(slot)
        if not os.path.exists(path):
            default = copy.deepcopy(DEFAULT_CONFIG)
            default.setdefault("ui", {})["tool_index"] = slot
            save_config(default, slot)
            log.info("Đã tạo config cho slot %d: %s", slot, path)


# ------------------------- GAME COORDS HELPERS (NEW) -------------------------

def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge: dict gặp dict thì merge đệ quy, còn lại ghi đè.
    """
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _game_file_path(game_name: str) -> str:
    safe = (game_name or "").strip().lower()
    return os.path.join(GAMES_DIR, f"{safe}.json")


def load_game_coords(game_name: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Load file /config/games/<game>.json
    Trả về (coords_dict, error_message)
    """
    path = _game_file_path(game_name)
    if not os.path.exists(path):
        return None, f"Không thấy file tọa độ game: {path}"

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None, f"File tọa độ không hợp lệ (không phải object): {path}"
        return data, None
    except Exception as e:
        return None, f"Lỗi đọc file tọa độ {path}: {e}"


def save_game_coords(game_name: str, coords: Dict[str, Any]) -> Optional[str]:
    """
    Ghi file /config/games/<game>.json
    Trả về error_message nếu lỗi, None nếu OK.
    """
    try:
        os.makedirs(GAMES_DIR, exist_ok=True)
        path = _game_file_path(game_name)
        _atomic_write_json(path, coords)
        return None
    except Exception as e:
        return f"Lỗi ghi file tọa độ game {game_name}: {e}"


def _extract_coord_blocks(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Lấy đúng 2 block tọa độ từ config.json: game_ui + capture (nếu có)
    """
    out: Dict[str, Any] = {}
    for k in COORD_KEYS:
        if k in cfg and isinstance(cfg.get(k), dict):
            out[k] = cfg.get(k)
    return out


def apply_game_to_config(game_name: str) -> Tuple[bool, str]:
    """
    Nút 1: "Chuyển game"
    /config/games/<game>.json -> merge tọa độ -> config.json
    """
    main_cfg = load_config()
    game_coords, err = load_game_coords(game_name)
    if err:
        log.error("apply_game_to_config: %s", err)
        return False, err

    # Chỉ merge các block tọa độ whitelist
    changed = False
    for k in COORD_KEYS:
        v = game_coords.get(k)
        if isinstance(v, dict):
            if not isinstance(main_cfg.get(k), dict):
                main_cfg[k] = {}
            _deep_merge(main_cfg[k], v)
            changed = True

    if not changed:
        msg = f"File tọa độ game '{game_name}' không có key nào trong {list(COORD_KEYS)}"
        log.error("apply_game_to_config: %s", msg)
        return False, msg

    ui = main_cfg.setdefault("ui", {})
    ui["active_game"] = (game_name or "").strip().lower()

    save_config(main_cfg)
    return True, f"Đã chuyển tọa độ sang game '{game_name}'."


def copy_config_coords_to_game(game_name: str) -> Tuple[bool, str]:
    """
    Nút 2: "Copy tọa độ gốc"
    config.json -> ghi ra /config/games/<game>.json (chỉ tọa độ)
    """
    main_cfg = load_config()
    coords = _extract_coord_blocks(main_cfg)

    if not coords:
        msg = f"config.json không có block tọa độ nào trong {list(COORD_KEYS)}"
        log.error("copy_config_coords_to_game: %s", msg)
        return False, msg

    err = save_game_coords(game_name, coords)
    if err:
        log.error("copy_config_coords_to_game: %s", err)
        return False, err

    return True, f"Đã copy tọa độ gốc sang file game '{game_name}'."
