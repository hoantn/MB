# engine/phom/ws_parser.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from .constants import CMD_DEAL, CMD_DISCARD, CMD_HAND_SNAPSHOT, CMD_ACTION_853, CMD_ACTION_854

@dataclass(frozen=True)
class PhomEvent:
    cmd: int
    payload: Dict[str, Any]

def parse_phom_payload(payload: Any) -> Optional[PhomEvent]:
    """Nhận payload đã được background.js bóc ra thành dict.
    Trả về PhomEvent (cmd, payload) hoặc None nếu không phải phỏm.
    """
    if payload is None:
        return None
    # đôi khi payload còn là list [opcode, {...}]
    if isinstance(payload, list) and len(payload) >= 2 and isinstance(payload[1], dict):
        payload = payload[1]

    if not isinstance(payload, dict):
        return None

    cmd = payload.get("cmd")
    if cmd not in (CMD_DEAL, CMD_DISCARD, CMD_HAND_SNAPSHOT, CMD_ACTION_853, CMD_ACTION_854):
        return None

    return PhomEvent(cmd=int(cmd), payload=payload)
