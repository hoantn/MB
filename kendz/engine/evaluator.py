# kendz/engine/evaluator.py
"""Bộ đánh giá sức mạnh chi/bộ bài.

Gồm:
- evaluate_poker5(cards) -> (hand_type, strength_key)
- compare_poker5(a, b)   -> -1/0/1
- evaluate_chi3(cards)   -> strength_key (ưu tiên sám > đôi > mậu thầu)
- compare_chi3(a, b)     -> -1/0/1

strength_key luôn là tuple số nguyên, so sánh lexicographic:
- key lớn hơn nghĩa là chi mạnh hơn.
"""

from __future__ import annotations

from collections import Counter
from typing import List, Tuple

from .cards import Card, RANK_ORDER, RANK_TO_VALUE, VALUE_TO_RANK
from .hand_types import PokerHandType


def _sorted_ranks_desc(cards: List[Card]) -> list[int]:
    return sorted((c.rank_value for c in cards), reverse=True)


def _is_flush(cards: List[Card]) -> bool:
    suits = {c.suit for c in cards}
    return len(suits) == 1


def _is_straight(values: list[int]) -> Tuple[bool, list[int]]:
    """Kiểm tra sảnh, có hỗ trợ wheel (A-2-3-4-5).

    Trả về (is_straight, used_values_sorted_desc).
    """
    vals = sorted(values)
    # Wheel: A-2-3-4-5 -> [2,3,4,5,14]
    if vals == [2, 3, 4, 5, 14]:
        return True, [5, 4, 3, 2, 1]
    # Thường: 5 số liên tiếp
    for i in range(4):
        if vals[i + 1] - vals[i] != 1:
            return False, []
    return True, sorted(values, reverse=True)


def evaluate_poker5(cards: List[Card]) -> Tuple[PokerHandType, tuple[int, ...]]:
    """Đánh giá 5 lá theo luật poker chuẩn.

    Trả về:
    - hand_type: PokerHandType
    - strength_key: tuple để so sánh 2 bộ cùng loại.
    """
    if len(cards) != 5:
        raise ValueError(f"evaluate_poker5 cần đúng 5 lá, hiện có {len(cards)}")

    values = [c.rank_value for c in cards]
    counts = Counter(values)
    # sắp xếp theo (số lượng, rank_value) desc để dễ lấy
    groups = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    is_flush = _is_flush(cards)
    is_straight, straight_vals = _is_straight(values)

    if is_straight and is_flush:
        # STRAIGHT FLUSH
        high = straight_vals[0]
        return PokerHandType.STRAIGHT_FLUSH, (high,)

    if groups[0][1] == 4:
        # TỨ QUÝ: (rank_tứ_quý, kicker)
        four_rank = groups[0][0]
        kicker = groups[1][0]
        return PokerHandType.FOUR_OF_A_KIND, (four_rank, kicker)

    if groups[0][1] == 3 and groups[1][1] == 2:
        # CÙ LŨ: (rank_bộ_3, rank_đôi)
        triple_rank = groups[0][0]
        pair_rank = groups[1][0]
        return PokerHandType.FULL_HOUSE, (triple_rank, pair_rank)

    if is_flush:
        # THÙNG: 5 lá, so sánh từng lá từ cao đến thấp
        return PokerHandType.FLUSH, tuple(sorted(values, reverse=True))

    if is_straight:
        # SẢNH: so điểm cao nhất
        high = straight_vals[0]
        return PokerHandType.STRAIGHT, (high,)

    if groups[0][1] == 3:
        # SÁM: (rank_bộ_3, kicker1, kicker2)
        triple_rank = groups[0][0]
        kickers = sorted((v for v in values if v != triple_rank), reverse=True)
        return PokerHandType.THREE_OF_A_KIND, (triple_rank, *kickers)

    if groups[0][1] == 2 and groups[1][1] == 2:
        # HAI ĐÔI: (rank_đôi_cao, rank_đôi_thấp, kicker)
        high_pair, low_pair = sorted(
            (groups[0][0], groups[1][0]), reverse=True
        )
        kicker = [v for v in values if v not in (high_pair, low_pair)][0]
        return PokerHandType.TWO_PAIR, (high_pair, low_pair, kicker)

    if groups[0][1] == 2:
        # MỘT ĐÔI: (rank_đôi, kicker1, kicker2, kicker3)
        pair_rank = groups[0][0]
        kickers = sorted((v for v in values if v != pair_rank), reverse=True)
        return PokerHandType.ONE_PAIR, (pair_rank, *kickers)

    # MẬU THẦU: 5 lá rời
    return PokerHandType.HIGH_CARD, tuple(sorted(values, reverse=True))


def compare_poker5(
    a: tuple[PokerHandType, tuple[int, ...]],
    b: tuple[PokerHandType, tuple[int, ...]],
) -> int:
    """So sánh 2 bộ 5 lá.

    Trả về:
    - 1  nếu a > b
    - -1 nếu a < b
    - 0  nếu bằng nhau
    """
    type_a, key_a = a
    type_b, key_b = b
    if type_a > type_b:
        return 1
    if type_a < type_b:
        return -1
    # cùng loại -> so strength_key
    if key_a > key_b:
        return 1
    if key_a < key_b:
        return -1
    return 0


def evaluate_chi3(cards: List[Card]) -> tuple[int, ...]:
    """Đánh giá chi 3 lá theo đúng ưu tiên Mậu Binh.

    Ưu tiên:
    - Sám (3 lá cùng rank)  -> group_type = 2
    - Đôi                  -> group_type = 1
    - Mậu thầu             -> group_type = 0

    strength_key:
    - Sám:        (2, rank_sam)
    - Đôi:        (1, rank_doi, kicker)
    - Mậu thầu:   (0, high, mid, low)
    """
    if len(cards) != 3:
        raise ValueError(f"evaluate_chi3 cần đúng 3 lá, hiện có {len(cards)}")

    values = sorted((c.rank_value for c in cards), reverse=True)
    v1, v2, v3 = values

    if v1 == v2 == v3:
        # SÁM
        return (2, v1)

    if v1 == v2 or v2 == v3:
        # ĐÔI
        pair = v2
        kicker = v1 if v1 != pair else v3
        return (1, pair, kicker)

    # Mậu thầu
    return (0, v1, v2, v3)


def compare_chi3(key_a: tuple[int, ...], key_b: tuple[int, ...]) -> int:
    """So sánh 2 chi3 dựa trên strength_key."""
    if key_a > key_b:
        return 1
    if key_a < key_b:
        return -1
    return 0
