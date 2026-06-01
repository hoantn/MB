from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class AutoRoomContext:
    """
    Closed room classification for Auto Play.

    kind values:
      - "external_opp" : 3P cùng bàn + có UID ngoài → tối ưu vs OPP
      - "internal_3p"  : đúng 3P cùng bàn, không có UID ngoài → cân vàng nội bộ 3P
      - "internal_2p"  : đúng 2P cùng bàn, không có UID ngoài → cân vàng nội bộ 2P
      - "unknown"      : thiếu dữ liệu → fallback Money độc lập
    """

    kind: str
    roster: Tuple[str, ...] = ()
    controlled_pids: Tuple[str, ...] = ()
    external_uids: Tuple[str, ...] = ()
    reason: str = ""
    # gold_by_pid: chỉ chứa các pid trong controlled_pids, None nếu chưa có data
    gold_by_pid: Dict[str, Optional[int]] = field(default_factory=dict)


def classify_auto_room_context(room_engine) -> AutoRoomContext:
    """Classify the live table conservatively; uncertainty always falls back."""
    if room_engine is None or not hasattr(room_engine, "get_room_monitor_state"):
        return AutoRoomContext(kind="unknown", reason="chưa có RoomEngine realtime")

    controlled_uid_by_pid: Dict[str, str] = {}
    roster_by_pid: Dict[str, Tuple[str, ...]] = {}
    gold_by_pid: Dict[str, Optional[int]] = {}

    for pid in PROFILES:
        try:
            state = room_engine.get_room_monitor_state(pid) or {}
        except Exception:
            return AutoRoomContext(kind="unknown", reason=f"không đọc được roster {pid}")

        profiles_info = state.get("profiles") or {}
        own = profiles_info.get(pid) or {}
        uid = str(own.get("uid") or "").strip()
        # gold từ cmd=205 (on_room_balance_205 đã update _gold_by_uid)
        gold_raw = own.get("gold")
        gold_by_pid[pid] = int(gold_raw) if gold_raw is not None else None

        roster = tuple(sorted(str(x).strip() for x in (state.get("room_uids") or []) if str(x).strip()))
        if uid:
            controlled_uid_by_pid[pid] = uid
        if uid and uid in roster:
            roster_by_pid[pid] = roster

    if not roster_by_pid:
        return AutoRoomContext(kind="unknown", reason="chưa xác định được UID đang ngồi bàn")

    # Prefer the largest agreement group.
    grouped: Dict[Tuple[str, ...], List[str]] = {}
    for pid, roster in roster_by_pid.items():
        grouped.setdefault(roster, []).append(pid)
    roster, reporting_pids = max(grouped.items(), key=lambda item: (len(item[1]), len(item[0])))

    controlled_uid_set = set(controlled_uid_by_pid.values())
    controlled_pids = tuple(
        pid for pid in PROFILES
        if controlled_uid_by_pid.get(pid) in set(roster)
    )
    external_uids = tuple(uid for uid in roster if uid not in controlled_uid_set)

    # External OPP: đủ 3P đồng thuận + có UID ngoài
    if len(reporting_pids) == 3 and len(controlled_pids) == 3 and external_uids:
        return AutoRoomContext(
            kind="external_opp",
            roster=roster,
            controlled_pids=controlled_pids,
            external_uids=external_uids,
            gold_by_pid=gold_by_pid,
        )

    # Internal: không có UID ngoài, 2 hoặc 3P cùng bàn và đồng thuận
    if (
        not external_uids
        and len(controlled_pids) in (2, 3)
        and set(reporting_pids) == set(controlled_pids)
    ):
        kind = "internal_3p" if len(controlled_pids) == 3 else "internal_2p"
        return AutoRoomContext(
            kind=kind,
            roster=roster,
            controlled_pids=controlled_pids,
            gold_by_pid=gold_by_pid,
        )

    return AutoRoomContext(
        kind="unknown",
        roster=roster,
        controlled_pids=controlled_pids,
        external_uids=external_uids,
        reason="roster chưa đủ đồng thuận để suy OPP",
        gold_by_pid=gold_by_pid,
    )


# ===========================================================================
# Internal balance helpers
# ===========================================================================

