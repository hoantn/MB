from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ui2.tabs.strategy2.strategy_anti_sap import _codes_to_threechi, _eval_vs_opp
from ui2.tabs.strategy2.strategy_combo_sap_lang import find_sap_lang_combo, SapLangCombo
from ui2.tabs.strategy2.strategy_intentional_foul import build_intentional_foul_suggestion
from ui2.tabs.strategy2.strategy_special13 import detect_special_13
from engine.money_scoring import score_money_vs_opp, evaluate_5cards, evaluate_3cards


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
    dependency_groups: Tuple[Tuple[str, ...], ...] = ()


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
        try:
            gold_by_pid[pid] = int(gold_raw) if gold_raw is not None else None
        except (TypeError, ValueError):
            gold_by_pid[pid] = None

        roster = tuple(sorted(str(x).strip() for x in (state.get("room_uids") or []) if str(x).strip()))
        if uid:
            controlled_uid_by_pid[pid] = uid
        # Runtime snapshots mark empty or aged membership as unsafe. Mocks from
        # older tests omit the flag, so they remain compatible by default.
        roster_fresh = bool(state.get("roster_fresh", True))
        if uid and uid in roster and roster_fresh:
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

    # External OPP: đủ 3P đồng thuận + đúng một UID ngoài.
    # NGU is derived as the fourth 13-card hand, so a stale roster containing
    # multiple external UIDs must fail closed instead of using the OPP path.
    if len(reporting_pids) == 3 and len(controlled_pids) == 3 and len(external_uids) == 1:
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
    Trả về (index, suggestion) của split Money tốt nhất cho pid.
    Dùng cho P_min (3P) và P_less (2P): cho phép chơi thế bài tự nhiên tốt nhất.

    Ưu tiên lấy split có flag _auto_profile_money (do worker arranger đánh dấu).
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

    [Hiện không dùng trong internal balance — giữ lại để dùng cho các module khác nếu cần]
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
    Từ _suggestions[pid], chọn split thua vs_sug nhiều nhất nhưng tự nhiên.
    Dùng cho P_mid (thua P_min) và P_more/P_max 2P (thua P_less).

    Ưu tiên:
      1. wins >= 1 → tránh sập hầm (thua 0-3 nhân đôi tiền)
      2. Minimize wins → thua nhiều chi nhất có thể
      3. Maximize money → bài tự nhiên, không ép thế quá yếu
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


def _pick_natural_lose_vs_both(
    tab, pid: str, vs_sug1: dict, vs_sug2: dict
) -> Optional[Tuple[int, dict]]:
    """
    Từ _suggestions[pid], chọn split thua tự nhiên nhất vs CẢ HAI đối thủ.
    Dùng cho P_max (3P): phải thua P_min và P_mid để đảm bảo cả hai đều thắng P_max.

    Ưu tiên:
      1. not_swept_1 + not_swept_2 → ưu tiên wins >= 1 vs mỗi người
         (tránh sập hầm × 2 với từng đối thủ riêng lẻ)
      2. Minimize tổng wins (wins_vs_1 + wins_vs_2) → thua nhiều nhất có thể
      3. Maximize money vs vs_sug1 → bài tự nhiên nhất trong số các thế thua
    """
    best: Optional[Tuple[int, dict]] = None
    best_key: Optional[Tuple[int, int, int]] = None
    for idx, s in enumerate(tab._suggestions.get(pid) or []):
        if not _is_playable(tab, s):
            continue
        money1, wins1, _, _ = _score_suggestion_vs_opp(s, vs_sug1)
        _money2, wins2, _, _ = _score_suggestion_vs_opp(s, vs_sug2)
        not_swept1 = 1 if wins1 >= 1 else 0
        not_swept2 = 1 if wins2 >= 1 else 0
        total_wins = wins1 + wins2
        key = (not_swept1 + not_swept2, -total_wins, money1)
        if best_key is None or key > best_key:
            best_key = key
            best = (idx, dict(s))
    return best


