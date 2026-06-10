from __future__ import annotations

from collections import Counter
import threading

from PySide6.QtCore import QTimer, QThread
from PySide6.QtWidgets import QMessageBox

from core.apply_trace import apply_trace
from core.logger import log
from ui2.tabs.dashboard.dashboard_scan_worker import ScanWorker
from ui2.tabs.strategy2.modules.layout_verifier import scan_layout_fresh
from ui2.tabs.strategy2.modules.apply_manual import apply_manual_dashboard_style


class ApplyController:
    """
    Contract with StrategyTab (MUST match):
      - on_apply(tab, pid)
      - on_apply_all(tab)

    Notes:
      - Keep existing behavior: per-profile apply uses currently selected suggestion.
      - Avoid crashing on ScanWorker signature changes.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def _prepare_manual_apply(tab, profile_ids) -> bool:
        """Let StrategyTab cancel delayed Auto callbacks before a manual drag."""
        hook = getattr(tab, "_prepare_manual_apply", None)
        if callable(hook):
            return bool(hook(profile_ids))
        return True

    @staticmethod
    def _is_current_snapshot(tab, ctx: dict) -> bool:
        """Reject a delayed manual callback if WS already moved to another hand."""
        pid = str(ctx.get("pid") or "")
        expected = list(ctx.get("ws_codes") or [])
        current = list((getattr(tab, "_codes_slot_order", {}) or {}).get(pid) or [])
        return (
            len(expected) == 13
            and len(current) == 13
            and Counter(map(str, expected)) == Counter(map(str, current))
        )

    def on_apply_combo(self, tab, suggestions_by_pid: dict) -> None:
        """Apply an explicit global combo suggestion for P1/P2/P3."""
        try:
            contexts = []
            for pid in getattr(tab, "profiles", ["P1", "P2", "P3"]):
                sug = dict((suggestions_by_pid or {}).get(pid) or {})
                ws_codes = list(tab._codes_slot_order.get(pid) or [])
                if len(ws_codes) != 13 or not sug:
                    continue

                target = (
                    list(sug.get("chi1_codes") or [])
                    + list(sug.get("chi2_codes") or [])
                    + list(sug.get("chi3_codes") or [])
                )
                if len(target) != 13 or Counter(map(str, target)) != Counter(map(str, ws_codes)):
                    log.error("[APPLY COMBO SKIP] pid=%s card-mismatch", pid)
                    continue

                contexts.append({
                    "pid": str(pid),
                    "ws_codes": list(ws_codes),
                    "suggestion": sug,
                })

            if len(contexts) != 3:
                QMessageBox.warning(tab, "Bẻ Sập Làng", "Combo không đủ 3P hợp lệ để xếp.")
                return

            if not self._prepare_manual_apply(tab, [ctx["pid"] for ctx in contexts]):
                return

            def _apply_context(ctx: dict) -> None:
                pid = str(ctx.get("pid") or "")
                try:
                    if not self._is_current_snapshot(tab, ctx):
                        log.warning("[Strategy2] Skip stale manual combo snapshot pid=%s", pid)
                        return
                    apply_manual_dashboard_style(
                        tab=tab,
                        profile_id=pid,
                        ws_codes=list(ctx.get("ws_codes") or []),
                        suggestion=dict(ctx.get("suggestion") or {}),
                    )
                except Exception as e:
                    log.exception("[Strategy2] ApplyController combo apply error pid=%s: %s", pid, e)

            for i, ctx in enumerate(contexts):
                QTimer.singleShot(i * 140, lambda c=ctx: _apply_context(c))

        except Exception as e:
            log.exception("[Strategy2] ApplyController.on_apply_combo error: %s", e)
            QMessageBox.warning(tab, "Bẻ Sập Làng", f"Apply combo lỗi: {e}")

    # -----------------------
    # PUBLIC API (contract)
    # -----------------------

    def on_apply(self, tab, pid: str) -> None:
        """Called by StrategyTab: apply for one profile."""
        try:
            ws_codes = tab._codes_slot_order.get(pid) or []
            if len(ws_codes) != 13:
                QMessageBox.warning(tab, "HÚP", f"{pid}: Chưa có đủ 13 lá.")
                return

            # suggestions store: prefer rendered if available
            suggs = tab._suggestions_render.get(pid) or tab._suggestions.get(pid) or []
            idx = tab._selected_index.get(pid, 0)

            if not suggs or idx < 0 or idx >= len(suggs):
                QMessageBox.warning(tab, "HÚP", f"{pid}: Chưa có gợi ý.")
                return

            sug = suggs[idx]

            try:
                if tab._is_special_row(sug):
                    c1 = list(sug.get("chi1_codes") or [])
                    c2 = list(sug.get("chi2_codes") or [])
                    c3 = list(sug.get("chi3_codes") or [])
                    if not (len(c1) == 5 and len(c2) == 5 and len(c3) == 3):
                        QMessageBox.information(
                            tab,
                            "Bai dac biet",
                            "Day la bai dac biet (bao binh), khong the Apply theo kieu keo 13 la.",
                        )
                        return
            except Exception:
                pass

            try:
                target = (
                    list(sug.get("chi1_codes") or [])
                    + list(sug.get("chi2_codes") or [])
                    + list(sug.get("chi3_codes") or [])
                )
                if len(target) == 13 and Counter(map(str, target)) != Counter(map(str, ws_codes)):
                    log.error(
                        "[APPLY ABORT] pid=%s card-mismatch ws_first3=%s target_first3=%s",
                        pid,
                        list(ws_codes)[:3],
                        list(target)[:3],
                    )
                    QMessageBox.warning(tab, "HUP", f"{pid}: Bai da doi (khong khop 13 la). Vui long cho goi y moi.")
                    return
            except Exception:
                pass

            if not self._prepare_manual_apply(tab, [pid]):
                return

            apply_manual_dashboard_style(
                tab=tab,
                profile_id=pid,
                ws_codes=list(ws_codes),
                suggestion=sug,
            )

        except Exception as e:
            log.exception("[Strategy2] ApplyController.on_apply error pid=%s: %s", pid, e)
            QMessageBox.warning(tab, "HÚP", f"{pid}: Apply lỗi: {e}")

    def on_apply_all(self, tab) -> None:
        """Called by StrategyTab: apply for all profiles that have 13 cards & a selected suggestion."""
        try:
            pids = getattr(tab, "profiles", None)
            if not pids:
                pids = ["P1", "P2", "P3"]

            for pid in pids:
                ws_codes = tab._codes_slot_order.get(pid) or []
                if len(ws_codes) != 13:
                    continue
                suggs = tab._suggestions_render.get(pid) or tab._suggestions.get(pid) or []
                idx = tab._selected_index.get(pid, 0)
                if not suggs or idx < 0 or idx >= len(suggs):
                    continue
                try:
                    if tab._is_special_row(suggs[idx]):
                        continue
                except Exception:
                    pass
                self.on_apply(tab, pid)

        except Exception as e:
            log.exception("[Strategy2] ApplyController.on_apply_all error: %s", e)
            QMessageBox.warning(tab, "HÚP", f"Apply All lỗi: {e}")

    # -----------------------
    # Scan / resync (optional)
    # -----------------------

    def refresh_slot_order_by_scan(self, tab, profile_id: str) -> None:
        """WS-only mode: cmd=606 owns post-apply layout sync."""
        apply_trace("refresh_scan_skip_ws_only", str(profile_id))
        return None

    def refresh_slot_order_by_scan_fresh(self, tab, profile_id: str) -> None:
        """Quét ảnh mới trong thread riêng và đồng bộ layout lên UI."""
        pid = str(profile_id)
        apply_trace("refresh_scan_enter", pid)
        try:
            running = tab._scan_threads.get(pid)
            if running is not None and getattr(running, "is_alive", lambda: False)():
                apply_trace("refresh_scan_skip_running", pid)
                return
        except Exception:
            pass

        def _scan() -> None:
            try:
                result = scan_layout_fresh(pid, getattr(tab, "capture_manager", None))
                if result is None:
                    apply_trace("refresh_scan_no_result", pid)
                    return
                codes = list(result.codes)

                def _apply_result() -> None:
                    tab._codes_slot_order[pid] = list(codes)
                    tab._layout_codes[pid] = list(codes)
                    if getattr(tab, "active_profile", None) == pid:
                        tab.view.set_cards_p_normalized(list(codes))
                    apply_trace("refresh_scan_result", pid, result_len=len(codes))

                try:
                    tab.ui_call.emit(_apply_result)
                except Exception:
                    _apply_result()
            except Exception as exc:
                apply_trace("refresh_scan_exception", pid, error=str(exc))
                log.exception("[Strategy2] fresh refresh scan failed pid=%s: %s", pid, exc)
            finally:
                try:
                    tab._scan_threads.pop(pid, None)
                except Exception:
                    pass
                apply_trace("refresh_scan_cleanup", pid)

        if not hasattr(tab, "_scan_threads"):
            tab._scan_threads = {}
        thread = threading.Thread(target=_scan, name=f"MB-Strategy2-Scan-{pid}", daemon=True)
        tab._scan_threads[pid] = thread
        apply_trace("refresh_scan_thread_start", pid)
        thread.start()

    def _refresh_slot_order_by_scan_legacy(self, tab, profile_id: str) -> None:
        """
        Optional post-apply resync. If StrategyTab calls it, keep robust.
        """
        apply_trace("refresh_scan_enter", profile_id)
        # Guard: prevent duplicate scan for the same profile_id
        try:
            th0 = tab._scan_threads.get(profile_id)
            if th0 is not None and th0.isRunning():
                apply_trace("refresh_scan_skip_running", profile_id)
                return
        except Exception:
            pass

        try:
            # Construct ScanWorker with a compatible signature
            try:
                worker = ScanWorker(tab.browser_manager, profile_id, tab.capture_manager)
            except TypeError:
                try:
                    worker = ScanWorker(tab.browser_manager, profile_id)
                except TypeError:
                    worker = ScanWorker(profile_id)
            apply_trace("refresh_scan_worker_created", profile_id, worker_type=type(worker).__name__)

            th = QThread(tab)
            worker.moveToThread(th)
            apply_trace("refresh_scan_thread_created", profile_id)

            def _cleanup():
                apply_trace("refresh_scan_cleanup", profile_id)
                try:
                    tab._scan_threads.pop(profile_id, None)
                except Exception:
                    pass
                try:
                    th.deleteLater()
                except Exception:
                    pass

            th.finished.connect(_cleanup)

            # stop thread loop on finish (if signals exist)
            try:
                worker.finished.connect(th.quit)  # type: ignore[attr-defined]
            except Exception:
                pass

            def _on_result(codes_slot_order):
                apply_trace(
                    "refresh_scan_result",
                    profile_id,
                    result_len=len(codes_slot_order) if isinstance(codes_slot_order, list) else -1,
                )
                try:
                    if isinstance(codes_slot_order, list) and len(codes_slot_order) == 13:
                        tab._codes_slot_order[profile_id] = list(codes_slot_order)
                        tab._layout_codes[profile_id] = list(codes_slot_order)
                        if getattr(tab, "active_profile", None) == profile_id:
                            tab.view.set_cards_p_normalized(list(codes_slot_order))
                except Exception:
                    log.exception("[Strategy2] scan result handler error pid=%s", profile_id)

            try:
                worker.result.connect(_on_result)  # type: ignore[attr-defined]
            except Exception:
                pass

            # start worker
            try:
                th.started.connect(worker.run)  # type: ignore[attr-defined]
            except Exception:
                try:
                    th.started.connect(worker.start)  # type: ignore[attr-defined]
                except Exception:
                    pass

            if not hasattr(tab, "_scan_threads"):
                tab._scan_threads = {}
            tab._scan_threads[profile_id] = th

            apply_trace("refresh_scan_thread_start", profile_id)
            th.start()

        except Exception as e:
            apply_trace("refresh_scan_exception", profile_id, error=str(e))
            log.exception("[Strategy2] refresh_slot_order_by_scan error pid=%s: %s", profile_id, e)
            try:
                QTimer.singleShot(0, lambda: QMessageBox.warning(tab, "HÚP", f"{profile_id}: Scan lỗi: {e}"))
            except Exception:
                pass

    def _refresh_slot_order_by_scan_legacy(self, tab, profile_id: str) -> None:
        """Scan real table layout after manual apply using the current ScanWorker API."""
        pid = str(profile_id)
        apply_trace("refresh_scan_enter", pid)

        try:
            th0 = tab._scan_threads.get(pid)
            if th0 is not None and th0.isRunning():
                apply_trace("refresh_scan_skip_running", pid)
                return
        except Exception:
            pass

        try:
            capture_manager = getattr(tab, "capture_manager", None)
            if capture_manager is None:
                apply_trace("refresh_scan_no_capture_manager", pid)
                log.warning("[Strategy2] refresh scan skipped: capture_manager missing pid=%s", pid)
                return

            worker = ScanWorker([pid], capture_manager)
            apply_trace("refresh_scan_worker_created", pid, worker_type=type(worker).__name__)

            th = QThread(tab)
            worker.moveToThread(th)
            apply_trace("refresh_scan_thread_created", pid)

            def _cleanup():
                apply_trace("refresh_scan_cleanup", pid)
                try:
                    tab._scan_threads.pop(pid, None)
                except Exception:
                    pass
                try:
                    worker.deleteLater()
                except Exception:
                    pass
                try:
                    th.deleteLater()
                except Exception:
                    pass

            def _on_profile_scanned(scanned_pid, codes_slot_order, _confs=None, _images=None):
                scanned_pid = str(scanned_pid or pid)
                if scanned_pid != pid:
                    return
                apply_trace(
                    "refresh_scan_result",
                    pid,
                    result_len=len(codes_slot_order) if isinstance(codes_slot_order, list) else -1,
                )
                try:
                    codes = list(codes_slot_order or [])
                    if len(codes) != 13 or any(c is None for c in codes):
                        apply_trace("refresh_scan_bad_result", pid, result_len=len(codes))
                        return
                    tab._layout_codes[pid] = list(codes)
                    if getattr(tab, "active_profile", None) == pid:
                        tab.view.set_cards_p_normalized(list(codes))
                except Exception:
                    log.exception("[Strategy2] scan result handler error pid=%s", pid)

            def _on_scan_error(scanned_pid, message):
                if str(scanned_pid or pid) == pid:
                    apply_trace("refresh_scan_error", pid, message=str(message))
                    log.warning("[Strategy2] refresh scan error pid=%s: %s", pid, message)

            try:
                worker.finished.connect(th.quit)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                worker.profile_scanned.connect(_on_profile_scanned)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                worker.error.connect(_on_scan_error)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                th.finished.connect(_cleanup)
            except Exception:
                pass
            try:
                th.started.connect(worker.run)  # type: ignore[attr-defined]
            except Exception:
                pass

            if not hasattr(tab, "_scan_threads"):
                tab._scan_threads = {}
            tab._scan_threads[pid] = th

            apply_trace("refresh_scan_thread_start", pid)
            th.start()

        except Exception as e:
            apply_trace("refresh_scan_exception", pid, error=str(e))
            log.exception("[Strategy2] refresh_slot_order_by_scan error pid=%s: %s", pid, e)
            try:
                QTimer.singleShot(0, lambda: QMessageBox.warning(tab, "HÚP", f"{pid}: Scan lỗi: {e}"))
            except Exception:
                pass