def _get_money_split(tab, pid: str) -> Optional[Tuple[int, dict]]:
    """
    Trả về (index, suggestion) của split _auto_profile_money cho pid.
    Fallback về split playable đầu tiên nếu không tìm thấy money split.
    """
    rows = list(tab._suggestions.get(pid) or [])
    for idx, s in enumerate(rows):
        if s.get("_auto_profile_money") and _is_playable(tab, s):
            return idx, dict(s)
    for idx, s in enumerate(rows):
        if _is_playable(tab, s):
            return idx, dict(s)
    return None


def _pick_best_win(tab, pid: str, vs_sug: dict) -> Optional[Tuple[int, dict]]:
    """
    Từ _suggestions[pid], chọn split có số chi thắng vs vs_sug cao nhất.
    Tiebreak: money cao nhất (bài tự nhiên nhất).
    Dùng cho P_less (2P) và P_mid (3P).
    """
    best: Optional[Tuple[int, dict]] = None
    best_key: Optional[Tuple[int, int]] = None
    for idx, s in enumerate(tab._suggestions.get(pid) or []):
        if not _is_playable(tab, s):
            continue
        money, wins, _neg_losses, _draws = _score_suggestion_vs_opp(s, vs_sug)
        key = (wins, money)
        if best_key is None or key > best_key:
            best_key = key
            best = (idx, dict(s))
    return best


def _pick_natural_lose(tab, pid: str, vs_sug: dict) -> Optional[Tuple[int, dict]]:
    """
    Từ _suggestions[pid], chọn split thua vs_sug nhiều nhất nhưng tự nhiên:
      1. Ưu tiên wins >= 1 (tránh sập hầm × 2)
      2. Minimize wins (thua nhiều chi nhất có thể)
      3. Maximize money (bài tự nhiên nhất, không ép thế yếu)
    Dùng cho P_more (2P) và P_max (3P).
    """
    best: Optional[Tuple[int, dict]] = None
    best_key: Optional[Tuple[int, int, int]] = None
    for idx, s in enumerate(tab._suggestions.get(pid) or []):
        if not _is_playable(tab, s):
            continue
        money, wins, _neg_losses, _draws = _score_suggestion_vs_opp(s, vs_sug)
        not_swept = 1 if wins >= 1 else 0
        key = (not_swept, -wins, money)
        if best_key is None or key > best_key:
            best_key = key
            best = (idx, dict(s))
    return best


def _build_3p_balance(tab, sorted_pids: List[str]) -> Optional[AutoPlayPlan]:
    """
    Tối ưu nội bộ 3P:
      sorted_pids = [P_min, P_mid, P_max] theo gold tăng dần

    Bước 1 — P_min: dùng Money split tốt nhất (được chơi tự do).
    Bước 2 — P_max: thua tự nhiên nhất vs P_min (tránh sập hầm).
    Bước 3 — P_mid: thắng nhiều nhất vs P_max (trung gian).
    """
    p_min, p_mid, p_max = sorted_pids

    # Bước 1
    min_result = _get_money_split(tab, p_min)
    if min_result is None:
        return None
    min_idx, min_sug = min_result

    # Bước 2
    max_result = _pick_natural_lose(tab, p_max, min_sug)
    if max_result is None:
        return None
    max_idx, max_sug = max_result

    # Bước 3
    mid_result = _pick_best_win(tab, p_mid, max_sug)
    if mid_result is None:
        return None
    mid_idx, mid_sug = mid_result

    return AutoPlayPlan(
        kind="internal_balance",
        opp_index=-1,
        score=(0, 0, 0, 0),
        selected_index={p_min: min_idx, p_mid: mid_idx, p_max: max_idx},
        suggestions={p_min: min_sug, p_mid: mid_sug, p_max: max_sug},
    )


