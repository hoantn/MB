from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from collections import Counter
from typing import List, Tuple, Optional, Any, Dict, Iterable

from engine.card import Card
from core.constants import RANK_ORDER

from engine.arranger_parts.eval_utils import _eval_5, _eval_3, _map_eval_top_to_5scale
from engine.arranger_parts.splits import _validate_no_foul
from engine.arranger_parts.break_patterns import generate_break_variants
from engine.money_scoring import detect_special_13
from engine.arranger_parts.special13 import build_special_split
from engine.arranger_parts.beauty_laws import _normalize_kicker_distribution


# =====================================================================
# LOW-LEVEL HELPERS
# =====================================================================

_RANK_INDEX = {r: i for i, r in enumerate(RANK_ORDER)}


def _rv(c: Card) -> int:
    return _RANK_INDEX[c.rank]


def _codes(hand: List[Card]) -> Tuple[str, ...]:
    return tuple(sorted([x.to_code() for x in hand]))


# =====================================================================
# BEAUTY LAWS (giữ lại – chỉ dùng làm đẹp / tie-break)
# =====================================================================

def _trash_law_key(
    chi1: List[Card],
    chi2: List[Card],
    chi3: List[Card],
) -> Tuple[int, int, int, int, int, int]:
    """
    LUẬT DỒN RÁC THEO TỪNG CHI (giữ y như bản bạn đang dùng):

      - Rác = kicker theo TỪNG CHI (lá không thuộc "bộ chính" của chi đó).
      - Ưu tiên:
          1) Chi3: nhiều rác và rác to
          2) Chi2: nhiều rác và rác to
          3) Chi1: ít rác, rác nhỏ

    Key: (len3, sum3, len2, sum2, -len1, -sum1)
    """

    def _kickers_5(hand: List[Card]) -> List[Card]:
        if len(hand) != 5:
            return []

        cnt = Counter(_rv(c) for c in hand)
        values = sorted(cnt.values(), reverse=True)

        # [3,2] Cù: không rác
        if values == [3, 2]:
            return []

        if values in ([4, 1], [2, 2, 1], [3, 1, 1], [2, 1, 1, 1]):
            single_ranks = {r for r, n in cnt.items() if n == 1}
            return [c for c in hand if _rv(c) in single_ranks]

        # [1,1,1,1,1] có thể là: thùng / sảnh / thùng phá sảnh / hoặc mậu 5 lá
        if values == [1, 1, 1, 1, 1]:
            # flush?
            is_flush = (len({c.suit for c in hand}) == 1)

            # straight? (xử lý cả A2345)
            idxs = sorted({_rv(c) for c in hand})
            is_wheel = (idxs == [0, 1, 2, 3, 12])  # A2345 nếu RANK_ORDER là 2..A
            is_normal_straight = (len(idxs) == 5 and (idxs[-1] - idxs[0] == 4))
            if is_normal_straight:
                # đảm bảo liên tiếp thật
                is_normal_straight = all(idxs[i] + 1 == idxs[i + 1] for i in range(4))

            is_straight = is_wheel or is_normal_straight

            # flush/straight => 0 rác (không phá bộ)
            if is_flush or is_straight:
                return []

            # high-card 5 => 5 rác (tất cả không tham gia tạo thế)
            return list(hand)

        # Các trường hợp còn lại (an toàn): coi như không rác
        return []

    def _kickers_3(hand: List[Card]) -> List[Card]:
        if len(hand) != 3:
            return []

        cnt = Counter(_rv(c) for c in hand)
        values = sorted(cnt.values(), reverse=True)

        if values == [3]:
            return []
        if values == [2, 1]:
            single_ranks = {r for r, n in cnt.items() if n == 1}
            return [c for c in hand if _rv(c) in single_ranks]

        # [1,1,1] mậu 3 lá: cả 3 là rác
        return list(hand)

    k1 = _kickers_5(chi1)
    k2 = _kickers_5(chi2)
    k3 = _kickers_3(chi3)

    len1 = len(k1)
    len2 = len(k2)
    len3 = len(k3)

    sum1 = sum(_rv(c) for c in k1) if k1 else 0
    sum2 = sum(_rv(c) for c in k2) if k2 else 0
    sum3 = sum(_rv(c) for c in k3) if k3 else 0

    return (len3, sum3, len2, sum2, -len1, -sum1)


