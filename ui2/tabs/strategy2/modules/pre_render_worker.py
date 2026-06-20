from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from core.constants import DEFAULT_DB_PATH
from ui2.tabs.strategy2.auto_choice_rules import (
    DEFAULT_SCOPE,
    DEFAULT_SIMILARITY_ENABLED,
    DEFAULT_SIMILARITY_THRESHOLD,
    RULES_TABLE,
    SETTINGS_TABLE,
    normalize_codes_key,
    split_key_from_suggestion,
    mark_rule_used,
)
from ui2.tabs.strategy2.auto_choice_similarity import (
    combined_similarity,
    extract_hand_features,
    extract_suggestion_features,
)
from ui2.tabs.strategy2.auto_suggestion_picker import (
    AUTO_OPP_FLAG,
    AUTO_PROFILE_FLAG,
    clear_auto_flags,
    pick_auto_suggestion_index,
    split_key,
)
from ui2.tabs.strategy2.modules.labeling import Labeling
from ui2.tabs.strategy2.strategy_anti_sap import build_anti_sap_suggestions
from ui2.tabs.strategy2.strategy_suggest import pick_default_suggestion


@dataclass(frozen=True)
class AutoMarkPlan:
    idx: int
    flag: str
    source: str
    split_key: str
    rule_id: Optional[int] = None
    match_info: Optional[dict] = None
    selected_auto_engine_money: bool = False
    selected: Optional[dict] = None


@dataclass(frozen=True)
class PreRenderSnapshot:
    pid: str
    request_id: int
    signature: tuple
    profiles: Tuple[str, ...]
    suggestions: Dict[str, List[dict]]
    suggestions_render: Dict[str, List[dict]]
    selected_index: Dict[str, int]
    codes_slot_order: Dict[str, List[str]]
    ngu_suggestions: List[dict]
    ngu_selected_index: int
    ngu_clicked_once: bool
    anti_sap_enabled: bool
    max_ui_p_items: int
    special_mode: str


@dataclass(frozen=True)
class PreRenderResult:
    pid: str
    request_id: int
    signature: tuple
    suggestions_render: List[dict]
    selected_index: int
    auto_mark_plan: Optional[AutoMarkPlan]
    elapsed_ms: float
    error: Optional[str] = None


def copy_suggestion(item: Optional[dict]) -> dict:
    if not isinstance(item, dict):
        return {}
    out = dict(item)
    for key, value in list(out.items()):
        if isinstance(value, list):
            out[key] = list(value)
        elif isinstance(value, tuple):
            out[key] = tuple(value)
        elif isinstance(value, dict):
            out[key] = dict(value)
    return out


def copy_suggestions(items: Iterable[dict]) -> List[dict]:
    return [copy_suggestion(item) for item in list(items or []) if isinstance(item, dict)]


def apply_auto_mark_plan(
    base_suggestions: List[dict],
    final_suggestions: List[dict],
    plan: Optional[AutoMarkPlan],
) -> int:
    if plan is None:
        clear_auto_flags(base_suggestions)
        clear_auto_flags(final_suggestions)
        return -1

    clear_auto_flags(base_suggestions)
    clear_auto_flags(final_suggestions)

    idx = int(plan.idx)
    if idx < 0 or idx >= len(final_suggestions):
        return -1

    selected = final_suggestions[idx]
    selected[plan.flag] = True
    selected["_auto_from_final_suggestions"] = True
    selected["_auto_choice_source"] = str(plan.source or "fallback")
    if plan.rule_id:
        selected["_auto_user_rule"] = True
        selected["_auto_rule_match"] = dict(plan.match_info or {})

    key = str(plan.split_key or split_key(selected) or "")
    matched = False
    for item in list(base_suggestions or []):
        if key and split_key(item) == key:
            item[plan.flag] = True
            item["_auto_from_final_suggestions"] = True
            item["_auto_choice_source"] = str(plan.source or "fallback")
            if bool(plan.selected_auto_engine_money):
                item["_auto_engine_money"] = True
            if plan.rule_id:
                item["_auto_user_rule"] = True
                item["_auto_rule_match"] = dict(plan.match_info or {})
            matched = True
            break

    if not matched and base_suggestions is not None:
        copied = copy_suggestion(plan.selected or selected)
        copied[plan.flag] = True
        copied["_auto_from_final_suggestions"] = True
        copied["_auto_choice_source"] = str(plan.source or "fallback")
        if plan.rule_id:
            copied["_auto_user_rule"] = True
            copied["_auto_rule_match"] = dict(plan.match_info or {})
        base_suggestions.append(copied)

    if plan.rule_id:
        mark_rule_used(plan.rule_id)

    return idx


