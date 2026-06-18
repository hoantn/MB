import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ui2.tabs.strategy2.strategy_tab import StrategyTab


class _Timer:
    def stop(self):
        return None

    def start(self):
        return None


class _View:
    def __init__(self):
        self.cards = []
        self.status = []

    def set_cards_p_normalized(self, codes):
        self.cards.append(list(codes))

    def set_p_status(self, text):
        self.status.append(str(text))


class _Signal:
    def emit(self, fn):
        fn()


class StrategyLayoutStateTests(unittest.TestCase):
    def _tab(self):
        tab = StrategyTab.__new__(StrategyTab)
        tab.profiles = ["P1", "P2", "P3"]
        tab.active_profile = "P1"
        tab.view = _View()
        tab._pending_ws_reset = {}
        tab._pending_ws_samehand = {}
        tab._layout_uncertain = {}
        tab._layout_codes = {}
        tab._manual_layout_codes = {}
        tab._manual_layout_locked_after_apply = {}
        tab._manual_apply_epoch = {}
        tab._codes_slot_order = {}
        tab._hand_generation = {}
        tab._last_hand_hash = {}
        tab._manual_pending_ws_reset = {}
        tab._manual_pending_ws_samehand = {}
        tab._batch_debounce = _Timer()
        tab._schedule_missing_3p_alert = lambda: None
        tab._force_reset_pid_state = lambda _pid: None
        tab._hand_hash = lambda codes: "|".join(sorted(map(str, codes)))
        tab._suggestions_render = {}
        tab._suggestions = {}
        tab._render_p_active = lambda: None
        tab.ui_call = _Signal()
        return tab

    def test_pending_cmd600_reset_clears_uncertain_layout(self):
        tab = self._tab()
        cards = [f"C{i}" for i in range(13)]
        tab._layout_uncertain["P1"] = True
        tab._pending_ws_reset["P1"] = list(cards)

        StrategyTab._apply_pending_ws_reset_if_any(tab, "P1")

        self.assertEqual(tab._codes_slot_order["P1"], cards)
        self.assertEqual(tab._layout_codes["P1"], cards)
        self.assertNotIn("P1", tab._layout_uncertain)

    def test_samehand_layout_sync_clears_uncertain_without_changing_original_hand(self):
        tab = self._tab()
        original = [f"C{i}" for i in range(13)]
        layout = list(reversed(original))
        tab._codes_slot_order["P1"] = list(original)
        tab._layout_uncertain["P1"] = True
        tab._pending_ws_samehand["P1"] = list(layout)

        StrategyTab._apply_pending_ws_samehand_if_any(tab, "P1")

        self.assertEqual(tab._codes_slot_order["P1"], original)
        self.assertEqual(tab._layout_codes["P1"], layout)
        self.assertNotIn("P1", tab._layout_uncertain)

    def test_manual_refresh_scan_updates_only_manual_layout_cache(self):
        tab = self._tab()
        original = [f"C{i}" for i in range(13)]
        scanned = list(reversed(original))
        auto_layout = list(original)
        tab.capture_manager = object()
        tab._codes_slot_order["P1"] = list(original)
        tab._layout_codes["P1"] = list(auto_layout)
        tab._manual_layout_codes = {}

        with patch(
            "ui2.tabs.strategy2.modules.layout_verifier.scan_layout_fresh",
            return_value=SimpleNamespace(codes=list(scanned)),
        ):
            StrategyTab.refresh_manual_slot_order(tab, "P1")
            worker = tab._manual_scan_threads.get("P1")
            if worker is not None:
                worker.join(timeout=2.0)

        self.assertEqual(tab._manual_layout_codes["P1"], scanned)
        self.assertEqual(tab._layout_codes["P1"], auto_layout)

    def test_locked_manual_layout_ignores_samehand_ws_cache(self):
        tab = self._tab()
        original = [f"C{i}" for i in range(13)]
        predicted = list(reversed(original))
        stale_samehand = original[1:] + original[:1]
        tab._manual_layout_codes["P1"] = list(predicted)
        tab._manual_layout_locked_after_apply["P1"] = True
        tab._pending_ws_samehand["P1"] = list(stale_samehand)

        StrategyTab._apply_pending_ws_samehand_if_any(tab, "P1")

        self.assertEqual(tab._layout_codes["P1"], stale_samehand)
        self.assertEqual(tab._manual_layout_codes["P1"], predicted)

    def test_locked_manual_pending_samehand_is_discarded(self):
        tab = self._tab()
        predicted = [f"C{i}" for i in range(13)]
        stale_samehand = list(reversed(predicted))
        tab._manual_layout_codes["P1"] = list(predicted)
        tab._manual_layout_locked_after_apply["P1"] = True
        tab._manual_pending_ws_samehand["P1"] = list(stale_samehand)

        StrategyTab._apply_manual_pending_ws_samehand_if_any(tab, "P1")

        self.assertEqual(tab._manual_layout_codes["P1"], predicted)
        self.assertNotIn("P1", tab._manual_pending_ws_samehand)

    def test_manual_refresh_stale_apply_epoch_does_not_overwrite_cache(self):
        tab = self._tab()
        original = [f"C{i}" for i in range(13)]
        predicted = list(original)
        scanned = list(reversed(original))
        tab.capture_manager = object()
        tab._codes_slot_order["P1"] = list(original)
        tab._manual_layout_codes["P1"] = list(predicted)
        tab._manual_apply_epoch["P1"] = 2

        with patch(
            "ui2.tabs.strategy2.modules.layout_verifier.scan_layout_fresh",
            return_value=SimpleNamespace(codes=list(scanned)),
        ):
            StrategyTab.refresh_manual_slot_order(tab, "P1", apply_epoch=1)
            worker = tab._manual_scan_threads.get("P1")
            if worker is not None:
                worker.join(timeout=2.0)

        self.assertEqual(tab._manual_layout_codes["P1"], predicted)

    def test_manual_refresh_does_not_fallback_to_layout_store_snapshot(self):
        tab = self._tab()
        original = [f"C{i}" for i in range(13)]
        predicted = list(original)
        snapshot_codes = list(reversed(original))
        tab.capture_manager = object()
        tab._codes_slot_order["P1"] = list(original)
        tab._manual_layout_codes["P1"] = list(predicted)
        tab._layout_store = SimpleNamespace(latest_snapshot=lambda _pid: SimpleNamespace(cards=list(snapshot_codes)))

        with patch(
            "ui2.tabs.strategy2.modules.layout_verifier.scan_layout_fresh",
            return_value=SimpleNamespace(codes=[]),
        ):
            StrategyTab.refresh_manual_slot_order(tab, "P1")
            worker = tab._manual_scan_threads.get("P1")
            if worker is not None:
                worker.join(timeout=2.0)

        self.assertEqual(tab._manual_layout_codes["P1"], predicted)


if __name__ == "__main__":
    unittest.main()