def _pick_not_swept_natural_lose(tab, pid: str, vs_sug: dict) -> Optional[Tuple[int, dict]]:
    """Pick a natural losing split that is not swept 0-3."""
    best: Optional[Tuple[int, dict]] = None
    best_key: Optional[Tuple[int, int, int]] = None
    for idx, s in enumerate(tab._suggestions.get(pid) or []):
        if not _is_playable(tab, s):
            continue
        money, wins, _neg_losses, draws = _score_suggestion_vs_opp(s, vs_sug)
        if _is_swept_by_opp(s, vs_sug):
            continue
        key = (-wins, -draws, money)
        if best_key is None or key > best_key:
            best_key = key
            best = (idx, dict(s))
    return best


def _pick_swept_natural(tab, pid: str, vs_sug: dict) -> Optional[Tuple[int, dict]]:
    """Pick the strongest natural split that loses all three chi to vs_sug."""
    best: Optional[Tuple[int, dict]] = None
    best_key: Optional[Tuple[int, int]] = None
    for idx, s in enumerate(tab._suggestions.get(pid) or []):
        if not _is_playable(tab, s):
            continue
        money, wins, _neg_losses, _draws = _score_suggestion_vs_opp(s, vs_sug)
        if wins != 0 or not _is_swept_by_opp(s, vs_sug):
            continue
        key = (money, idx)
        if best_key is None or key > best_key:
            best_key = key
            best = (idx, dict(s))
    return best


def _build_3p_balance(tab, sorted_pids: List[str]) -> Optional[AutoPlayPlan]:
    """
    Tối ưu nội bộ 3P:
      sorted_pids = [P_min, P_mid, P_max] theo gold tăng dần

    Bước 1 — P_min: Money split mạnh nhất.
    Bước 2 — P_mid: thua tự nhiên nhất vs P_min → đảm bảo P_min > P_mid.
    Bước 3 — P_max: thua tự nhiên nhất vs CẢ HAI → đảm bảo P_min > P_max và P_mid > P_max.

    Kết quả: P_min > P_mid > P_max (gold transfer đúng hướng).
    """
    p_min, p_mid, p_max = sorted_pids

    # Bước 1: P_min chơi tốt nhất
    min_result = _get_money_split(tab, p_min)
    if min_result is None:
        return None
    min_idx, min_sug = min_result

    # Bước 2: P_mid thua P_min tự nhiên
    mid_result = _pick_natural_lose(tab, p_mid, min_sug)
    if mid_result is None:
        return None
    mid_idx, mid_sug = mid_result

    # Bước 3: P_max thua cả P_min và P_mid
    max_result = _pick_natural_lose_vs_both(tab, p_max, min_sug, mid_sug)
    if max_result is None:
        return None
    max_idx, max_sug = max_result

    return AutoPlayPlan(
        kind="internal_balance",
        opp_index=-1,
        score=(0, 0, 0, 0),
        selected_index={p_min: min_idx, p_mid: mid_idx, p_max: max_idx},
        suggestions={p_min: min_sug, p_mid: mid_sug, p_max: max_sug},
        dependency_groups=(tuple(sorted_pids),),
    )


def _build_2p_balance(tab, sorted_pids: List[str]) -> Optional[AutoPlayPlan]:
    """
    Build the coordinated plan for the two profiles sharing one table.

    The profile on another table is intentionally excluded here. StrategyTab
    schedules its Money fallback as a separate dependency group.
    """
    p_less, p_more = sorted_pids

    # Bước 1: P_less chơi tốt nhất
    less_result = _get_money_split(tab, p_less)
    if less_result is None:
        return None
    less_idx, less_sug = less_result

    # Bước 2: P_more thua P_less tự nhiên
    more_result = _pick_natural_lose(tab, p_more, less_sug)
    if more_result is None:
        return None
    more_idx, more_sug = more_result

    selected_index: Dict[str, int] = {p_less: less_idx, p_more: more_idx}
    suggestions: Dict[str, dict] = {p_less: less_sug, p_more: more_sug}

    return AutoPlayPlan(
        kind="internal_balance",
        opp_index=-1,
        score=(0, 0, 0, 0),
        selected_index=selected_index,
        suggestions=suggestions,
        dependency_groups=(tuple(sorted_pids),),
    )


