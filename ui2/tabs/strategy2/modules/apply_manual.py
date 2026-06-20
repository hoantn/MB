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


def _read_manual_apply_timing(tab) -> tuple[float, float]:
    try:
        slot = getattr(getattr(tab, "browser_manager", None), "_slot", 1)
        cfg = load_config(slot)
        ui_cfg = cfg.get("ui") or {}
        ui_apply = ui_cfg.get("apply") or {}
        delay_ms = int(ui_apply.get("delay_between_drag_ms") or 0)
        second_pass_ms = int(ui_apply.get("manual_second_pass_delay_ms") or 250)
    except Exception:
        delay_ms = 0
        second_pass_ms = 250

    delay_s = max(0.0, float(delay_ms) / 1000.0)
    second_pass_wait_s = max(0.05, min(1.0, float(second_pass_ms) / 1000.0))
    return delay_s, second_pass_wait_s


def _wait_real_layout_606(
    tab,
    pid: str,
    ws_codes: List[str],
    *,
    after_sequence: int,
    after_event_at: float,
    timeout_s: float,
    expected_hand_generation: Optional[int],
) -> Optional[List[str]]:
    """Return a real cmd=606 layout for the current hand, never predicted cache."""
    try:
        store = getattr(tab, "_layout_store", ws_layout_store)
        snapshot = store.wait_for_newer(
            pid,
            after_sequence=int(after_sequence),
            after_event_at=float(after_event_at),
            timeout_s=max(0.0, float(timeout_s)),
            expected_hand_generation=expected_hand_generation,
        )
        if snapshot is None:
            return None
        cards = list(getattr(snapshot, "cards", None) or [])
        if len(cards) == 13 and Counter(map(str, cards)) == Counter(map(str, ws_codes)):
            return cards
    except Exception:
        return None
    return None


