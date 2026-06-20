from __future__ import annotations

import argparse
import copy
import json
import random
import sys
import time
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from typing import Dict, Iterable, List, Optional, Tuple
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.arranger_parts.arrange import arrange_cache_clear, arrange_cache_stats
from ui2.tabs.strategy2.modules.labeling import Labeling
from ui2.tabs.strategy2.modules.render_controller import RenderController
from ui2.tabs.strategy2.modules.special_row import is_special_row
from ui2.tabs.strategy2.strategy_suggest_worker import (
    build_suggestions_for_codes,
    clear_cache_for_pid,
)


PROFILES = ("P1", "P2", "P3")
RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A")
SUITS = ("R", "C", "B", "T")
DECK = [rank + suit for rank in RANKS for suit in SUITS]
MODES = ("stable", "fast", "compare")

FIXED_HANDS = {
    "P1": ["AR", "KC", "QB", "JT", "9R", "9C", "9B", "5T", "5R", "3C", "3B", "2T", "7R"],
    "P2": ["AC", "KB", "QT", "JR", "TR", "8C", "8B", "8T", "6R", "6C", "4B", "4T", "2R"],
    "P3": ["AB", "KT", "QR", "JC", "TC", "7C", "7B", "7T", "5C", "4R", "3T", "2C", "6B"],
    "NGU": ["AT", "KR", "QC", "JB", "TB", "TT", "9T", "8R", "6T", "5B", "4C", "3R", "2B"],
}


class _Button:
    def __init__(self) -> None:
        self.enabled: Optional[bool] = None

    def setEnabled(self, value) -> None:
        self.enabled = bool(value)


class _View:
    def __init__(self) -> None:
        self.btn_hup = _Button()
        self.active_profile = None
        self.p_cards: Dict[str, List[str]] = {}
        self.p_labels: Dict[str, tuple] = {}
        self.ngu_cards: List[str] = []
        self.retry_visible: Optional[bool] = None

    def set_active_profile(self, pid) -> None:
        self.active_profile = str(pid)

    def set_p_retry_visible(self, value) -> None:
        self.retry_visible = bool(value)

    def set_cards_p_normalized(self, codes) -> None:
        self.p_cards[str(self.active_profile)] = list(codes or [])

    def set_p_labels(self, items, idx) -> None:
        self.p_labels[str(self.active_profile)] = (copy.deepcopy(list(items or [])), int(idx))

    def set_cards_ngu_normalized(self, codes) -> None:
        self.ngu_cards = list(codes or [])


class _Log:
    def error(self, *args, **kwargs) -> None:
        return None

    def warning(self, *args, **kwargs) -> None:
        return None

    def exception(self, *args, **kwargs) -> None:
        return None


def _partition(deck: List[str]) -> Dict[str, List[str]]:
    return {
        "P1": list(deck[0:13]),
        "P2": list(deck[13:26]),
        "P3": list(deck[26:39]),
        "NGU": list(deck[39:52]),
    }


def build_table_scenarios(random_count: int, seed: int) -> List[Tuple[str, Dict[str, List[str]]]]:
    scenarios: List[Tuple[str, Dict[str, List[str]]]] = [
        ("fixed_table_existing", {key: list(value) for key, value in FIXED_HANDS.items()}),
    ]
    rng = random.Random(int(seed))
    for idx in range(1, max(0, int(random_count)) + 1):
        deck = list(DECK)
        rng.shuffle(deck)
        scenarios.append((f"random_seed_{seed}_{idx:02d}", _partition(deck)))
    return scenarios


def build_hand_stress_cases() -> List[Tuple[str, str, List[str]]]:
    return [
        ("stress_same_suit_13", "P1", [rank + "R" for rank in RANKS]),
        ("stress_rank_blocks_first_13", "P1", [rank + suit for rank in RANKS[:4] for suit in SUITS][:13]),
    ]


def _split_key(item: dict) -> str:
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


def _normalize_suggestion(item: dict) -> tuple:
    ignored = {"_template_key_cache", "_template_key_cache_error"}
    return tuple(
        sorted(
            (str(key), _clean_value(value))
            for key, value in dict(item or {}).items()
            if key not in ignored
        )
    )


