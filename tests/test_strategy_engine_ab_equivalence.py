import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ui2.tabs.strategy2.modules.labeling import Labeling
from ui2.tabs.strategy2.modules.render_controller import RenderController
from ui2.tabs.strategy2.modules.special_row import is_special_row
from ui2.tabs.strategy2.strategy_suggest_worker import build_suggestions_for_codes, clear_cache_for_pid


PROFILES = ("P1", "P2", "P3")
HANDS = {
    "P1": ["AR", "KC", "QB", "JT", "9R", "9C", "9B", "5T", "5R", "3C", "3B", "2T", "7R"],
    "P2": ["AC", "KB", "QT", "JR", "TR", "8C", "8B", "8T", "6R", "6C", "4B", "4T", "2R"],
    "P3": ["AB", "KT", "QR", "JC", "TC", "7C", "7B", "7T", "5C", "4R", "3T", "2C", "6B"],
    "NGU": ["AT", "KR", "QC", "JB", "TB", "TT", "9T", "8R", "6T", "5B", "4C", "3R", "2B"],
}


class _Button:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, value):
        self.enabled = bool(value)


class _View:
    def __init__(self):
        self.btn_hup = _Button()
        self.active_profile = None
        self.retry_visible = None
        self.p_cards = {}
        self.p_labels = {}
        self.ngu_cards = []

    def set_active_profile(self, pid):
        self.active_profile = str(pid)

    def set_p_retry_visible(self, value):
        self.retry_visible = bool(value)

    def set_cards_p_normalized(self, codes):
        self.p_cards[str(self.active_profile)] = list(codes or [])

    def set_p_labels(self, items, idx):
        self.p_labels[str(self.active_profile)] = (copy.deepcopy(list(items or [])), int(idx))

    def set_cards_ngu_normalized(self, codes):
        self.ngu_cards = list(codes or [])


class _Log:
    def error(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def exception(self, *args, **kwargs):
        return None


def _split_key(item):
    c1 = tuple(sorted(map(str, item.get("chi1_codes") or [])))
    c2 = tuple(sorted(map(str, item.get("chi2_codes") or [])))
    c3 = tuple(sorted(map(str, item.get("chi3_codes") or [])))
    return "|".join([",".join(c3), ",".join(c2), ",".join(c1)])


def _clean_value(value):
    if isinstance(value, list):
        return tuple(_clean_value(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_clean_value(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((str(k), _clean_value(v)) for k, v in value.items()))
    return value


def _normalize_suggestion(item):
    ignored = {
        "_template_key_cache",
        "_template_key_cache_error",
    }
    return tuple(
        sorted(
            (str(k), _clean_value(v))
            for k, v in dict(item or {}).items()
            if k not in ignored
        )
    )


def _normalize_suggestions(items):
    return tuple(_normalize_suggestion(item) for item in list(items or []))


def _make_tab(engine_mode, *, ngu_clicked_once=False):
    for key in ("P1", "P2", "P3", "NGU"):
        clear_cache_for_pid(key)

    suggestions = {
        pid: build_suggestions_for_codes(pid, HANDS[pid], engine_mode=engine_mode)
        for pid in PROFILES
    }
    ngu_suggestions = build_suggestions_for_codes("NGU", HANDS["NGU"], engine_mode=engine_mode)

    tab = SimpleNamespace()
    tab.profiles = list(PROFILES)
    tab.active_profile = "P1"
    tab.view = _View()
    tab.log = _Log()
    tab._labeling = Labeling()
    tab._suggestions = suggestions
    tab._suggestions_render = {pid: [] for pid in PROFILES}
    tab._codes_slot_order = {pid: list(HANDS[pid]) for pid in PROFILES}
    tab._selected_index = {pid: 0 for pid in PROFILES}
    tab._ngu_suggestions = ngu_suggestions
    tab._ngu_selected_index = 0
    tab._ngu_clicked_once = bool(ngu_clicked_once)
    tab._ngu_base_codes = list(HANDS["NGU"])
    tab._anti_sap_enabled = False
    tab._SPECIAL_MODE = "__special13__"
    tab.MAX_UI_P_ITEMS = 12
    tab.MAX_UI_NGU_ITEMS = 12
    tab._is_special_row = lambda item: is_special_row(item, special_mode=tab._SPECIAL_MODE)
    tab._inject_special_row_for_profile = lambda _pid, _codes, render_suggs: list(render_suggs or [])
    tab._make_split_key = _split_key
    tab._compute_sap_lang_flags_for_active_suggestion = lambda _pid, _item: (False, False)
    return tab


def _render_snapshot(engine_mode, *, ngu_clicked_once=False):
    tab = _make_tab(engine_mode, ngu_clicked_once=ngu_clicked_once)
    renderer = RenderController(max_ui_p_items=12, max_ui_ngu_items=12)

    renderer.render_ngu(tab)
    out = {
        "NGU": {
            "selected_index": int(tab._ngu_selected_index),
            "cards": tuple(tab.view.ngu_cards),
            "suggestions": _normalize_suggestions(tab._ngu_suggestions),
        }
    }

    for pid in PROFILES:
        tab.active_profile = pid
        renderer.render_p_active(tab)
        labels, label_idx = tab.view.p_labels.get(pid, ([], 0))
        out[pid] = {
            "selected_index": int(tab._selected_index.get(pid, 0)),
            "label_index": int(label_idx),
            "cards": tuple(tab.view.p_cards.get(pid) or []),
            "suggestions_render": _normalize_suggestions(tab._suggestions_render.get(pid) or []),
            "view_labels": _normalize_suggestions(labels),
        }
    return out


def _worker_snapshot(key, codes, engine_mode):
    clear_cache_for_pid(key)
    return _normalize_suggestions(build_suggestions_for_codes(key, codes, engine_mode=engine_mode))


class StrategyEngineABEquivalenceTests(unittest.TestCase):
    def test_worker_suggestions_match_between_stable_fast_and_compare(self):
        for key, codes in HANDS.items():
            stable = _worker_snapshot(key, codes, "stable")
            fast = _worker_snapshot(key, codes, "fast")
            compare = _worker_snapshot(key, codes, "compare")
            self.assertEqual(stable, fast, key)
            self.assertEqual(stable, compare, key)

    def test_final_ui_suggestions_match_for_3p_and_opp_without_opp_click(self):
        with patch("ui2.tabs.strategy2.auto_suggestion_picker.find_rule_match", return_value=(-1, None, {})):
            stable = _render_snapshot("stable", ngu_clicked_once=False)
            fast = _render_snapshot("fast", ngu_clicked_once=False)
        self.assertEqual(stable, fast)

    def test_final_ui_suggestions_match_for_3p_and_opp_after_opp_click(self):
        with patch("ui2.tabs.strategy2.auto_suggestion_picker.find_rule_match", return_value=(-1, None, {})):
            stable = _render_snapshot("stable", ngu_clicked_once=True)
            fast = _render_snapshot("fast", ngu_clicked_once=True)
        self.assertEqual(stable, fast)


if __name__ == "__main__":
    unittest.main()
