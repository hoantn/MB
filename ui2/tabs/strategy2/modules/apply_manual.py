from __future__ import annotations

from collections import Counter
from typing import Callable, List, Optional
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from core.apply_lock import acquire as _acquire_apply_lock, release as _release_apply_lock
from core.apply_trace import apply_trace
from core.config import load_config
from core.logger import log
from engine.action import apply_arrangement, compute_moves
from engine.card import Card
from ui2.bridge.ws_layout_store import ws_layout_store


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


def _take_pending_samehand_layout(tab, pid: str, ws_codes: List[str]) -> Optional[List[str]]:
    """Return one pending cmd=606 layout for this hand, if the UI poller queued it."""
    try:
        pend = getattr(tab, "_pending_ws_samehand", None)
        if not isinstance(pend, dict):
            return None
        codes = pend.pop(pid, None)
    except Exception:
        return None

    if isinstance(codes, list) and len(codes) == 13:
        if Counter(map(str, codes)) == Counter(map(str, ws_codes)):
            try:
                tab._layout_codes[pid] = list(codes)
            except Exception:
                pass
            return list(codes)
    return None


def _clear_pending_samehand_layout(tab, pid: str) -> None:
    try:
        pend = getattr(tab, "_pending_ws_samehand", None)
        if isinstance(pend, dict):
            pend.pop(pid, None)
    except Exception:
        pass


def _has_pending_new_hand(tab, pid: str) -> bool:
    try:
        pend = getattr(tab, "_pending_ws_reset", None)
        return isinstance(pend, dict) and pid in pend
    except Exception:
        return False


def _layout_matches_target(final_codes: List[str], target_codes: List[str]) -> bool:
    if len(list(final_codes or [])) != 13 or len(list(target_codes or [])) != 13:
        return False
    return all(
        Counter(map(str, final_codes[a:b])) == Counter(map(str, target_codes[a:b]))
        for a, b in ((0, 3), (3, 8), (8, 13))
    )


def _wait_for_cmd606_layout(tab, pid: str, ws_codes: List[str], previous_layout: List[str], timeout_s: float) -> Optional[List[str]]:
    """Wait briefly for cmd=606 to publish the real game layout before pass 2."""
    end_at = time.time() + max(0.0, float(timeout_s))
    while time.time() < end_at:
        pending = _take_pending_samehand_layout(tab, pid, ws_codes)
        if pending is not None:
            log.debug("[Strategy2] cmd606 pending layout consumed pid=%s first3=%s", pid, pending[:3])
            return pending

        try:
            cur = (getattr(tab, "_layout_codes", {}) or {}).get(pid)
        except Exception:
            cur = None
        if isinstance(cur, list) and len(cur) == 13:
            if Counter(map(str, cur)) == Counter(map(str, ws_codes)) and list(cur) != list(previous_layout):
                log.debug("[Strategy2] cmd606 layout observed pid=%s first3=%s", pid, list(cur)[:3])
                return list(cur)

        time.sleep(0.03)
    return None