def _build_2p_balance(tab, sorted_pids: List[str], third_pids: List[str]) -> Optional[AutoPlayPlan]:
    """
    Tối ưu nội bộ 2P:
      sorted_pids = [P_less, P_more] theo gold tăng dần
      third_pids  = P không cùng bàn → dùng Money split độc lập

    Bước 1 — P_less: thắng nhiều nhất vs Money split của P_more.
    Bước 2 — P_more: thua tự nhiên nhất vs split P_less đã chọn (tránh sập hầm).
    P_third: Money split riêng.
    """
    p_less, p_more = sorted_pids

    more_money = _get_money_split(tab, p_more)
    if more_money is None:
        return None
    _, more_money_sug = more_money

    # Bước 1
    less_result = _pick_best_win(tab, p_less, more_money_sug)
    if less_result is None:
        return None
    less_idx, less_sug = less_result

    # Bước 2
    more_result = _pick_natural_lose(tab, p_more, less_sug)
    if more_result is None:
        return None
    more_idx, more_sug = more_result

    selected_index: Dict[str, int] = {p_less: less_idx, p_more: more_idx}
    suggestions: Dict[str, dict] = {p_less: less_sug, p_more: more_sug}

    # P_third dùng Money độc lập
    for pid in third_pids:
        result = _get_money_split(tab, pid)
        if result is not None:
            t_idx, t_sug = result
            selected_index[pid] = t_idx
            suggestions[pid] = t_sug

    return AutoPlayPlan(
        kind="internal_balance",
        opp_index=-1,
        score=(0, 0, 0, 0),
        selected_index=selected_index,
        suggestions=suggestions,
    )


def build_internal_balance_plan(tab, context: AutoRoomContext) -> Optional[AutoPlayPlan]:
    """
    Tối ưu nội bộ khi bàn chỉ có P của tool (không có UID ngoài).

    Điều kiện fire:
      - Tất cả gold khác nhau (nếu có bất kỳ cặp gold bằng nhau → fallback Money)
      - Không có gold None trong controlled_pids
      - _suggestions[pid] đủ cho tất cả controlled_pids

    Thuật toán:
      3P: [P_min → chơi tốt nhất] [P_max → thua tự nhiên nhất] [P_mid → thắng P_max]
      2P: [P_less → thắng P_more] [P_more → thua tự nhiên nhất] [P_third → Money riêng]
    """
    import logging as _log
    _logger = _log.getLogger("MauBinhTool")

    controlled = list(context.controlled_pids)
    if len(controlled) < 2:
        _logger.info("[INTERNAL-BALANCE] skip: controlled_pids < 2 (%s)", controlled)
        return None

    gold_map = context.gold_by_pid
    _logger.info(
        "[INTERNAL-BALANCE] kind=%s controlled=%s gold=%s",
        context.kind, controlled, {p: gold_map.get(p) for p in controlled}
    )

    # Nếu bất kỳ pid nào thiếu gold → fallback
    none_pids = [pid for pid in controlled if gold_map.get(pid) is None]
    if none_pids:
        _logger.info("[INTERNAL-BALANCE] skip: gold=None cho %s", none_pids)
        return None

    # Nếu bất kỳ 2 pid nào có gold bằng nhau → thứ tự không rõ, fallback Money
    # (chỉ cân vàng khi TẤT CẢ gold đều khác nhau hoàn toàn)
    unique_golds = {gold_map[pid] for pid in controlled}
    if len(unique_golds) < len(controlled):
        _logger.info(
            "[INTERNAL-BALANCE] skip: gold co cap bang nhau %s",
            {p: gold_map.get(p) for p in controlled}
        )
        return None

    # Kiểm tra suggestions đủ
    empty_pids = [pid for pid in controlled if not (tab._suggestions.get(pid) or [])]
    if empty_pids:
        _logger.info("[INTERNAL-BALANCE] skip: suggestions rong cho %s", empty_pids)
        return None

    # Sort theo gold tăng dần; tie-break theo thứ tự PROFILES
    profile_order = {p: i for i, p in enumerate(PROFILES)}
    sorted_pids = sorted(controlled, key=lambda p: (gold_map[p], profile_order.get(p, 99)))
    _logger.info(
        "[INTERNAL-BALANCE] thu tu can vang: %s",
        " > ".join(f"{p}={gold_map[p]}" for p in sorted_pids)
    )

    if context.kind == "internal_3p":
        return _build_3p_balance(tab, sorted_pids)

    if context.kind == "internal_2p":
        third_pids = [p for p in PROFILES if p not in set(controlled)]
        return _build_2p_balance(tab, sorted_pids, third_pids)

    return None


# ===========================================================================
# Existing helpers (unchanged)
# ===========================================================================

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