def run_pre_render_snapshot(snapshot: PreRenderSnapshot) -> PreRenderResult:
    start = time.perf_counter()
    try:
        render_suggs, selected_idx, auto_plan = _compute_pre_render(snapshot)
        return PreRenderResult(
            pid=snapshot.pid,
            request_id=int(snapshot.request_id),
            signature=snapshot.signature,
            suggestions_render=render_suggs,
            selected_index=int(selected_idx),
            auto_mark_plan=auto_plan,
            elapsed_ms=(time.perf_counter() - start) * 1000.0,
        )
    except Exception as exc:
        return PreRenderResult(
            pid=snapshot.pid,
            request_id=int(snapshot.request_id),
            signature=snapshot.signature,
            suggestions_render=[],
            selected_index=0,
            auto_mark_plan=None,
            elapsed_ms=(time.perf_counter() - start) * 1000.0,
            error=repr(exc),
        )


def _compute_pre_render(snapshot: PreRenderSnapshot) -> Tuple[List[dict], int, Optional[AutoMarkPlan]]:
    pid = str(snapshot.pid)
    base_suggs = copy_suggestions((snapshot.suggestions or {}).get(pid) or [])
    if not base_suggs:
        return [], 0, None

    opp = _pick_ngu_for_pre_render(snapshot)
    render_suggs = _build_render_suggestions(base_suggs, opp, bool(snapshot.anti_sap_enabled))

    try:
        idx = int((snapshot.selected_index or {}).get(pid, 0) or 0)
    except Exception:
        idx = 0
    if idx < 0 or idx >= len(render_suggs):
        idx = int(pick_default_suggestion(render_suggs))
        if idx < 0:
            idx = 0

    auto_plan = _build_auto_mark_plan(
        base_suggs,
        render_suggs,
        policy="self",
        special_mode=str(snapshot.special_mode),
        hand_codes=list((snapshot.codes_slot_order or {}).get(pid) or []),
    )

    labeling = Labeling()
    labeling.set_cache_limits(chi_type_cache_limit=5000, cmp_cache_limit=8000)

    for item in render_suggs[: max(0, int(snapshot.max_ui_p_items or 0))]:
        if _is_special_row(item, snapshot.special_mode):
            continue
        if not item.get("_split_key"):
            item["_split_key"] = _make_split_key(item)
        try:
            lang_win, lang_lose = _compute_sap_lang_flags(snapshot, item, labeling)
            item["_sap_lang_win"] = bool(lang_win)
            item["_sap_lang_lose"] = bool(lang_lose)
        except Exception:
            pass
        try:
            item["label_html"] = labeling.build_label_html_vs(item, opp)
        except Exception:
            item["label_html"] = item.get("label_html", "")

    return list(render_suggs[: int(snapshot.max_ui_p_items or 0)]), idx, auto_plan


def _build_render_suggestions(base_suggs: List[dict], opp: Optional[dict], anti_sap_enabled: bool) -> List[dict]:
    out = list(base_suggs or [])
    if opp is None or not out or not anti_sap_enabled:
        return out
    my_base = _find_money_base(out)
    if my_base is None:
        return out
    try:
        anti = build_anti_sap_suggestions(
            my_base=my_base,
            opp_base=opp,
            label_prefix="Tối ưu",
            max_out=3,
        )
    except Exception:
        anti = []
    for i, item in enumerate(anti):
        item["mode"] = "optimize_vs_ngu"
        item["label"] = f"[TỐI ƯU] Gợi ý {i + 1}"
    out.extend(anti)
    return out


def _find_money_base(suggs: List[dict]) -> Optional[dict]:
    if not suggs:
        return None
    for item in suggs:
        if str(item.get("mode", "")).lower() == "money":
            return item
    return suggs[0]


