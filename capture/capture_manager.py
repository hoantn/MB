from typing import Optional
from PIL import Image
from browser.manager import BrowserManager
from .region import get_game_region
from core.logger import log

class CaptureManager:
    def __init__(self, browser_manager: BrowserManager):
        self.browser_manager = browser_manager

    def capture_region(self, profile_id: str) -> Optional[Image.Image]:
        tab = self.browser_manager.get_active_tab(profile_id)
        if not tab:
            log.warning("No active tab for profile %s", profile_id)
            return None
        region = get_game_region(profile_id)
        img = tab.capture(region=region)
        return img

    def capture_full(self, profile_id: str) -> Optional[Image.Image]:
        tab = self.browser_manager.get_active_tab(profile_id)
        if not tab:
            log.warning("No active tab for profile %s", profile_id)
            return None
        img = tab.capture(region=None)
        return img
