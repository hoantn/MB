from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class ProxyConfig:
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""

@dataclass
class WindowConfig:
    width: int = 1280
    height: int = 720
    scale_percent: int = 100

@dataclass
class ProfileConfig:
    name: str
    chrome_path: str
    user_data_dir: str
    proxy: ProxyConfig
    window: WindowConfig

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProfileConfig":
        proxy = d.get("proxy", {})
        win = d.get("window", {})
        return cls(
            name=d.get("name", ""),
            chrome_path=d.get("chrome_path", ""),
            user_data_dir=d.get("user_data_dir", ""),
            proxy=ProxyConfig(
                host=proxy.get("host", ""),
                port=proxy.get("port", 0),
                username=proxy.get("username", ""),
                password=proxy.get("password", ""),
            ),
            window=WindowConfig(
                width=win.get("width", 1280),
                height=win.get("height", 720),
                scale_percent=win.get("scale_percent", 100),
            ),
        )
