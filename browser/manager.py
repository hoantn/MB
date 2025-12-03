import os
import subprocess
from typing import Dict, Optional

from core.config import load_config, save_config
from core.logger import log
from .profile import ProfileConfig
from .devtools import DevToolsClient
from .tab import BrowserTab


PROFILE_PORTS = {
    "P1": 9222,
    "P2": 9223,
    "P3": 9224,
}


def get_default_chrome_path() -> str:
    """Tìm chrome.exe mặc định trên Windows, nếu không thấy thì trả 'chrome'."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return "chrome"


def get_default_user_data_dir(profile_id: str) -> str:
    base = os.getenv("LOCALAPPDATA") or os.getcwd()
    root = os.path.join(base, "MauBinhTool")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, f"Profile_{profile_id}")


class BrowserManager:
    """
    QUAN TRỌNG: mọi thao tác với config đều dựa trên file mới nhất trên ổ đĩa
    để không ghi đè mất phần capture.regions / capture.slots đã lưu.
    """

    def __init__(self):
        self.config = load_config()
        self.tabs: Dict[str, BrowserTab] = {}
        self.processes: Dict[str, subprocess.Popen] = {}

    # luôn load lại config mới nhất trước khi xử lý
    def _load_config_fresh(self) -> dict:
        self.config = load_config()
        return self.config

    def reload_config(self):
        self._load_config_fresh()

    def get_profile_config(self, profile_id: str) -> ProfileConfig:
        """
        Đọc config mới nhất, bổ sung chrome_path + user_data_dir nếu trống,
        sau đó lưu lại nhưng KHÔNG đụng tới các key khác (capture, v.v.).
        """
        cfg = self._load_config_fresh()
        profiles = cfg.get("profiles", {})
        d = profiles.get(profile_id, {})

        if not d.get("chrome_path"):
            d["chrome_path"] = get_default_chrome_path()
        if not d.get("user_data_dir"):
            d["user_data_dir"] = get_default_user_data_dir(profile_id)

        profiles[profile_id] = d
        cfg["profiles"] = profiles
        save_config(cfg)
        self.config = cfg

        return ProfileConfig.from_dict(d)

    def update_profile_config(self, profile_id: str, profile_dict: Dict):
        """
        Cập nhật cấu hình 1 profile nhưng merge trên bản config mới nhất
        để không mất phần capture.regions / slots.
        """
        cfg = self._load_config_fresh()
        profiles = cfg.get("profiles", {})
        profiles[profile_id] = profile_dict
        cfg["profiles"] = profiles
        save_config(cfg)
        self.config = cfg
        log.info("Updated profile config for %s", profile_id)

    def _get_port(self, profile_id: str) -> int:
        return PROFILE_PORTS.get(profile_id, 9222)

    def open_browser(self, profile_id: str) -> None:
        cfg = self.get_profile_config(profile_id)
        port = self._get_port(profile_id)

        chrome_path = cfg.chrome_path or get_default_chrome_path()
        user_data_dir = cfg.user_data_dir or get_default_user_data_dir(profile_id)

        os.makedirs(user_data_dir, exist_ok=True)

        # width/height/scale từ cấu hình window
        width = cfg.window.width
        height = cfg.window.height
        scale = max(10, cfg.window.scale_percent) / 100.0  # tránh 0
        win_w = int(width * scale)
        win_h = int(height * scale)

        if profile_id in self.processes and self.processes[profile_id].poll() is None:
            log.info("Browser for %s already running", profile_id)
        else:
            args = [
                chrome_path,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data_dir}",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                f"--window-size={win_w},{win_h}",
                # cho phép WebSocket từ 127.0.0.1, tránh 403 Forbidden
                "--remote-allow-origins=*",
            ]
            try:
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.processes[profile_id] = proc
                log.info(
                    "Launched Chrome for %s on port %s, window=%sx%s, scale=%.2f",
                    profile_id, port, win_w, win_h, scale
                )
            except Exception as e:
                log.error("Không thể mở Chrome cho %s: %s", profile_id, e)
                raise

        dt = DevToolsClient(profile_id, port)
        dt.connect()
        tab = BrowserTab(profile_id=profile_id, devtools=dt)
        self.tabs[profile_id] = tab

    def close_browser(self, profile_id: str) -> None:
        tab = self.tabs.get(profile_id)
        if tab:
            tab.devtools.disconnect()
            del self.tabs[profile_id]
            log.info("DevTools for %s closed", profile_id)

        proc = self.processes.get(profile_id)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                log.info("Chrome process for %s terminated", profile_id)
            except Exception as e:
                log.warning("Không thể terminate Chrome cho %s: %s", profile_id, e)
        if profile_id in self.processes:
            del self.processes[profile_id]

    def get_active_tab(self, profile_id: str) -> Optional[BrowserTab]:
        return self.tabs.get(profile_id)
