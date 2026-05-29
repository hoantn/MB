from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QTimer, QThread
from PySide6.QtWidgets import QMessageBox

from core.logger import log
from ui2.tabs.dashboard.dashboard_scan_worker import ScanWorker
from ui2.tabs.strategy2.strategy_suggest import apply_suggestion_dashboard_style


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

            def _apply_context(ctx: dict) -> None:
                pid = str(ctx.get("pid") or "")
                try:
                    apply_suggestion_dashboard_style(
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

            # If it is special-row, do not drag-apply
            try:
                if tab._is_special_row(sug):
                    c1 = list(sug.get("chi1_codes") or [])
                    c2 = list(sug.get("chi2_codes") or [])
                    c3 = list(sug.get("chi3_codes") or [])

                    # CHỈ chặn nếu special row chưa được build split (chưa có 5-5-3)
                    if not (len(c1) == 5 and len(c2) == 5 and len(c3) == 3):
                        QMessageBox.information(
                            tab,
                            "Bài đặc biệt",
                            "Đây là bài đặc biệt (báo binh), không thể Apply theo kiểu kéo 13 lá."
                        )
                        return

                    # Nếu đã có split 5-5-3 -> cho đi tiếp như gợi ý bình thường

            except Exception:
                pass
                
            # FAIL-SAFE: suggestion phải sử dụng đúng 13 lá hiện tại
            try:
                target = (sug.get("chi1_codes") or []) + (sug.get("chi2_codes") or []) + (sug.get("chi3_codes") or [])
                if len(target) == 13:
                    if Counter(map(str, target)) != Counter(map(str, ws_codes)):
                        log.error(
                            "[APPLY ABORT] pid=%s card-mismatch ws_first3=%s target_first3=%s",
                            pid,
                            list(ws_codes)[:3],
                            list(target)[:3],
                        )
                        QMessageBox.warning(tab, "HÚP", f"{pid}: Bài đã đổi (không khớp 13 lá). Vui lòng chờ gợi ý mới.")
                        return
            except Exception:
                pass

            apply_suggestion_dashboard_style(
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
            # Prefer StrategyTab.profiles if exists, else fallback to fixed P1..P3
            pids = getattr(tab, "profiles", None)
            if not pids:
                pids = ["P1", "P2", "P3"]

            contexts = []
            for pid in pids:
                # Apply only if we have 13 cards + suggestions
                ws_codes = list(tab._codes_slot_order.get(pid) or [])
                if len(ws_codes) != 13:
                    continue
                suggs = tab._suggestions_render.get(pid) or tab._suggestions.get(pid) or []
                idx = tab._selected_index.get(pid, 0)
                if not suggs or idx < 0 or idx >= len(suggs):
                    continue

                sug = dict(suggs[idx])

                # Do NOT apply special row
                try:
                    if tab._is_special_row(sug):
                        continue
                except Exception:
                    pass

                target = (sug.get("chi1_codes") or []) + (sug.get("chi2_codes") or []) + (sug.get("chi3_codes") or [])
                if len(target) == 13 and Counter(map(str, target)) != Counter(map(str, ws_codes)):
                    log.error(
                        "[APPLY ALL SKIP] pid=%s card-mismatch ws_first3=%s target_first3=%s",
                        pid,
                        list(ws_codes)[:3],
                        list(target)[:3],
                    )
                    continue

                # Snapshot everything needed before starting workers. After this,
                # Apply All must not depend on active_profile or UI selection.
                contexts.append({
                    "pid": str(pid),
                    "ws_codes": list(ws_codes),
                    "suggestion": sug,
                })

            if not contexts:
                return

            def _apply_context(ctx: dict) -> None:
                pid = str(ctx.get("pid") or "")
                try:
                    apply_suggestion_dashboard_style(
                        tab=tab,
                        profile_id=pid,
                        ws_codes=list(ctx.get("ws_codes") or []),
                        suggestion=dict(ctx.get("suggestion") or {}),
                    )
                except Exception as e:
                    log.exception("[Strategy2] ApplyController parallel apply error pid=%s: %s", pid, e)

            # Start nearly together, but not on the exact same millisecond.
            # Each profile uses its own snapshot so P1/P2/P3 do not read shared
            # active_profile/list selection while applying.
            for i, ctx in enumerate(contexts):
                QTimer.singleShot(i * 140, lambda c=ctx: _apply_context(c))

        except Exception as e:
            log.exception("[Strategy2] ApplyController.on_apply_all error: %s", e)
            QMessageBox.warning(tab, "HÚP", f"Apply All lỗi: {e}")

    # -----------------------
    # Scan / resync (optional)
    # -----------------------

    def refresh_slot_order_by_scan(self, tab, profile_id: str) -> None:
        """
        Optional post-apply resync. If StrategyTab calls it, keep robust.
        """
        # Guard: prevent duplicate scan for the same profile_id
        try:
            th0 = tab._scan_threads.get(profile_id)
            if th0 is not None and th0.isRunning():
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

            th = QThread(tab)
            worker.moveToThread(th)

            def _cleanup():
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

            th.start()

        except Exception as e:
            log.exception("[Strategy2] refresh_slot_order_by_scan error pid=%s: %s", profile_id, e)
            try:
                QTimer.singleShot(0, lambda: QMessageBox.warning(tab, "HÚP", f"{profile_id}: Scan lỗi: {e}"))
            except Exception:
                pass