def _build_3p_sap_ham(tab, sorted_pids: List[str]) -> Optional[AutoPlayPlan]:
    """
    Internal 3P sap-ham cycle:
      - P_min plays Money.
      - P_max must lose all three chi to P_min.
      - P_mid must not also be swept by P_min, so this never becomes sap-lang.
    """
    p_min, p_mid, p_max = sorted_pids

    min_result = _get_money_split(tab, p_min)
    if min_result is None:
        return None
    min_idx, min_sug = min_result

    mid_result = _pick_not_swept_natural_lose(tab, p_mid, min_sug)
    if mid_result is None:
        return None
    mid_idx, mid_sug = mid_result

    max_result = _pick_swept_natural(tab, p_max, min_sug)
    if max_result is None:
        return None
    max_idx, max_sug = max_result

    if _is_swept_by_opp(mid_sug, min_sug):
        return None
    if not _is_swept_by_opp(max_sug, min_sug):
        return None

    return AutoPlayPlan(
        kind="internal_sap_ham",
        opp_index=-1,
        score=(0, 0, 0, 0),
        selected_index={p_min: min_idx, p_mid: mid_idx, p_max: max_idx},
        suggestions={p_min: min_sug, p_mid: mid_sug, p_max: max_sug},
        dependency_groups=(tuple(sorted_pids),),
    )


def _build_2p_sap_ham(tab, sorted_pids: List[str]) -> Optional[AutoPlayPlan]:
    """
    Internal 2P sap-ham cycle: the higher-gold profile loses all three chi to
    the lower-gold profile. Sap-lang does not apply to a two-player table.
    """
    p_less, p_more = sorted_pids

    less_result = _get_money_split(tab, p_less)
    if less_result is None:
        return None
    less_idx, less_sug = less_result

    more_result = _pick_swept_natural(tab, p_more, less_sug)
    if more_result is None:
        return None
    more_idx, more_sug = more_result

    if not _is_swept_by_opp(more_sug, less_sug):
        return None

    return AutoPlayPlan(
        kind="internal_sap_ham",
        opp_index=-1,
        score=(0, 0, 0, 0),
        selected_index={p_less: less_idx, p_more: more_idx},
        suggestions={p_less: less_sug, p_more: more_sug},
        dependency_groups=(tuple(sorted_pids),),
    )