def _build_auto_mark_plan(
    base_suggestions: List[dict],
    final_suggestions: List[dict],
    *,
    policy: str,
    special_mode: str,
    hand_codes: Optional[Sequence[str]] = None,
) -> Optional[AutoMarkPlan]:
    flag = AUTO_OPP_FLAG if str(policy).lower() == "opp" else AUTO_PROFILE_FLAG
    clear_auto_flags(base_suggestions)
    clear_auto_flags(final_suggestions)

    idx = -1
    rule_id: Optional[int] = None
    match_info: dict = {}
    if hand_codes:
        idx, rule_id, match_info = _find_rule_match_threadsafe(hand_codes, final_suggestions)

    if idx < 0:
        rule_id = None
        match_info = {}
        idx = pick_auto_suggestion_index(
            final_suggestions,
            is_special_row=lambda item: _is_special_row(item, special_mode),
        )
    if idx < 0 or idx >= len(final_suggestions):
        return None

    selected = final_suggestions[idx]
    source = _choice_source(selected, rule_id, match_info)
    selected[flag] = True
    selected["_auto_from_final_suggestions"] = True
    selected["_auto_choice_source"] = source
    if rule_id:
        selected["_auto_user_rule"] = True
        selected["_auto_rule_match"] = dict(match_info or {})

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
        copied = copy_suggestion(selected)
        copied[flag] = True
        copied["_auto_from_final_suggestions"] = True
        copied["_auto_choice_source"] = source
        if rule_id:
            copied["_auto_user_rule"] = True
            copied["_auto_rule_match"] = dict(match_info or {})
        base_suggestions.append(copied)

    return AutoMarkPlan(
        idx=int(idx),
        flag=flag,
        source=source,
        split_key=key,
        rule_id=rule_id,
        match_info=dict(match_info or {}),
        selected_auto_engine_money=bool(selected.get("_auto_engine_money")),
        selected=copy_suggestion(selected),
    )


def _choice_source(suggestion: dict, rule_id: Optional[int], match_info: Optional[dict] = None) -> str:
    if rule_id:
        if str((match_info or {}).get("match_type") or "") == "similar":
            return "user_rule_similar"
        return "user_rule"
    if str(suggestion.get("mode", "")).lower() == "money" or suggestion.get("_auto_engine_money"):
        return "engine_money"
    return "fallback"


def _find_rule_match_threadsafe(
    hand_codes: Sequence[str],
    suggestions: Iterable[dict],
    *,
    scope: str = DEFAULT_SCOPE,
) -> Tuple[int, Optional[int], dict]:
    hand_key = normalize_codes_key(hand_codes)
    if not hand_key:
        return -1, None, {}

    suggestion_list = list(suggestions or [])
    conn = None
    try:
        conn = sqlite3.connect(DEFAULT_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"""
            SELECT id, selected_split_key
            FROM {RULES_TABLE}
            WHERE hand_key=? AND scope=? AND COALESCE(enabled, 1)=1
            LIMIT 1
            """,
            (hand_key, str(scope or DEFAULT_SCOPE)),
        ).fetchone()
        if row is not None:
            wanted = str(row["selected_split_key"] or "")
            for idx, item in enumerate(suggestion_list):
                if isinstance(item, dict) and split_key_from_suggestion(item) == wanted:
                    return int(idx), int(row["id"]), {"match_type": "exact", "similarity": 100.0}

        settings = _get_ai_learning_settings_threadsafe(conn)
        if not settings.get("similarity_enabled"):
            return -1, None, {}
        return _find_similar_rule_match_threadsafe(
            conn,
            hand_codes,
            suggestion_list,
            scope=scope,
            threshold=float(settings.get("similarity_threshold") or DEFAULT_SIMILARITY_THRESHOLD),
        )
    except Exception:
        return -1, None, {}
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _get_ai_learning_settings_threadsafe(conn: sqlite3.Connection) -> dict:
    try:
        rows = conn.execute(f"SELECT key, value FROM {SETTINGS_TABLE}").fetchall()
        data = {str(row["key"]): str(row["value"]) for row in rows}
        enabled_raw = data.get("similarity_enabled")
        threshold_raw = data.get("similarity_threshold")
        enabled = DEFAULT_SIMILARITY_ENABLED if enabled_raw is None else enabled_raw not in ("0", "false", "False")
        try:
            threshold = int(threshold_raw) if threshold_raw is not None else DEFAULT_SIMILARITY_THRESHOLD
        except Exception:
            threshold = DEFAULT_SIMILARITY_THRESHOLD
        return {
            "similarity_enabled": bool(enabled),
            "similarity_threshold": max(50, min(100, int(threshold))),
        }
    except Exception:
        return {
            "similarity_enabled": DEFAULT_SIMILARITY_ENABLED,
            "similarity_threshold": DEFAULT_SIMILARITY_THRESHOLD,
        }


