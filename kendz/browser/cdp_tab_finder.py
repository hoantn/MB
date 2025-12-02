import json
from typing import Any, Dict, List, Optional
from urllib.request import urlopen


def fetch_targets(
    host: str = "127.0.0.1",
    port: int = 9222,
) -> List[Dict[str, Any]]:
    """Lấy danh sách targets DevTools (tabs, extension, iframe...)."""
    url = f"http://{host}:{port}/json"
    with urlopen(url, timeout=3.0) as resp:
        data = resp.read().decode("utf-8")
    targets = json.loads(data)
    if not isinstance(targets, list):
        return []
    return targets


def find_first_page_target(
    host: str = "127.0.0.1",
    port: int = 9222,
) -> Optional[Dict[str, Any]]:
    """Tìm target đầu tiên có type == 'page'.

    Đây chính là tab đầu tiên mà Chrome đang mở (không phải extension / devtools).
    Phù hợp với chiến lược:
    - User tự mở tab game bằng tay
    - Tool luôn bắt tab page đầu tiên
    """
    targets = fetch_targets(host=host, port=port)
    for t in targets:
        if t.get("type") == "page":
            return t
    return None


def get_websocket_debugger_url(
    host: str = "127.0.0.1",
    port: int = 9222,
) -> Optional[str]:
    """Lấy websocketDebuggerUrl của tab 'page' đầu tiên.

    Ví dụ:
    ws://127.0.0.1:9222/devtools/page/XXXX
    """
    target = find_first_page_target(host=host, port=port)
    if not target:
        return None
    return target.get("webSocketDebuggerUrl")
