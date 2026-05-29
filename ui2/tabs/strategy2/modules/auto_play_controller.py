from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ui2.tabs.strategy2.strategy_anti_sap import _codes_to_threechi, _eval_vs_opp
from ui2.tabs.strategy2.strategy_combo_sap_lang import find_sap_lang_combo, SapLangCombo


PROFILES = ("P1", "P2", "P3")


@dataclass
class AutoPlayPlan:
    kind: str
    opp_index: int
    score: Tuple[int, int, int, int]
    selected_index: Dict[str, int]
    suggestions: Dict[str, dict]
    combo: Optional[SapLangCombo] = None
    delay_each_profile: bool = False
    partial: bool = False


def _is_playable(tab, s: Optional[dict]) -> bool:
    if not s:
        return False
    try:
        if tab._is_special_row(s):
            return False
    except Exception:
        pass
    return (
        len(list(s.get("chi1_codes") or [])) == 5
        and len(list(s.get("chi2_codes") or [])) == 5
        and len(list(s.get("chi3_codes") or [])) == 3
    )


def _score_suggestion_vs_opp(s: dict, opp: dict) -> Tuple[int, int, int, int]:
    my_three = _codes_to_threechi(s)
    opp_three = _codes_to_threechi(opp)
    if my_three is None or opp_three is None:
        return (-9999, -9999, -9999, -9999)
    info = _eval_vs_opp(my_three, opp_three)
    return (
        int(info.total_money),
        int(info.wins),
        -int(info.losses),
        int(info.draws),
    )


def _best_normal_for_pid(tab, pid: str, opp: dict) -> Optional[Tuple[int, dict, Tuple[int, int, int, int]]]:
    base_suggs = list(tab._suggestions.get(pid) or [])
    if not base_suggs:
        return None

    rendered = list(tab._build_render_suggestions(base_suggs, opp) or [])
    if not rendered:
        return None

    best: Optional[Tuple[int, dict, Tuple[int, int, int, int]]] = None
    for idx, sug in enumerate(rendered):
        if not _is_playable(tab, sug):
            continue
        score = _score_suggestion_vs_opp(sug, opp)
        if best is None or score > best[2]:
            best = (idx, dict(sug), score)
    return best


def _sum_scores(items: List[Tuple[int, int, int, int]]) -> Tuple[int, int, int, int]:
    return (
        sum(x[0] for x in items),
        sum(x[1] for x in items),
        sum(x[2] for x in items),
        sum(x[3] for x in items),
    )


def build_best_plan_for_opp(tab, opp_index: int, opp: dict) -> Optional[AutoPlayPlan]:
    selected_index: Dict[str, int] = {}
    normal_suggestions: Dict[str, dict] = {}
    normal_scores: List[Tuple[int, int, int, int]] = []

    for pid in PROFILES:
        picked = _best_normal_for_pid(tab, pid, opp)
        if picked is None:
            return None
        idx, sug, score = picked
        selected_index[pid] = int(idx)
        normal_suggestions[pid] = sug
        normal_scores.append(score)

    normal_plan = AutoPlayPlan(
        kind="normal",
        opp_index=int(opp_index),
        score=_sum_scores(normal_scores),
        selected_index=selected_index,
        suggestions=normal_suggestions,
    )

    combo = find_sap_lang_combo(
        suggestions_by_pid={
            pid: list(tab._build_render_suggestions(list(tab._suggestions.get(pid) or []), opp) or [])
            + list(tab._suggestions.get(pid) or [])
            for pid in PROFILES
        },
        ws_codes_by_pid={pid: list(tab._codes_slot_order.get(pid) or []) for pid in PROFILES},
        opp_suggestion=opp,
    )
    if combo is None:
        return normal_plan

    combo_plan = AutoPlayPlan(
        kind="sap_lang",
        opp_index=int(opp_index),
        score=tuple(int(x) for x in combo.score),
        selected_index={},
        suggestions={pid: dict(s) for pid, s in combo.suggestions.items()},
        combo=combo,
    )
    return combo_plan if combo_plan.score > normal_plan.score else normal_plan


def build_partial_plan_for_opp(tab, opp_index: int, opp: dict) -> Optional[AutoPlayPlan]:
    """
    Build the best single-profile responses that are currently ready.

    This is the Auto Play fallback when the full 3P plan is not available yet:
    no sap-lang/global combo is considered, only money-optimal normal sorting for
    each ready P against the selected OPP.
    """
    selected_index: Dict[str, int] = {}
    normal_suggestions: Dict[str, dict] = {}
    normal_scores: List[Tuple[int, int, int, int]] = []
    applied_keys = getattr(tab, "_auto_play_applied_profile_keys", set()) or set()

    for pid in PROFILES:
        if len(list(tab._codes_slot_order.get(pid) or [])) != 13:
            continue
        if hasattr(tab, "_auto_profile_apply_key"):
            try:
                if tab._auto_profile_apply_key(pid) in applied_keys:
                    continue
            except Exception:
                pass
        picked = _best_normal_for_pid(tab, pid, opp)
        if picked is None:
            continue
        idx, sug, score = picked
        selected_index[pid] = int(idx)
        normal_suggestions[pid] = sug
        normal_scores.append(score)

    if not normal_suggestions:
        return None

    return AutoPlayPlan(
        kind="partial",
        opp_index=int(opp_index),
        score=_sum_scores(normal_scores),
        selected_index=selected_index,
        suggestions=normal_suggestions,
        partial=True,
    )


def build_auto_play_plan(tab, max_opp: int = 3) -> Optional[AutoPlayPlan]:
    """Pick worst-case OPP, then return the best available response."""
    opp_candidates: List[Tuple[int, dict]] = []
    for idx, opp in enumerate(list(tab._ngu_suggestions or [])):
        if _is_playable(tab, opp):
            opp_candidates.append((idx, dict(opp)))
        if len(opp_candidates) >= int(max_opp):
            break

    plans: List[AutoPlayPlan] = []
    applied_keys = getattr(tab, "_auto_play_applied_profile_keys", set()) or set()
    full_has_no_prior_apply = True
    if hasattr(tab, "_auto_profile_apply_key"):
        for pid in PROFILES:
            try:
                if tab._auto_profile_apply_key(pid) in applied_keys:
                    full_has_no_prior_apply = False
                    break
            except Exception:
                pass

    full_ready = full_has_no_prior_apply and all(
        len(list(tab._codes_slot_order.get(pid) or [])) == 13
        and bool(tab._suggestions.get(pid) or [])
        for pid in PROFILES
    )
    for idx, opp in opp_candidates:
        if full_ready:
            plan = build_best_plan_for_opp(tab, idx, opp)
        else:
            plan = build_partial_plan_for_opp(tab, idx, opp)
        if plan is not None:
            plans.append(plan)

    if not plans:
        return None

    # Reverse thinking: assume OPP chooses the line that gives 3P the worst result.
    return min(plans, key=lambda p: p.score)