def _find_similar_rule_match_threadsafe(
    conn: sqlite3.Connection,
    hand_codes: Sequence[str],
    suggestions: Iterable[dict],
    *,
    scope: str,
    threshold: float,
    limit: int = 2000,
) -> Tuple[int, Optional[int], dict]:
    hand_key = normalize_codes_key(hand_codes)
    suggestion_list = [item for item in list(suggestions or []) if isinstance(item, dict) and split_key_from_suggestion(item)]
    if not hand_key or not suggestion_list:
        return -1, None, {}

    current_hand = extract_hand_features(hand_codes)
    current_choices = [extract_suggestion_features(item) for item in suggestion_list]
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT id, hand_key, selected_split_key, selected_template,
                       chi1_codes, chi2_codes, chi3_codes, label, hit_count,
                       hand_features_json, selected_features_json
                FROM {RULES_TABLE}
                WHERE scope=? AND COALESCE(enabled, 1)=1
                ORDER BY hit_count DESC, updated_at DESC, id DESC
                LIMIT ?
                """,
                (str(scope or DEFAULT_SCOPE), max(1, int(limit or 2000))),
            ).fetchall()
        ]
    except Exception:
        return -1, None, {}

    threshold_f = max(0.0, min(100.0, float(threshold or DEFAULT_SIMILARITY_THRESHOLD)))
    best: Optional[tuple[float, int, int, dict]] = None
    for row in rows:
        saved_hand = _row_hand_features(row)
        saved_choice = _row_choice_features(row)
        for idx, current_choice in enumerate(current_choices):
            raw_score = combined_similarity(saved_hand, current_hand, saved_choice, current_choice) * 100.0
            if raw_score < threshold_f:
                continue
            hit_bonus = min(2.5, float(row.get("hit_count") or 0) * 0.05)
            adjusted_score = min(100.0, raw_score + hit_bonus)
            info = {
                "match_type": "similar",
                "similarity": round(raw_score, 2),
                "similarity_adjusted": round(adjusted_score, 2),
                "threshold": threshold_f,
                "matched_rule_id": int(row.get("id") or 0),
                "matched_rule_template": row.get("selected_template") or row.get("label") or "",
            }
            candidate = (adjusted_score, int(row.get("id") or 0), int(idx), info)
            if best is None or candidate[0] > best[0]:
                best = candidate

    if best is None:
        return -1, None, {}
    _score, rule_id, idx, info = best
    return int(idx), int(rule_id), info


def _decode_json(value: object) -> dict:
    try:
        if not value:
            return {}
        data = json.loads(str(value))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _row_hand_features(row: dict) -> dict:
    data = _decode_json(row.get("hand_features_json"))
    if data:
        return data
    return extract_hand_features(str(row.get("hand_key") or "").split(","))


def _row_choice_features(row: dict) -> dict:
    data = _decode_json(row.get("selected_features_json"))
    if data:
        return data
    return extract_suggestion_features(
        {
            "chi1_codes": str(row.get("chi1_codes") or "").split(","),
            "chi2_codes": str(row.get("chi2_codes") or "").split(","),
            "chi3_codes": str(row.get("chi3_codes") or "").split(","),
        }
    )


def _is_special_row(item: Optional[dict], special_mode: str) -> bool:
    if not item:
        return False
    return str(item.get("mode")) == str(special_mode) or bool(item.get("_is_special_row", False))


def _has_playable_split(item: Optional[dict]) -> bool:
    if not item:
        return False
    return (
        len(list(item.get("chi1_codes") or [])) == 5
        and len(list(item.get("chi2_codes") or [])) == 5
        and len(list(item.get("chi3_codes") or [])) == 3
    )


def _pick_current_suggestion_for_pid(snapshot: PreRenderSnapshot, pid: str) -> Optional[dict]:
    render_list = list((snapshot.suggestions_render or {}).get(pid) or [])
    base_list = list((snapshot.suggestions or {}).get(pid) or [])
    candidates = render_list or base_list

    if candidates:
        try:
            idx = int((snapshot.selected_index or {}).get(pid, 0) or 0)
        except Exception:
            idx = 0
        if 0 <= idx < len(candidates):
            selected = candidates[idx]
            if _has_playable_split(selected) and not _is_special_row(selected, snapshot.special_mode):
                return selected

    for item in render_list:
        if _has_playable_split(item) and not _is_special_row(item, snapshot.special_mode):
            return item
    for item in base_list:
        if _has_playable_split(item) and not _is_special_row(item, snapshot.special_mode):
            return item
    return None


def _pick_current_ngu_suggestion(snapshot: PreRenderSnapshot) -> Optional[dict]:
    if not snapshot.ngu_suggestions:
        return None
    try:
        idx = int(snapshot.ngu_selected_index or 0)
    except Exception:
        idx = 0
    if 0 <= idx < len(snapshot.ngu_suggestions):
        selected = snapshot.ngu_suggestions[idx]
        if _has_playable_split(selected) and not _is_special_row(selected, snapshot.special_mode):
            return selected
    for item in snapshot.ngu_suggestions:
        if _has_playable_split(item) and not _is_special_row(item, snapshot.special_mode):
            return item
    return None


def _pick_ngu_for_pre_render(snapshot: PreRenderSnapshot) -> Optional[dict]:
    if not snapshot.ngu_suggestions:
        return None
    try:
        idx = int(snapshot.ngu_selected_index or 0)
    except Exception:
        idx = 0
    if idx < 0 or idx >= len(snapshot.ngu_suggestions):
        idx = 0
    if (
        snapshot.ngu_suggestions
        and _is_special_row(snapshot.ngu_suggestions[0], snapshot.special_mode)
        and idx <= 0
        and len(snapshot.ngu_suggestions) > 1
    ):
        idx = 1
    candidate = snapshot.ngu_suggestions[idx] if 0 <= idx < len(snapshot.ngu_suggestions) else None
    if candidate and not _is_special_row(candidate, snapshot.special_mode):
        return candidate
    return None


def _compute_sap_lang_flags(snapshot: PreRenderSnapshot, sug: dict, labeling: Labeling) -> Tuple[bool, bool]:
    opp_list: List[dict] = []
    opp = _pick_current_ngu_suggestion(snapshot)
    if opp:
        opp_list.append(opp)

    for other in snapshot.profiles:
        if other == snapshot.pid:
            continue
        item = _pick_current_suggestion_for_pid(snapshot, other)
        if item and not _is_special_row(item, snapshot.special_mode):
            opp_list.append(item)

    if len(opp_list) < 3:
        return False, False

    def sweep_vs(opp_sug: dict) -> int:
        d1 = labeling.compare_chi(list(sug.get("chi1_codes") or []), list(opp_sug.get("chi1_codes") or []), 1)
        d2 = labeling.compare_chi(list(sug.get("chi2_codes") or []), list(opp_sug.get("chi2_codes") or []), 2)
        d3 = labeling.compare_chi(list(sug.get("chi3_codes") or []), list(opp_sug.get("chi3_codes") or []), 3)
        if d1 == 0 or d2 == 0 or d3 == 0:
            return 0
        if d1 > 0 and d2 > 0 and d3 > 0:
            return 1
        if d1 < 0 and d2 < 0 and d3 < 0:
            return -1
        return 0

    wins_all = True
    lose_all = True
    for opp_sug in opp_list:
        result = sweep_vs(opp_sug)
        if result != 1:
            wins_all = False
        if result != -1:
            lose_all = False
    return wins_all, lose_all


def _make_split_key(item: dict) -> str:
    try:
        c1 = tuple(sorted(map(str, item.get("chi1_codes") or [])))
        c2 = tuple(sorted(map(str, item.get("chi2_codes") or [])))
        c3 = tuple(sorted(map(str, item.get("chi3_codes") or [])))
        return "|".join([",".join(c3), ",".join(c2), ",".join(c1)])
    except Exception:
        return ""
