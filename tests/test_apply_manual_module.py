import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ui2.tabs.strategy2.modules.apply_manual import apply_manual_dashboard_style


BOTTOM = ["9C", "QB", "JB", "TC", "KT"]
MIDDLE = ["3C", "2R", "5T", "3R", "3B"]
TOP = ["QR", "AT", "KB"]
TARGET_LAYOUT = TOP + MIDDLE + BOTTOM
WS_LAYOUT = list(reversed(TARGET_LAYOUT))
REAL_606_LAYOUT = [
    "AT",
    "QR",
    "KB",
    "2R",
    "3C",
    "5T",
    "3R",
    "3B",
    "9C",
    "QB",
    "JB",
    "TC",
    "KT",
]
BAD_606_LAYOUT = [
    "2R",
    "QR",
    "KB",
    "AT",
    "3C",
    "5T",
    "3R",
    "3B",
    "9C",
    "QB",
    "JB",
    "TC",
    "KT",
]
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
    def __init__(self, layout_store):
        self.browser_manager = _BrowserManager()
        self.ui_call = _Signal()
        self._layout_codes = {}
        self._layout_uncertain = {}
        self._apply_threads = {}
        self._ws_freeze = {}
        self._layout_store = layout_store

    def _apply_btn_set_busy(self, _pid):
        return None

    def _apply_btn_set_default(self, _pid):
        return None


class _LayoutStore:
    def __init__(self, snapshot=None, snapshots=None):
        if snapshots is not None:
            self.snapshots = list(snapshots)
        elif snapshot is not None:
            self.snapshots = [snapshot]
        else:
            self.snapshots = []

    def latest_sequence(self, _pid):
        return 1

    def hand_generation(self, _pid):
        return 1

    def wait_for_newer(self, *_args, **_kwargs):
        if self.snapshots:
            return self.snapshots.pop(0)
        return None


def _load_config(_slot=1):
    return {
        "ui": {
            "apply": {
                "delay_between_drag_ms": 0,
                "manual_second_pass_delay_ms": 50,
            }
        }
    }


class ApplyManualModuleTests(unittest.TestCase):
    def _run_apply(self, tab):
        with patch("ui2.tabs.strategy2.modules.apply_manual.load_config", side_effect=_load_config):
            with patch("ui2.tabs.strategy2.modules.apply_manual.acquire_profile_action", return_value=object()):
                with patch("ui2.tabs.strategy2.modules.apply_manual.release_profile_action"):
                    with patch("ui2.tabs.strategy2.modules.apply_manual._acquire_apply_lock", return_value=True):
                        with patch("ui2.tabs.strategy2.modules.apply_manual._release_apply_lock"):
                            apply_manual_dashboard_style(tab, "P1", list(WS_LAYOUT), dict(SUGGESTION))

        deadline = time.time() + 2.5
        while time.time() < deadline:
            worker = tab._apply_threads.get("P1")
            if worker is None:
                return
            worker.join(0.02)
        self.fail("manual apply worker did not finish")

    def test_no_cmd606_still_runs_second_pass_from_predicted_layout(self):
        tab = _Tab(_LayoutStore(snapshot=None))
        bases = []

        def fake_apply(_pid, _manager, base_layout, *_args, **_kwargs):
            bases.append(list(base_layout))
            return list(TARGET_LAYOUT)

        with patch("ui2.tabs.strategy2.modules.apply_manual.apply_arrangement", side_effect=fake_apply):
            self._run_apply(tab)

        self.assertEqual(bases, [WS_LAYOUT, TARGET_LAYOUT])
        self.assertEqual(tab._layout_codes["P1"], TARGET_LAYOUT)
        self.assertTrue(tab._layout_uncertain["P1"])
        self.assertFalse(tab._ws_freeze["P1"])

    def test_fresh_cmd606_target_confirms_layout_after_second_pass(self):
        snapshot = SimpleNamespace(sequence=2, cards=list(TARGET_LAYOUT))
        tab = _Tab(_LayoutStore(snapshot=snapshot))
        bases = []

        def fake_apply(_pid, _manager, base_layout, *_args, **_kwargs):
            bases.append(list(base_layout))
            return list(TARGET_LAYOUT)

        with patch("ui2.tabs.strategy2.modules.apply_manual.apply_arrangement", side_effect=fake_apply):
            self._run_apply(tab)

        self.assertEqual(bases, [WS_LAYOUT, TARGET_LAYOUT])
        self.assertEqual(tab._layout_codes["P1"], TARGET_LAYOUT)
        self.assertFalse(tab._layout_uncertain)
        self.assertFalse(tab._ws_freeze["P1"])

    def test_fresh_cmd606_mismatch_without_confirm_leaves_layout_uncertain(self):
        mismatch = SimpleNamespace(sequence=2, cards=list(BAD_606_LAYOUT))
        tab = _Tab(_LayoutStore(snapshot=mismatch))
        bases = []

        def fake_apply(_pid, _manager, base_layout, *_args, **_kwargs):
            bases.append(list(base_layout))
            return list(TARGET_LAYOUT)

        with patch("ui2.tabs.strategy2.modules.apply_manual.apply_arrangement", side_effect=fake_apply):
            self._run_apply(tab)

        self.assertEqual(bases, [WS_LAYOUT, TARGET_LAYOUT, BAD_606_LAYOUT])
        self.assertEqual(tab._layout_codes["P1"], TARGET_LAYOUT)
        self.assertTrue(tab._layout_uncertain["P1"])
        self.assertFalse(tab._ws_freeze["P1"])

    def test_real_cmd606_mismatch_triggers_repair_from_actual_layout(self):
        confirmed = SimpleNamespace(sequence=3, cards=list(TARGET_LAYOUT))
        mismatch = SimpleNamespace(sequence=2, cards=list(BAD_606_LAYOUT))
        tab = _Tab(_LayoutStore(snapshots=[mismatch, confirmed]))
        bases = []

        def fake_apply(_pid, _manager, base_layout, *_args, **_kwargs):
            bases.append(list(base_layout))
            return list(TARGET_LAYOUT)

        with patch("ui2.tabs.strategy2.modules.apply_manual.apply_arrangement", side_effect=fake_apply):
            self._run_apply(tab)

        self.assertEqual(bases, [WS_LAYOUT, TARGET_LAYOUT, BAD_606_LAYOUT])
        self.assertEqual(tab._layout_codes["P1"], TARGET_LAYOUT)
        self.assertFalse(tab._layout_uncertain)
        self.assertFalse(tab._ws_freeze["P1"])


if __name__ == "__main__":
    unittest.main()
