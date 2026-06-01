from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ui2.tabs.strategy2.strategy_anti_sap import _codes_to_threechi, _eval_vs_opp
from ui2.tabs.strategy2.strategy_combo_sap_lang import find_sap_lang_combo, SapLangCombo
from engine.money_scoring import score_money_vs_opp


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
    report_binh_pids: Tuple[str, ...] = ()


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


def _score_suggestion_vs_opp(
    s: dict,
    opp: dict,
    *,
    allow_special_13: bool = False,
) -> Tuple[int, int, int, int]:
    my_three = _codes_to_threechi(s)
    opp_three = _codes_to_threechi(opp)
    if my_three is None or opp_three is None:
        return (-9999, -9999, -9999, -9999)
    info = _eval_vs_opp(my_three, opp_three, allow_special_13=allow_special_13)
    return (
        int(score_money_vs_opp(my_three, opp_three, allow_special_13=allow_special_13)),
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
        score = _score_suggestion_vs_opp(sug, opp, allow_special_13=False)
        if best is None or score > best[2]:
            best = (idx, dict(sug), score)
    return best


def _best_special_for_pid(tab, pid: str, opp: dict) -> Optional[Tuple[int, dict, Tuple[int, int, int, int]]]:
    """Return the reportable special row if its worker-built 5-5-3 split exists."""
    base_suggs = list(tab._suggestions.get(pid) or [])
    for idx, sug in enumerate(base_suggs):
        try:
            is_special = tab._is_special_row(sug)
        except Exception:
            is_special = bool(sug.get("_is_special_row"))
        if not is_special:
            continue
        if not (
            len(list(sug.get("chi1_codes") or [])) == 5
            and len(list(sug.get("chi2_codes") or [])) == 5
            and len(list(sug.get("chi3_codes") or [])) == 3
        ):
            continue
        score = _score_suggestion_vs_opp(sug, opp, allow_special_13=True)
        try:
            # Worker detector is the UI/game contract for Báo binh. Prefer its
            # explicit award over re-detecting through a second legacy engine.
            chi_points = int(sug.get("special_chi_points"))
            score = (chi_points, score[1], score[2], score[3])
        except Exception:
            pass
        return idx, dict(sug), score
    return None


def _best_response_for_pid(tab, pid: str, opp: dict) -> Optional[Tuple[int, dict, Tuple[int, int, int, int], bool]]:
    normal = _best_normal_for_pid(tab, pid, opp)
    special = _best_special_for_pid(tab, pid, opp)
    if special is not None and (normal is None or special[2] > normal[2]):
        return special[0], special[1], special[2], True
    if normal is not None:
        return normal[0], normal[1], normal[2], False
    return None


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
    report_binh_pids: List[str] = []

    for pid in PROFILES:
        picked = _best_response_for_pid(tab, pid, opp)
        if picked is None:
            return None
        idx, sug, score, report_binh = picked
        selected_index[pid] = int(idx)
        normal_suggestions[pid] = sug
        normal_scores.append(score)
        if report_binh:
            report_binh_pids.append(pid)

    normal_plan = AutoPlayPlan(
        kind="normal",
        opp_index=int(opp_index),
        score=_sum_scores(normal_scores),
        selected_index=selected_index,
        suggestions=normal_suggestions,
        report_binh_pids=tuple(report_binh_pids),
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
    report_binh_pids: List[str] = []
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
        picked = _best_response_for_pid(tab, pid, opp)
        if picked is None:
            continue
        idx, sug, score, report_binh = picked
        selected_index[pid] = int(idx)
        normal_suggestions[pid] = sug
        normal_scores.append(score)
        if report_binh:
            report_binh_pids.append(pid)

    if not normal_suggestions:
        return None

    return AutoPlayPlan(
        kind="partial",
        opp_index=int(opp_index),
        score=_sum_scores(normal_scores),
        selected_index=selected_index,
        suggestions=normal_suggestions,
        partial=True,
        report_binh_pids=tuple(report_binh_pids),
    )


def build_money_fallback_plan(tab) -> Optional[AutoPlayPlan]:
    """
    Build an OPP-free safety plan for every ready profile.

    Prefer a reportable special hand. Otherwise use the exact Money split
    captured during that profile's normal arranger scan.
    """
    selected_index: Dict[str, int] = {}
    suggestions: Dict[str, dict] = {}
    report_binh_pids: List[str] = []
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

        rows = list(tab._suggestions.get(pid) or [])
        picked = None
        report_binh = False
        for idx, sug in enumerate(rows):
            try:
                is_special = tab._is_special_row(sug)
            except Exception:
                is_special = bool(sug.get("_is_special_row"))
            if is_special and _has_553_split(sug):
                picked = (idx, dict(sug))
                report_binh = True
                break

        if picked is None:
            for idx, sug in enumerate(rows):
                if sug.get("_auto_profile_money") and _is_playable(tab, sug):
                    picked = (idx, dict(sug))
                    break

        if picked is None:
            continue
        idx, sug = picked
        selected_index[pid] = int(idx)
        suggestions[pid] = sug
        if report_binh:
            report_binh_pids.append(pid)

    if not suggestions:
        return None
    return AutoPlayPlan(
        kind="money_fallback",
        opp_index=-1,
        score=(0, 0, 0, 0),
        selected_index=selected_index,
        suggestions=suggestions,
        partial=True,
        report_binh_pids=tuple(report_binh_pids),
    )


def _has_553_split(s: Optional[dict]) -> bool:
    if not s:
        return False
    return (
        len(list(s.get("chi1_codes") or [])) == 5
        and len(list(s.get("chi2_codes") or [])) == 5
        and len(list(s.get("chi3_codes") or [])) == 3
    )


def build_auto_play_plan(tab, max_opp: int = 3) -> Optional[AutoPlayPlan]:
    """Use the protected OPP Auto Money suggestion, then return the best response."""
    # Keep max_opp in the public signature for compatibility with the existing
    # StrategyTab caller. Auto Play now intentionally benchmarks one Money row.
    del max_opp
    opp_candidate: Optional[Tuple[int, dict]] = None
    for idx, opp in enumerate(list(tab._ngu_suggestions or [])):
        if not opp.get("_auto_opp_money"):
            continue
        if _is_playable(tab, opp):
            opp_candidate = (idx, dict(opp))
            break

    if opp_candidate is None:
        return None

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
    idx, opp = opp_candidate
    if full_ready:
        return build_best_plan_for_opp(tab, idx, opp)
    return build_partial_plan_for_opp(tab, idx, opp)