def _chi_structure_key(chi: List[Card]) -> Tuple[int, int, int]:
    """
    Luật cấu trúc riêng cho CHI 5 lá (chỉ dùng làm tie-break, KHÔNG quyết định cấu trúc):

      - Cù (3+2): trips càng to càng tốt, đôi càng nhỏ càng tốt
      - Thú (2,2,1): spread càng lớn càng tốt, và đôi to nhất càng to càng tốt
    """
    if len(chi) != 5:
        return (0, 0, 0)

    cnt = Counter(_rv(c) for c in chi)
    values = sorted(cnt.values())

    if values == [2, 3]:
        trip_rank = max(r for r, k in cnt.items() if k == 3)
        pair_rank = min(r for r, k in cnt.items() if k == 2)
        return (2, trip_rank, -pair_rank)

    pair_ranks = [r for r, k in cnt.items() if k == 2]
    if len(pair_ranks) == 2:
        lo = min(pair_ranks)
        hi = max(pair_ranks)
        spread = hi - lo
        return (1, spread, hi)

    return (0, 0, 0)


def _structure_law_key(
    chi1: List[Card],
    chi2: List[Card],
) -> Tuple[int, int, int, int, int, int]:
    s1 = _chi_structure_key(chi1)
    s2 = _chi_structure_key(chi2)
    return (s1[0], s1[1], s1[2], s2[0], s2[1], s2[2])


def _pair_distribution_key(
    chi1: List[Card],
    chi2: List[Card],
    chi3: List[Card],
) -> Tuple[int, ...]:
    """
    Luật phân bố đôi/trips/quads (chỉ làm tie-break).

    Style của bạn: ưu tiên dup mạnh xuống Chi3 -> Chi2 -> Chi1.
    """

    def chi_pair_stats(chi: List[Card]) -> Tuple[int, int, int, int, int]:
        cnt = Counter(_rv(c) for c in chi)

        pair_ranks: List[int] = []
        trip_ranks: List[int] = []
        dup_units: List[int] = []

        for r, k in cnt.items():
            if k >= 2:
                pair_ranks.append(r)
                dup_units.append(r)      # pair = 1 unit
                if k >= 3:
                    trip_ranks.append(r)
                    dup_units.append(r)  # trips thêm 1 unit (tổng 2)

        if not dup_units:
            return (0, 0, 0, 0, 0)

        pair_hi = max(pair_ranks) if pair_ranks else 0
        pair_lo = min(pair_ranks) if pair_ranks else 0
        trip_hi = max(trip_ranks) if trip_ranks else 0
        sum_dup = sum(dup_units)

        return (len(dup_units), pair_hi, pair_lo, trip_hi, sum_dup)

    c1 = chi_pair_stats(chi1)
    c2 = chi_pair_stats(chi2)
    c3 = chi_pair_stats(chi3)

    return (
        c3[0], c3[1], c3[2], c3[3], c3[4],
        c2[0], c2[1], c2[2], c2[3], c2[4],
        c1[0], c1[1], c1[2], c1[3], c1[4],
    )

