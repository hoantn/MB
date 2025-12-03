from itertools import combinations
from typing import List, Tuple, Dict

from core.constants import RANK_ORDER
from engine.card import Card
from engine.scorer import score_matchup  # dùng cho Engine B


# Map rank -> index để so sánh
_RANK_INDEX: Dict[str, int] = {r: i for i, r in enumerate(RANK_ORDER)}


def _rank_val(rank: str) -> int:
    """Giá trị rank dùng để so sánh (2 nhỏ, A lớn)."""
    return _RANK_INDEX[rank]


# =========================================================
# ĐÁNH GIÁ 5 LÁ
# =========================================================

def _eval_5(cards: List[Card]) -> Tuple[int, ...]:
    """
    Trả về tuple điểm cho bộ 5 lá.
    hand_type (tăng dần):
      0: mậu thầu (high card)
      1: đôi
      2: thú (2 đôi)
      3: sám
      4: sảnh
      5: thùng
      6: cù lũ
      7: tứ quý
      8: thùng phá sảnh
    Tuple càng lớn càng mạnh.
    """
    ranks = [c.rank for c in cards]
    suits = [c.suit for c in cards]
    vals = sorted([_rank_val(r) for r in ranks], reverse=True)

    # Đếm số lượng từng rank
    count: Dict[int, int] = {}
    for v in vals:
        count[v] = count.get(v, 0) + 1

    # sort theo (count, value) để dễ phân loại
    groups = sorted(count.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    # groups: [(val_mạnh_nhất, count), ...]

    is_flush = len(set(suits)) == 1

    # kiểm tra sảnh (xử lý wheel A2345)
    sorted_unique = sorted(count.keys())
    is_straight = False
    high_straight_val = max(sorted_unique)
    if len(sorted_unique) == 5:
        # trường hợp bình thường
        if sorted_unique[-1] - sorted_unique[0] == 4:
            is_straight = True
            high_straight_val = sorted_unique[-1]
        # wheel: A,2,3,4,5
        elif sorted_unique == [
            _RANK_INDEX["2"],
            _RANK_INDEX["3"],
            _RANK_INDEX["4"],
            _RANK_INDEX["5"],
            _RANK_INDEX["A"],
        ]:
            is_straight = True
            high_straight_val = _RANK_INDEX["5"]

    # Phân loại
    if is_straight and is_flush:
        # Thùng phá sảnh
        return (8, high_straight_val)

    # groups[0] là group có count lớn nhất
    main_val, main_cnt = groups[0]

    if main_cnt == 4:
        # Tứ quý
        kicker = max(v for v in vals if v != main_val)
        return (7, main_val, kicker)

    if main_cnt == 3:
        # Có thể là sám hoặc cù lũ
        if len(groups) == 2:
            # 3 + 2
            pair_val, _ = groups[1]
            return (6, main_val, pair_val)  # Cù lũ
        else:
            # Sám
            kickers = sorted([v for v in vals if v != main_val], reverse=True)
            return (3, main_val, *kickers)

    if main_cnt == 2:
        # Đôi / Thú
        pair_vals = [v for v, c in groups if c == 2]
        if len(pair_vals) == 2:
            # Thú
            high_pair, low_pair = sorted(pair_vals, reverse=True)
            kicker = max(v for v in vals if v not in pair_vals)
            return (2, high_pair, low_pair, kicker)
        else:
            # Một đôi
            pair_val = pair_vals[0]
            kickers = sorted([v for v in vals if v != pair_val], reverse=True)
            return (1, pair_val, *kickers)

    # Không có bộ → có thể là thùng, sảnh hoặc mậu thầu
    if is_flush:
        return (5, *vals)
    if is_straight:
        return (4, high_straight_val)

    # Mậu thầu
    return (0, *vals)


# =========================================================
# ĐÁNH GIÁ 3 LÁ (CHI TRÊN)
# =========================================================

def _eval_3(cards: List[Card]) -> Tuple[int, ...]:
    """
    Đánh giá 3 lá (chi trên).
    hand_type:
      0: mậu thầu
      1: đôi
      2: sám
    """
    vals = sorted([_rank_val(c.rank) for c in cards], reverse=True)
    count: Dict[int, int] = {}
    for v in vals:
        count[v] = count.get(v, 0) + 1

    groups = sorted(count.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    main_val, main_cnt = groups[0]

    if main_cnt == 3:
        # Sám
        return (2, main_val)
    if main_cnt == 2:
        # Đôi
        pair_val = main_val
        kicker = max(v for v in vals if v != pair_val)
        return (1, pair_val, kicker)

    # Mậu thầu
    return (0, *vals)


# =========================================================
# ENGINE A: ARRANGE 13 CARDS – FULL SEARCH (MẠNH NHẤT)
# =========================================================

def arrange_13_cards(cards: List[Card]) -> Tuple[List[Card], List[Card], List[Card]]:
    """
    Xếp 13 lá thành 3 chi tối ưu theo Mậu Binh, với ràng buộc:
      - Chi trên (3 lá) <= Chi giữa (5 lá) <= Chi dưới (5 lá)
      - Ưu tiên chi dưới mạnh nhất, rồi tới chi giữa, rồi chi trên.

    Trả về (chi_dưới_5lá, chi_giữa_5lá, chi_trên_3lá) = (chi1, chi2, chi3).

    Thuật toán:
      - Duyệt toàn bộ 72.072 partition:
            chọn 5 lá cho chi dưới,
            chọn 5 lá cho chi giữa từ phần còn lại,
            3 lá còn lại là chi trên.
      - Loại các cấu hình binh lủng:
            top > mid hoặc mid > bottom.
      - Chọn cấu hình với key tối ưu:
            key = (eval_bottom, eval_mid, eval_top)
        (tuple so sánh lexicographic → ưu tiên chi dưới).
    """
    if len(cards) != 13:
        raise ValueError("arrange_13_cards cần đúng 13 lá")

    best_key = None
    best_split = None

    indices = list(range(13))

    # duyệt 5 lá chi dưới
    for bottom_idx in combinations(indices, 5):
        bottom_set = set(bottom_idx)
        bottom_cards = [cards[i] for i in bottom_idx]
        eval_bottom = _eval_5(bottom_cards)

        # 8 lá còn lại
        remaining_after_bottom = [i for i in indices if i not in bottom_set]

        # duyệt 5 lá chi giữa
        for mid_idx in combinations(remaining_after_bottom, 5):
            mid_set = set(mid_idx)
            mid_cards = [cards[i] for i in mid_idx]
            top_idx = [i for i in remaining_after_bottom if i not in mid_set]
            top_cards = [cards[i] for i in top_idx]  # 3 lá

            eval_mid = _eval_5(mid_cards)
            eval_top = _eval_3(top_cards)

            # Ràng buộc không binh lủng:
            #   top <= mid <= bottom
            if eval_top > eval_mid:
                continue
            if eval_mid > eval_bottom:
                continue

            key = (eval_bottom, eval_mid, eval_top)

            if (best_key is None) or (key > best_key):
                best_key = key
                best_split = (bottom_cards, mid_cards, top_cards)

    if best_split is None:
        # Không tìm được cấu hình hợp lệ (rất hiếm, chỉ khi engine/hàm eval lỗi),
        # fallback: chia đơn giản 5-5-3 theo thứ tự ban đầu.
        bottom = cards[0:5]
        mid = cards[5:10]
        top = cards[10:13]
        return bottom, mid, top

    return best_split


def arrange_13_cards_max_strength(cards: List[Card]) -> Tuple[List[Card], List[Card], List[Card]]:
    """
    Alias rõ nghĩa cho Engine A:
    - Xếp 13 lá thành 3 chi mạnh nhất theo luật (không xét đối thủ).
    """
    return arrange_13_cards(cards)


# =========================================================
# ENGINE B: ARRANGE 13 CARDS VS OPPONENT (LỜI NHẤT)
# =========================================================

def arrange_13_cards_vs_opp(
    cards: List[Card],
    opp_chi1: List[Card],
    opp_chi2: List[Card],
    opp_chi3: List[Card],
) -> Tuple[List[Card], List[Card], List[Card]]:
    """
    Xếp 13 lá thành 3 chi TỐI ƯU THEO ĐỐI THỦ, với ràng buộc:
      - Chi trên (3 lá) <= Chi giữa (5 lá) <= Chi dưới (5 lá)
      - Mục tiêu: tối đa hoá score_matchup(chi_dưới, chi_giữa, chi_trên, opp_chi1, opp_chi2, opp_chi3)

    Trả về:
      (chi_dưới_5lá, chi_giữa_5lá, chi_trên_3lá),
    cùng format với arrange_13_cards để tái sử dụng apply_arrangement.
    """
    if len(cards) != 13:
        raise ValueError("arrange_13_cards_vs_opp cần đúng 13 lá")

    best_score = None
    best_split = None

    indices = list(range(13))

    # duyệt 5 lá chi dưới
    for bottom_idx in combinations(indices, 5):
        bottom_set = set(bottom_idx)
        bottom_cards = [cards[i] for i in bottom_idx]
        eval_bottom = _eval_5(bottom_cards)

        # 8 lá còn lại
        remaining_after_bottom = [i for i in indices if i not in bottom_set]

        # duyệt 5 lá chi giữa
        for mid_idx in combinations(remaining_after_bottom, 5):
            mid_set = set(mid_idx)
            mid_cards = [cards[i] for i in mid_idx]
            top_idx = [i for i in remaining_after_bottom if i not in mid_set]
            top_cards = [cards[i] for i in top_idx]  # 3 lá

            eval_mid = _eval_5(mid_cards)
            eval_top = _eval_3(top_cards)

            # Ràng buộc không binh lủng:
            #   top <= mid <= bottom
            if eval_top > eval_mid:
                continue
            if eval_mid > eval_bottom:
                continue

            # Tính điểm đối đầu với đối thủ
            score = score_matchup(
                bottom_cards, mid_cards, top_cards,
                opp_chi1, opp_chi2, opp_chi3,
            )

            if (best_score is None) or (score > best_score):
                best_score = score
                best_split = (bottom_cards, mid_cards, top_cards)

    if best_split is None:
        # fallback: giống Engine A
        return arrange_13_cards(cards)

    return best_split
