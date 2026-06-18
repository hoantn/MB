from __future__ import annotations

from collections import Counter
from typing import Callable, List, Optional
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from core.config import load_config
from core.logger import log
from engine.action import apply_arrangement
from engine.card import Card


def _ui_call(tab, fn: Callable[[], None], delay_ms: int = 0) -> None:
    try:
        if hasattr(tab, "ui_call") and tab.ui_call is not None:
            if delay_ms and delay_ms > 0:
                tab.ui_call.emit(lambda: QTimer.singleShot(int(delay_ms), fn))
            else:
                tab.ui_call.emit(fn)
            return
    except Exception:
        pass

    try:
        if delay_ms and delay_ms > 0:
            QTimer.singleShot(int(delay_ms), fn)
        else:
            fn()
    except Exception:
        pass


def _ensure_dict(tab, attr: str) -> dict:
    value = getattr(tab, attr, None)
    if not isinstance(value, dict):
        value = {}
        try:
            setattr(tab, attr, value)
        except Exception:
            pass
    return value


def _call_manual_busy(tab, pid: str) -> None:
    hook = getattr(tab, "_manual_apply_btn_set_busy", None)
    if not callable(hook):
        hook = getattr(tab, "_apply_btn_set_busy", None)
    if callable(hook):
        hook(pid)


def _call_manual_default(tab, pid: str) -> None:
    hook = getattr(tab, "_manual_apply_btn_set_default", None)
    if not callable(hook):
        hook = getattr(tab, "_apply_btn_set_default", None)
    if callable(hook):
        hook(pid)


def _begin_manual_epoch(tab, pid: str) -> int:
    epochs = _ensure_dict(tab, "_manual_apply_epoch")
    try:
        value = int(epochs.get(pid, 0) or 0) + 1
    except Exception:
        value = 1
    epochs[pid] = value
    return value


def _current_manual_epoch(tab, pid: str) -> int:
    try:
        return int((_ensure_dict(tab, "_manual_apply_epoch")).get(pid, 0) or 0)
    except Exception:
        return 0


def _lock_manual_layout(tab, pid: str) -> None:
    locked = _ensure_dict(tab, "_manual_layout_locked_after_apply")
    locked[pid] = True


def _unlock_manual_layout(tab, pid: str) -> None:
    locked = _ensure_dict(tab, "_manual_layout_locked_after_apply")
    try:
        locked.pop(pid, None)
    except Exception:
        pass


def _read_manual_apply_timing(tab) -> tuple[float, float, float]:
    try:
        slot = int(getattr(getattr(tab, "browser_manager", None), "_slot", 1) or 1)
    except Exception:
        slot = 1

    try:
        cfg = load_config(slot)
        ui_cfg = cfg.get("ui") or {}
        ui_apply = ui_cfg.get("apply") or {}
        delay_raw = ui_apply.get("delay_between_drag_ms")
        if delay_raw is None:
            delay_raw = ui_apply.get("manual_delay_between_drag_ms")
        delay_ms = 10 if delay_raw is None else int(delay_raw)
        drag_raw = ui_apply.get("drag_duration_ms")
        if drag_raw is None:
            drag_raw = ui_apply.get("manual_drag_duration_ms")
        drag_duration_ms = 120 if drag_raw is None else int(drag_raw)
        second_pass_raw = ui_apply.get("manual_second_pass_delay_ms")
        second_pass_ms = 250 if second_pass_raw is None else int(second_pass_raw)
    except Exception:
        delay_ms = 10
        drag_duration_ms = 120
        second_pass_ms = 250

    delay_s = max(0.0, float(delay_ms) / 1000.0)
    drag_duration_s = max(0.0, float(drag_duration_ms) / 1000.0)
    second_pass_wait_s = max(0.0, float(second_pass_ms) / 1000.0)
    return delay_s, second_pass_wait_s, drag_duration_s


def _pick_current_layout(tab, pid: str, ws_codes: List[str]) -> List[str]:
    manual_layouts = _ensure_dict(tab, "_manual_layout_codes")
    ws_codes = list(ws_codes or [])

    try:
        cached = manual_layouts.get(pid)
        if isinstance(cached, list) and len(cached) == 13:
            if Counter(map(str, cached)) == Counter(map(str, ws_codes)):
                return list(cached)
    except Exception:
        pass

    return list(ws_codes)


