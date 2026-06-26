import unittest
from collections import deque

from ui2.tabs.strategy2.modules.auto_play_controller import (
    build_money_fallback_plan,
    classify_hand_start_room_context,
)
from ui2.tabs.strategy2 import strategy_tab as strategy_tab_module
from ui2.tabs.strategy2.modules.auto_play_controller import AutoRoomContext
from ui2.tabs.strategy2.strategy_tab import StrategyTab


PROFILES = ["P1", "P2", "P3"]


def _cards(prefix):
    return [f"{prefix}{i}" for i in range(13)]


def _make_tab():
    tab = StrategyTab.__new__(StrategyTab)
    tab.profiles = list(PROFILES)
    tab._codes_slot_order = {pid: _cards(pid) for pid in PROFILES}
    tab._layout_codes = {pid: _cards(pid) for pid in PROFILES}
    tab._manual_layout_codes = {pid: _cards(pid) for pid in PROFILES}
    tab._ws_snapshot = {pid: _cards(pid) for pid in PROFILES}
    tab._last_hand_hash = {pid: "|".join(_cards(pid)) for pid in PROFILES}
    tab._hand_generation = {pid: 1 for pid in PROFILES}
    tab._hand_seen_at = {pid: 100.0 for pid in PROFILES}
    tab._profile_waiting_new_hand_after_room_change = {pid: False for pid in PROFILES}
    tab._hand_hash = lambda codes: "|".join(map(str, codes or []))
    money_row = {
        "mode": "money",
        "_auto_profile_money": True,
        "chi1_codes": ["A1", "A2", "A3", "A4", "A5"],
        "chi2_codes": ["B1", "B2", "B3", "B4", "B5"],
        "chi3_codes": ["C1", "C2", "C3"],
    }
    tab._suggestions = {pid: [dict(money_row)] for pid in PROFILES}
    tab._suggestions_render = {pid: [] for pid in PROFILES}
    tab._selected_index = {pid: 0 for pid in PROFILES}
    tab._auto_play_applied_profile_keys = set()
    tab._auto_play_reservations = {}
    tab._auto_apply_unsafe_retry_counts = {}
    tab._auto_play_session = 1
    tab._auto_play_hand_key = None
    tab._auto_play_pending_key = None
    tab._auto_opp_plan_inflight = None
    tab._auto_opp_plan_force_sync_key = None
    tab._ngu_refresh_pending = False
    tab._ngu_refresh_debounce = None
    tab._ngu_key = "ngu-key"
    tab._ngu_base_codes = _cards("N")
    tab._ngu_pending_cohort_key = None
    tab._ngu_ready_cohort_key = None
    tab._sap_lang_combo = None
    tab._hand_room_context_by_profile = {pid: _ctx("internal_3p", ("U1", "U2", "U3")) for pid in PROFILES}
    tab._scheduled_hash = {pid: None for pid in PROFILES}
    tab._scheduled_hash["NGU"] = None
    tab._confirmed_apply_tokens = {}
    tab._pending_ws_reset = {}
    tab._pending_ws_samehand = {}
    tab._pending_ws_reset_context = {}
    tab._manual_pending_ws_reset = {}
    tab._manual_pending_ws_samehand = {}
    tab._manual_pending_ws_reset_context = {}
    tab._pre_render_pending = {}
    tab._pre_render_inflight = {}
    tab._pre_render_queue = deque()
    tab._p_render_core_sig = {pid: None for pid in PROFILES}
    tab._ngu_render_last_input_sig = None
    tab._ngu_render_last_output_sig = None
    tab._ngu_render_cached_output = []
    tab._ngu_render_cached_selected_index = 0
    tab._auto_play_log = lambda _text: None
    tab._is_special_row = lambda _s: False
    tab.active_profile = "P2"

    class _DummyStore:
        def __init__(self):
            self.cleared = []

        def clear_profile(self, pid):
            self.cleared.append(str(pid))

    class _DummyView:
        def set_break_sap_lang_available(self, *_args):
            pass

    tab._card_store = _DummyStore()
    tab._layout_store = _DummyStore()
    tab.view = _DummyView()
    return tab