def build_internal_balance_plan(tab, context: AutoRoomContext) -> Optional[AutoPlayPlan]:
    """
    Tối ưu nội bộ khi bàn chỉ có P của tool (không có UID ngoài).

    Điều kiện fire:
      - Tất cả gold khác nhau hoàn toàn (nếu bất kỳ cặp nào bằng nhau → fallback Money)
      - Không có gold=None trong controlled_pids (cần đủ dữ liệu để xếp thứ tự)
      - _suggestions[pid] đủ cho tất cả controlled_pids

    Thuật toán 3P — sorted = [P_min, P_mid, P_max] theo gold tăng dần:
      Bước 1 — P_min : _get_money_split        → bài mạnh nhất (P ít vàng được thắng)
      Bước 2 — P_mid : _pick_natural_lose(vs P_min) → thua P_min, đảm bảo P_min > P_mid
      Bước 3 — P_max : _pick_natural_lose_vs_both(vs P_min, vs P_mid)
                       → thua cả hai, đảm bảo P_mid > P_max và P_min > P_max
      Kết quả: P_min > P_mid > P_max (vàng chuyển từ nhiều → ít)

    Thuật toán 2P — sorted = [P_less, P_more] theo gold tăng dần:
      Bước 1 — P_less : _get_money_split           → bài mạnh nhất
      Bước 2 — P_more : _pick_natural_lose(vs P_less) → thua P_less tự nhiên
      P_third (không cùng bàn): StrategyTab lập lịch Money độc lập
      Kết quả: P_less > P_more (vàng chuyển từ nhiều → ít)

    Fallback → None: caller dùng build_money_fallback_plan.
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
    # sorted_pids: P_min (ít vàng, được thắng) → P_max (nhiều vàng, phải thua)
    _logger.info(
        "[INTERNAL-BALANCE] thu tu chien thuat: %s",
        " > ".join(
            f"{p}(vang={gold_map[p]})" for p in reversed(sorted_pids)
        ) + f"  [P_min={sorted_pids[0]}, P_max={sorted_pids[-1]}]"
    )

    if context.kind == "internal_3p":
        return _build_3p_balance(tab, sorted_pids)

    if context.kind == "internal_2p":
        return _build_2p_balance(tab, sorted_pids)

    return None


def build_internal_sap_ham_plan(tab, context: AutoRoomContext) -> Optional[AutoPlayPlan]:
    """
    Build the special internal cycle round after the normal no-sweep rounds.

    It is intentionally separate from build_internal_balance_plan because the
    normal helper avoids sap-ham, while this helper requires one controlled
    sap-ham and blocks sap-lang in 3P.
    """
    import logging as _log
    _logger = _log.getLogger("MauBinhTool")

    controlled = list(context.controlled_pids)
    if len(controlled) not in (2, 3):
        return None

    gold_map = context.gold_by_pid
    none_pids = [pid for pid in controlled if gold_map.get(pid) is None]
    if none_pids:
        _logger.info("[INTERNAL-SAP-HAM] skip: gold=None cho %s", none_pids)
        return None

    unique_golds = {gold_map[pid] for pid in controlled}
    if len(unique_golds) < len(controlled):
        _logger.info(
            "[INTERNAL-SAP-HAM] skip: gold co cap bang nhau %s",
            {p: gold_map.get(p) for p in controlled}
        )
        return None

    empty_pids = [pid for pid in controlled if not (tab._suggestions.get(pid) or [])]
    if empty_pids:
        _logger.info("[INTERNAL-SAP-HAM] skip: suggestions rong cho %s", empty_pids)
        return None

    profile_order = {p: i for i, p in enumerate(PROFILES)}
    sorted_pids = sorted(controlled, key=lambda p: (gold_map[p], profile_order.get(p, 99)))
    _logger.info(
        "[INTERNAL-SAP-HAM] thu tu: P_min=%s(vang=%s) P_max=%s(vang=%s)",
        sorted_pids[0], gold_map.get(sorted_pids[0]), sorted_pids[-1], gold_map.get(sorted_pids[-1])
    )

    if context.kind == "internal_3p":
        return _build_3p_sap_ham(tab, sorted_pids)
    if context.kind == "internal_2p":
        return _build_2p_sap_ham(tab, sorted_pids)
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


def _is_swept_by_opp(suggestion: dict, opp: dict) -> bool:
    my_three = _codes_to_threechi(suggestion)
    opp_three = _codes_to_threechi(opp)
    if my_three is None or opp_three is None:
        return False
    return bool(_eval_vs_opp(my_three, opp_three, allow_special_13=False).lose_all)


def _opp_has_bonus_line(opp: dict) -> bool:
    """Return True when OPP has a bonus line: straight flush, quads, or trips on top."""
    opp_three = _codes_to_threechi(opp)
    if opp_three is None:
        return False
    try:
        chi1_type = int(evaluate_5cards(opp_three.chi1)[0])
        chi2_type = int(evaluate_5cards(opp_three.chi2)[0])
        chi3_type = int(evaluate_3cards(opp_three.chi3)[0])
    except Exception:
        return False
    return bool(chi1_type in (7, 8) or chi2_type in (7, 8) or chi3_type == 3)


def _has_any_special(tab) -> bool:
    for pid in PROFILES:
        codes = list(tab._codes_slot_order.get(pid) or [])
        if len(codes) == 13:
            try:
                if detect_special_13(codes):
                    return True
            except Exception:
                pass
        for suggestion in list(tab._suggestions.get(pid) or []):
            try:
                if tab._is_special_row(suggestion):
                    return True
            except Exception:
                if suggestion.get("_is_special_row"):
                    return True
    return False


def _has_special_codes(codes: List[str]) -> bool:
    if len(codes) != 13:
        return False
    try:
        return bool(detect_special_13(codes))
    except Exception:
        return False


def _build_intentional_foul_plan(
    tab,
    *,
    opp_index: int,
    opp: dict,
    normal_plan: AutoPlayPlan,
) -> Optional[AutoPlayPlan]:
    """
    Build the last-resort foul plan after normal optimization cannot escape.

    Rules:
      - If all 3 profiles are swept, foul all 3 regardless of OPP bonus lines.
      - Otherwise, only foul the swept profiles when OPP has a bonus line
        (straight flush, quads, or trips on top).
    """
    if _has_any_special(tab):
        return None
    opp_codes = (
        list(opp.get("chi1_codes") or [])
        + list(opp.get("chi2_codes") or [])
        + list(opp.get("chi3_codes") or [])
    )
    if _has_special_codes(opp_codes):
        return None

    swept_pids = tuple(
        pid for pid in PROFILES
        if _is_swept_by_opp(normal_plan.suggestions.get(pid) or {}, opp)
    )
    if len(swept_pids) == len(PROFILES):
        foul_pids = PROFILES
    elif swept_pids and _opp_has_bonus_line(opp):
        foul_pids = swept_pids
    else:
        return None

    foul_suggestions: Dict[str, dict] = {}
    selected_index: Dict[str, int] = {}
    for pid in PROFILES:
        if pid not in foul_pids:
            normal_sug = normal_plan.suggestions.get(pid)
            if normal_sug is None:
                return None
            foul_suggestions[pid] = dict(normal_sug)
            if pid in normal_plan.selected_index:
                selected_index[pid] = int(normal_plan.selected_index[pid])
            continue
        money = _get_money_split(tab, pid)
        if money is None:
            return None
        _idx, money_suggestion = money
        foul = build_intentional_foul_suggestion(
            money_suggestion,
            list(tab._codes_slot_order.get(pid) or []),
        )
        if foul is None:
            return None
        foul_suggestions[pid] = dict(foul)

    return AutoPlayPlan(
        kind="intentional_foul",
        opp_index=int(opp_index),
        score=normal_plan.score,
        selected_index=selected_index,
        suggestions=foul_suggestions,
        report_binh_pids=tuple(pid for pid in foul_pids),
        dependency_groups=(PROFILES,),
    )


def build_best_plan_for_opp(
    tab,
    opp_index: int,
    opp: dict,
    *,
    allow_intentional_foul: bool = False,
) -> Optional[AutoPlayPlan]:
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
        dependency_groups=(PROFILES,),
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
    best_plan = normal_plan
    if combo is not None:
        combo_plan = AutoPlayPlan(
            kind="sap_lang",
            opp_index=int(opp_index),
            score=tuple(int(x) for x in combo.score),
            selected_index={},
            suggestions={pid: dict(s) for pid, s in combo.suggestions.items()},
            combo=combo,
            dependency_groups=(PROFILES,),
        )
        if combo_plan.score > normal_plan.score:
            best_plan = combo_plan

    if best_plan.kind != "normal" or not allow_intentional_foul:
        return best_plan
    foul_plan = _build_intentional_foul_plan(
        tab,
        opp_index=opp_index,
        opp=opp,
        normal_plan=normal_plan,
    )
    return foul_plan or best_plan


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
        dependency_groups=(PROFILES,),
    )


def build_money_fallback_plan(tab, profile_ids=None) -> Optional[AutoPlayPlan]:
    """
    Build an OPP-free safety plan for every ready profile.

    Prefer a reportable special hand. Otherwise use the exact Money split
    captured during that profile's normal arranger scan.
    """
    selected_index: Dict[str, int] = {}
    suggestions: Dict[str, dict] = {}
    report_binh_pids: List[str] = []
    applied_keys = getattr(tab, "_auto_play_applied_profile_keys", set()) or set()

    source_profiles = PROFILES if profile_ids is None else profile_ids
    scoped_profiles = tuple(pid for pid in source_profiles if pid in PROFILES)
    for pid in scoped_profiles:
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
        dependency_groups=tuple((pid,) for pid in suggestions),
    )


def _has_553_split(s: Optional[dict]) -> bool:
    if not s:
        return False
    return (
        len(list(s.get("chi1_codes") or [])) == 5
        and len(list(s.get("chi2_codes") or [])) == 5
        and len(list(s.get("chi3_codes") or [])) == 3
    )


def build_auto_play_plan(
    tab,
    max_opp: int = 3,
    *,
    allow_intentional_foul: bool = False,
) -> Optional[AutoPlayPlan]:
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
        return build_best_plan_for_opp(
            tab,
            idx,
            opp,
            allow_intentional_foul=allow_intentional_foul,
        )
    return build_partial_plan_for_opp(tab, idx, opp)
