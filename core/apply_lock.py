from __future__ import annotations

import threading
from typing import Dict, Tuple

_busy: Dict[Tuple[int, str], bool] = {}
_lock = threading.Lock()


def acquire(slot: int, pid: str) -> bool:
    key = (int(slot), str(pid))
    with _lock:
        if _busy.get(key, False):
            return False
        _busy[key] = True
        return True


def release(slot: int, pid: str) -> None:
    key = (int(slot), str(pid))
    with _lock:
        _busy[key] = False
