import queue
import unittest
from types import SimpleNamespace

from ui2.tabs.strategy2.modules.staged_scheduler import StagedScheduler
from ui2.tabs.strategy2.strategy_tab import StrategyTab


class _Timer:
    def __init__(self):
        self.active = False
        self.starts = 0
        self.stops = 0

    def stop(self):
        self.stops += 1
        self.active = False

    def start(self):
        self.starts += 1
        self.active = True

    def isActive(self):
        return self.active


class _View:
    def __init__(self):
        self.calls = []

    def set_cards_ngu_normalized(self, codes):
        self.calls.append(("cards_ngu", list(codes or [])))

    def set_ngu_labels(self, items, selected_index):
        self.calls.append(("ngu_labels", list(items or []), selected_index))

    def set_ngu_status(self, text):
        self.calls.append(("ngu_status", text))

    def set_ngu_special_text(self, text, color):
        self.calls.append(("ngu_special", text, color))


class _Pipeline:
    def build_snapshot(self, *, codes_slot_order, ngu_codes13):
        snapshot = {
            pid: list(codes)
            for pid, codes in (codes_slot_order or {}).items()
            if len(codes or []) == 13
        }
        if ngu_codes13 and len(ngu_codes13) == 13:
            snapshot["NGU"] = list(ngu_codes13)
        ordered = []
        if "NGU" in snapshot:
            ordered.append("NGU")
        ordered.extend([pid for pid in ("P1", "P2", "P3") if pid in snapshot])
        return type("Snapshot", (), {"snapshot": snapshot, "ordered_keys": ordered})()


class _SchedulerTab:
    profiles = ["P1", "P2", "P3"]
    active_profile = "P1"
    MAX_UI_NGU_ITEMS = 3

    def __init__(self):
        self._pipeline = _Pipeline()
        self._codes_slot_order = {pid: [] for pid in self.profiles}
        self._ngu_base_codes = []
        self._ngu_key = None
        self._scheduled_hash = {pid: None for pid in self.profiles + ["NGU"]}
        self._q = queue.Queue()
        self._suggestions = {pid: [] for pid in self.profiles}
        self._suggestions_render = {pid: [] for pid in self.profiles}
        self._selected_index = {pid: 0 for pid in self.profiles}
        self._ngu_suggestions = []
        self._ngu_selected_index = 0
        self.view = object()

    def _hand_hash(self, codes):
        return "|".join(codes or [])

    def _derive_ngu_from_3p(self):
        raise AssertionError("NGU must not be derived while pending debounce")

    def _is_ngu_refresh_pending(self):
        return False

    def build_suggestions_for_codes(self, key, codes):
        return [{"mode": "money", "chi1_codes": codes[:5], "chi2_codes": codes[5:10], "chi3_codes": codes[10:]}]

    def _filter_extras(self, full):
        return list(full or [])


def _cards(prefix):
    ranks = "23456789TJQKA"
    return [f"{prefix}{rank}" for rank in ranks]


def _allow_ngu_room(tab, kind="external_opp"):
    tab._codes_slot_order = {pid: _cards(pid) for pid in tab.profiles}
    tab._current_room_context_safe = lambda: SimpleNamespace(kind=kind)


