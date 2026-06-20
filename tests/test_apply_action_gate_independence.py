import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ui2.tabs.strategy2.modules.apply_auto import apply_suggestion_dashboard_style


BOTTOM = ["9C", "QB", "JB", "TC", "KT"]
MIDDLE = ["3C", "2R", "5T", "3R", "3B"]
TOP = ["QR", "AT", "KB"]
EXPECTED_LAYOUT = TOP + MIDDLE + BOTTOM
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
    _slot = 91

    def get_active_tab(self, _pid):
        return object()


class _BlockingActionGate:
    def try_acquire(self, *_args, **_kwargs):
        raise AssertionError("apply must not use ToolActionGate")


class _LayoutStore:
    def latest_sequence(self, _pid):
        return 1

    def hand_generation(self, _pid):
        return 1

    def wait_for_newer(self, *_args, **_kwargs):
        return None


class _Tab:
    def __init__(self):
        self.browser_manager = _BrowserManager()
        self.ui_call = _Signal()
        self._action_gate = _BlockingActionGate()
        self._layout_store = _LayoutStore()
        self._layout_codes = {}
        self._apply_threads = {}
        self._ws_freeze = {}
        self._confirmed_apply_tokens = {}
        self.busy = []
        self.default = []

    def _apply_btn_set_busy(self, pid):
        self.busy.append(pid)

    def _apply_btn_set_default(self, pid):
        self.default.append(pid)


class _AliveThread:
    def is_alive(self):
        return True


def _load_config(_slot=1):
    return {
        "ui": {
            "apply": {
                "delay_between_drag_ms": 0,
                "double_pass": False,
                "layout606_timeout_retry_count": 0,
                "layout606_timeout_retry_ms": 1,
            }
        }
    }


class ApplyActionGateIndependenceTests(unittest.TestCase):
    def _wait_worker(self, tab):
        deadline = time.time() + 1.0
        while time.time() < deadline:
            worker = tab._apply_threads.get("P1")
            if worker is None:
                return
            worker.join(0.02)
        self.fail("apply worker did not finish")

    def test_auto_apply_ignores_busy_tool_action_gate(self):
        tab = _Tab()
        confirmation = SimpleNamespace(
            confirmed=True,
            layout=list(EXPECTED_LAYOUT),
            snapshot=None,
            reason="confirmed",
            repair_attempts=0,
        )

        with patch("ui2.tabs.strategy2.modules.apply_auto.load_config", side_effect=_load_config):
            with patch(
                "ui2.tabs.strategy2.modules.apply_auto.apply_arrangement",
                return_value=list(EXPECTED_LAYOUT),
            ):
                with patch(
                    "ui2.tabs.strategy2.modules.apply_auto.confirm_and_repair_layout",
                    return_value=confirmation,
                ):
                    spawned = apply_suggestion_dashboard_style(
                        tab,
                        "P1",
                        list(EXPECTED_LAYOUT),
                        dict(SUGGESTION),
                    )
                    self.assertTrue(spawned)
                    self._wait_worker(tab)

        self.assertTrue(tab.busy)
        self.assertTrue(tab.default)
        self.assertEqual(tab._layout_codes["P1"], EXPECTED_LAYOUT)

    def test_auto_apply_still_rejects_same_profile_apply_thread(self):
        tab = _Tab()
        tab._apply_threads["P1"] = _AliveThread()

        spawned = apply_suggestion_dashboard_style(
            tab,
            "P1",
            list(EXPECTED_LAYOUT),
            dict(SUGGESTION),
        )

        self.assertFalse(spawned)


if __name__ == "__main__":
    unittest.main()