def _apply_pair_allocation_within_template(
    chi1: List[Card],
    chi2: List[Card],
    chi3: List[Card],
) -> Tuple[List[Card], List[Card], List[Card]]:
    """
    Rule (áp dụng SAU khi template đã chốt):
      - Chỉ hoán đổi các NHÓM ĐÔI (rank có đúng 2 lá) giữa các chi,
        để ưu tiên đôi mạnh về Chi3 -> Chi2 -> Chi1.
      - KHÔNG được làm đổi pattern của từng chi (cù/thú/đôi...), tức:
          + Chi 5 lá: giữ nguyên multiset counts (vd [3,2], [2,2,1], [2,1,1,1]...)
          + Chi 3 lá: giữ nguyên multiset counts (vd [2,1] hoặc [1,1,1] hoặc [3])
      - Nếu không rebuild được hoặc bị foul -> trả split gốc.
    """
    from collections import Counter

    def _pat(hand: List[Card]) -> Tuple[int, ...]:
        cnt = Counter(_rv(c) for c in hand)
        return tuple(sorted(cnt.values(), reverse=True))

    def _pair_ranks(hand: List[Card]) -> List[int]:
        cnt = Counter(_rv(c) for c in hand)
        return sorted([r for r, n in cnt.items() if n == 2], reverse=True)

    def _pair_groups(hand: List[Card]) -> Dict[int, List[Card]]:
        # rank -> đúng 2 card
        ranks = _pair_ranks(hand)
        out: Dict[int, List[Card]] = {}
        for r in ranks:
            grp = [c for c in hand if _rv(c) == r]
            if len(grp) == 2:
                out[r] = grp
        return out

    # pattern gốc (để đảm bảo không đổi template của từng chi)
    p1, p2, p3 = _pat(chi1), _pat(chi2), _pat(chi3)

    # số slot đôi mà từng chi đang “tiêu thụ” trong template hiện tại
    s1 = len(_pair_ranks(chi1))
    s2 = len(_pair_ranks(chi2))
    s3 = len(_pair_ranks(chi3))

    total_slots = s1 + s2 + s3
    if total_slots == 0:
        return chi1, chi2, chi3

    g1 = _pair_groups(chi1)
    g2 = _pair_groups(chi2)
    g3 = _pair_groups(chi3)

    # gom toàn bộ nhóm đôi hiện có trong split
    pool: List[Tuple[int, List[Card]]] = []
    for r, grp in g1.items():
        pool.append((r, grp))
    for r, grp in g2.items():
        pool.append((r, grp))
    for r, grp in g3.items():
        pool.append((r, grp))

    if len(pool) != total_slots:
        # Có gì đó không khớp (hiếm), trả về gốc cho an toàn
        return chi1, chi2, chi3

    def _rebuild(
        orig: List[Card],
        orig_pairs: Dict[int, List[Card]],
        take: List[Tuple[int, List[Card]]],
    ) -> Optional[List[Card]]:
        # remove các lá thuộc nhóm đôi cũ (theo code để tránh remove nhầm khi cùng rank xuất hiện thêm)
        old_codes = {c.to_code() for grp in orig_pairs.values() for c in grp}
        base = [c for c in orig if c.to_code() not in old_codes]

        # add nhóm đôi mới
        add_cards: List[Card] = []
        for _, grp in take:
            add_cards.extend(grp)

        out = base + add_cards
        if len(out) != len(orig):
            return None
        return out

    # =========================
    # NEW: search best valid assignment (thay cho take3/take2/take1 cứng)
    # =========================
    idx_all = list(range(len(pool)))
    best_key: Optional[Tuple[int, ...]] = None
    best_split: Optional[Tuple[List[Card], List[Card], List[Card]]] = None

    def _try_assignment(idxs3: Tuple[int, ...], idxs2: Tuple[int, ...]) -> None:
        nonlocal best_key, best_split

        set3 = set(idxs3)
        set2 = set(idxs2)
        if set3 & set2:
            return

        take3 = [pool[i] for i in idxs3]
        take2 = [pool[i] for i in idxs2]
        take1 = [pool[i] for i in idx_all if i not in set3 and i not in set2]

        n3 = _rebuild(chi3, g3, take3)
        n2 = _rebuild(chi2, g2, take2)
        n1 = _rebuild(chi1, g1, take1)
        if n1 is None or n2 is None or n3 is None:
            return

        # giữ nguyên pattern từng chi
        if _pat(n1) != p1 or _pat(n2) != p2 or _pat(n3) != p3:
            return

        # không binh lủng
        if not _validate_no_foul(n1, n2, n3):
            return

        # chấm điểm theo style: ưu tiên dup mạnh xuống Chi3 -> Chi2 -> Chi1
        k = _pair_distribution_key(n1, n2, n3)
        if best_key is None or k > best_key:
            best_key = k
            best_split = (list(n1), list(n2), list(n3))

    # enumerate tất cả cách gán (rất nhẹ vì số đôi nhỏ)
    if s3 == 0:
        # chi3 không có slot đôi
        for idxs2 in combinations(idx_all, s2):
            _try_assignment((), idxs2)
    else:
        for idxs3 in combinations(idx_all, s3):
            remain = [i for i in idx_all if i not in set(idxs3)]
            for idxs2 in combinations(remain, s2):
                _try_assignment(idxs3, idxs2)

    if best_split is None:
        return chi1, chi2, chi3

    return best_split
    
def _normalize_style_distribution(
    chi1: List[Card],
    chi2: List[Card],
    chi3: List[Card],
) -> Tuple[List[Card], List[Card], List[Card]]:
    # 1) phân bổ đôi theo template đã chốt
    chi1, chi2, chi3 = _apply_pair_allocation_within_template(list(chi1), list(chi2), list(chi3))
    # 2) dồn kicker (beauty_laws) như hiện tại
    return _normalize_kicker_distribution(list(chi1), list(chi2), list(chi3))

# =====================================================================
# HAND PROFILE (GIỮ TÊN HÀM để không vỡ import; giờ chỉ dùng nhẹ)
# =====================================================================

@dataclass
class HandProfile:
    # Giữ cấu trúc để không vỡ những chỗ khác nếu có import.
    quads: List[List[Card]]
    trips: List[List[Card]]
    pairs: List[List[Card]]
    singles: List[Card]
    suit_groups: Dict[str, List[Card]]
    flush_suits: List[str]
    straight_ranks: List[List[int]]


