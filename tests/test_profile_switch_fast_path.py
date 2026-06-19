import unittest

from ui2.tabs.strategy2.strategy_tab import StrategyTab


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


if __name__ == "__main__":
    unittest.main()
