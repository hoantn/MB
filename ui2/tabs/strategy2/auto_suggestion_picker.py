from __future__ import annotations

from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from .auto_choice_rules import find_rule_match, mark_rule_used


AUTO_PROFILE_FLAG = "_auto_profile_money"
AUTO_OPP_FLAG = "_auto_opp_money"


def has_playable_split(suggestion: Optional[dict]) -> bool:
    if not suggestion:
        return False
    return (
        len(list(suggestion.get("chi1_codes") or [])) == 5
        and len(list(suggestion.get("chi2_codes") or [])) == 5
        and len(list(suggestion.get("chi3_codes") or [])) == 3
    )


def split_key(suggestion: Optional[dict]) -> str:
    if not suggestion:
        return ""
    try:
        c1 = tuple(sorted(str(c).strip().upper() for c in (suggestion.get("chi1_codes") or [])))
        c2 = tuple(sorted(str(c).strip().upper() for c in (suggestion.get("chi2_codes") or [])))
        c3 = tuple(sorted(str(c).strip().upper() for c in (suggestion.get("chi3_codes") or [])))
        if len(c1) != 5 or len(c2) != 5 or len(c3) != 3:
            return ""
        return "|".join([",".join(c3), ",".join(c2), ",".join(c1)])
    except Exception:
        return ""


def _is_blocked_by_special(
    item: dict,
    is_special_row: Optional[Callable[[dict], bool]],
) -> bool:
    if is_special_row is None:
        return False
    try:
        return bool(is_special_row(item))
    except Exception:
        return False


def _iter_playable_candidates(
    suggestions: List[dict],
    is_special_row: Optional[Callable[[dict], bool]],
) -> Iterable[Tuple[int, dict]]:
    for idx, item in enumerate(list(suggestions or [])):
        if not isinstance(item, dict) or not has_playable_split(item):
            continue
        if _is_blocked_by_special(item, is_special_row):
            continue
        yield idx, item


def clear_auto_flags(suggestions: Iterable[dict]) -> None:
    for item in list(suggestions or []):
        if isinstance(item, dict):
            item.pop(AUTO_PROFILE_FLAG, None)
            item.pop(AUTO_OPP_FLAG, None)
            item.pop("_auto_user_rule", None)
            item.pop("_auto_from_final_suggestions", None)
            item.pop("_auto_choice_source", None)
            item.pop("_auto_rule_match", None)


def pick_auto_suggestion_index(
    suggestions: List[dict],
    *,
    is_special_row: Optional[Callable[[dict], bool]] = None,
) -> int:
    """Pick Auto from existing final-list rows.

    Auto no longer re-scores visible suggestions. The engine Money row is the
    default Auto split; if it is missing, use the first playable row only as a
    defensive fallback.
    """
    candidates = list(_iter_playable_candidates(suggestions, is_special_row))
    if not candidates:
        return -1

    for idx, item in candidates:
        if str(item.get("mode", "")).lower() == "money" or item.get("_auto_engine_money"):
            return int(idx)

    return int(candidates[0][0])


def _choice_source(suggestion: dict, rule_id: Optional[int], match_info: Optional[dict] = None) -> str:
    if rule_id:
        if str((match_info or {}).get("match_type") or "") == "similar":
            return "user_rule_similar"
        return "user_rule"
    if str(suggestion.get("mode", "")).lower() == "money" or suggestion.get("_auto_engine_money"):
        return "engine_money"
    return "fallback"


def mark_auto_suggestion(
    base_suggestions: List[dict],
    final_suggestions: List[dict],
    *,
    policy: str,
    is_special_row: Optional[Callable[[dict], bool]] = None,
    hand_codes: Optional[Sequence[str]] = None,
    use_user_rules: bool = True,
) -> int:
    """Mark the selected Auto row in the final list and matching base list.

    Priority:
    1. user-saved rule for the exact 13 cards;
    2. engine Money row already injected into final suggestions;
    3. first playable row as a defensive fallback.
    """
    flag = AUTO_OPP_FLAG if str(policy).lower() == "opp" else AUTO_PROFILE_FLAG
    clear_auto_flags(base_suggestions)
    clear_auto_flags(final_suggestions)

    idx = -1
    rule_id: Optional[int] = None
    match_info: dict = {}
    if use_user_rules and hand_codes:
        idx, rule_id, match_info = find_rule_match(hand_codes, final_suggestions)

    if idx < 0:
        rule_id = None
        match_info = {}
        idx = pick_auto_suggestion_index(final_suggestions, is_special_row=is_special_row)
    if idx < 0:
        return -1

    selected = final_suggestions[idx]
    source = _choice_source(selected, rule_id, match_info)
    selected[flag] = True
    selected["_auto_from_final_suggestions"] = True
    selected["_auto_choice_source"] = source
    if rule_id:
        selected["_auto_user_rule"] = True
        selected["_auto_rule_match"] = dict(match_info or {})
        mark_rule_used(rule_id)

    key = split_key(selected)
    matched = False
    for item in list(base_suggestions or []):
        if key and split_key(item) == key:
            item[flag] = True
            item["_auto_from_final_suggestions"] = True
            item["_auto_choice_source"] = source
            if selected.get("_auto_engine_money"):
                item["_auto_engine_money"] = True
            if rule_id:
                item["_auto_user_rule"] = True
                item["_auto_rule_match"] = dict(match_info or {})
            matched = True
            break

    if not matched and base_suggestions is not None:
        copied = dict(selected)
        copied[flag] = True
        copied["_auto_from_final_suggestions"] = True
        copied["_auto_choice_source"] = source
        if rule_id:
            copied["_auto_user_rule"] = True
            copied["_auto_rule_match"] = dict(match_info or {})
        base_suggestions.append(copied)

    return idx
