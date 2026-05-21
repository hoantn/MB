# engine/phom/debug.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .store import PhomVisibilityStore

def dump_state(store: PhomVisibilityStore, path: str) -> None:
    Path(path).write_text(json.dumps(store.state.as_debug_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