def _refresh_manual_layout_after_apply(
    tab,
    pid: str,
    manual_layouts: dict,
    apply_epoch: int,
) -> Optional[List[str]]:
    try:
        prev_layout = manual_layouts.get(pid)
        prev_layout = list(prev_layout) if isinstance(prev_layout, list) else None
    except Exception:
        prev_layout = None

    def _start_refresh() -> None:
        try:
            if hasattr(tab, "refresh_manual_slot_order"):
                tab.refresh_manual_slot_order(pid, apply_epoch=apply_epoch)
        except Exception as e:
            log.exception("[MANUAL APPLY] refresh_manual_slot_order error pid=%s: %s", pid, e)

    _ui_call(tab, _start_refresh, delay_ms=0)

    real_codes = None
    started = time.time()
    while (time.time() - started) < 1.0:
        try:
            if _current_manual_epoch(tab, pid) != int(apply_epoch):
                return None
            cur = manual_layouts.get(pid)
        except Exception:
            cur = None
        if isinstance(cur, list) and len(cur) == 13:
            if prev_layout is None or list(cur) != prev_layout:
                real_codes = list(cur)
                break
        time.sleep(0.03)

    if real_codes is None:
        try:
            if _current_manual_epoch(tab, pid) != int(apply_epoch):
                return None
            cur = manual_layouts.get(pid)
            if isinstance(cur, list) and len(cur) == 13:
                real_codes = list(cur)
        except Exception:
            real_codes = None
    return real_codes