def _ctx(kind, roster, controlled=tuple(PROFILES), external=()):
    return AutoRoomContext(
        kind=kind,
        roster=tuple(roster),
        controlled_pids=tuple(controlled),
        external_uids=tuple(external),
        gold_by_pid={pid: 1000 for pid in PROFILES},
    )


class _SingleRosterEngine:
    def get_room_monitor_state(self, pid):
        uid_by_pid = {"P1": "U1", "P2": "U2", "P3": "U3"}
        return {
            "room_uids": ["U1", "U2", "U3", "OPP"] if pid == "P1" else [],
            "roster_fresh": True,
            "profiles": {
                profile_id: {
                    "uid": uid,
                    "gold": 1000,
                    "in_room": pid == "P1" and uid in {"U1", "U2", "U3"},
                }
                for profile_id, uid in uid_by_pid.items()
            },
        }


class AutoHandContextLatchTests(unittest.TestCase):
    def test_cmd600_lpi_can_latch_external_before_all_profiles_report_live_roster(self):
        context = classify_hand_start_room_context(
            _SingleRosterEngine(),
            ["U1", "U2", "U3", "OPP"],
        )

        self.assertEqual(context.kind, "external_opp")
        self.assertEqual(context.controlled_pids, ("P1", "P2", "P3"))
        self.assertEqual(context.external_uids, ("OPP",))

    def test_cmd600_lpi_dict_roster_latches_external_opp(self):
        for roster in (
            [{"uid": "U1"}, {"uid": "U2"}, {"uid": "U3"}, {"uid": "OPP"}],
            [{"u": "U1"}, {"u": "U2"}, {"u": "U3"}, {"u": "OPP"}],
        ):
            with self.subTest(roster=roster):
                context = classify_hand_start_room_context(_SingleRosterEngine(), roster)

                self.assertEqual(context.kind, "external_opp")
                self.assertEqual(context.controlled_pids, ("P1", "P2", "P3"))
                self.assertEqual(context.external_uids, ("OPP",))
                self.assertEqual(context.roster, ("OPP", "U1", "U2", "U3"))

    def test_late_opp_does_not_promote_internal_hand_to_external(self):
        tab = _make_tab()
        internal = _ctx("internal_3p", ("U1", "U2", "U3"))
        late_external = _ctx("external_opp", ("U1", "U2", "U3", "OPP"), external=("OPP",))
        tab._hand_room_context_by_profile = {
            "P1": internal,
            "P2": late_external,
            "P3": late_external,
        }
        tab._live_room_context_safe = lambda: late_external

        resolved = StrategyTab._current_room_context_safe(tab)

        self.assertEqual(resolved.kind, "internal_3p")
        self.assertEqual(resolved.external_uids, ())

    def test_external_opp_present_at_hand_start_remains_external(self):
        tab = _make_tab()
        external = _ctx("external_opp", ("U1", "U2", "U3", "OPP"), external=("OPP",))
        tab._hand_room_context_by_profile = {pid: external for pid in PROFILES}
        tab._live_room_context_safe = lambda: external

        resolved = StrategyTab._current_room_context_safe(tab)

        self.assertEqual(resolved.kind, "external_opp")
        self.assertEqual(resolved.external_uids, ("OPP",))

    def test_latched_external_opp_fails_closed_if_original_opp_disappears(self):
        tab = _make_tab()
        external = _ctx("external_opp", ("U1", "U2", "U3", "OPP"), external=("OPP",))
        live_without_opp = _ctx("internal_3p", ("U1", "U2", "U3"))
        tab._hand_room_context_by_profile = {pid: external for pid in PROFILES}
        tab._live_room_context_safe = lambda: live_without_opp

        resolved = StrategyTab._current_room_context_safe(tab)

        self.assertEqual(resolved.kind, "unknown")
        self.assertIn("OPP", resolved.reason)

    def test_auto_apply_timer_rejects_stale_room_context_before_drag(self):
        tab = _make_tab()
        tab._auto_play_session = 10
        tab._auto_play_reservations = {}
        tab._auto_apply_unsafe_retry_counts = {}
        tab._auto_play_log = lambda _text: None
        tab._auto_random_delay_ms = lambda: 0
        released = []
        tab._auto_release_pending_group = lambda keys: released.append(dict(keys))

        current_context = _ctx("internal_3p", ("U1", "U2", "U3"))
        stale_context = _ctx("external_opp", ("U1", "U2", "U3", "OPP"), external=("OPP",))
        tab._current_room_context_safe = lambda: current_context
        stale_key = StrategyTab._auto_room_context_key(stale_context)

        calls = []

        def fake_apply(*_args, **_kwargs):
            calls.append("apply")
            return True

        old_qtimer = strategy_tab_module.QTimer
        import ui2.tabs.strategy2.modules.apply_auto as apply_auto_module

        old_apply = apply_auto_module.apply_suggestion_dashboard_style

        class ImmediateTimer:
            @staticmethod
            def singleShot(_delay_ms, fn):
                fn()

        try:
            strategy_tab_module.QTimer = ImmediateTimer
            apply_auto_module.apply_suggestion_dashboard_style = fake_apply
            StrategyTab._auto_apply_suggestions_random(
                tab,
                {"P1": {"mode": "money", "chi1_codes": _cards("A")[:5]}},
                expected_room_context_key=stale_key,
            )
        finally:
            strategy_tab_module.QTimer = old_qtimer
            apply_auto_module.apply_suggestion_dashboard_style = old_apply

        self.assertEqual(calls, [])
        self.assertTrue(released)

    def test_room_change_invalidates_stale_profile_hand_before_auto(self):
        tab = _make_tab()

        self.assertTrue(StrategyTab._is_profile_auto_hand_ready(tab, "P1", require_suggestions=True))

        StrategyTab._invalidate_profile_hand_for_room_change(tab, "P1", "room_snapshot")

        self.assertFalse(StrategyTab._is_profile_auto_hand_ready(tab, "P1"))
        self.assertTrue(tab._profile_waiting_new_hand_after_room_change["P1"])
        self.assertEqual(tab._codes_slot_order["P1"], [])
        self.assertEqual(tab._suggestions["P1"], [])
        self.assertIn("P1", tab._card_store.cleared)
        self.assertIn("P1", tab._layout_store.cleared)

        plan = build_money_fallback_plan(tab)

        self.assertIsNotNone(plan)
        self.assertNotIn("P1", plan.suggestions)
        self.assertIn("P2", plan.suggestions)
        self.assertIn("P3", plan.suggestions)

    def test_cmd600_after_room_change_rearms_profile_for_auto(self):
        tab = _make_tab()

        StrategyTab._invalidate_profile_hand_for_room_change(tab, "P1", "room_snapshot")
        new_cards = _cards("NEW")
        tab._force_reset_pid_state("P1")
        tab._hand_generation["P1"] += 1
        tab._profile_waiting_new_hand_after_room_change["P1"] = False
        tab._codes_slot_order["P1"] = list(new_cards)
        tab._suggestions["P1"] = [{
            "_auto_profile_money": True,
            "chi1_codes": new_cards[:5],
            "chi2_codes": new_cards[5:10],
            "chi3_codes": new_cards[10:13],
        }]

        self.assertTrue(StrategyTab._is_profile_auto_hand_ready(tab, "P1", require_suggestions=True))

    def test_room_change_does_not_offset_next_3p_cohort(self):
        tab = _make_tab()

        StrategyTab._invalidate_profile_hand_for_room_change(tab, "P2", "room_snapshot")
        self.assertEqual(tab._hand_generation["P2"], 1)

        for index, pid in enumerate(PROFILES):
            new_cards = _cards(f"NEXT{pid}")
            tab._force_reset_pid_state(pid)
            tab._hand_generation[pid] += 1
            tab._hand_seen_at[pid] = 200.0 + index
            tab._profile_waiting_new_hand_after_room_change[pid] = False
            tab._codes_slot_order[pid] = list(new_cards)
            tab._suggestions[pid] = [{
                "_auto_profile_money": True,
                "chi1_codes": new_cards[:5],
                "chi2_codes": new_cards[5:10],
                "chi3_codes": new_cards[10:13],
            }]

        self.assertEqual(tab._hand_generation, {"P1": 2, "P2": 2, "P3": 2})
        self.assertTrue(StrategyTab._has_all_3p_cards(tab))


if __name__ == "__main__":
    unittest.main()
