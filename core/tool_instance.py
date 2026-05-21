from __future__ import annotations

import os
from typing import Dict

from core.constants import BASE_DIR
from core.config import load_config


TOOL_MIN = 1
TOOL_MAX = 10
PROFILE_IDS = ("P1", "P2", "P3")


def _clamp_tool_index(value: object) -> int:
    try:
        idx = int(value)
    except Exception:
        idx = TOOL_MIN
    return max(TOOL_MIN, min(TOOL_MAX, idx))


def get_tool_index() -> int:
    try:
        cfg = load_config()
        ui = cfg.get("ui") or {}
        return _clamp_tool_index(ui.get("tool_index", TOOL_MIN))
    except Exception:
        return TOOL_MIN


def get_tool_name(tool_index: int | None = None) -> str:
    idx = _clamp_tool_index(tool_index if tool_index is not None else get_tool_index())
    return f"Tool {idx}"


def get_bridge_port(tool_index: int | None = None) -> int:
    idx = _clamp_tool_index(tool_index if tool_index is not None else get_tool_index())
    return 9526 + idx


def get_profile_ports(tool_index: int | None = None) -> Dict[str, int]:
    idx = _clamp_tool_index(tool_index if tool_index is not None else get_tool_index())
    base = 9222 + (idx - 1) * 10
    return {
        "P1": base,
        "P2": base + 1,
        "P3": base + 2,
    }


def get_profile_port(profile_id: str, tool_index: int | None = None) -> int:
    ports = get_profile_ports(tool_index)
    return ports.get(str(profile_id or "P1"), ports["P1"])


def get_local_proxy_port(profile_id: str, tool_index: int | None = None) -> int:
    idx = _clamp_tool_index(tool_index if tool_index is not None else get_tool_index())
    offset = {"P1": 1, "P2": 2, "P3": 3}.get(str(profile_id or "P1"), 1)
    return 19080 + (idx - 1) * 10 + offset


def get_tool_extension_dir(profile_id: str, tool_index: int | None = None) -> str:
    idx = _clamp_tool_index(tool_index if tool_index is not None else get_tool_index())
    pid = str(profile_id or "P1")
    return os.path.join(BASE_DIR, "chrome_ext", f"tool{idx}", f"KenDZ_{pid}")