def build_hand_profile(cards: List[Card]) -> HandProfile:
    """
    Giữ lại để phục vụ thống kê/diagnostic, không còn là trung tâm pipeline.
    """
    if len(cards) != 13:
        raise ValueError("build_hand_profile chỉ dùng cho đúng 13 lá")

    rank_cnt: Counter[str] = Counter(c.rank for c in cards)
    rank_to_cards: Dict[str, List[Card]] = {}
    for c in cards:
        rank_to_cards.setdefault(c.rank, []).append(c)

    quads: List[List[Card]] = []
    trips: List[List[Card]] = []
    pairs: List[List[Card]] = []
    singles: List[Card] = []

    for r, n in rank_cnt.items():
        group = rank_to_cards[r]
        if n >= 4:
            quads.append(group[:4])
            singles.extend(group[4:])
        elif n == 3:
            trips.append(group)
        elif n == 2:
            pairs.append(group)
        else:
            singles.extend(group)

    suit_groups: Dict[str, List[Card]] = {}
    for c in cards:
        suit_groups.setdefault(c.suit, []).append(c)
    flush_suits = [s for s, g in suit_groups.items() if len(g) >= 5]

    seen_rank_idxs = sorted({_RANK_INDEX[c.rank] for c in cards})
    straight_ranks: List[List[int]] = []
    if seen_rank_idxs:
        cur = [seen_rank_idxs[0]]
        for idx in seen_rank_idxs[1:]:
            if idx == cur[-1] + 1:
                cur.append(idx)
            else:
                if len(cur) >= 5:
                    straight_ranks.append(cur[:])
                cur = [idx]
        if len(cur) >= 5:
            straight_ranks.append(cur)

    return HandProfile(
        quads=quads,
        trips=trips,
        pairs=pairs,
        singles=singles,
        suit_groups=suit_groups,
        flush_suits=flush_suits,
        straight_ranks=straight_ranks,
    )


def classify_profile(profile: HandProfile) -> str:
    """
    Giữ lại để không vỡ API (giờ chỉ dùng tham khảo).
    """
    if profile.quads:
        return "Q"
    if len(profile.trips) >= 2 or (len(profile.trips) >= 1 and len(profile.pairs) >= 2):
        return "F"
    if len(profile.pairs) >= 4:
        return "P"
    if profile.flush_suits or profile.straight_ranks:
        return "R"
    if len(profile.trips) == 1 or (1 <= len(profile.pairs) <= 3):
        return "M"
    return "T"


# =====================================================================
# CORE: find best Chi1, then best Chi2/Chi3 from remaining
# =====================================================================

def _find_best_5_hand_with_eval(cards: List[Card]) -> Tuple[Optional[List[Card]], Optional[Tuple[int, ...]]]:
    """
    Tìm 5 lá mạnh nhất trong 13 lá theo _eval_5 (đúng định nghĩa 'thế trục Chi1').
    """
    best_hand: Optional[List[Card]] = None
    best_eval: Optional[Tuple[int, ...]] = None

    idxs = list(range(len(cards)))
    for comb in combinations(idxs, 5):
        hand = [cards[i] for i in comb]
        e = _eval_5(hand)
        if best_eval is None or e > best_eval:
            best_eval = e
            best_hand = hand

    return best_hand, best_eval


def _best_mid_top_for_bottom(
    remaining_cards: List[Card],
    eval_bottom: Tuple[int, ...],
) -> Tuple[Optional[List[Card]], Optional[List[Card]], Optional[Tuple[int, ...]], Optional[Tuple[int, ...]]]:
    """
    Quy tắc MỚI (đúng ý bạn):

      - Chi2 = hand mạnh nhất có thể từ 8 lá còn lại,
              miễn sao không binh lủng với Chi1:
                  top <= mid <= bottom
      - Chi3 = 3 lá còn lại.
      - Luật beauty (rác/đôi/cấu trúc) CHỈ làm tie-break, không làm yếu Chi2.

    Score ưu tiên:
      1) e2 (Chi2 mạnh nhất)
      2) map(e3) (Chi3 mạnh nhất)
      3) trash_key (dồn rác theo style)
      4) pair_key (phân bố đôi theo style)
      5) structure_key (cù/thú đẹp)
    """
    if len(remaining_cards) != 8:
        return None, None, None, None

    best_score: Optional[Any] = None
    best_mid: Optional[List[Card]] = None
    best_top: Optional[List[Card]] = None
    best_e2: Optional[Tuple[int, ...]] = None
    best_e3: Optional[Tuple[int, ...]] = None

    idxs = list(range(8))
    for mid_idx in combinations(idxs, 5):
        mid = [remaining_cards[i] for i in mid_idx]
        top = [remaining_cards[i] for i in idxs if i not in mid_idx]

        e2 = _eval_5(mid)
        e3 = _eval_3(top)

        if _map_eval_top_to_5scale(e3) > e2:
            continue
        if e2 > eval_bottom:
            continue

        trash_key = _trash_law_key([], mid, top)  # chi1 không tham gia đoạn này
        pair_key = _pair_distribution_key([], mid, top)
        structure_key = _structure_law_key([], mid)

        score = (e2, _map_eval_top_to_5scale(e3), trash_key, pair_key, structure_key)

        if best_score is None or score > best_score:
            best_score = score
            best_mid = mid
            best_top = top
            best_e2 = e2
            best_e3 = e3

    return best_mid, best_top, best_e2, best_e3