def apply_manual_dashboard_style(
    tab,
    profile_id: str,
    ws_codes: List[str],
    suggestion: dict,
) -> None:
    """Manual apply flow isolated from auto apply state.

    This mirrors the MB-Copy drag behavior: pass 1 from the known layout,
    a short settle wait, then an unconditional second pass from the cached
    predicted layout. It deliberately avoids auto-only gates, cross-tab apply
    locks, fast drag flags and cmd=606 confirmation/repair.
    """

    pid = str(profile_id)

    chi1_codes = list((suggestion or {}).get("chi1_codes") or [])
    chi2_codes = list((suggestion or {}).get("chi2_codes") or [])
    chi3_codes = list((suggestion or {}).get("chi3_codes") or [])
    expected_layout = list(chi3_codes) + list(chi2_codes) + list(chi1_codes)

    try:
        chi1 = [Card.from_code(c) for c in chi1_codes]
        chi2 = [Card.from_code(c) for c in chi2_codes]
        chi3 = [Card.from_code(c) for c in chi3_codes]
    except Exception as e:
        QMessageBox.warning(tab, "HUP", f"{pid}: Loi parse Card: {e}")
        return

    if not (len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3):
        QMessageBox.warning(tab, "HUP", f"{pid}: Chi khong hop le (khong phai 5-5-3).")
        return

    ws_codes = list(ws_codes or [])
    if len(ws_codes) != 13:
        QMessageBox.warning(tab, "HUP", f"{pid}: WS khong du 13 la, khong the Apply.")
        return

    if Counter(map(str, expected_layout)) != Counter(map(str, ws_codes)):
        log.error("[MANUAL APPLY ABORT] pid=%s card-mismatch", pid)
        QMessageBox.warning(tab, "HUP", f"{pid}: Bai da doi (khong khop 13 la).")
        return

    current_codes = _pick_current_layout(tab, pid, ws_codes)
    manual_layouts = _ensure_dict(tab, "_manual_layout_codes")
    manual_layouts[pid] = list(current_codes)
    apply_epoch = _begin_manual_epoch(tab, pid)

    bm = getattr(tab, "browser_manager", None)
    if bm is None or not hasattr(bm, "get_active_tab"):
        log.error("[Strategy2] INVALID browser_manager type=%s value=%s", type(bm), bm)
        QMessageBox.warning(tab, "HUP", f"{pid}: BrowserManager khong hop le.")
        return

    threads = _ensure_dict(tab, "_manual_apply_threads")
    try:
        old_thread = threads.get(pid)
    except Exception:
        old_thread = None

    if old_thread is not None and getattr(old_thread, "is_alive", lambda: False)():
        return

    _unlock_manual_layout(tab, pid)

    try:
        _call_manual_busy(tab, pid)
    except Exception:
        pass

    def _worker_apply() -> None:
        nonlocal current_codes

        res_codes: Optional[List[str]] = None
        err_msg: Optional[str] = None
        unlocked_early = False
        try:
            delay_s, second_pass_wait_s, drag_duration_s = _read_manual_apply_timing(tab)
            manual_freeze = _ensure_dict(tab, "_manual_ws_freeze")

            try:
                manual_freeze[pid] = True
            except Exception:
                pass

            res_codes = apply_arrangement(
                pid,
                tab.browser_manager,
                list(current_codes),
                chi1,
                chi2,
                chi3,
                delay_s=delay_s,
                use_copy_moves=True,
                drag_duration_s_override=drag_duration_s,
                validate_runtime=False,
            )

            if isinstance(res_codes, list) and len(res_codes) == 13:
                manual_layouts[pid] = list(res_codes)
            elif res_codes is None:
                log.warning("[MANUAL APPLY] apply returned None pid=%s; continue second pass", pid)
                res_codes = list(current_codes)
                manual_layouts[pid] = list(res_codes)
            else:
                raise RuntimeError("apply_arrangement tra ve ket qua khong hop le.")

            try:
                manual_freeze[pid] = False
            except Exception:
                pass

            if second_pass_wait_s > 0:
                time.sleep(second_pass_wait_s)

            base_layout = None
            try:
                cached_now = manual_layouts.get(pid)
                if isinstance(cached_now, list) and len(cached_now) == 13:
                    base_layout = list(cached_now)
            except Exception:
                base_layout = None

            if base_layout is None:
                if isinstance(res_codes, list) and len(res_codes) == 13:
                    base_layout = list(res_codes)
                else:
                    base_layout = list(current_codes)

            manual_layouts[pid] = list(base_layout)

            res_codes_apply2 = apply_arrangement(
                pid,
                tab.browser_manager,
                list(base_layout),
                chi1,
                chi2,
                chi3,
                delay_s=delay_s,
                use_copy_moves=True,
                drag_duration_s_override=drag_duration_s,
                validate_runtime=False,
            )

            if isinstance(res_codes_apply2, list) and len(res_codes_apply2) == 13:
                res_codes = list(res_codes_apply2)
                current_codes = list(res_codes)
                manual_layouts[pid] = list(res_codes)

            if isinstance(res_codes, list) and len(res_codes) == 13:
                manual_layouts[pid] = list(res_codes)
                _lock_manual_layout(tab, pid)

            try:
                if isinstance(res_codes, list) and len(res_codes) == 13:
                    _ui_call(tab, lambda p=pid: _call_manual_default(tab, p), delay_ms=0)
                    unlocked_early = True
            except Exception:
                pass

            try:
                if Counter(map(str, res_codes or [])) != Counter(map(str, ws_codes)):
                    log.error(
                        "[MANUAL APPLY] VERIFY-13 mismatch pid=%s ws_first3=%s res_first3=%s",
                        pid,
                        list(ws_codes)[:3],
                        list(res_codes or [])[:3],
                    )
            except Exception:
                pass

            try:
                real_codes = _refresh_manual_layout_after_apply(tab, pid, manual_layouts, apply_epoch)
                if isinstance(real_codes, list) and len(real_codes) == 13:
                    manual_layouts[pid] = list(real_codes)
                    _lock_manual_layout(tab, pid)
            except Exception:
                pass

        except Exception as e:
            err_msg = str(e)
            log.exception("[MANUAL APPLY] apply_arrangement error pid=%s: %s", pid, err_msg)

        finally:
            try:
                threads.pop(pid, None)
            except Exception:
                pass

            if err_msg:
                _ui_call(
                    tab,
                    lambda m=err_msg: QMessageBox.warning(tab, "HUP", f"{pid}: Apply loi: {m}"),
                    delay_ms=0,
                )

            if not unlocked_early:
                _ui_call(tab, lambda p=pid: _call_manual_default(tab, p), delay_ms=0)

            try:
                manual_freeze = _ensure_dict(tab, "_manual_ws_freeze")
                manual_freeze[pid] = False
            except Exception:
                pass

            try:
                if hasattr(tab, "refresh_manual_slot_order"):
                    _ui_call(
                        tab,
                        lambda p=pid, e=apply_epoch: tab.refresh_manual_slot_order(p, apply_epoch=e),
                        delay_ms=300,
                    )
            except Exception:
                pass

    thread = threading.Thread(target=_worker_apply, name=f"MB-Strategy2-ManualApply-{pid}", daemon=True)
    threads[pid] = thread
    try:
        thread.start()
    except Exception:
        threads.pop(pid, None)
        try:
            _call_manual_default(tab, pid)
        except Exception:
            pass


apply_manual_copy_style = apply_manual_dashboard_style
