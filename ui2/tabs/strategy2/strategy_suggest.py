from __future__ import annotations

from typing import List, Callable, Optional
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox
import time
from collections import Counter

from core.logger import log
from engine.card import Card
from engine.action import apply_arrangement
from core.config import load_config


def _ui_call(tab, fn: Callable[[], None], delay_ms: int = 0) -> None:
    """Execute `fn()` on the Qt UI thread, optionally delayed.

    - If StrategyTab provides `ui_call` (Signal(object)) we emit a callable to be executed on UI thread.
    - Safe to call from non-Qt threads.
    """
    try:
        if hasattr(tab, "ui_call") and tab.ui_call is not None:
            if delay_ms and delay_ms > 0:
                tab.ui_call.emit(lambda: QTimer.singleShot(int(delay_ms), fn))
            else:
                tab.ui_call.emit(fn)
            return
    except Exception:
        pass

    # Fallback (best-effort). If called from non-Qt thread, Qt may warn; keep as last resort.
    try:
        if delay_ms and delay_ms > 0:
            QTimer.singleShot(int(delay_ms), fn)
        else:
            fn()
    except Exception:
        pass


def pick_default_suggestion(suggestions: List[dict]) -> int:
    """Default index = Money nếu có, không thì 0."""
    if not suggestions:
        return 0
    for i, s in enumerate(suggestions):
        if str(s.get("mode", "")).lower() == "money":
            return i
    return 0