def _normalize_suggestions(items: Iterable[dict]) -> tuple:
    return tuple(_normalize_suggestion(item) for item in list(items or []))


def _reset_for_hand(pid: str, cold: bool) -> None:
    clear_cache_for_pid(pid)
    if cold:
        arrange_cache_clear()


def worker_snapshot(pid: str, codes: List[str], mode: str, *, cold: bool) -> tuple:
    _reset_for_hand(pid, cold)
    return _normalize_suggestions(build_suggestions_for_codes(pid, codes, engine_mode=mode))


def timed_worker_snapshot(pid: str, codes: List[str], mode: str, *, cold: bool) -> Tuple[tuple, float]:
    start = time.perf_counter()
    snapshot = worker_snapshot(pid, codes, mode, cold=cold)
    return snapshot, (time.perf_counter() - start) * 1000.0


def _make_tab(hands: Dict[str, List[str]], mode: str, *, ngu_clicked_once: bool, cold: bool):
    for key in ("P1", "P2", "P3", "NGU"):
        _reset_for_hand(key, cold)

    suggestions = {
        pid: build_suggestions_for_codes(pid, hands[pid], engine_mode=mode)
        for pid in PROFILES
    }
    ngu_suggestions = build_suggestions_for_codes("NGU", hands["NGU"], engine_mode=mode)

    tab = SimpleNamespace()
    tab.profiles = list(PROFILES)
    tab.active_profile = "P1"
    tab.view = _View()
    tab.log = _Log()
    tab._labeling = Labeling()
    tab._suggestions = suggestions
    tab._suggestions_render = {pid: [] for pid in PROFILES}
    tab._codes_slot_order = {pid: list(hands[pid]) for pid in PROFILES}
    tab._selected_index = {pid: 0 for pid in PROFILES}
    tab._ngu_suggestions = ngu_suggestions
    tab._ngu_selected_index = 0
    tab._ngu_clicked_once = bool(ngu_clicked_once)
    tab._ngu_base_codes = list(hands["NGU"])
    tab._anti_sap_enabled = False
    tab._SPECIAL_MODE = "__special13__"
    tab.MAX_UI_P_ITEMS = 12
    tab.MAX_UI_NGU_ITEMS = 12
    tab._is_special_row = lambda item: is_special_row(item, special_mode=tab._SPECIAL_MODE)
    tab._inject_special_row_for_profile = lambda _pid, _codes, render_suggs: list(render_suggs or [])
    tab._make_split_key = _split_key
    tab._compute_sap_lang_flags_for_active_suggestion = lambda _pid, _item: (False, False)
    return tab


def render_snapshot(hands: Dict[str, List[str]], mode: str, *, ngu_clicked_once: bool, cold: bool) -> dict:
    tab = _make_tab(hands, mode, ngu_clicked_once=ngu_clicked_once, cold=cold)
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


def timed_render_snapshot(
    hands: Dict[str, List[str]],
    mode: str,
    *,
    ngu_clicked_once: bool,
    cold: bool,
) -> Tuple[dict, float]:
    start = time.perf_counter()
    snapshot = render_snapshot(hands, mode, ngu_clicked_once=ngu_clicked_once, cold=cold)
    return snapshot, (time.perf_counter() - start) * 1000.0