class NguRefreshDebounceTests(unittest.TestCase):
    def test_schedule_ngu_refresh_preserves_visible_opp_while_pending(self):
        tab = StrategyTab.__new__(StrategyTab)
        tab.profiles = ["P1", "P2", "P3"]
        tab._p_render_core_sig = {pid: "valid" for pid in tab.profiles}
        tab._ngu_render_last_input_sig = ("old",)
        tab._ngu_render_last_output_sig = ("old",)
        tab._ngu_render_cached_output = [{"mode": "old"}]
        tab._ngu_render_cached_selected_index = 4
        tab._ngu_base_codes = _cards("N")
        tab._ngu_key = "old"
        tab._ngu_suggestions = [{"mode": "old"}]
        tab._ngu_selected_index = 1
        tab._scheduled_hash = {"P1": None, "P2": None, "P3": None, "NGU": "old"}
        tab._ngu_refresh_pending = False
        tab._ngu_refresh_debounce = _Timer()
        tab.view = _View()
        _allow_ngu_room(tab)

        StrategyTab._schedule_ngu_refresh_from_3p(tab)

        self.assertTrue(tab._ngu_refresh_pending)
        self.assertTrue(tab._ngu_refresh_debounce.active)
        self.assertEqual(tab._ngu_refresh_debounce.starts, 1)
        self.assertEqual(tab._ngu_base_codes, [])
        self.assertIsNone(tab._ngu_key)
        self.assertEqual(tab._ngu_suggestions, [{"mode": "old"}])
        self.assertEqual(tab._ngu_selected_index, 1)
        self.assertEqual(tab._scheduled_hash["NGU"], None)
        self.assertEqual(set(tab._p_render_core_sig.values()), {None})
        self.assertNotIn(("cards_ngu", []), tab.view.calls)
        self.assertNotIn(("ngu_labels", [], 0), tab.view.calls)

    def test_schedule_ngu_refresh_clears_without_start_when_room_not_eligible(self):
        tab = StrategyTab.__new__(StrategyTab)
        tab.profiles = ["P1", "P2", "P3"]
        tab._p_render_core_sig = {pid: "valid" for pid in tab.profiles}
        tab._ngu_render_last_input_sig = ("old",)
        tab._ngu_render_last_output_sig = ("old",)
        tab._ngu_render_cached_output = [{"mode": "old"}]
        tab._ngu_render_cached_selected_index = 4
        tab._ngu_base_codes = _cards("N")
        tab._ngu_key = "old"
        tab._ngu_suggestions = [{"mode": "old"}]
        tab._ngu_selected_index = 1
        tab._scheduled_hash = {"P1": None, "P2": None, "P3": None, "NGU": "old"}
        tab._ngu_refresh_pending = False
        tab._ngu_refresh_debounce = _Timer()
        tab.view = _View()
        _allow_ngu_room(tab, kind="internal_2p")

        StrategyTab._schedule_ngu_refresh_from_3p(tab)

        self.assertFalse(tab._ngu_refresh_pending)
        self.assertFalse(tab._ngu_refresh_debounce.active)
        self.assertEqual(tab._ngu_refresh_debounce.starts, 0)
        self.assertEqual(tab._ngu_base_codes, [])
        self.assertIsNone(tab._ngu_key)
        self.assertEqual(tab._ngu_suggestions, [])

    def test_deferred_ngu_refresh_runs_original_refresh_then_missing_alert(self):
        tab = StrategyTab.__new__(StrategyTab)
        calls = []
        tab.profiles = ["P1", "P2", "P3"]
        tab._ngu_refresh_pending = True
        _allow_ngu_room(tab)
        tab._refresh_ngu_from_3p = lambda force: calls.append(("refresh", force))
        tab._schedule_missing_3p_alert = lambda: calls.append(("missing_alert",))

        StrategyTab._run_deferred_ngu_refresh_from_3p(tab)

        self.assertFalse(tab._ngu_refresh_pending)
        self.assertEqual(calls, [("refresh", True), ("missing_alert",)])

    def test_auto_waits_while_ngu_refresh_is_pending_even_without_ngu_key(self):
        tab = StrategyTab.__new__(StrategyTab)
        tab._ngu_refresh_pending = True
        tab._ngu_refresh_debounce = _Timer()
        tab._ngu_key = None
        tab._ngu_base_codes = []

        self.assertTrue(StrategyTab._auto_is_waiting_for_ngu_suggestions(tab))

    def test_room_gate_allows_external_and_internal_3p_only(self):
        tab = StrategyTab.__new__(StrategyTab)
        tab.profiles = ["P1", "P2", "P3"]
        tab._codes_slot_order = {pid: _cards(pid) for pid in tab.profiles}

        self.assertTrue(StrategyTab._should_allow_ngu_work(tab, SimpleNamespace(kind="external_opp")))
        self.assertTrue(StrategyTab._should_allow_ngu_work(tab, SimpleNamespace(kind="internal_3p")))
        self.assertFalse(StrategyTab._should_allow_ngu_work(tab, SimpleNamespace(kind="internal_2p")))
        self.assertFalse(StrategyTab._should_allow_ngu_work(tab, SimpleNamespace(kind="unknown")))

    def test_auto_hand_key_uses_ngu_only_for_eligible_room_contexts(self):
        tab = StrategyTab.__new__(StrategyTab)
        tab.profiles = ["P1", "P2", "P3"]
        tab._codes_slot_order = {pid: _cards(pid) for pid in tab.profiles}
        tab._suggestions = {pid: [{"mode": "money"}] for pid in tab.profiles}
        tab._auto_play_applied_profile_keys = set()
        tab._hand_generation = {pid: 1 for pid in tab.profiles}
        tab._ngu_key = "ngu-key"
        tab._ngu_base_codes = _cards("N")

        tab._current_room_context_safe = lambda: SimpleNamespace(kind="external_opp")
        self.assertTrue(StrategyTab._current_auto_play_hand_key(tab).startswith("NGU:ngu-key|"))

        tab._ngu_key = None
        tab._ngu_base_codes = []
        self.assertIsNone(StrategyTab._current_auto_play_hand_key(tab))

        tab._current_room_context_safe = lambda: SimpleNamespace(kind="internal_2p")
        self.assertTrue(StrategyTab._current_auto_play_hand_key(tab).startswith("ROOM:internal_2p|"))

    def test_scheduler_skips_ngu_derivation_while_pending(self):
        tab = _SchedulerTab()
        tab._codes_slot_order["P1"] = _cards("P1")
        tab._ngu_base_codes = _cards("N")
        tab._ngu_key = "old"
        tab._is_ngu_refresh_pending = lambda: True
        scheduler = StagedScheduler()
        scheduler.job_running = True

        scheduler.enqueue_batch_jobs(tab)

        self.assertEqual(tab._ngu_base_codes, _cards("N"))
        self.assertEqual(tab._ngu_key, "old")
        self.assertEqual([job[0] for job in scheduler.job_q], ["P1"])

    def test_ngu_uses_recent_hand_cohort_instead_of_equal_generation(self):
        tab = StrategyTab.__new__(StrategyTab)
        tab.profiles = ["P1", "P2", "P3"]
        tab._codes_slot_order = {pid: _cards(pid) for pid in tab.profiles}
        tab._hand_generation = {"P1": 8, "P2": 2, "P3": 5}
        tab._hand_seen_at = {"P1": 100.0, "P2": 105.0, "P3": 108.0}
        tab._current_room_context_safe = lambda: SimpleNamespace(kind="external_opp")

        self.assertTrue(StrategyTab._has_all_3p_cards(tab))
        self.assertTrue(StrategyTab._should_allow_ngu_work(tab))

        tab._hand_seen_at = {"P1": 100.0, "P2": 105.0, "P3": 160.5}

        self.assertFalse(StrategyTab._has_all_3p_cards(tab))
        self.assertFalse(StrategyTab._should_allow_ngu_work(tab))

    def test_scheduler_skips_ngu_when_room_gate_blocks_it(self):
        tab = _SchedulerTab()
        tab._codes_slot_order["P1"] = _cards("P1")
        tab._codes_slot_order["P2"] = _cards("P2")
        tab._codes_slot_order["P3"] = _cards("P3")
        tab._ngu_base_codes = _cards("N")
        tab._ngu_key = "old"
        tab._should_enqueue_ngu_jobs = lambda: False
        tab._clear_ngu_for_ineligible_room = lambda *_args, **_kwargs: (
            setattr(tab, "_ngu_base_codes", []),
            setattr(tab, "_ngu_key", None),
        )
        scheduler = StagedScheduler()
        scheduler.job_running = True

        scheduler.enqueue_batch_jobs(tab)

        self.assertEqual(tab._ngu_base_codes, [])
        self.assertIsNone(tab._ngu_key)
        self.assertEqual([job[0] for job in scheduler.job_q], ["P1", "P2", "P3"])

    def test_scheduler_enqueues_ngu_when_room_gate_allows_it(self):
        tab = _SchedulerTab()
        tab._codes_slot_order["P1"] = _cards("P1")
        tab._codes_slot_order["P2"] = _cards("P2")
        tab._codes_slot_order["P3"] = _cards("P3")
        tab._should_enqueue_ngu_jobs = lambda: True
        tab._derive_ngu_from_3p = lambda: _cards("N")
        scheduler = StagedScheduler()
        scheduler.job_running = True

        scheduler.enqueue_batch_jobs(tab)

        self.assertEqual([job[0] for job in scheduler.job_q], ["NGU", "P1", "P2", "P3"])

    def test_scheduler_discards_stale_worker_result_by_hash(self):
        tab = _SchedulerTab()
        old_cards = _cards("OLD")
        tab._codes_slot_order["P1"] = _cards("NEW")
        old_hash = tab._hand_hash(old_cards)
        tab._scheduled_hash["P1"] = old_hash
        scheduler = StagedScheduler()
        scheduler.job_running = True
        tab._q.put(
            (
                "P1",
                None,
                [{"mode": "old", "chi1_codes": old_cards[:5], "chi2_codes": old_cards[5:10], "chi3_codes": old_cards[10:]}],
                None,
                "EXTRA",
                "ALL",
                old_hash,
            )
        )

        scheduler.poll_suggest_results(tab)

        self.assertEqual(tab._suggestions["P1"], [])
        self.assertIsNone(tab._scheduled_hash["P1"])
        self.assertFalse(scheduler.job_running)

    def test_scheduler_discards_ngu_result_when_room_gate_blocks_it(self):
        tab = _SchedulerTab()
        ngu_cards = _cards("N")
        h = tab._hand_hash(ngu_cards)
        tab._ngu_base_codes = list(ngu_cards)
        tab._scheduled_hash["NGU"] = h
        tab._should_enqueue_ngu_jobs = lambda: False
        tab._clear_ngu_for_ineligible_room = lambda *_args, **_kwargs: (
            setattr(tab, "_ngu_base_codes", []),
            setattr(tab, "_ngu_key", None),
            setattr(tab, "_ngu_suggestions", []),
        )
        scheduler = StagedScheduler()
        scheduler.job_running = True
        tab._q.put(
            (
                "NGU",
                None,
                [{"mode": "money", "chi1_codes": ngu_cards[:5], "chi2_codes": ngu_cards[5:10], "chi3_codes": ngu_cards[10:]}],
                None,
                "EXTRA",
                "ALL",
                h,
            )
        )

        scheduler.poll_suggest_results(tab)

        self.assertEqual(tab._ngu_suggestions, [])
        self.assertIsNone(tab._scheduled_hash["NGU"])
        self.assertFalse(scheduler.job_running)


if __name__ == "__main__":
    unittest.main()
