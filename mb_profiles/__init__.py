"""Gói mb_profiles

- ProfileConfig: dataclass cấu hình 1 hồ sơ (P1/P2/P3)
- ProfilesStore: load/save file config/profiles.json
- BrowserManager: quản lý mở/đóng Chrome profile + proxy

Lưu ý:
- UI hồ sơ & trình duyệt hiện tại được định nghĩa trong:
    kendz/tools/mau_binh_control_panel.py (class ProfilesTab - Tkinter)
- Gói này KHÔNG còn cung cấp UI nữa, chỉ cung cấp model + service.
"""

from .profiles_model import ProfileConfig, ProfilesStore
from .browser_manager import BrowserManager

__all__ = [
    "ProfileConfig",
    "ProfilesStore",
    "BrowserManager",
]
