"""
Tests cho luồng thủ công apply_manual_dashboard_style và mouse_drag.

Kiểm tra:
- mouse_drag default fire-and-forget (không chờ Chrome ACK)
- mouse_drag wait_ack=True gọi recv() đúng cách
- Manual worker gọi apply_arrangement đúng 2 lần (LẦN 1 + FORCE-APPLY2)
- WS FREEZE chỉ bao LẦN 1, unfreeze trước FORCE-APPLY2
- Thread được pop khỏi _apply_threads trong finally (kể cả khi lỗi)
- Guard block click thứ 2 khi thread đang chạy
"""
import json
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from engine.card import Card

# ── Layout dùng cho tất cả tests ───────────────────────────────────────────

BOTTOM = ["9C", "QB", "JB", "TC", "KT"]
MIDDLE = ["3C", "2R", "5T", "3R", "3B"]
TOP    = ["QR", "AT", "KB"]
SLOT_LAYOUT = TOP + MIDDLE + BOTTOM   # 13 lá, đúng thứ tự slot 1–13


def _make_cards(codes):
    cards = []
    for code in codes:
        c = MagicMock(spec=Card)
        c.code = code
        str(c)  # warm up mock
        cards.append(c)
    return cards


WS_CODES = list(SLOT_LAYOUT)
SUGGESTION = {
    "chi1_codes": BOTTOM,
    "chi2_codes": MIDDLE,
    "chi3_codes": TOP,
}

# ── Helpers cho fake Tab / WebSocket ───────────────────────────────────────

class _Signal:
    """Thực thi fn() đồng bộ; nuốt lỗi QTimer (không có Qt trong tests)."""
    def emit(self, fn):
        try:
            fn()
        except Exception:
            pass


class _Tab:
    def __init__(self):
        self.ui_call = _Signal()
        self.browser_manager = MagicMock()
        self._layout_codes = {"P1": list(SLOT_LAYOUT)}
        self._apply_threads = {}
        self._ws_freeze = {}
        self._confirmed_apply_tokens = {}
        self.busy_calls = []
        self.default_calls = []
        self.scan_calls = []

    def _apply_btn_set_busy(self, pid):
        self.busy_calls.append(pid)

    def _apply_btn_set_default(self, pid):
        self.default_calls.append(pid)

    def refresh_slot_order_by_scan(self, pid):
        self.scan_calls.append(pid)
        # Thay đổi layout để scan poll thoát ngay vòng đầu
        self._layout_codes[pid] = list(reversed(SLOT_LAYOUT))


def _run_manual(tab, pid, apply_side_effect=None, join_timeout=10.0):
    """Chạy apply_manual_dashboard_style và chờ thread xong."""
    from ui2.tabs.strategy2.strategy_suggest import apply_manual_dashboard_style

    if apply_side_effect is None:
        apply_side_effect = lambda *a, **kw: list(SLOT_LAYOUT)

    with patch("ui2.tabs.strategy2.strategy_suggest.apply_arrangement",
               side_effect=apply_side_effect) as mock_apply, \
         patch("ui2.tabs.strategy2.strategy_suggest.time") as mock_time:

        mock_time.sleep = lambda s: None   # không chờ thật (kể cả sleep(0.25))
        mock_time.time = time.time         # giữ time.time() thật để poll thoát đúng

        apply_manual_dashboard_style(tab, pid, WS_CODES, SUGGESTION)

        t = tab._apply_threads.get(pid)
        if t is not None:
            t.join(timeout=join_timeout)

    return mock_apply


# ── Tests mouse_drag fire-and-forget vs wait_ack ───────────────────────────

