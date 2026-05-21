from __future__ import annotations

from typing import List, Tuple, Dict, Optional, Iterable, Any
from collections import Counter

from core.constants import RANK_ORDER
from engine.card import Card

# Map rank -> index để so sánh
_RANK_INDEX: Dict[str, int] = {r: i for i, r in enumerate(RANK_ORDER)}

def _rank_val(rank: str) -> int:
    """Giá trị rank dùng để so sánh (2 nhỏ, A lớn)."""
    return _RANK_INDEX[rank]


# ====================================
# ĐÁNH GIÁ 5 LÁ (CHI 1, CHI 2)
# ====================================
def _eval_5(cards: List[Card]) -> Tuple[int, ...]:
    """
    Đánh giá sức mạnh 5 lá, trả về tuple:

        (hand_type, ...chi tiết...)

    hand_type (theo thứ tự tăng dần):

        0: mậu thầu (high card)
        1: đôi
        2: thú (2 đôi)
        3: sám
        4: sảnh
        5: thùng
        6: cù lũ
        7: tứ quý
        8: thùng phá sảnh

    Quy ước sảnh A-2-3-4-5:
        - Được coi là sảnh nhỏ nhất.
        - 10-J-Q-K-A là sảnh lớn nhất.
    """
    if len(cards) != 5:
        raise ValueError("Cần đúng 5 lá để đánh giá 5-card hand")

    vals = sorted((_rank_val(c.rank) for c in cards), reverse=True)
    suits = [c.suit for c in cards]

    # Đếm số lượng mỗi rank
    count: Dict[int, int] = {}
    for v in vals:
        count[v] = count.get(v, 0) + 1

    # groups: [(val, count), ...] sort theo (count, value) giảm dần
    groups = sorted(count.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    is_flush = len(set(suits)) == 1

    # kiểm tra sảnh (xử lý wheel A2345)
    sorted_unique = sorted(count.keys())
    is_straight = False
    high_straight_val = max(sorted_unique)
    if len(sorted_unique) == 5:
        # trường hợp bình thường
        if sorted_unique[-1] - sorted_unique[0] == 4 and len(sorted_unique) == 5:
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
    # groups đã sort theo (count desc, rank desc)
    # Ví dụ:
    #   - Tứ quý: groups = [(x,4), (y,1)]
    #   - Cù lũ: groups = [(x,3), (y,2)]
    #   - Thú:   groups = [(x,2), (y,2), (z,1)]
    #   - Đôi:   groups = [(x,2), (y,1), (z,1), (t,1)]
    #   - Sám:   groups = [(x,3), (y,1), (z,1)]
    if len(groups) == 2:
        # Một trong: tứ quý (4+1) hoặc cù lũ (3+2)
        (v1, c1), (v2, c2) = groups
        if c1 == 4:
            # Tứ quý
            kicker = v2
            return (7, v1, kicker)
        else:
            # Cù lũ
            return (6, v1, v2)

    if len(groups) == 3:
        # Một trong: thú (2+2+1) hoặc sám (3+1+1)
        (v1, c1), (v2, c2), (v3, c3) = groups
        if c1 == 3:
            # Sám
            kickers = sorted([v2, v3], reverse=True)
            return (3, v1, *kickers)
        else:
            # Thú
            pair1, pair2 = sorted([v1, v2], reverse=True)
            kicker = v3
            return (2, pair1, pair2, kicker)

    if len(groups) == 4:
        # Đôi (2+1+1+1)
        (v1, c1) = groups[0]
        if c1 == 2:
            kickers = sorted([g[0] for g in groups[1:]], reverse=True)
            return (1, v1, *kickers)

    # Không có bộ → có thể là thùng phá sảnh, thùng, sảnh hoặc mậu thầu
    if is_flush and is_straight:
        # Thùng phá sảnh: so bằng high card của sảnh (A2345 -> 5)
        return (8, high_straight_val)
    if is_flush:
        return (5, *vals)
    if is_straight:
        return (4, high_straight_val)

    # Mậu thầu
    return (0, *vals)


# =====================================================================
# ĐÁNH GIÁ 3 LÁ (CHI TRÊN)
# =====================================================================
def _eval_3(cards: List[Card]) -> Tuple[int, ...]:
    """
    Đánh giá 3 lá (chi trên).
    hand_type:
      0: mậu thầu
      1: đôi
      3: sám
    """
    vals = sorted([_rank_val(c.rank) for c in cards], reverse=True)
    count: Dict[int, int] = {}
    for v in vals:
        count[v] = count.get(v, 0) + 1

    groups = sorted(count.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    (v1, c1) = groups[0]

    if c1 == 3:
        # sám
        return (3, v1)
    if c1 == 2:
        # đôi
        kicker = groups[1][0]
        return (1, v1, kicker)

    # mậu thầu: so sánh high card
    return (0, *vals)


# =====================================================================
# MAP eval_3 (chi trên 3 lá) -> cùng thang hand_type của 5 lá để so binh lủng
# 5-card scale: 0 high, 1 pair, 2 two-pair, 3 trips, 4 straight, ...
# 3-card eval trả: 0 high, 1 pair, 3 trips
# => map: trips(3) giữ nguyên 3, giữ nguyên 0/1
def _map_eval_top_to_5scale(eval_top: Tuple[int, ...]) -> Tuple[int, ...]:
    # giữ nguyên; thang đã tương thích: 0/1/3
    return eval_top


# ====================================
# CHIẾN LƯỢC XẾP BÀI
# ====================================