def _best_mid_top_for_bottom_focus(
    remaining_cards: List[Card],
    eval_bottom: Tuple[int, ...],
    focus: str,  # "mid" hoặc "top"
) -> Tuple[Optional[List[Card]], Optional[List[Card]], Optional[Tuple[int, ...]], Optional[Tuple[int, ...]]]:
    """
    Sinh split theo "focus" sau khi đã cố định Chi1.

    - focus="mid": đẩy toàn lực Chi2 (ưu tiên e2 trước)
    - focus="top": đẩy toàn lực Chi3 (ưu tiên e3 trước)

    Lưu ý: KHÔNG tính trash_key trong score (nhưng vẫn normalize kicker ở bước cuối pipeline).
    """
    if focus not in ("mid", "top"):
        raise ValueError(f"Invalid focus={focus!r}, expected 'mid' or 'top'")

    if len(remaining_cards) != 8:
        return None, None, None, None

    best_score = None
    best_mid = None
    best_top = None
    best_e2 = None
    best_e3 = None

    idxs = list(range(8))
    for mid_idx in combinations(idxs, 5):
        mid = [remaining_cards[i] for i in mid_idx]
        top = [remaining_cards[i] for i in idxs if i not in mid_idx]

        e2 = _eval_5(mid)
        e3 = _eval_3(top)

        # Ràng buộc không binh lủng: top <= mid <= bottom
        if _map_eval_top_to_5scale(e3) > e2:
            continue
        if e2 > eval_bottom:
            continue

        # Không tính rác. Chỉ dùng đôi/cấu trúc làm tie-break sau strength.
        pair_key = _pair_distribution_key([], mid, top)
        structure_key = _structure_law_key([], mid)

        if focus == "mid":
            score = (e2, _map_eval_top_to_5scale(e3), pair_key, structure_key)
        else:  # focus == "top"
            score = (_map_eval_top_to_5scale(e3), pair_key, e2, structure_key)

        if best_score is None or score > best_score:
            best_score = score
            best_mid = mid
            best_top = top
            best_e2 = e2
            best_e3 = e3

    return best_mid, best_top, best_e2, best_e3

# =====================================================================
# TEMPLATE / RULE KEYS
# =====================================================================

def _template_key_from_evals(
    e1: Tuple[int, ...],
    e2: Tuple[int, ...],
    e3: Tuple[int, ...],
) -> Tuple[int, int, int]:
    t1 = int(e1[0]) if isinstance(e1, tuple) and len(e1) else int(e1)
    t2 = int(e2[0]) if isinstance(e2, tuple) and len(e2) else int(e2)
    t3 = int(e3[0]) if isinstance(e3, tuple) and len(e3) else int(e3)
    return (t1, t2, t3)


def _rule_primary_key_from_evals(
    e1: Tuple[int, ...],
    e2: Tuple[int, ...],
    e3: Tuple[int, ...],
) -> Tuple[int, int, int]:
    """
    Rule key tổng quát: ưu tiên type Chi1 rồi Chi2 rồi Chi3.
    """
    return _template_key_from_evals(e1, e2, e3)


# =====================================================================
# NEW BEAUTY MAIN PIPELINE (giữ tên hàm để không vỡ chỗ khác)
# =====================================================================

