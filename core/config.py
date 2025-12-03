import json
import os
from typing import Any, Dict
from .constants import CONFIG_DIR
from .logger import log

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "profiles": {
        "P1": {
            "name": "Profile 1",
            "chrome_path": "",
            "user_data_dir": "",
            "proxy": {
                "host": "",
                "port": 0,
                "username": "",
                "password": ""
            },
            "window": {
                "width": 1280,
                "height": 720,
                "scale_percent": 100
            }
        },
        "P2": {
            "name": "Profile 2",
            "chrome_path": "",
            "user_data_dir": "",
            "proxy": {
                "host": "",
                "port": 0,
                "username": "",
                "password": ""
            },
            "window": {
                "width": 1280,
                "height": 720,
                "scale_percent": 100
            }
        },
        "P3": {
            "name": "Profile 3",
            "chrome_path": "",
            "user_data_dir": "",
            "proxy": {
                "host": "",
                "port": 0,
                "username": "",
                "password": ""
            },
            "window": {
                "width": 1280,
                "height": 720,
                "scale_percent": 100
            }
        }
    },
    "capture": {
        "regions": {
            "P1": None,
            "P2": None,
            "P3": None
        },
        "slots": {
            "P1": {},
            "P2": {},
            "P3": {}
        }
    }
}

def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        log.error(f"Failed to load config: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(config: Dict[str, Any]) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"Failed to save config: {e}")
