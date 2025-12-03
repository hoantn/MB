from dataclasses import dataclass
from .devtools import DevToolsClient

@dataclass
class BrowserTab:
    profile_id: str
    devtools: DevToolsClient

    def capture(self, region=None):
        return self.devtools.capture_screenshot(region=region)