def _arrange_cards_template_beauty(
    cards: List[Card],
) -> Tuple[List[Card], List[Card], List[Card]]:
    """
    PIPELINE MỚI (đã thay hoàn toàn cách cũ):

      1) Nếu có bài đặc biệt 13 lá -> ưu tiên dựng luôn (không lủng).
      2) Chọn Chi1 = 5 lá mạnh nhất (thế trục duy nhất).
      3) Chi2 = hand mạnh nhất từ 8 lá còn lại theo _best_mid_top_for_bottom.
      4) Chi3 = phần còn lại.
      5) Normalize kicker ở bước cuối.

    Không còn chạy generator nhóm Q/F/P/R/M/T.
    """
    if len(cards) != 13:
        raise ValueError("arrange_cards cần đúng 13 lá")

    # 1) Special 13 (nếu có)
    special_type = detect_special_13(cards)
    if special_type is not None:
        try:
            sp = build_special_split(cards, special_type)
        except Exception:
            sp = None
        if sp is not None:
            b, m, t = sp
            b, m, t = _normalize_style_distribution(list(b), list(m), list(t))
            return list(b), list(m), list(t)

    # 2) Main Chi1
    chi1, e1 = _find_best_5_hand_with_eval(cards)
    if chi1 is None or e1 is None:
        # cực hiếm: fallback an toàn
        cards_sorted = sorted(cards, key=_rv, reverse=True)
        b = cards_sorted[:5]
        m = cards_sorted[5:10]
        t = cards_sorted[10:]
        b, m, t = _normalize_style_distribution(list(b), list(m), list(t))
        return b, m, t

    # 3) Best Chi2/Chi3 from remaining
    rem = [c for c in cards if c not in chi1]
    if len(rem) != 8:
        # fallback an toàn
        cards_sorted = sorted(cards, key=_rv, reverse=True)
        b = cards_sorted[:5]
        m = cards_sorted[5:10]
        t = cards_sorted[10:]
        b, m, t = _normalize_style_distribution(list(b), list(m), list(t))
        return b, m, t

    chi2, chi3, e2, e3 = _best_mid_top_for_bottom(rem, e1)
    if chi2 is None or chi3 is None or e2 is None or e3 is None:
        # fallback an toàn: chia theo strength thô
        cards_sorted = sorted(cards, key=_rv, reverse=True)
        b = cards_sorted[:5]
        m = cards_sorted[5:10]
        t = cards_sorted[10:]
        b, m, t = _normalize_style_distribution(list(b), list(m), list(t))
        return b, m, t

    # 4) Double-check không binh lủng
    if not _validate_no_foul(chi1, chi2, chi3):
        # fallback an toàn
        cards_sorted = sorted(cards, key=_rv, reverse=True)
        b = cards_sorted[:5]
        m = cards_sorted[5:10]
        t = cards_sorted[10:]
        b, m, t = _normalize_style_distribution(list(b), list(m), list(t))
        return b, m, t

    # 5) Normalize kicker cuối
    chi1, chi2, chi3 = _normalize_style_distribution(list(chi1), list(chi2), list(chi3))
    return chi1, chi2, chi3


# =====================================================================
# SCORING + TOPK (giữ tên hàm để không vỡ UI)
# =====================================================================

def _score_beauty_split(
    chi1: List[Card],
    chi2: List[Card],
    chi3: List[Card],
    e1: Optional[Tuple[int, ...]] = None,
    e2: Optional[Tuple[int, ...]] = None,
    e3: Optional[Tuple[int, ...]] = None,
) -> Optional[Tuple[Any, Tuple[List[Card], List[Card], List[Card]]]]:
    if e1 is None:
        e1 = _eval_5(chi1)
    if e2 is None:
        e2 = _eval_5(chi2)
    if e3 is None:
        e3 = _eval_3(chi3)

    if not _validate_no_foul(chi1, chi2, chi3):
        return None

    tpl = _template_key_from_evals(e1, e2, e3)
    rule_key = _rule_primary_key_from_evals(e1, e2, e3)
    trash_key = _trash_law_key(chi1, chi2, chi3)
    pair_key = _pair_distribution_key(chi1, chi2, chi3)
    structure_key = _structure_law_key(chi1, chi2)

    # Theo hướng mới: rule (hand-type) vẫn là ưu tiên đầu,
    # sau đó giữ "bài chơi thật": rác, đôi, cấu trúc chỉ là tie-break.
    score = (rule_key, e1, e2, _map_eval_top_to_5scale(e3), trash_key, pair_key, structure_key, tpl)

    split = (list(chi1), list(chi2), list(chi3))
    return score, split

def _append_unique_candidate(
    out: List[Tuple[List[Card], List[Card], List[Card]]],
    seen: set,
    chi1: List[Card],
    chi2: List[Card],
    chi3: List[Card],
) -> None:
    if chi1 is None or chi2 is None or chi3 is None:
        return
    if len(chi1) != 5 or len(chi2) != 5 or len(chi3) != 3:
        return

    chi1, chi2, chi3 = _normalize_style_distribution(list(chi1), list(chi2), list(chi3))
    if not _validate_no_foul(chi1, chi2, chi3):
        return

    sig = (_codes(chi1), _codes(chi2), _codes(chi3))
    if sig in seen:
        return
    seen.add(sig)
    out.append((chi1, chi2, chi3))
