import unittest

from ui2.tabs.strategy2.auto_suggestion_picker import mark_auto_suggestion
from ui2.tabs.strategy2.strategy_tab import StrategyTab


def _suggestion(mode="money", offset=0):
    ranks = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]
    suits = ["C", "D", "H", "S"]
    cards = [f"{rank}{suits[(idx + offset) % len(suits)]}" for idx, rank in enumerate(ranks)]
    return {
        "mode": mode,
        "chi1_codes": cards[:5],
        "chi2_codes": cards[5:10],
        "chi3_codes": cards[10:],
    }


class _View:
    def __init__(self):
        self.cards = []

    def set_cards_ngu_normalized(self, codes):
        self.cards.append(list(codes or []))


class _Renderer:
    def __init__(self):
        self.render_calls = 0

    def build_preview_codes(self, suggestion):
        chi1 = list(suggestion.get("chi1_codes") or [])
        chi2 = list(suggestion.get("chi2_codes") or [])
        chi3 = list(suggestion.get("chi3_codes") or [])
        if len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3:
            return chi1 + chi2 + chi3
        return None

    def render_ngu(self, tab):
        self.render_calls += 1
        base = list(tab._ngu_suggestions or [])
        out = [dict(base[0])] if base else []
        mark_auto_suggestion(
            base,
            out,
            policy="opp",
            is_special_row=tab._is_special_row,
            hand_codes=[],
        )
        tab._ngu_suggestions = out
        if tab._ngu_selected_index < 0 or tab._ngu_selected_index >= len(out):
            tab._ngu_selected_index = 0
        if out:
            tab.view.set_cards_ngu_normalized(self.build_preview_codes(out[tab._ngu_selected_index]) or [])


def _copy_items(items):
    copied = []
    for item in items:
        row = dict(item)
        row["chi1_codes"] = list(row.get("chi1_codes") or [])
        row["chi2_codes"] = list(row.get("chi2_codes") or [])
        row["chi3_codes"] = list(row.get("chi3_codes") or [])
        copied.append(row)
    return copied


def _tab():
    tab = StrategyTab.__new__(StrategyTab)
    tab.profiles = ["P1", "P2", "P3"]
    tab.MAX_UI_NGU_ITEMS = 12
    tab._p_render_core_sig = {pid: None for pid in tab.profiles}
    tab._ngu_render_last_input_sig = None
    tab._ngu_render_last_output_sig = None
    tab._ngu_render_cached_output = []
    tab._ngu_render_cached_selected_index = 0
    tab._ngu_base_codes = []
    tab._ngu_suggestions = []
    tab._ngu_selected_index = 0
    tab._ngu_clicked_once = False
    tab._renderer = _Renderer()
    tab.view = _View()
    tab._update_special_labels = lambda: None
    tab._refresh_sap_lang_combo = lambda: None
    return tab


class NguPostEngineCacheTests(unittest.TestCase):
    def test_post_engine_cache_hit_restores_cached_output_without_core_render(self):
        tab = _tab()
        raw = [_suggestion("money", 0), _suggestion("max", 1)]
        tab._ngu_suggestions = _copy_items(raw)

        tab._render_ngu_post_engine()

        self.assertEqual(tab._renderer.render_calls, 1)
        self.assertEqual(len(tab._ngu_suggestions), 1)
        self.assertTrue(tab._ngu_suggestions[0].get("_auto_opp_money"))

        tab._ngu_suggestions = _copy_items(raw)
        tab._ngu_selected_index = 0
        tab._render_ngu_post_engine()

        self.assertEqual(tab._renderer.render_calls, 1)
        self.assertEqual(len(tab._ngu_suggestions), 1)
        self.assertTrue(tab._ngu_suggestions[0].get("_auto_opp_money"))
        self.assertEqual(tab.view.cards[-1], tab._renderer.build_preview_codes(tab._ngu_suggestions[0]))

    def test_post_engine_cache_misses_when_selected_index_changes(self):
        tab = _tab()
        raw = [_suggestion("money", 0), _suggestion("max", 1)]
        tab._ngu_suggestions = _copy_items(raw)
        tab._render_ngu_post_engine()

        tab._ngu_suggestions = _copy_items(raw)
        tab._ngu_selected_index = 1
        tab._render_ngu_post_engine()

        self.assertEqual(tab._renderer.render_calls, 2)

    def test_direct_render_ngu_still_forces_core_render(self):
        tab = _tab()
        raw = [_suggestion("money", 0), _suggestion("max", 1)]
        tab._ngu_suggestions = _copy_items(raw)
        tab._render_ngu()

        tab._ngu_suggestions = _copy_items(raw)
        tab._render_ngu()

        self.assertEqual(tab._renderer.render_calls, 2)


if __name__ == "__main__":
    unittest.main()
