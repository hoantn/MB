from __future__ import annotations

from typing import List, Callable, Optional
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox
from collections import Counter

from core.logger import log
from core.apply_trace import apply_trace
from engine.card import Card
from engine.action import apply_arrangement, compute_moves
from core.config import load_config
from engine.foul_rules import is_no_foul, is_no_foul_slot_layout
from ui2.tabs.strategy2.modules.apply_diagnostics import record_apply_failure
from ui2.bridge.ws_layout_store import ws_layout_store
from ui2.tabs.strategy2.modules.apply_confirmation import confirm_and_repair_layout


# ---------------------------------------------------------------------------
# Helpers dùng chung
# ---------------------------------------------------------------------------

def _layout_matches_target(final_codes: List[str], target_codes: List[str]) -> bool:
    if len(list(final_codes or [])) != 13 or len(list(target_codes or [])) != 13:
        return False
    return all(
        Counter(map(str, final_codes[a:b])) == Counter(map(str, target_codes[a:b]))
        for a, b in ((0, 3), (3, 8), (8, 13))
    )


def _layout_is_safe_to_complete(
    pid: str,
    ws_codes: List[str],
    final_codes: List[str],
    target_codes: Optional[List[str]] = None,
) -> bool:
    if len(list(ws_codes or [])) != 13 or len(list(final_codes or [])) != 13:
        log.warning("[AUTO-SAFE] %s: thiếu 13 lá khi verify Xong", pid)
        return False
    if Counter(map(str, final_codes)) != Counter(map(str, ws_codes)):
        log.warning("[AUTO-SAFE] %s: layout cuối không khớp bộ bài WS", pid)
        return False
    if target_codes and len(target_codes) == 13:
        if not _layout_matches_target(final_codes, target_codes):
            log.warning("[AUTO-SAFE] %s: layout cuối chưa khớp chi mục tiêu", pid)
            return False
    try:
        if not is_no_foul_slot_layout(final_codes):
            log.warning("[AUTO-SAFE] %s: layout cuối bị binh lủng, không click Xong", pid)
            return False
    except Exception as e:
        log.warning("[AUTO-SAFE] %s: lỗi verify không lủng: %s", pid, e)
        return False
    return True


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


def _call_unsafe(callback: Callable, reason: str) -> None:
    try:
        callback(str(reason))
    except TypeError:
        callback()


def pick_default_suggestion(suggestions: List[dict]) -> int:
    if not suggestions:
        return 0
    for i, s in enumerate(suggestions):
        if str(s.get("mode", "")).lower() == "money":
            return i
    return 0


def _read_apply_timing_config(slot: int = 1) -> tuple[float, bool, int, int, int]:
    try:
        cfg = load_config(slot)
        ui_cfg = cfg.get("ui") or {}
        ui_apply = ui_cfg.get("apply") or {}
        delay_ms = int(ui_apply.get("delay_between_drag_ms") or 0)
        double_pass = bool(ui_apply.get("double_pass", True))
        double_pass_gap_ms = int(ui_apply.get("double_pass_gap_ms") or 4000)
        layout606_timeout_retry_count = int(ui_apply.get("layout606_timeout_retry_count") or 1)
        layout606_timeout_retry_ms = int(ui_apply.get("layout606_timeout_retry_ms") or 6500)
    except Exception:
        delay_ms = 0
        double_pass = True
        double_pass_gap_ms = 4000
        layout606_timeout_retry_count = 1
        layout606_timeout_retry_ms = 6500
    return (
        max(0.0, float(delay_ms) / 1000.0),
        bool(double_pass),
        max(0, int(double_pass_gap_ms)),
        max(0, int(layout606_timeout_retry_count)),
        max(1, int(layout606_timeout_retry_ms)),
    )


# ---------------------------------------------------------------------------
# LUỒNG THỦ CÔNG — y chang MB - Copy
# ---------------------------------------------------------------------------

