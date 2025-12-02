from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any


DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_ZOOM_PERCENT = 100
DEFAULT_PROXY_TYPE = "none"  # none | http | socks5
DEFAULT_START_URL = "https://www.google.com/"


@dataclass
class ProfileConfig:
    key: str
    name: str
    chrome_profile_path: str = ""
    proxy_type: str = DEFAULT_PROXY_TYPE
    proxy_host: str = ""
    proxy_port: str = ""
    proxy_username: str = ""
    proxy_password: str = ""
    start_url: str = DEFAULT_START_URL
    window_width: int = DEFAULT_WIDTH
    window_height: int = DEFAULT_HEIGHT
    zoom_percent: int = DEFAULT_ZOOM_PERCENT

    @classmethod
    def from_dict(cls, key: str, data: Dict[str, Any]) -> "ProfileConfig":
        if data is None:
            data = {}

        proxy_type = data.get("proxy_type", DEFAULT_PROXY_TYPE) or DEFAULT_PROXY_TYPE
        proxy_type = str(proxy_type).lower()
        if proxy_type not in {"none", "http", "socks5"}:
            proxy_type = DEFAULT_PROXY_TYPE

        start_url = data.get("start_url", DEFAULT_START_URL) or DEFAULT_START_URL

        return cls(
            key=key,
            name=data.get("name", key),
            chrome_profile_path=data.get("chrome_profile_path", "") or "",
            proxy_type=proxy_type,
            proxy_host=data.get("proxy_host", "") or "",
            proxy_port=str(data.get("proxy_port", "") or ""),
            proxy_username=data.get("proxy_username", "") or "",
            proxy_password=data.get("proxy_password", "") or "",
            start_url=start_url,
            window_width=int(data.get("window_width", DEFAULT_WIDTH) or DEFAULT_WIDTH),
            window_height=int(data.get("window_height", DEFAULT_HEIGHT) or DEFAULT_HEIGHT),
            zoom_percent=int(data.get("zoom_percent", DEFAULT_ZOOM_PERCENT) or DEFAULT_ZOOM_PERCENT),
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("key", None)
        return data


class ProfilesStore:
    """Quản lý load/save cấu hình profiles từ JSON.

    File JSON có dạng:

        {
          "P1": { ... },
          "P2": { ... },
          "P3": { ... }
        }
    """

    def __init__(self, json_path: Path) -> None:
        self._json_path = Path(json_path)

    @property
    def json_path(self) -> Path:
        return self._json_path

    def load(self) -> Dict[str, ProfileConfig]:
        import json

        if not self._json_path.exists():
            profiles: Dict[str, ProfileConfig] = {}
            for key in ("P1", "P2", "P3"):
                profiles[key] = ProfileConfig(
                    key=key,
                    name=f"Profile {key[-1]}",
                )
            self.save(profiles)
            return profiles

        with self._json_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        profiles: Dict[str, ProfileConfig] = {}
        if isinstance(raw, dict):
            for key, data in raw.items():
                profiles[key] = ProfileConfig.from_dict(key, data or {})
        else:
            for key in ("P1", "P2", "P3"):
                profiles[key] = ProfileConfig(
                    key=key,
                    name=f"Profile {key[-1]}",
                )
        return profiles

    def save(self, profiles: Dict[str, ProfileConfig]) -> None:
        import json

        raw: Dict[str, Any] = {}
        for key, cfg in profiles.items():
            raw[key] = cfg.to_dict()

        self._json_path.parent.mkdir(parents=True, exist_ok=True)
        with self._json_path.open("w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