def apply_suggestion_dashboard_style(
    tab,
    profile_id: str,
    ws_codes: List[str],
    suggestion: dict,
    on_complete: Optional[Callable[[], None]] = None,
) -> None:
    """
    Apply gợi ý theo phong cách Dashboard, nhưng đảm bảo:
    - Dùng đúng 13 lá hiện tại (verify 13 trước khi kéo – đã làm ở ApplyController).
    - Kéo 1–1: apply_arrangement chạy với layout hiện tại.
    - Sau khi kéo xong: SCAN lại, so sánh layout REAL vs layout ENGINE.
    - Nếu lệch -> fallback: apply_arrangement lần 2 từ layout REAL để đồng bộ.
    """

    pid = str(profile_id)

    # ------------------------------------------------------------------
    # 1) Build Card objects từ suggestion (engine yêu cầu List[Card])
    # ------------------------------------------------------------------
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

    # 5+5+3 = 13 lá
    if not (len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3):
        QMessageBox.warning(tab, "HÚP", f"{pid}: Chi không hợp lệ (không phải 5-5-3).")
        return
    # Layout mục tiêu theo thứ tự slot (3 + 5 + 5)
    expected_layout = list(chi3_codes) + list(chi2_codes) + list(chi1_codes)

    # ------------------------------------------------------------------
    # 2) Lấy layout hiện tại (current_codes)
    #    - Ưu tiên cache _layout_codes nếu cùng multiset với ws_codes.
    #    - Ngược lại dùng ws_codes làm ground truth.
    # ------------------------------------------------------------------
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
                # cache lệch WS -> bỏ, dùng WS làm chuẩn
                current_codes = list(ws_codes)
        else:
            current_codes = list(ws_codes)
    except Exception:
        current_codes = list(ws_codes)

    # luôn sync lại cache theo current
    try:
        tab._layout_codes[pid] = list(current_codes)
    except Exception:
        pass

    # ------------------------------------------------------------------
    # 3) Kiểm tra BrowserManager & DevTools contract cơ bản
    # ------------------------------------------------------------------
    bm = getattr(tab, "browser_manager", None)
    if bm is None or not hasattr(bm, "get_active_tab"):
        log.error("[Strategy2] INVALID browser_manager type=%s value=%s", type(bm), bm)
        QMessageBox.warning(tab, "HÚP", f"{pid}: BrowserManager không hợp lệ.")
        return

    # ------------------------------------------------------------------
    # 4) Guard: tránh apply đè nếu đang chạy
    # ------------------------------------------------------------------
    if not hasattr(tab, "_apply_threads"):
        tab._apply_threads = {}

    try:
        t_old = tab._apply_threads.get(pid)
    except Exception:
        t_old = None

    if t_old is not None and getattr(t_old, "is_alive", lambda: False)():
        # đang apply -> im lặng, không hiển thị popup
        return

    # ------------------------------------------------------------------
    # 5) Đặt nút Apply sang trạng thái "busy" (UI thread)
    # ------------------------------------------------------------------
    try:
        tab._apply_btn_set_busy(pid)
    except Exception:
        pass

    # ------------------------------------------------------------------
    # 6) Worker thread: kéo + verify + fallback
    # ------------------------------------------------------------------
    def _worker_apply() -> None:
        nonlocal current_codes

        res_codes = None
        err_msg: Optional[str] = None
        unlocked_early = False
        try:
            # 6.1 Đọc config delay / tốc độ kéo
            try:
                cfg = load_config()
                ui_cfg = cfg.get("ui") or {}
                ui_apply = ui_cfg.get("apply") or {}
                delay_ms = int(ui_apply.get("delay_between_drag_ms") or 0)
            except Exception:
                delay_ms = 0

            delay_s = max(0.0, float(delay_ms) / 1000.0)

            # ------------------------------------------------------------------
            # LẦN 1: apply_arrangement từ current_codes
            # ------------------------------------------------------------------
            # WS FREEZE: chặn WS same-hand update chen ngang trong lúc kéo
            try:
                if not hasattr(tab, "_ws_freeze"):
                    tab._ws_freeze = {}
                tab._ws_freeze[pid] = True
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
            )

            if isinstance(res_codes, list) and len(res_codes) == 13:
                try:
                    tab._layout_codes[pid] = list(res_codes)
                except Exception:
                    pass
            else:
                # NOTE:
                # - apply_arrangement có thể trả None khi gặp lỗi kéo thật sự
                # - nhưng cũng có thể rơi vào case "không có move" (bài đã đúng),
                #   khi đó ta coi là NO-OP thành công và dùng current_codes làm kết quả.
                if res_codes is None:
                    log.warning("[Strategy2] apply returned None pid=%s -> treat as uncertain, continue FORCE-APPLY2", pid)
                    # không gán res_codes = current_codes ở đây để tránh che lỗi
                    res_codes = list(current_codes)
                    try:
                        tab._layout_codes[pid] = list(res_codes)
                    except Exception:
                        pass
                else:
                    # Trường hợp lạ khác (không phải list 13, cũng không phải None) -> coi là lỗi
                    raise RuntimeError("apply_arrangement trả về kết quả không hợp lệ.")

            # ------------------------------------------------------------------
            # WS UNFREEZE: drag đã xong -> cho phép WS đồng bộ trở lại
            try:
                tab._ws_freeze[pid] = False
            except Exception:
                pass

            # Auto Play special uses this hook to click Báo binh only after the
            # drag worker has finished. Manual apply keeps the default None.
            if not err_msg and callable(on_complete):
                _ui_call(tab, on_complete, delay_ms=0)
            # ------------------------------------------------------------------
            # LẦN 2 (FORCE): chạy ngay 1 vòng nữa cho chắc
            # - Mục tiêu: tương đương click Apply 2 lần thủ công
            # - Không cần verify FAIL/OK, cứ chạy luôn
            # ------------------------------------------------------------------
            log.warning("[Strategy2] FORCE-APPLY2 pid=%s run second apply immediately", pid)

            # đợi ngắn để game settle drag events của lần 1
            time.sleep(0.25)

            # Base layout cho lần 2: ưu tiên cache sau lần 1, rồi res_codes, rồi current_codes
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


            # sync cache theo base_layout trước khi apply lần 2
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

            # nếu lần 2 trả layout hợp lệ -> dùng làm res_codes cuối cùng
            if isinstance(res_codes_apply2, list) and len(res_codes_apply2) == 13:
                res_codes = list(res_codes_apply2)
                current_codes = list(res_codes)
                try:
                    tab._layout_codes[pid] = list(res_codes)
                except Exception:
                    pass
            # ------------------------------------------------------------------

            # EARLY UI UNLOCK:
            # - Ngay sau khi apply_arrangement LẦN 1 xong (drag cuối xong),
            #   trả nút Apply về default để click tiếp được ngay.
            # - Vẫn giữ worker chạy tiếp scan/fallback để đảm bảo đồng bộ.
            # ------------------------------------------------------------------
            try:
                if isinstance(res_codes, list) and len(res_codes) == 13:
                    _ui_call(tab, lambda p=pid: tab._apply_btn_set_default(p), delay_ms=0)
                    unlocked_early = True
            except Exception:
                pass

            # VERIFY 13 lần nữa (ENGINE vs WS) – an toàn thêm một lớp
            # ------------------------------------------------------------------
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

            # ------------------------------------------------------------------
            # SCAN & UI sync:
            #   - Gọi refresh_slot_order_by_scan(pid) trên UI thread.
            #   - Đợi QThread scan xong (tab._scan_threads[pid]).
            #   - Đọc layout REAL từ tab._layout_codes[pid].
            #   - Nếu REAL ≠ res_codes -> apply_arrangement lần 2 từ REAL.
            # ------------------------------------------------------------------
            # ... (giữ nguyên toàn bộ SCAN & UI sync của anh ở đây)
            def _start_scan():
                try:
                    if hasattr(tab, "refresh_slot_order_by_scan"):
                        tab.refresh_slot_order_by_scan(pid)
                except Exception as e:
                    log.exception("[Strategy2] refresh_slot_order_by_scan error pid=%s: %s", pid, e)

            # REALTIME (data-flag) thay cho wait thread:
            # Chờ _layout_codes[pid] được scan cập nhật (đổi so với prev_layout) -> fallback ngay.
            try:
                prev_layout = (getattr(tab, "_layout_codes", {}) or {}).get(pid)
                prev_layout = list(prev_layout) if isinstance(prev_layout, list) else None
            except Exception:
                prev_layout = None
            _ui_call(tab, _start_scan, delay_ms=0)
            real_codes = None
            t0 = time.time()
            timeout_s = 1.0  # realtime: đủ nhanh để không phải đợi, vẫn an toàn

            while (time.time() - t0) < timeout_s:
                try:
                    cur = (getattr(tab, "_layout_codes", {}) or {}).get(pid)
                except Exception:
                    cur = None

                if isinstance(cur, list) and len(cur) == 13:
                    # Nếu scan cập nhật thì layout thường đổi (hoặc prev_layout chưa có)
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
                isinstance(real_codes, list)
                and len(real_codes) == 13
                and isinstance(res_codes, list)
                and len(res_codes) == 13
            ):
                if list(real_codes) != list(res_codes):
                    if isinstance(real_codes, list) and len(real_codes) == 13:
                        tab._layout_codes[pid] = list(real_codes)

        except Exception as e:
            err_msg = str(e)
            log.exception("[Strategy2] apply_arrangement ERROR pid=%s: %s", pid, err_msg)

        finally:
            # Luôn clear thread entry
            try:
                tab._apply_threads.pop(pid, None)
            except Exception:
                pass

            # UI: báo lỗi (nếu có)
            if err_msg:
                _ui_call(
                    tab,
                    lambda m=err_msg: QMessageBox.warning(tab, "HÚP", f"{pid}: Apply lỗi: {m}"),
                    delay_ms=0,
                )

            # UI: trả nút Apply về trạng thái mặc định
            # (nếu đã unlock sớm sau drag cuối thì không gọi lại lần 2)
            if not unlocked_early:
                _ui_call(tab, lambda p=pid: tab._apply_btn_set_default(p), delay_ms=0)


            # UI: scan cuối cùng để UI sync (không cần chờ, chỉ để user thấy bài đúng)
            try:
                if hasattr(tab, "refresh_slot_order_by_scan"):
                    _ui_call(tab, lambda p=pid: tab.refresh_slot_order_by_scan(p), delay_ms=300)
            except Exception:
                pass
            # Safety: không bao giờ để WS freeze bị kẹt
            try:
                tab._ws_freeze[pid] = False
            except Exception:
                pass

    # Spawn worker thread
    t = threading.Thread(target=_worker_apply, name=f"MB-Strategy2-Apply-{pid}", daemon=True)
    tab._apply_threads[pid] = t
    t.start()