def apply_manual_dashboard_style(
    tab,
    profile_id: str,
    ws_codes: List[str],
    suggestion: dict,
) -> None:
    """Kéo bài thủ công: double pass ngay, không chờ cmd=606, scan 1s."""

    pid = str(profile_id)

    # 1) Build Card objects
    chi1_codes = suggestion.get("chi1_codes") or []
    chi2_codes = suggestion.get("chi2_codes") or []
    chi3_codes = suggestion.get("chi3_codes") or []

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

    # 2) current_codes: ưu tiên cache nếu cùng multiset với ws_codes
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

    # 3) Kiểm tra BrowserManager
    bm = getattr(tab, "browser_manager", None)
    if bm is None or not hasattr(bm, "get_active_tab"):
        log.error("[Strategy2] INVALID browser_manager type=%s value=%s", type(bm), bm)
        QMessageBox.warning(tab, "HÚP", f"{pid}: BrowserManager không hợp lệ.")
        return

    # 4) Guard: tránh apply đè
    if not hasattr(tab, "_apply_threads"):
        tab._apply_threads = {}

    try:
        t_old = tab._apply_threads.get(pid)
    except Exception:
        t_old = None

    if t_old is not None and getattr(t_old, "is_alive", lambda: False)():
        return

    # 5) Set busy
    try:
        tab._apply_btn_set_busy(pid)
    except Exception:
        pass

    # 6) Worker thread
    def _worker_apply() -> None:
        nonlocal current_codes

        res_codes = None
        err_msg: Optional[str] = None
        unlocked_early = False
        try:
            try:
                cfg = load_config(getattr(getattr(tab, "browser_manager", None), "_slot", 1))
                ui_cfg = cfg.get("ui") or {}
                ui_apply = ui_cfg.get("apply") or {}
                delay_ms = int(ui_apply.get("delay_between_drag_ms") or 0)
            except Exception:
                delay_ms = 0
            delay_s = max(0.0, float(delay_ms) / 1000.0)

            # WS FREEZE
            try:
                if not hasattr(tab, "_ws_freeze"):
                    tab._ws_freeze = {}
                tab._ws_freeze[pid] = True
            except Exception:
                pass

            # Pass 1
            res_codes = apply_arrangement(
                pid, tab.browser_manager, list(current_codes), chi1, chi2, chi3, delay_s=delay_s,
            )

            if isinstance(res_codes, list) and len(res_codes) == 13:
                try:
                    tab._layout_codes[pid] = list(res_codes)
                except Exception:
                    pass
            elif res_codes is None:
                log.warning("[Strategy2] FORCE-APPLY2 pid=%s apply returned None -> treat as uncertain", pid)
                res_codes = list(current_codes)
                try:
                    tab._layout_codes[pid] = list(res_codes)
                except Exception:
                    pass
            else:
                raise RuntimeError("apply_arrangement trả về kết quả không hợp lệ.")

            # WS UNFREEZE ngay sau pass 1
            try:
                tab._ws_freeze[pid] = False
            except Exception:
                pass

            # Pass 2 (FORCE): chạy ngay sau 0.25s, không điều kiện
            log.warning("[Strategy2] FORCE-APPLY2 pid=%s run second apply immediately", pid)
            time.sleep(0.25)

            base_layout = None
            try:
                cached_now = (getattr(tab, "_layout_codes", {}) or {}).get(pid)
                if isinstance(cached_now, list) and len(cached_now) == 13:
                    base_layout = list(cached_now)
            except Exception:
                base_layout = None

            if base_layout is None:
                if isinstance(res_codes, list) and len(res_codes) == 13:
                    base_layout = list(res_codes)
                else:
                    base_layout = list(current_codes)

            try:
                tab._layout_codes[pid] = list(base_layout)
            except Exception:
                pass

            res_codes_apply2 = apply_arrangement(
                pid, tab.browser_manager, list(base_layout), chi1, chi2, chi3, delay_s=delay_s,
            )

            if isinstance(res_codes_apply2, list) and len(res_codes_apply2) == 13:
                res_codes = list(res_codes_apply2)
                current_codes = list(res_codes)
                try:
                    tab._layout_codes[pid] = list(res_codes)
                except Exception:
                    pass

            # EARLY UI UNLOCK ngay sau pass 2
            try:
                if isinstance(res_codes, list) and len(res_codes) == 13:
                    _ui_call(tab, lambda p=pid: tab._apply_btn_set_default(p), delay_ms=0)
                    unlocked_early = True
            except Exception:
                pass

            # VERIFY 13 (log only)
            try:
                if Counter(map(str, res_codes)) != Counter(map(str, ws_codes)):
                    log.error(
                        "[Strategy2] VERIFY-13 mismatch after apply pid=%s ws_first3=%s res_first3=%s",
                        pid, list(ws_codes)[:3], list(res_codes)[:3],
                    )
            except Exception:
                pass

            # SCAN + poll 1s chờ scan cập nhật _layout_codes
            def _start_scan():
                try:
                    if hasattr(tab, "refresh_slot_order_by_scan"):
                        tab.refresh_slot_order_by_scan(pid)
                except Exception as exc:
                    log.exception("[Strategy2] refresh_slot_order_by_scan error pid=%s: %s", pid, exc)

            try:
                prev_layout = (getattr(tab, "_layout_codes", {}) or {}).get(pid)
                prev_layout = list(prev_layout) if isinstance(prev_layout, list) else None
            except Exception:
                prev_layout = None
            _ui_call(tab, _start_scan, delay_ms=0)

            real_codes = None
            t0 = time.time()
            while (time.time() - t0) < 1.0:
                try:
                    cur = (getattr(tab, "_layout_codes", {}) or {}).get(pid)
                except Exception:
                    cur = None
                if isinstance(cur, list) and len(cur) == 13:
                    if (prev_layout is None) or (list(cur) != prev_layout):
                        real_codes = list(cur)
                        break
                time.sleep(0.03)

            if real_codes is None:
                try:
                    cur = (getattr(tab, "_layout_codes", {}) or {}).get(pid)
                    if isinstance(cur, list) and len(cur) == 13:
                        real_codes = list(cur)
                except Exception:
                    real_codes = None

            if (
                isinstance(real_codes, list) and len(real_codes) == 13
                and isinstance(res_codes, list) and len(res_codes) == 13
                and list(real_codes) != list(res_codes)
            ):
                try:
                    tab._layout_codes[pid] = list(real_codes)
                except Exception:
                    pass

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
                if hasattr(tab, "refresh_slot_order_by_scan"):
                    _ui_call(tab, lambda p=pid: tab.refresh_slot_order_by_scan(p), delay_ms=300)
            except Exception:
                pass

            try:
                tab._ws_freeze[pid] = False
            except Exception:
                pass

    t = threading.Thread(target=_worker_apply, name=f"MB-Strategy2-Apply-{pid}", daemon=True)
    tab._apply_threads[pid] = t
    t.start()