class MouseDragDispatchTests(unittest.TestCase):

    def _make_client(self, ws):
        from browser.devtools import DevToolsClient
        client = DevToolsClient("P1", 9222)
        client._open_ws = lambda: ws
        return client

    def test_default_fire_and_forget_never_calls_recv(self):
        """mouse_drag() mặc định → bắn event không chờ Chrome ACK."""

        class _NoRecvWS:
            def __init__(self):
                self.sent = []
            def send(self, payload):
                self.sent.append(json.loads(payload))
            def recv(self):
                raise AssertionError("recv() không được gọi ở fire-and-forget mode")
            def close(self):
                pass

        ws = _NoRecvWS()
        client = self._make_client(ws)
        client.mouse_drag(100, 200, 300, 400)   # wait_ack=False by default

        # Các events CDP đã được gửi đi
        methods = [m["method"] for m in ws.sent]
        self.assertIn("Page.enable", methods)
        self.assertIn("Input.dispatchMouseEvent", methods)

    def test_steps_18_produces_21_events(self):
        """steps=18 → 1 move + 1 press + 17 mid + 1 final + 1 release = 21 events."""

        class _CountWS:
            def __init__(self):
                self.sent = []
            def send(self, p):
                msg = json.loads(p)
                if msg.get("method") == "Input.dispatchMouseEvent":
                    self.sent.append(msg)
            def close(self):
                pass

        ws = _CountWS()
        client = self._make_client(ws)
        client.mouse_drag(0, 0, 100, 100)   # default steps=18

        # 1 move + 1 press + (18-1)=17 mid + 1 final + 1 release = 21
        self.assertEqual(len(ws.sent), 21)

    def test_wait_ack_true_calls_recv(self):
        """mouse_drag(wait_ack=True) → chờ Chrome ACK mỗi event."""

        class _AckWS:
            def __init__(self):
                self._buf = []
                self.recv_called = False
            def send(self, p):
                self._buf.append(json.loads(p))
            def recv(self):
                self.recv_called = True
                msg = self._buf.pop(0)
                return json.dumps({"id": msg["id"], "result": {}})
            def close(self):
                pass

        ws = _AckWS()
        client = self._make_client(ws)
        client.mouse_drag(0, 0, 100, 100, wait_ack=True)

        self.assertTrue(ws.recv_called, "recv() phải được gọi khi wait_ack=True")
        self.assertEqual(ws._buf, [], "Mọi message phải được ACK hết")


# ── Tests manual worker flow ───────────────────────────────────────────────

