from dataclasses import dataclass
from .devtools import DevToolsClient

@dataclass
class BrowserTab:
    profile_id: str
    devtools: DevToolsClient

    def capture(self, region=None):
        return self.devtools.capture_screenshot(region=region)
        
    def get_cocos_canvas_info(self) -> dict:
        """
        Trả về thông tin canvas Cocos (left, top, width, height).
        """
        return self.devtools.get_cocos_canvas_info()
