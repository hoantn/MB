import unittest

from ui2.tabs.strategy2.strategy_tab import StrategyTab


def _suggestion(offset=0):
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
    rotated = ranks[offset:] + ranks[:offset]
    return {
        "mode": "money",
        "chi1_codes": [f"{rank}T" for rank in rotated[:5]],
        "chi2_codes": [f"{rank}B" for rank in rotated[5:10]],
        "chi3_codes": [f"{rank}C" for rank in rotated[10:13]],
    }


class ProfileSwitchFastPathTests(unittest.TestCase):
    def _tab(self):
        tab = StrategyTab.__new__(StrategyTab)
        tab.profiles = ["P1", "P2", "P3"]
        tab.active_profile = "P1"
        return tab

    def test_profile_switch_uses_valid_cache_without_rendering(self):
        tab = self._tab()
        calls = []

        tab._show_active_profile_from_render_cache = lambda pid: calls.append(("cache", pid)) or True
        tab._render_p_active = lambda: calls.append(("render_p", tab.active_profile))
        tab._render_ngu = lambda: calls.append(("render_ngu", tab.active_profile))

        StrategyTab._on_profile_switch(tab, "P2")

        self.assertEqual(tab.active_profile, "P2")
        self.assertEqual(calls, [("cache", "P2")])

    def test_profile_switch_falls_back_to_p_render_only(self):
        tab = self._tab()
        calls = []

        tab._show_active_profile_from_render_cache = lambda pid: calls.append(("cache", pid)) or False
        tab._render_p_active = lambda: calls.append(("render_p", tab.active_profile))
        tab._render_ngu = lambda: calls.append(("render_ngu", tab.active_profile))

        StrategyTab._on_profile_switch(tab, "P3")

        self.assertEqual(tab.active_profile, "P3")
        self.assertEqual(calls, [("cache", "P3"), ("render_p", "P3")])

    def _cache_tab(self):
        tab = self._tab()
        tab._codes_slot_order = {pid: [] for pid in tab.profiles}
        tab._suggestions = {
            "P1": [_suggestion(0), _suggestion(1)],
            "P2": [_suggestion(2), _suggestion(3)],
            "P3": [_suggestion(4)],
        }
        tab._suggestions_render = {
            pid: [dict(item) for item in items]
            for pid, items in tab._suggestions.items()
        }
        tab._selected_index = {"P1": 0, "P2": 0, "P3": 0}
        tab._ngu_suggestions = []
        tab._ngu_selected_index = 0
        tab._ngu_clicked_once = False
        tab._anti_sap_enabled = False
        tab.MAX_UI_P_ITEMS = 12
        tab._SPECIAL_MODE = "__special13__"
        return tab

    def test_p_render_cache_signature_ignores_own_selection(self):
        tab = self._cache_tab()

        before = StrategyTab._build_p_render_cache_signature(tab, "P1")
        tab._selected_index["P1"] = 1
        after = StrategyTab._build_p_render_cache_signature(tab, "P1")

        self.assertEqual(before, after)

    def test_p_render_cache_signature_tracks_peer_selection(self):
        tab = self._cache_tab()

        before = StrategyTab._build_p_render_cache_signature(tab, "P2")
        tab._selected_index["P1"] = 1
        after = StrategyTab._build_p_render_cache_signature(tab, "P2")

        self.assertNotEqual(before, after)

    def test_render_p_active_uses_valid_cache_before_heavy_renderer(self):
        tab = self._tab()
        calls = []
        tab._flush_pre_render_for_profile = lambda pid: calls.append(("flush", pid))
        tab._show_active_profile_from_render_cache = lambda pid: calls.append(("cache", pid)) or True
        tab._clear_pending_pre_render_profile = lambda pid: calls.append(("clear", pid))
        tab._renderer = type(
            "Renderer",
            (),
            {"render_p_active": lambda _self, _tab: calls.append(("renderer", _tab.active_profile))},
        )()
        tab._mark_p_render_cache_valid = lambda pid: calls.append(("mark", pid))
        tab._update_special_labels = lambda: calls.append(("special",))
        tab._refresh_sap_lang_combo = lambda: calls.append(("sap",))
        tab._sync_apply_button_enabled = lambda: calls.append(("sync",))

        StrategyTab._render_p_active(tab)

        self.assertEqual(calls, [("flush", "P1"), ("cache", "P1"), ("clear", "P1")])


if __name__ == "__main__":
    unittest.main()