def apply_manual_dashboard_style(
    tab,
    profile_id: str,
    ws_codes: List[str],
    suggestion: dict,
) -> None:
    """
    Manual apply is pure WS:
    - cmd=600 provides the hand base,
    - _layout_codes stores the current known layout,
    - cmd=606 syncs the real game layout after dragging.
    """
    pid = str(profile_id)

    chi1_codes = suggestion.get("chi1_codes") or []
    chi2_codes = suggestion.get("chi2_codes") or []
    chi3_codes = suggestion.get("chi3_codes") or []
    expected_layout = list(chi3_codes) + list(chi2_codes) + list(chi1_codes)

    try:
        chi1 = [Card.from_code(c) for c in chi1_codes]
        chi2 = [Card.from_code(c) for c in chi2_codes]
        chi3 = [Card.from_code(c) for c in chi3_codes]
    except Exception as e:
        QMessageBox.warning(tab, "HÚP", f"{pid}: Lỗi parse Card: {e}")
        return

    if not (len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3):
        QMessageBox.warning(tab, "HÚP", f"{pid}: Chi không hợp lệ (không phải 5-5-3).")
        return

    if not hasattr(tab, "_layout_codes"):
        tab._layout_codes = {}

    ws_codes = list(ws_codes or [])
    if len(ws_codes) != 13:
        QMessageBox.warning(tab, "HÚP", f"{pid}: WS không đủ 13 lá, không thể Apply.")
        return

    try:
        cached = tab._layout_codes.get(pid)
        if isinstance(cached, list) and len(cached) == 13:
            if Counter(map(str, cached)) == Counter(map(str, ws_codes)):
                current_codes = list(cached)
            else:
                current_codes = list(ws_codes)
        else:
            current_codes = list(ws_codes)
    except Exception:
        current_codes = list(ws_codes)

    try:
        tab._layout_codes[pid] = list(current_codes)
    except Exception:
        pass

    bm = getattr(tab, "browser_manager", None)
    if bm is None or not hasattr(bm, "get_active_tab"):
        log.error("[Strategy2] INVALID browser_manager type=%s value=%s", type(bm), bm)
        QMessageBox.warning(tab, "HÚP", f"{pid}: BrowserManager không hợp lệ.")
        return

    if not hasattr(tab, "_apply_threads"):
        tab._apply_threads = {}

    try:
        t_old = tab._apply_threads.get(pid)
    except Exception:
        t_old = None

    if t_old is not None and getattr(t_old, "is_alive", lambda: False)():
        return

    try:
        apply_slot = int(getattr(getattr(tab, "browser_manager", None), "_slot", 1) or 1)
    except Exception:
        apply_slot = 1
    if not _acquire_apply_lock(apply_slot, pid):
        log.warning("[Strategy2] MANUAL skip: slot=%d pid=%s is already applying", apply_slot, pid)
        return

    try:
        tab._apply_btn_set_busy(pid)
    except Exception:
        pass

    def _worker_apply() -> None:
        nonlocal current_codes

        res_codes = None
        err_msg: Optional[str] = None
        unlocked_early = False
        try:
            try:
                slot = getattr(getattr(tab, "browser_manager", None), "_slot", 1)
                cfg = load_config(slot)
                ui_cfg = cfg.get("ui") or {}
                ui_apply = ui_cfg.get("apply") or {}
                delay_ms = int(ui_apply.get("delay_between_drag_ms") or 0)
                double_pass_gap_ms = int(ui_apply.get("double_pass_gap_ms") or 4000)
            except Exception:
                delay_ms = 0
                double_pass_gap_ms = 4000

            delay_s = max(0.0, float(delay_ms) / 1000.0)
            cmd606_wait_s = max(0.05, float(double_pass_gap_ms) / 1000.0)

            try:
                if not hasattr(tab, "_ws_freeze"):
                    tab._ws_freeze = {}
                tab._ws_freeze[pid] = True
            except Exception:
                pass

            _clear_pending_samehand_layout(tab, pid)
            layout_store = getattr(tab, "_layout_store", ws_layout_store)
            before_606_seq = layout_store.latest_sequence(pid)
            layout_hand_generation = layout_store.hand_generation(pid)
            planned_moves = compute_moves(list(current_codes), list(expected_layout))
            apply_trace(
                "manual_apply_pass1_before",
                pid,
                moves_len=len(planned_moves),
                seq=before_606_seq,
                hand_generation=layout_hand_generation,
            )

            res_codes = apply_arrangement(
                pid,
                tab.browser_manager,
                list(current_codes),
                chi1,
                chi2,
                chi3,
                delay_s=delay_s,
            )

            if isinstance(res_codes, list) and len(res_codes) == 13:
                try:
                    tab._layout_codes[pid] = list(res_codes)
                except Exception:
                    pass
            else:
                if res_codes is None:
                    log.warning("[Strategy2] apply returned None pid=%s -> treat as uncertain, continue FORCE-APPLY2", pid)
                    res_codes = list(current_codes)
                    try:
                        tab._layout_codes[pid] = list(res_codes)
                    except Exception:
                        pass
                else:
                    raise RuntimeError("apply_arrangement trả về kết quả không hợp lệ.")

            first_drag_finished_at = time.time()
            apply_trace(
                "manual_apply_pass1_after",
                pid,
                result_len=len(res_codes) if isinstance(res_codes, list) else -1,
            )

            if _has_pending_new_hand(tab, pid):
                log.warning("[Strategy2] MANUAL stop repair: new hand pending pid=%s", pid)
                return

            log.warning("[Strategy2] FORCE-APPLY2 pid=%s wait cmd606 before second apply", pid)

            try:
                predicted_layout = list(res_codes) if isinstance(res_codes, list) and len(res_codes) == 13 else list(current_codes)
            except Exception:
                predicted_layout = list(current_codes)

            real_layout = None
            try:
                snapshot = layout_store.wait_for_newer(
                    pid,
                    after_sequence=before_606_seq,
                    after_event_at=first_drag_finished_at,
                    timeout_s=cmd606_wait_s,
                    expected_hand_generation=layout_hand_generation,
                )
                if (
                    snapshot is not None
                    and Counter(map(str, snapshot.cards)) == Counter(map(str, ws_codes))
                ):
                    real_layout = list(snapshot.cards)
                    apply_trace(
                        "manual_cmd606_after_pass1",
                        pid,
                        seq=snapshot.sequence,
                        target_ok=_layout_matches_target(real_layout, list(expected_layout)),
                    )
            except Exception:
                real_layout = None

            if not (isinstance(real_layout, list) and len(real_layout) == 13):
                log.warning(
                    "[Strategy2] FORCE-APPLY2 pid=%s skip: no post-pass1 cmd606, avoid blind repair",
                    pid,
                )
                base_layout = list(predicted_layout)
                try:
                    tab._layout_codes[pid] = list(base_layout)
                except Exception:
                    pass
            else:
                base_layout = list(real_layout)

            if real_layout is None:
                pass
            elif _layout_matches_target(base_layout, list(expected_layout)):
                log.warning("[Strategy2] FORCE-APPLY2 pid=%s skip: cmd606 already matches target", pid)
                _clear_pending_samehand_layout(tab, pid)
                res_codes = list(base_layout)
                try:
                    tab._layout_codes[pid] = list(base_layout)
                except Exception:
                    pass
            else:
                repair_moves = compute_moves(list(base_layout), list(expected_layout))
                log.warning(
                    "[Strategy2] FORCE-APPLY2 pid=%s repair from %s moves=%d",
                    pid,
                    "cmd606",
                    len(repair_moves),
                )

                try:
                    tab._layout_codes[pid] = list(base_layout)
                except Exception:
                    pass

                res_codes_apply2 = apply_arrangement(
                    pid,
                    tab.browser_manager,
                    list(base_layout),
                    chi1,
                    chi2,
                    chi3,
                    delay_s=delay_s,
                )

                if isinstance(res_codes_apply2, list) and len(res_codes_apply2) == 13:
                    res_codes = list(res_codes_apply2)
                    current_codes = list(res_codes)
                    try:
                        tab._layout_codes[pid] = list(res_codes)
                    except Exception:
                        pass

            _clear_pending_samehand_layout(tab, pid)

            try:
                if isinstance(res_codes, list) and len(res_codes) == 13:
                    _ui_call(tab, lambda p=pid: tab._apply_btn_set_default(p), delay_ms=0)
                    unlocked_early = True
            except Exception:
                pass

            try:
                if Counter(map(str, res_codes)) != Counter(map(str, ws_codes)):
                    log.error(
                        "[Strategy2] VERIFY-13 mismatch after apply pid=%s ws_first3=%s res_first3=%s",
                        pid,
                        list(ws_codes)[:3],
                        list(res_codes)[:3],
                    )
            except Exception:
                pass

            log.debug("[Strategy2] wait cmd606 to sync real layout pid=%s", pid)

        except Exception as e:
            err_msg = str(e)
            log.exception("[Strategy2] apply_arrangement ERROR pid=%s: %s", pid, err_msg)

        finally:
            try:
                tab._apply_threads.pop(pid, None)
            except Exception:
                pass

            if err_msg:
                _ui_call(
                    tab,
                    lambda m=err_msg: QMessageBox.warning(tab, "HÚP", f"{pid}: Apply lỗi: {m}"),
                    delay_ms=0,
                )

            if not unlocked_early:
                _ui_call(tab, lambda p=pid: tab._apply_btn_set_default(p), delay_ms=0)

            try:
                tab._ws_freeze[pid] = False
            except Exception:
                pass
            try:
                _release_apply_lock(apply_slot, pid)
            except Exception:
                pass

    t = threading.Thread(target=_worker_apply, name=f"MB-Strategy2-Apply-{pid}", daemon=True)
    tab._apply_threads[pid] = t
    t.start()
