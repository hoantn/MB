from __future__ import annotations

from itertools import combinations
from typing import Iterable, List, Optional, Tuple

from engine.card import Card
from engine.arranger_parts.eval_utils import _eval_5, _eval_3, _map_eval_top_to_5scale, _rank_val
def _generate_valid_splits(cards: List[Card]) -> Iterable[
    Tuple[List[Card], List[Card], List[Card], Tuple[int, ...], Tuple[int, ...], Tuple[int, ...]]
]:
    """
    Sinh toàn bộ các cách chia 13 lá thành (chi1, chi2, chi3) hợp lệ:
      - chi1 (bottom, 5 lá dưới)
      - chi2 (middle, 5 lá giữa)
      - chi3 (top, 3 lá trên)
    với ràng buộc: eval_chi3 <= eval_chi2 <= eval_chi1.

    Trả về từng phần tử:
      (chi1_cards, chi2_cards, chi3_cards, eval_chi1, eval_chi2, eval_chi3)
    """
    if len(cards) != 13:
        raise ValueError("Cần đúng 13 lá để xếp bài")

    indices = list(range(13))

    # Duyệt 5 lá chi dưới
    for bottom_idx in combinations(indices, 5):
        bottom_set = set(bottom_idx)
        bottom_cards = [cards[i] for i in bottom_idx]
        eval_bottom = _eval_5(bottom_cards)

        # 8 lá còn lại
        remaining_after_bottom = [i for i in indices if i not in bottom_set]

        # Duyệt 5 lá chi giữa
        for mid_idx in combinations(remaining_after_bottom, 5):
            mid_set = set(mid_idx)
            mid_cards = [cards[i] for i in mid_idx]
            top_idx = [i for i in remaining_after_bottom if i not in mid_set]
            top_cards = [cards[i] for i in top_idx]  # 3 lá

            eval_mid = _eval_5(mid_cards)
            eval_top = _eval_3(top_cards)

            # Ràng buộc không binh lủng:
            #   top <= mid <= bottom
            if _map_eval_top_to_5scale(eval_top) > eval_mid:
                continue
            if eval_mid > eval_bottom:
                continue

            yield bottom_cards, mid_cards, top_cards, eval_bottom, eval_mid, eval_top

# =====================================================================
# HÀM CHÍNH: XẾP 13 LÁ THEO CHIẾN LƯỢC
# =====================================================================

# =====================================================================
#  SPECIAL-FIRST: DỰNG SPLIT CHO BÀI ĐẶC BIỆT 13 LÁ (MODE TIỀN)
# =====================================================================
def _sort_cards_desc(cards: List[Card]) -> List[Card]:
    return sorted(cards, key=lambda c: _rank_val(c.rank), reverse=True)
def _best_strength_split(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Chọn split hợp lệ (không binh lủng) có strength lớn nhất theo thang eval hiện tại.
    Dùng như fallback an toàn cho các special 13 lá không cần hình thức split cố định.
    """
    best = None
    best_score = None
    for chi1, chi2, chi3, e1, e2, e3 in _generate_valid_splits(cards):
        score = (e1, e2, _map_eval_top_to_5scale(e3))
        if best_score is None or score > best_score:
            best_score = score
            best = (chi1, chi2, chi3)
    return best
def _validate_no_foul(chi1: List[Card], chi2: List[Card], chi3: List[Card]) -> bool:
    e1 = _eval_5(chi1)
    e2 = _eval_5(chi2)
    e3 = _eval_3(chi3)
    if _map_eval_top_to_5scale(e3) > e2:
        return False
    if e2 > e1:
        return False
    return True
