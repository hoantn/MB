import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from ui2.tabs.strategy2.modules.manual_apply_flow import apply_manual_copy_style


BOTTOM = ["9C", "QB", "JB", "TC", "KT"]
MIDDLE = ["3C", "2R", "5T", "3R", "3B"]
TOP = ["QR", "AT", "KB"]
TARGET_LAYOUT = TOP + MIDDLE + BOTTOM
WS_LAYOUT = list(reversed(TARGET_LAYOUT))
SUGGESTION = {
    "mode": "money",
    "chi1_codes": BOTTOM,
    "chi2_codes": MIDDLE,
    "chi3_codes": TOP,
}


class _Signal:
    def emit(self, fn):
        fn()


class _BrowserManager:
    _slot = 1

    def get_active_tab(self, _pid):
        return object()


class _Tab:
    def __init__(self):
        self.browser_manager = _BrowserManager()
        self.ui_call = _Signal()
        self._manual_layout_codes = {"P1": list(WS_LAYOUT)}
        self._manual_apply_threads = {}
        self._manual_ws_freeze = {}
        self._manual_apply_busy = {}
        self._layout_codes = {"P1": list(TARGET_LAYOUT)}
        self.busy_calls = []
        self.default_calls = []
        self.refresh_calls = []

    def _manual_apply_btn_set_busy(self, pid):
        self.busy_calls.append(pid)
        self._manual_apply_busy[pid] = True

    def _manual_apply_btn_set_default(self, pid):
        self.default_calls.append(pid)
        self._manual_apply_busy[pid] = False

    def refresh_manual_slot_order(self, pid, *args, **kwargs):
        self.refresh_calls.append(pid)


def _load_config(_slot=1):
    return {
        "ui": {
            "apply": {
                "delay_between_drag_ms": 25,
                "drag_duration_ms": 60,
                "manual_second_pass_delay_ms": 0,
            }
        }
    }


def _run_manual(tab, side_effect=None):
    if side_effect is None:
        side_effect = lambda *_args, **_kwargs: list(TARGET_LAYOUT)

    with patch("ui2.tabs.strategy2.modules.manual_apply_flow.load_config", side_effect=_load_config):
        with patch("ui2.tabs.strategy2.modules.manual_apply_flow.apply_arrangement", side_effect=side_effect) as mock_apply:
            apply_manual_copy_style(tab, "P1", list(WS_LAYOUT), dict(SUGGESTION))
            worker = tab._manual_apply_threads.get("P1")
            if worker is not None:
                worker.join(timeout=2.0)
    return mock_apply


class ManualApplyFlowTests(unittest.TestCase):
    def test_copy_style_double_pass_uses_manual_layout_cache(self):
        tab = _Tab()
        bases = []

        def fake_apply(_pid, _manager, base_layout, *_args, **_kwargs):
            bases.append(list(base_layout))
            return list(TARGET_LAYOUT)

        mock_apply = _run_manual(tab, fake_apply)

        self.assertEqual(mock_apply.call_count, 2)
        self.assertEqual(bases, [WS_LAYOUT, TARGET_LAYOUT])
        self.assertEqual(tab._manual_layout_codes["P1"], TARGET_LAYOUT)
        self.assertTrue(tab._manual_layout_locked_after_apply["P1"])
        self.assertEqual(tab._layout_codes["P1"], TARGET_LAYOUT)
        self.assertEqual(tab.busy_calls, ["P1"])
        self.assertIn("P1", tab.default_calls)

    def test_manual_flow_uses_shared_apply_timing_config(self):
        tab = _Tab()
        kwargs_seen = []

        def fake_apply(*_args, **kwargs):
            kwargs_seen.append(dict(kwargs))
            return list(TARGET_LAYOUT)

        _run_manual(tab, fake_apply)

        self.assertEqual(len(kwargs_seen), 2)
        for kwargs in kwargs_seen:
            self.assertNotIn("use_fast_drag", kwargs)
            self.assertNotIn("use_exact", kwargs)
            self.assertEqual(kwargs.get("delay_s"), 0.025)
            self.assertIs(kwargs.get("use_copy_moves"), True)
            self.assertEqual(kwargs.get("drag_duration_s_override"), 0.06)
            self.assertIs(kwargs.get("validate_runtime"), False)

    def test_manual_state_isolated_from_auto_layout_cache(self):
        tab = _Tab()
        auto_layout_before = list(tab._layout_codes["P1"])
        tab._manual_layout_codes["P1"] = list(WS_LAYOUT)

        _run_manual(tab)

        self.assertEqual(tab._layout_codes["P1"], auto_layout_before)
        self.assertEqual(tab._manual_layout_codes["P1"], TARGET_LAYOUT)

    def test_manual_guard_blocks_second_click_while_thread_alive(self):
        tab = _Tab()
        started = threading.Event()
        can_finish = threading.Event()
        call_count = [0]

        def slow_apply(*_args, **_kwargs):
            call_count[0] += 1
            started.set()
            can_finish.wait(timeout=2.0)
            return list(TARGET_LAYOUT)

        with patch("ui2.tabs.strategy2.modules.manual_apply_flow.load_config", side_effect=_load_config):
            with patch("ui2.tabs.strategy2.modules.manual_apply_flow.apply_arrangement", side_effect=slow_apply):
                apply_manual_copy_style(tab, "P1", list(WS_LAYOUT), dict(SUGGESTION))
                self.assertTrue(started.wait(timeout=1.0))
                apply_manual_copy_style(tab, "P1", list(WS_LAYOUT), dict(SUGGESTION))
                can_finish.set()
                worker = tab._manual_apply_threads.get("P1")
                if worker is not None:
                    worker.join(timeout=2.0)

        self.assertEqual(call_count[0], 2)

    def test_apply_controller_routes_manual_to_isolated_module(self):
        from ui2.tabs.strategy2.modules.apply_controller import ApplyController

        tab = _Tab()
        tab._codes_slot_order = {"P1": list(WS_LAYOUT)}
        tab._suggestions_render = {"P1": [dict(SUGGESTION)]}
        tab._suggestions = {"P1": []}
        tab._selected_index = {"P1": 0}
        tab._is_special_row = MagicMock(return_value=False)
        tab.profiles = ["P1"]
        tab._prepare_manual_apply = MagicMock(return_value=True)

        with patch("ui2.tabs.strategy2.modules.apply_controller.apply_manual_copy_style") as routed:
            ApplyController().on_apply(tab, "P1")

        routed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
