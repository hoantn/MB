from __future__ import annotations

from itertools import combinations
from typing import List, Tuple, Optional, Dict
from collections import Counter

from engine.card import Card
from engine.money_scoring import detect_special_13, Special13Type

def _build_three_flushes(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Dựng 3 thùng theo đúng định nghĩa detect_special_13:
      tồn tại cách chia 5–5–3 sao cho cả 3 chi đều flush (3 lá cũng cùng suit).
    Chọn split hợp lệ (không binh lủng) có strength tốt nhất.
    """
    indices = list(range(13))
    best = None
    best_score = None

    def is_flush(cs: List[Card]) -> bool:
        return len({c.suit for c in cs}) == 1

    for idx1 in combinations(indices, 5):
        chi1 = [cards[i] for i in idx1]
        if not is_flush(chi1):
            continue
        rem1 = [i for i in indices if i not in idx1]
        for idx2 in combinations(rem1, 5):
            chi2 = [cards[i] for i in idx2]
            if not is_flush(chi2):
                continue
            used = set(idx1) | set(idx2)
            chi3_idx = [i for i in indices if i not in used]
            if len(chi3_idx) != 3:
                continue
            chi3 = [cards[i] for i in chi3_idx]
            if not is_flush(chi3):
                continue

            # Sắp lại theo strength để giảm nguy cơ binh lủng
            for bottom, mid in [(chi1, chi2), (chi2, chi1)]:
                if _validate_no_foul(bottom, mid, chi3):
                    e1 = _eval_5(bottom); e2 = _eval_5(mid); e3 = _eval_3(chi3)
                    score = (e1, e2, _map_eval_top_to_5scale(e3))
                    if best_score is None or score > best_score:
                        best_score = score
                        best = (bottom, mid, chi3)

    return best
def _build_three_straights(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Dựng 3 sảnh theo đúng định nghĩa detect_special_13:
      tồn tại cách chia 5–5–3 sao cho cả 3 chi đều sảnh.
    Chọn split hợp lệ (không binh lủng) có strength tốt nhất.
    """
    indices = list(range(13))
    best = None
    best_score = None

    def is_straight_5(cs: List[Card]) -> bool:
        e = _eval_5(cs)
        return e[0] in (4, 8)  # straight hoặc straight_flush

    def is_straight_3(cs: List[Card]) -> bool:
        # replicate detect_special_13() logic cho 3 lá
        r = sorted({_rank_val(c.rank) for c in cs})
        if len(r) != 3:
            return False
        # A-2-3
        if r == [_RANK_INDEX["2"], _RANK_INDEX["3"], _RANK_INDEX["A"]]:
            return True
        # Q-K-A
        if r == [_RANK_INDEX["Q"], _RANK_INDEX["K"], _RANK_INDEX["A"]]:
            return True
        return r[1] == r[0] + 1 and r[2] == r[1] + 1

    for idx1 in combinations(indices, 5):
        chi1 = [cards[i] for i in idx1]
        if not is_straight_5(chi1):
            continue
        rem1 = [i for i in indices if i not in idx1]
        for idx2 in combinations(rem1, 5):
            chi2 = [cards[i] for i in idx2]
            if not is_straight_5(chi2):
                continue
            used = set(idx1) | set(idx2)
            chi3_idx = [i for i in indices if i not in used]
            if len(chi3_idx) != 3:
                continue
            chi3 = [cards[i] for i in chi3_idx]
            if not is_straight_3(chi3):
                continue

            for bottom, mid in [(chi1, chi2), (chi2, chi1)]:
                if _validate_no_foul(bottom, mid, chi3):
                    e1 = _eval_5(bottom); e2 = _eval_5(mid); e3 = _eval_3(chi3)
                    score = (e1, e2, _map_eval_top_to_5scale(e3))
                    if best_score is None or score > best_score:
                        best_score = score
                        best = (bottom, mid, chi3)

    return best
def _build_six_pairs(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    6 đôi + 1 lẻ.
    Dựng split "đẹp" và không binh lủng bằng cách:
      - Break 1 đôi nhỏ nhất để lấy 2 kicker + dùng thêm 1 lá lẻ → đủ 3 kicker
      - Chi1: 2 đôi mạnh nhất + kicker mạnh nhất
      - Chi2: 2 đôi tiếp theo + kicker tiếp theo
      - Chi3: 1 đôi còn lại (yếu nhất trong 5 đôi còn lại) + kicker nhỏ nhất
    """
    by_rank: Dict[str, List[Card]] = {}
    for c in cards:
        by_rank.setdefault(c.rank, []).append(c)

    pairs = [cs for cs in by_rank.values() if len(cs) == 2]
    singles = [cs[0] for cs in by_rank.values() if len(cs) == 1]

    if len(pairs) != 6 or len(singles) != 1:
        return None

    # sort pairs by rank desc
    pairs_sorted = sorted(pairs, key=lambda cs: _rank_val(cs[0].rank), reverse=True)
    # break the lowest pair
    broken_pair = pairs_sorted[-1]
    remaining_pairs = pairs_sorted[:-1]  # 5 pairs left

    kicker_cards = singles + list(broken_pair)
    kicker_cards = _sort_cards_desc(kicker_cards)  # 3 cards

    if len(remaining_pairs) != 5 or len(kicker_cards) != 3:
        return None

    chi1 = remaining_pairs[0] + remaining_pairs[1] + [kicker_cards[0]]
    chi2 = remaining_pairs[2] + remaining_pairs[3] + [kicker_cards[1]]
    chi3 = remaining_pairs[4] + [kicker_cards[2]]

    # đảm bảo đúng size
    if not (len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3):
        return None

    if _validate_no_foul(chi1, chi2, chi3):
        return chi1, chi2, chi3

    # fallback: tìm split hợp lệ tốt nhất (rất hiếm khi cần)
    return _best_strength_split(cards)
def _build_five_pairs_one_trips(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    5 đôi + 1 xám.
    Dựng split gợi ý:
      - Chi1: Cù lũ (xám + đôi mạnh nhất) để chi1 chắc chắn mạnh.
      - Break 1 đôi nhỏ nhất còn lại để lấy 2 kicker cho chi2/chi3.
      - Chi2: 2 đôi tiếp theo + kicker mạnh hơn
      - Chi3: 1 đôi còn lại + kicker còn lại
    """
    by_rank: Dict[str, List[Card]] = {}
    for c in cards:
        by_rank.setdefault(c.rank, []).append(c)

    trips = [cs for cs in by_rank.values() if len(cs) == 3]
    pairs = [cs for cs in by_rank.values() if len(cs) == 2]

    if len(trips) != 1 or len(pairs) != 5:
        return None

    trips_cards = trips[0]

    pairs_sorted = sorted(pairs, key=lambda cs: _rank_val(cs[0].rank), reverse=True)

    # use strongest pair to make fullhouse in chi1
    best_pair = pairs_sorted[0]
    remaining_pairs = pairs_sorted[1:]  # 4 pairs

    # break the lowest remaining pair for kickers
    broken_pair = remaining_pairs[-1]
    remaining_pairs2 = remaining_pairs[:-1]  # 3 pairs

    kicker_cards = list(broken_pair)
    kicker_cards = _sort_cards_desc(kicker_cards)  # 2 cards

    chi1 = trips_cards + best_pair  # full house 5 cards
    chi2 = remaining_pairs2[0] + remaining_pairs2[1] + [kicker_cards[0]]
    chi3 = remaining_pairs2[2] + [kicker_cards[1]]

    if not (len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3):
        return None

    if _validate_no_foul(chi1, chi2, chi3):
        return chi1, chi2, chi3

    return _best_strength_split(cards)
def _build_all_same_color(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Đồng hoa: 13 lá đồng màu (đỏ/đen).
    Split không có "hình thức" bắt buộc; ưu tiên split mạnh & hợp lệ.
    """
    return _best_strength_split(cards)
def _build_dragon(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Sảnh rồng 2–A: 13 lá đủ 2..A (mỗi rank 1 lá).
    Dựng split hiển thị:
      - Chi1: A K Q J T
      - Chi2: 9 8 7 6 5
      - Chi3: 4 3 2
    """
    # map rank -> card (phải unique)
    by_rank: Dict[str, Card] = {}
    for c in cards:
        if c.rank in by_rank:
            return None
        by_rank[c.rank] = c

    needed = list(RANK_ORDER)  # ['2',...,'A']
    if any(r not in by_rank for r in needed):
        return None

    chi1_ranks = ["A", "K", "Q", "J", "T"]
    chi2_ranks = ["9", "8", "7", "6", "5"]
    chi3_ranks = ["4", "3", "2"]

    chi1 = [by_rank[r] for r in chi1_ranks]
    chi2 = [by_rank[r] for r in chi2_ranks]
    chi3 = [by_rank[r] for r in chi3_ranks]

    # validate sizes and no foul
    if _validate_no_foul(chi1, chi2, chi3):
        return chi1, chi2, chi3

    # fallback
    return _best_strength_split(cards)
def _build_dragon_color(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Sảnh rồng đồng hoa: vẫn là 2–A nhưng đồng màu.
    Split giống sảnh rồng.
    """
    return _build_dragon(cards)
def build_special_split(cards: List[Card], special_type: Special13Type) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Dựng split cho bài đặc biệt. Trả None nếu không dựng được an toàn.
    """
    try:
        if special_type == Special13Type.THREE_FLUSHES:
            return _build_three_flushes(cards)
        if special_type == Special13Type.THREE_STRAIGHTS:
            return _build_three_straights(cards)
        if special_type == Special13Type.SIX_PAIRS:
            return _build_six_pairs(cards)
        if special_type == Special13Type.FIVE_PAIRS_ONE_TRIPS:
            return _build_five_pairs_one_trips(cards)
        if special_type == Special13Type.ALL_SAME_COLOR:
            return _build_all_same_color(cards)
        if special_type == Special13Type.DRAGON:
            return _build_dragon(cards)
        if special_type == Special13Type.DRAGON_COLOR:
            return _build_dragon_color(cards)
    except Exception:
        # Nếu có lỗi bất ngờ, tuyệt đối không làm crash flow xếp bài
        return None
    return None