def _stats(values: List[float]) -> dict:
    if not values:
        return {"count": 0, "avg_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0}
    sorted_values = sorted(values)
    p95_idx = max(0, min(len(sorted_values) - 1, int(len(sorted_values) * 0.95) - 1))
    return {
        "count": len(values),
        "avg_ms": round(mean(values), 2),
        "min_ms": round(min(values), 2),
        "p95_ms": round(sorted_values[p95_idx], 2),
        "max_ms": round(max(values), 2),
    }


def run_benchmark(*, random_count: int, seed: int, cold: bool, include_stress: bool) -> dict:
    table_scenarios = build_table_scenarios(random_count=random_count, seed=seed)
    worker_times = {mode: [] for mode in MODES}
    worker_mismatches = []
    ui_times = {mode: [] for mode in ("stable", "fast")}
    ui_mismatches = []
    scenario_details = []

    with patch("ui2.tabs.strategy2.auto_suggestion_picker.find_rule_match", return_value=(-1, None, {})):
        for scenario_name, hands in table_scenarios:
            raw_counts = {}
            for pid in ("P1", "P2", "P3", "NGU"):
                snapshots = {}
                for mode in MODES:
                    snapshots[mode], elapsed_ms = timed_worker_snapshot(pid, hands[pid], mode, cold=cold)
                    worker_times[mode].append(elapsed_ms)
                raw_counts[pid] = len(snapshots["stable"])
                if snapshots["stable"] != snapshots["fast"] or snapshots["stable"] != snapshots["compare"]:
                    worker_mismatches.append({"scenario": scenario_name, "pid": pid})

            ui_counts = {}
            for clicked in (False, True):
                state = "opp_click" if clicked else "no_click"
                stable_ui, stable_ms = timed_render_snapshot(hands, "stable", ngu_clicked_once=clicked, cold=cold)
                fast_ui, fast_ms = timed_render_snapshot(hands, "fast", ngu_clicked_once=clicked, cold=cold)
                ui_times["stable"].append(stable_ms)
                ui_times["fast"].append(fast_ms)
                if stable_ui != fast_ui:
                    ui_mismatches.append({"scenario": scenario_name, "state": state})
                ui_counts[state] = {
                    "NGU": len(stable_ui["NGU"]["suggestions"]),
                    "P1": len(stable_ui["P1"]["suggestions_render"]),
                    "P2": len(stable_ui["P2"]["suggestions_render"]),
                    "P3": len(stable_ui["P3"]["suggestions_render"]),
                }

            scenario_details.append(
                {
                    "name": scenario_name,
                    "raw_counts": raw_counts,
                    "ui_counts": ui_counts,
                }
            )

    stress_details = []
    if include_stress:
        for name, pid, codes in build_hand_stress_cases():
            snapshots = {}
            elapsed = {}
            for mode in ("stable", "fast"):
                snapshots[mode], elapsed[mode] = timed_worker_snapshot(pid, codes, mode, cold=cold)
            stress_details.append(
                {
                    "name": name,
                    "pid": pid,
                    "count": len(snapshots["stable"]),
                    "stable_fast_equal": snapshots["stable"] == snapshots["fast"],
                    "stable_ms": round(elapsed["stable"], 2),
                    "fast_ms": round(elapsed["fast"], 2),
                }
            )

    return {
        "config": {
            "random_count": int(random_count),
            "seed": int(seed),
            "cold": bool(cold),
            "include_stress": bool(include_stress),
        },
        "summary": {
            "table_scenarios": len(table_scenarios),
            "worker_cases": len(table_scenarios) * 4,
            "ui_checks": len(table_scenarios) * 2,
            "worker_mismatches": worker_mismatches,
            "ui_mismatches": ui_mismatches,
            "worker_times": {mode: _stats(values) for mode, values in worker_times.items()},
            "ui_times": {mode: _stats(values) for mode, values in ui_times.items()},
            "arrange_cache_stats": arrange_cache_stats(),
        },
        "scenario_details": scenario_details,
        "stress_details": stress_details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Strategy2 suggestion engine and UI-final snapshots.")
    parser.add_argument("--random-count", type=int, default=12, help="Number of deterministic random table scenarios.")
    parser.add_argument("--seed", type=int, default=20260621, help="Random seed for table scenarios.")
    parser.add_argument("--warm", action="store_true", help="Do not clear arranger cache before each measured call.")
    parser.add_argument("--no-stress", action="store_true", help="Skip expensive hand-level stress cases.")
    parser.add_argument(
        "--json-out",
        default=str(ROOT / "logs" / "strategy_engine_benchmark_latest.json"),
        help="Path to write benchmark JSON.",
    )
    args = parser.parse_args()

    result = run_benchmark(
        random_count=args.random_count,
        seed=args.seed,
        cold=not bool(args.warm),
        include_stress=not bool(args.no_stress),
    )

    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")

    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True, indent=2))
    print(f"json_out={out_path}")
    if result["summary"]["worker_mismatches"] or result["summary"]["ui_mismatches"]:
        return 2
    if any(not item.get("stable_fast_equal", False) for item in result["stress_details"]):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
