from ui2.bridge.ws_http_bridge import WS_EVENT_QUEUE
from core.logger import log


def simulate_ws_cards(profile_id: str, ws_codes: list[int]) -> None:
    """
    Giả lập WS gửi 13 lá bài cho tool.
    ws_codes: list 13 int (0..51)
    """
    if not isinstance(ws_codes, list) or len(ws_codes) != 13:
        raise ValueError("ws_codes must be list of 13 integers")

    evt = {
        "profile_id": profile_id,
        "kind": "cards_snapshot",
        "payload": {
            "cmd": 600,
            "cs": list(ws_codes),
            "_sim": True,   # chỉ để log, không ảnh hưởng logic
        },
    }

    WS_EVENT_QUEUE.put_nowait(evt)
    log.info("[SIM-WS] inject cards for %s: %s", profile_id, ws_codes)