def _build_axes_chi1(cards: List[Card]) -> List[List[Card]]:
    """
    Sinh danh sách "trục Chi1" theo các thế bài chính (ít nhưng đủ).
    Mục tiêu: thay cho best_by_type brute-force 13C5.

    Output: list các hand 5 lá (đã unique theo codes), ưu tiên mạnh -> yếu theo _eval_5.
    """
    if len(cards) != 13:
        return []

    profile = build_hand_profile(cards)

    def sort_desc(cs: List[Card]) -> List[Card]:
        return sorted(cs, key=_rv, reverse=True)

    def uniq_push(out: List[List[Card]], hand: Optional[List[Card]], seen: set) -> None:
        if not hand or len(hand) != 5:
            return
        sig = _codes(hand)
        if sig in seen:
            return
        seen.add(sig)
        out.append(hand)

    axes: List[List[Card]] = []
    seen: set = set()

    # -------------------------
    # 1) QUADS (Tứ quý) -> 4 + kicker
    # -------------------------
    if profile.quads:
        quad = sort_desc(profile.quads[0])[:4]  # quads đã là 4 lá
        remain = [c for c in cards if c not in quad]
        kicker = sort_desc(remain)[:1]
        uniq_push(axes, quad + kicker, seen)

    # -------------------------
    # 2) FULL HOUSE (Cù) -> trips + pair
    # -------------------------
    if profile.trips:
        # chọn trips cao nhất
        trips_sorted = sorted(profile.trips, key=lambda g: _rv(sort_desc(g)[0]), reverse=True)
        for trip in trips_sorted:
            trip3 = sort_desc(trip)[:3]
            remain = [c for c in cards if c not in trip3]

            # pair: ưu tiên đôi cao nhất từ remaining (pair thật hoặc lấy 2 lá từ trip khác)
            cnt = Counter(_rv(c) for c in remain)
            pair_ranks = sorted([r for r, n in cnt.items() if n >= 2], reverse=True)
            if pair_ranks:
                pr = pair_ranks[0]
                pair2 = sort_desc([c for c in remain if _rv(c) == pr])[:2]
                uniq_push(axes, trip3 + pair2, seen)
                break

    # -------------------------
    # 3) FLUSH (Thùng) -> lấy 5 lá cao nhất của 1 suit flush
    # -------------------------
    for s in profile.flush_suits:
        suit_cards = sort_desc(profile.suit_groups.get(s, []))
        if len(suit_cards) >= 5:
            uniq_push(axes, suit_cards[:5], seen)

    # -------------------------
    # 4) STRAIGHT (Sảnh) -> dựng theo rank sequences có sẵn trong profile
    #     (chọn 5-rank window, mỗi rank lấy lá cao nhất hiện có)
    # -------------------------
    # profile.straight_ranks là các đoạn liên tiếp length>=5 theo index rank
    best_straight = None
    for seq in profile.straight_ranks:
        # duyệt mọi cửa sổ 5 trong seq
        for i in range(0, len(seq) - 4):
            window = seq[i:i+5]
            # pick 1 card per rank (rank idx) -> dùng card cao nhất (thực tế suit không quan trọng)
            chosen: List[Card] = []
            for ridx in window:
                r = RANK_ORDER[ridx]
                candidates = [c for c in cards if c.rank == r]
                if not candidates:
                    chosen = []
                    break
                chosen.append(sort_desc(candidates)[0])
            if len(chosen) == 5:
                e = _eval_5(chosen)
                if best_straight is None or e > best_straight[0]:
                    best_straight = (e, chosen)
    if best_straight is not None:
        uniq_push(axes, best_straight[1], seen)

    # -------------------------
    # 5) TRIPS (Xám) -> trips + 2 kicker cao nhất
    # -------------------------
    if profile.trips:
        trip = sorted(profile.trips, key=lambda g: _rv(sort_desc(g)[0]), reverse=True)[0]
        trip3 = sort_desc(trip)[:3]
        remain = [c for c in cards if c not in trip3]
        kickers = sort_desc(remain)[:2]
        uniq_push(axes, trip3 + kickers, seen)

    # -------------------------
    # 6) TWO PAIRS (Thú) -> 2 đôi cao nhất + 1 kicker cao nhất
    # -------------------------
    if len(profile.pairs) >= 2:
        pairs_sorted = sorted(profile.pairs, key=lambda g: _rv(sort_desc(g)[0]), reverse=True)
        p1 = sort_desc(pairs_sorted[0])[:2]
        p2 = sort_desc(pairs_sorted[1])[:2]
        remain = [c for c in cards if c not in p1 and c not in p2]
        kicker = sort_desc(remain)[:1]
        uniq_push(axes, p1 + p2 + kicker, seen)

    # -------------------------
    # 7) ONE PAIR (Đôi) -> đôi cao nhất + 3 kicker cao nhất
    # -------------------------
    if profile.pairs:
        pair = sorted(profile.pairs, key=lambda g: _rv(sort_desc(g)[0]), reverse=True)[0]
        p2 = sort_desc(pair)[:2]
        remain = [c for c in cards if c not in p2]
        kickers = sort_desc(remain)[:3]
        uniq_push(axes, p2 + kickers, seen)

    # -------------------------
    # 8) HIGH CARD (Mậu) -> 5 lá cao nhất
    # -------------------------
    uniq_push(axes, sort_desc(cards)[:5], seen)

    # sort axes mạnh -> yếu theo _eval_5 (đảm bảo thứ tự trục đúng)
    axes.sort(key=lambda h: _eval_5(h), reverse=True)
    return axes