# ---------------------------------------------------------------------------
# LUỒNG AUTO — giữ nguyên, chờ cmd=606, confirm_and_repair, callbacks
# ---------------------------------------------------------------------------

def apply_suggestion_dashboard_style(
    tab,
    profile_id: str,
    ws_codes: List[str],
    suggestion: dict,
    on_complete: Optional[Callable[[], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
    on_unsafe: Optional[Callable[[], None]] = None,
) -> bool:
    """Kéo bài auto: chờ cmd=606, confirm_and_repair, gọi callbacks."""

    pid = str(profile_id)
    transaction_id = f"{pid}-{time.time_ns()}"
    apply_trace(
        "apply_request", pid,
        tx=transaction_id,
        ws_len=len(ws_codes or []),
        mode=str((suggestion or {}).get("mode", "")),
        has_complete=bool(on_complete),
    )

    # 1) Build Card objects
    chi1_codes = suggestion.get("chi1_codes") or []
    chi2_codes = suggestion.get("chi2_codes") or []
    chi3_codes = suggestion.get("chi3_codes") or []
    is_special = bool(
        suggestion.get("is_special")
        or suggestion.get("_is_special_row")
        or str(suggestion.get("mode", "")).lower() == "special"
    )
    require_no_foul = bool(callable(on_complete) and not is_special)

    try:
        chi1 = [Card.from_code(c) for c in chi1_codes]
        chi2 = [Card.from_code(c) for c in chi2_codes]
        chi3 = [Card.from_code(c) for c in chi3_codes]
    except Exception as e:
        QMessageBox.warning(tab, "HÚP", f"{pid}: Lỗi parse Card: {e}")
        return False

    if not (len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3):
        QMessageBox.warning(tab, "HÚP", f"{pid}: Chi không hợp lệ (không phải 5-5-3).")
        return False
    if require_no_foul and not is_no_foul(chi1, chi2, chi3):
        log.error("[AUTO-SAFE] %s: từ chối gợi ý thường bị binh lủng trước khi kéo", pid)
        record_apply_failure(
            "invalid_target_foul_before_drag", pid,
            chi1_codes=list(chi1_codes), chi2_codes=list(chi2_codes), chi3_codes=list(chi3_codes),
            mode=str((suggestion or {}).get("mode", "")),
        )
        if callable(on_unsafe):
            _ui_call(tab, lambda: _call_unsafe(on_unsafe, "invalid_target_foul_before_drag"), delay_ms=0)
        return False

    expected_layout = list(chi3_codes) + list(chi2_codes) + list(chi1_codes)

    # 2) current_codes từ ws_codes
    if not hasattr(tab, "_layout_codes"):
        tab._layout_codes = {}

    ws_codes = list(ws_codes or [])
    if len(ws_codes) != 13:
        QMessageBox.warning(tab, "HÚP", f"{pid}: WS không đủ 13 lá, không thể Apply.")
        return False
    if Counter(map(str, expected_layout)) != Counter(map(str, ws_codes)):
        log.warning("[AUTO-SAFE] %s: suggestion không khớp 13 lá hiện tại", pid)
        return False

    current_codes = list(ws_codes)
    apply_trace("apply_start_from_cmd600", pid, tx=transaction_id)
    try:
        tab._layout_codes[pid] = list(current_codes)
    except Exception:
        pass

    # 3) Kiểm tra BrowserManager
    bm = getattr(tab, "browser_manager", None)
    if bm is None or not hasattr(bm, "get_active_tab"):
        log.error("[Strategy2] INVALID browser_manager type=%s value=%s", type(bm), bm)
        QMessageBox.warning(tab, "HÚP", f"{pid}: BrowserManager không hợp lệ.")
        return False

    # 4) Guard
    if not hasattr(tab, "_apply_threads"):
        tab._apply_threads = {}

    try:
        t_old = tab._apply_threads.get(pid)
    except Exception:
        t_old = None

    if t_old is not None and getattr(t_old, "is_alive", lambda: False)():
        apply_trace("apply_reject_thread_alive", pid)
        return False

    # 5) Set busy
    try:
        tab._apply_btn_set_busy(pid)
    except Exception:
        pass

    # 6) Worker thread
    def _worker_apply() -> None:
        nonlocal current_codes

        res_codes = None
        err_msg: Optional[str] = None
        unlocked_early = False
        apply_trace("worker_enter", pid)
        try:
            (
                delay_s,
                double_pass_enabled,
                double_pass_gap_ms,
                layout606_timeout_retry_count,
                layout606_timeout_retry_ms,
            ) = _read_apply_timing_config(
                slot=getattr(getattr(tab, "browser_manager", None), "_slot", 1)
            )

            try:
                if not hasattr(tab, "_ws_freeze"):
                    tab._ws_freeze = {}
                tab._ws_freeze[pid] = True
            except Exception:
                pass

            base_layout = list(current_codes)
            planned_moves = compute_moves(base_layout, list(expected_layout))
            before_606_seq = ws_layout_store.latest_sequence(pid)
            layout_hand_generation = ws_layout_store.hand_generation(pid)
            apply_trace("apply_once_before", pid, moves_len=len(planned_moves))
            res_codes = apply_arrangement(
                pid, tab.browser_manager, base_layout, chi1, chi2, chi3, delay_s=delay_s,
            )
            apply_trace(
                "apply_once_after", pid,
                result_len=len(res_codes) if isinstance(res_codes, list) else -1,
            )
            first_drag_finished_at = time.time()

            if double_pass_enabled and planned_moves:
                fast_snapshot = ws_layout_store.wait_for_newer(
                    pid,
                    after_sequence=before_606_seq,
                    after_event_at=first_drag_finished_at,
                    timeout_s=float(double_pass_gap_ms) / 1000.0,
                    expected_hand_generation=layout_hand_generation,
                )
                fast_layout = (
                    list(fast_snapshot.cards)
                    if (
                        fast_snapshot is not None
                        and Counter(map(str, fast_snapshot.cards)) == Counter(map(str, ws_codes))
                    )
                    else []
                )
                second_moves = (
                    compute_moves(list(fast_layout), list(expected_layout))
                    if fast_layout and not _layout_matches_target(fast_layout, list(expected_layout))
                    else []
                )
                apply_trace(
                    "apply_double_pass_check", pid,
                    moves_len=len(second_moves), gap_ms=double_pass_gap_ms,
                    has_606=bool(fast_layout), tx=transaction_id,
                )
                if second_moves:
                    apply_trace("apply_double_pass_before", pid, moves_len=len(second_moves), tx=transaction_id)
                    res_codes2 = apply_arrangement(
                        pid, tab.browser_manager, list(fast_layout), chi1, chi2, chi3, delay_s=delay_s,
                    )
                    apply_trace(
                        "apply_double_pass_after", pid,
                        result_len=len(res_codes2) if isinstance(res_codes2, list) else -1,
                        tx=transaction_id,
                    )
                    if isinstance(res_codes2, list) and len(res_codes2) == 13:
                        res_codes = list(res_codes2)
            drag_finished_at = time.time()

            apply_ok = bool(
                isinstance(res_codes, list)
                and len(res_codes) == 13
                and Counter(map(str, res_codes)) == Counter(map(str, ws_codes))
                and _layout_matches_target(list(res_codes), list(expected_layout))
            )
            confirmation = None
            if apply_ok:
                def _repair_from_actual(actual_layout: List[str]) -> float:
                    repair_result = apply_arrangement(
                        pid, tab.browser_manager, list(actual_layout),
                        chi1, chi2, chi3, delay_s=delay_s,
                    )
                    apply_trace(
                        "layout606_repair_drag_result", pid,
                        result_len=len(repair_result) if isinstance(repair_result, list) else -1,
                    )
                    return time.time()

                confirmation = confirm_and_repair_layout(
                    pid, list(expected_layout),
                    after_sequence=before_606_seq,
                    drag_finished_at=drag_finished_at,
                    repair=_repair_from_actual,
                    timeout_retry_count=layout606_timeout_retry_count,
                    timeout_retry_s=float(layout606_timeout_retry_ms) / 1000.0,
                    transaction_id=transaction_id,
                    expected_hand_generation=layout_hand_generation,
                )
                apply_ok = bool(confirmation.confirmed and confirmation.layout)
                if apply_ok:
                    res_codes = list(confirmation.layout or [])

            if apply_ok and require_no_foul:
                apply_ok = _layout_is_safe_to_complete(
                    pid, list(ws_codes), list(res_codes), list(expected_layout),
                )

            if not apply_ok:
                if confirmation is not None and confirmation.snapshot is not None:
                    tab._layout_codes[pid] = list(confirmation.snapshot.cards)
                failure_event = (
                    f"layout606_{confirmation.reason}"
                    if confirmation is not None
                    else "drag_send_failed_or_invalid_result"
                )
                record_apply_failure(
                    failure_event, pid,
                    base_layout=base_layout,
                    target_layout=list(expected_layout),
                    planned_moves=list(planned_moves),
                    drag_result=list(res_codes) if isinstance(res_codes, list) else None,
                    drag_result_type=type(res_codes).__name__,
                    layout606_seq=(
                        confirmation.snapshot.sequence
                        if confirmation is not None and confirmation.snapshot is not None
                        else None
                    ),
                    repair_attempts=confirmation.repair_attempts if confirmation is not None else 0,
                    transaction_id=transaction_id,
                )
                if callable(on_unsafe):
                    _ui_call(
                        tab,
                        lambda reason=failure_event: _call_unsafe(on_unsafe, reason),
                        delay_ms=0,
                    )
                return

            tab._layout_codes[pid] = list(res_codes)
            if not hasattr(tab, "_confirmed_apply_tokens"):
                tab._confirmed_apply_tokens = {}
            tab._confirmed_apply_tokens[pid] = transaction_id
            apply_trace("apply_once_safe", pid, tx=transaction_id)

            try:
                _ui_call(tab, lambda p=pid: tab._apply_btn_set_default(p), delay_ms=0)
                unlocked_early = True
            except Exception:
                pass

            apply_trace("auto_safe_ok", pid)
            _ui_call(tab, on_complete, delay_ms=0)
            if callable(on_finished):
                apply_trace("on_finished_call", pid)
                _ui_call(tab, on_finished, delay_ms=0)

        except Exception as e:
            err_msg = str(e)
            apply_trace("worker_exception", pid, error=err_msg)
            log.exception("[Strategy2] apply_arrangement ERROR pid=%s: %s", pid, err_msg)

        finally:
            apply_trace("worker_finally", pid, err=bool(err_msg), unlocked=bool(unlocked_early))
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

    t = threading.Thread(target=_worker_apply, name=f"MB-Strategy2-Apply-{pid}", daemon=True)
    tab._apply_threads[pid] = t
    apply_trace("thread_start", pid, thread_name=t.name)
    t.start()
    return True