def apply_manual_dashboard_style(
    tab,
    profile_id: str,
    ws_codes: List[str],
    suggestion: dict,
) -> None:
    """
    Manual apply follows MB-Copy behavior:
    - apply once from the current known layout,
    - wait briefly, apply a forced second pass from the cached layout,
    - refresh the real post-apply layout separately.
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
        uncertain = bool((getattr(tab, "_layout_uncertain", {}) or {}).get(pid))
        if isinstance(cached, list) and len(cached) == 13:
            if not uncertain and Counter(map(str, cached)) == Counter(map(str, ws_codes)):
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
            delay_s, second_pass_wait_s = _read_manual_apply_timing(tab)

            try:
                if not hasattr(tab, "_ws_freeze"):
                    tab._ws_freeze = {}
                tab._ws_freeze[pid] = True
            except Exception:
                pass

            _clear_pending_samehand_layout(tab, pid)
            layout_store = getattr(tab, "_layout_store", ws_layout_store)
            try:
                layout_hand_generation = layout_store.hand_generation(pid)
            except Exception:
                layout_hand_generation = None
            planned_moves = compute_moves(list(current_codes), list(expected_layout))
            apply_trace(
                "manual_apply_pass1_before",
                pid,
                moves_len=len(planned_moves),
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

            apply_trace(
                "manual_apply_pass1_after",
                pid,
                result_len=len(res_codes) if isinstance(res_codes, list) else -1,
            )

            if _has_pending_new_hand(tab, pid):
                log.warning("[Strategy2] MANUAL stop repair: new hand pending pid=%s", pid)
                return

            try:
                predicted_layout = list(res_codes) if isinstance(res_codes, list) and len(res_codes) == 13 else list(current_codes)
            except Exception:
                predicted_layout = list(current_codes)

            try:
                tab._ws_freeze[pid] = False
            except Exception:
                pass

            log.warning(
                "[Strategy2] FORCE-APPLY2 pid=%s wait %.0fms then run second apply",
                pid,
                second_pass_wait_s * 1000.0,
            )
            time.sleep(second_pass_wait_s)

            if _has_pending_new_hand(tab, pid):
                log.warning("[Strategy2] MANUAL stop FORCE-APPLY2: new hand pending pid=%s", pid)
                return

            base_layout = None
            try:
                cached_now = (getattr(tab, "_layout_codes", {}) or {}).get(pid)
                if isinstance(cached_now, list) and len(cached_now) == 13:
                    base_layout = list(cached_now)
            except Exception:
                base_layout = None
            if base_layout is None:
                base_layout = list(predicted_layout)

            repair_moves = compute_moves(list(base_layout), list(expected_layout))
            apply_trace(
                "manual_apply_pass2_before",
                pid,
                source="cache",
                moves_len=len(repair_moves),
            )
            log.warning(
                "[Strategy2] FORCE-APPLY2 pid=%s run second apply from cache moves=%d",
                pid,
                len(repair_moves),
            )

            try:
                tab._layout_codes[pid] = list(base_layout)
            except Exception:
                pass

            try:
                before_pass2_seq = layout_store.latest_sequence(pid)
            except Exception:
                before_pass2_seq = 0
            pass2_started_at = time.time()
            res_codes_apply2 = apply_arrangement(
                pid,
                tab.browser_manager,
                list(base_layout),
                chi1,
                chi2,
                chi3,
                delay_s=delay_s,
            )

            apply_trace(
                "manual_apply_pass2_after",
                pid,
                result_len=len(res_codes_apply2) if isinstance(res_codes_apply2, list) else -1,
            )
            if isinstance(res_codes_apply2, list) and len(res_codes_apply2) == 13:
                res_codes = list(res_codes_apply2)
                current_codes = list(res_codes)
                try:
                    tab._layout_codes[pid] = list(res_codes)
                except Exception:
                    pass

            _clear_pending_samehand_layout(tab, pid)

            real_codes = _wait_real_layout_606(
                tab,
                pid,
                list(ws_codes),
                after_sequence=before_pass2_seq,
                after_event_at=pass2_started_at,
                timeout_s=2.5,
                expected_hand_generation=layout_hand_generation,
            )
            if isinstance(real_codes, list) and len(real_codes) == 13:
                try:
                    tab._layout_codes[pid] = list(real_codes)
                    if hasattr(tab, "_layout_uncertain"):
                        tab._layout_uncertain.pop(pid, None)
                except Exception:
                    pass
                target_ok = _layout_matches_target(real_codes, list(expected_layout))
                apply_trace(
                    "manual_cmd606_after_pass2",
                    pid,
                    target_ok=target_ok,
                    moves_len=len(compute_moves(list(real_codes), list(expected_layout))),
                )
                if not target_ok and not _has_pending_new_hand(tab, pid):
                    repair_moves = compute_moves(list(real_codes), list(expected_layout))
                    log.warning(
                        "[Strategy2] MANUAL real-layout repair pid=%s moves=%d",
                        pid,
                        len(repair_moves),
                    )
                    apply_trace("manual_real_repair_before", pid, moves_len=len(repair_moves))
                    repair_started_at = time.time()
                    try:
                        before_repair_seq = layout_store.latest_sequence(pid)
                    except Exception:
                        before_repair_seq = before_pass2_seq
                    res_codes_repair = apply_arrangement(
                        pid,
                        tab.browser_manager,
                        list(real_codes),
                        chi1,
                        chi2,
                        chi3,
                        delay_s=delay_s,
                    )
                    apply_trace(
                        "manual_real_repair_after",
                        pid,
                        result_len=len(res_codes_repair) if isinstance(res_codes_repair, list) else -1,
                    )
                    if isinstance(res_codes_repair, list) and len(res_codes_repair) == 13:
                        res_codes = list(res_codes_repair)
                        current_codes = list(res_codes)
                        try:
                            tab._layout_codes[pid] = list(res_codes)
                        except Exception:
                            pass
                    confirmed_after_repair = _wait_real_layout_606(
                        tab,
                        pid,
                        list(ws_codes),
                        after_sequence=before_repair_seq,
                        after_event_at=repair_started_at,
                        timeout_s=1.5,
                        expected_hand_generation=layout_hand_generation,
                    )
                    if isinstance(confirmed_after_repair, list) and len(confirmed_after_repair) == 13:
                        try:
                            tab._layout_codes[pid] = list(confirmed_after_repair)
                            if hasattr(tab, "_layout_uncertain"):
                                tab._layout_uncertain.pop(pid, None)
                        except Exception:
                            pass
                        apply_trace(
                            "manual_real_repair_confirm",
                            pid,
                            target_ok=_layout_matches_target(confirmed_after_repair, list(expected_layout)),
                        )
                    else:
                        try:
                            if not hasattr(tab, "_layout_uncertain"):
                                tab._layout_uncertain = {}
                            tab._layout_uncertain[pid] = True
                        except Exception:
                            pass
                        apply_trace("manual_real_repair_unconfirmed", pid)
            else:
                try:
                    if not hasattr(tab, "_layout_uncertain"):
                        tab._layout_uncertain = {}
                    tab._layout_uncertain[pid] = True
                except Exception:
                    pass
                apply_trace("manual_cmd606_after_pass2_missing", pid)

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

            def _start_refresh() -> None:
                try:
                    if hasattr(tab, "refresh_slot_order_by_scan"):
                        tab.refresh_slot_order_by_scan(pid)
                except Exception as e:
                    log.exception("[Strategy2] refresh_slot_order_by_scan error pid=%s: %s", pid, e)

            try:
                prev_layout = (getattr(tab, "_layout_codes", {}) or {}).get(pid)
                prev_layout = list(prev_layout) if isinstance(prev_layout, list) else None
            except Exception:
                prev_layout = None
            _ui_call(tab, _start_refresh, delay_ms=0)

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
    try:
        t.start()
    except Exception:
        try:
            _release_apply_lock(apply_slot, pid)
        except Exception:
            pass
        tab._apply_threads.pop(pid, None)
