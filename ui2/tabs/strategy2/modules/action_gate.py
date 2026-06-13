from __future__ import annotations

from typing import Any, Optional

from core.logger import log


def acquire_profile_action(tab: Any, profile_id: str, action: str, *, owner: str) -> Optional[Any]:
    gate = getattr(tab, "_action_gate", None)
    if gate is None:
        return None
    pid = str(profile_id or "P1")
    lease, busy = gate.try_acquire(pid, str(action or "apply"), owner=owner)
    if lease is not None:
        return lease

    msg = f"{pid} dang ban ({getattr(busy, 'action', 'action')}); bo qua {action} de tranh xung dot."
    log.warning("[ACTION-GATE] slot=%s %s", getattr(busy, "slot", "?"), msg)
    try:
        hook = getattr(tab, "_auto_play_log", None)
        if callable(hook):
            hook(msg)
    except Exception:
        pass
    return False


def release_profile_action(tab: Any, lease: Optional[Any]) -> None:
    if not lease:
        return
    gate = getattr(tab, "_action_gate", None)
    if gate is None:
        return
    try:
        gate.release(lease)
    except Exception:
        log.exception("[ACTION-GATE] release failed action=%s pid=%s", getattr(lease, "action", None), getattr(lease, "profile_id", None))