def arrange_beauty_topk(
    cards: List[Card],
    k: int = 256,
    max_candidates: int = 256,
) -> List[Tuple[List[Card], List[Card], List[Card]]]:
    """
    TOPK MỚI theo kiến trúc mới:

      - Candidate 1: bài chính duy nhất từ _arrange_cards_template_beauty
      - Candidate break: thay Chi1 bằng "best per hand-type" (mỗi type 1 cái) -> tự build Chi2/Chi3 theo strength
      - Candidate break nâng cao: generate_break_variants(cards) (giữ lại công sức bạn viết)

    Sau đó score bằng _score_beauty_split, sort desc, unique theo codes, lấy top-k.
    """
    if len(cards) != 13:
        raise ValueError("arrange_beauty_topk cần đúng 13 lá")

    candidates: List[Tuple[List[Card], List[Card], List[Card]]] = []
    pinned: List[Tuple[List[Card], List[Card], List[Card]]] = []
    pinned_seen: set = set()

    # 1) Main + 2 biến thể focus (GHIM để luôn xuất hiện đúng thứ tự)
    b, m, t = _arrange_cards_template_beauty(cards)

    # ghim main
    _append_unique_candidate(pinned, pinned_seen, list(b), list(m), list(t))

    # ghim focus nếu có thể (chỉ khi chi1 là 5 lá và còn đúng 8 lá)
    chi1_main = list(b)
    if len(chi1_main) == 5:
        e1_main = _eval_5(chi1_main)
        rem_main = [c for c in cards if c not in chi1_main]
        if len(rem_main) == 8:
            # focus Chi2
            mid2, top2, _, _ = _best_mid_top_for_bottom_focus(rem_main, e1_main, "mid")
            _append_unique_candidate(pinned, pinned_seen, chi1_main, mid2, top2)

            # focus Chi3
            mid3, top3, _, _ = _best_mid_top_for_bottom_focus(rem_main, e1_main, "top")
            _append_unique_candidate(pinned, pinned_seen, chi1_main, mid3, top3)

    # 2) Axes Chi1 theo các thế bài chính (nhẹ, đủ dùng, đúng hướng "1 main + bẻ")
    axes = _build_axes_chi1(cards)

    # Dùng set riêng để tránh đẩy candidates trùng quá nhiều
    seen_axes: set = set()

    for chi1 in axes:
        e1 = _eval_5(chi1)
        rem = [c for c in cards if c not in chi1]
        if len(rem) != 8:
            continue

        # 1) balanced (mid mạnh nhất)
        chi2, chi3, _, _ = _best_mid_top_for_bottom(rem, e1)
        _append_unique_candidate(candidates, seen_axes, chi1, chi2, chi3)

        # 2) focus mid (đẩy toàn lực Chi2)
        chi2m, chi3m, _, _ = _best_mid_top_for_bottom_focus(rem, e1, "mid")
        _append_unique_candidate(candidates, seen_axes, chi1, chi2m, chi3m)

        # 3) focus top (đẩy toàn lực Chi3)
        chi2t, chi3t, _, _ = _best_mid_top_for_bottom_focus(rem, e1, "top")
        _append_unique_candidate(candidates, seen_axes, chi1, chi2t, chi3t)

    # 3) Thế bẻ chuyên biệt từ break_patterns (giữ lại)
    for b2, m2, t2 in generate_break_variants(cards):
        candidates.append((list(b2), list(m2), list(t2)))

    # 4) Score + unique + top-k
    scored: List[Tuple[Any, Tuple[List[Card], List[Card], List[Card]]]] = []
    for b2, m2, t2 in candidates:
        s = _score_beauty_split(b2, m2, t2)
        if s is None:
            continue
        scored.append(s)

    scored.sort(key=lambda x: x[0], reverse=True)

    # 5) Kết quả: pinned trước, rồi mới fill theo score
    results: List[Tuple[List[Card], List[Card], List[Card]]] = list(pinned)
    seen: set = set(pinned_seen)

    if len(results) >= k:
        return results[:k]

    for score, (b2, m2, t2) in scored:
        b2, m2, t2 = _normalize_style_distribution(list(b2), list(m2), list(t2))
        sig = (_codes(b2), _codes(m2), _codes(t2))
        if sig in seen:
            continue
        seen.add(sig)
        results.append((b2, m2, t2))

        if len(results) >= k:
            break
        if len(seen) >= max(k, max_candidates):
            break

    return results