class ManualWorkerFlowTests(unittest.TestCase):

    def test_apply_arrangement_called_twice(self):
        """LẦN 1 + FORCE-APPLY2 đều được gọi."""
        tab = _Tab()
        mock = _run_manual(tab, "P1")
        self.assertEqual(mock.call_count, 2,
                         f"Expect 2 calls (LẦN 1 + FORCE-APPLY2), got {mock.call_count}")

    def test_ws_freeze_true_during_lam1_false_during_apply2(self):
        """WS FREEZE bật trong LẦN 1, tắt trước FORCE-APPLY2."""
        tab = _Tab()
        freeze_states = []

        def track(*a, **kw):
            freeze_states.append(tab._ws_freeze.get("P1"))
            return list(SLOT_LAYOUT)

        _run_manual(tab, "P1", apply_side_effect=track)

        self.assertEqual(len(freeze_states), 2, "Cần đúng 2 lần gọi apply_arrangement")
        self.assertTrue(freeze_states[0],  "LẦN 1: _ws_freeze phải là True")
        self.assertFalse(freeze_states[1], "FORCE-APPLY2: _ws_freeze phải là False")

    def test_ws_freeze_reset_to_false_after_complete(self):
        """WS FREEZE luôn được reset False trong finally."""
        tab = _Tab()
        _run_manual(tab, "P1")
        self.assertFalse(tab._ws_freeze.get("P1", False))

    def test_ws_freeze_reset_even_on_lam1_error(self):
        """WS FREEZE được reset dù LẦN 1 ném exception."""
        tab = _Tab()

        def always_fail(*a, **kw):
            raise RuntimeError("simulated drag error")

        _run_manual(tab, "P1", apply_side_effect=always_fail)
        self.assertFalse(tab._ws_freeze.get("P1", False))

    def test_thread_cleaned_up_after_complete(self):
        """_apply_threads[pid] được pop sau khi hoàn tất bình thường."""
        tab = _Tab()
        _run_manual(tab, "P1")
        self.assertNotIn("P1", tab._apply_threads)

    def test_thread_cleaned_up_on_lam1_error(self):
        """_apply_threads[pid] được pop kể cả khi LẦN 1 raise."""
        tab = _Tab()

        def always_fail(*a, **kw):
            raise RuntimeError("simulated error")

        _run_manual(tab, "P1", apply_side_effect=always_fail)
        self.assertNotIn("P1", tab._apply_threads)

    def test_thread_cleaned_up_on_apply2_error(self):
        """_apply_threads[pid] được pop kể cả khi FORCE-APPLY2 raise."""
        tab = _Tab()
        call_n = [0]

        def fail_on_second(*a, **kw):
            call_n[0] += 1
            if call_n[0] >= 2:
                raise RuntimeError("apply2 error")
            return list(SLOT_LAYOUT)

        _run_manual(tab, "P1", apply_side_effect=fail_on_second)
        self.assertNotIn("P1", tab._apply_threads)

    def test_guard_blocks_second_click_while_alive(self):
        """Click thứ 2 không spawn thread mới khi thread cũ đang chạy."""
        from ui2.tabs.strategy2.strategy_suggest import apply_manual_dashboard_style

        tab = _Tab()
        started = threading.Event()
        can_finish = threading.Event()
        call_n = [0]

        def slow_apply(*a, **kw):
            call_n[0] += 1
            started.set()
            can_finish.wait(timeout=5.0)
            return list(SLOT_LAYOUT)

        with patch("ui2.tabs.strategy2.strategy_suggest.apply_arrangement",
                   side_effect=slow_apply), \
             patch("ui2.tabs.strategy2.strategy_suggest.time") as mock_time:

            mock_time.sleep = lambda s: None
            mock_time.time = time.time

            # Click 1: thread chạy, block tại LẦN 1
            apply_manual_dashboard_style(tab, "P1", WS_CODES, SUGGESTION)
            started.wait(timeout=5.0)

            # Click 2: phải bị block (thread P1 vẫn alive)
            apply_manual_dashboard_style(tab, "P1", WS_CODES, SUGGESTION)

            # Cho thread 1 chạy tiếp
            can_finish.set()
            t = tab._apply_threads.get("P1")
            if t:
                t.join(timeout=5.0)

        # Click 2 bị block → chỉ có đúng 2 calls (LẦN 1 + FORCE-APPLY2 từ click 1)
        self.assertEqual(call_n[0], 2,
                         f"Expect 2 calls (click 2 bị block), got {call_n[0]}")

    def test_force_apply2_uses_layout_from_lam1_result(self):
        """FORCE-APPLY2 dùng layout từ kết quả LẦN 1 (hoặc cache)."""
        tab = _Tab()
        layouts_passed = []

        def track_current(*a, **kw):
            # Arg thứ 3 là current_codes
            layouts_passed.append(list(a[2]))
            return list(SLOT_LAYOUT)

        _run_manual(tab, "P1", apply_side_effect=track_current)

        self.assertEqual(len(layouts_passed), 2)
        # FORCE-APPLY2 nhận layout từ cache sau LẦN 1, không phải ws_codes raw
        self.assertEqual(layouts_passed[1], list(SLOT_LAYOUT))

    def test_lam1_and_apply2_both_chi_based(self):
        """LẦN 1 và FORCE-APPLY2 đều chi-based: không use_exact, không use_fast_drag."""
        tab = _Tab()
        kwargs_list = []

        def capture(*a, **kw):
            kwargs_list.append(dict(kw))
            return list(SLOT_LAYOUT)

        _run_manual(tab, "P1", apply_side_effect=capture)

        self.assertEqual(len(kwargs_list), 2)
        for i, name in enumerate(["LẦN 1", "FORCE-APPLY2"]):
            self.assertNotIn("use_exact", kwargs_list[i],
                             f"{name} không được truyền use_exact")
            self.assertNotIn("use_fast_drag", kwargs_list[i],
                             f"{name} không được truyền use_fast_drag")


if __name__ == "__main__":
    unittest.main()
