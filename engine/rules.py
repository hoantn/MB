from typing import List, Tuple
from .card import Card
from core.constants import RANK_ORDER


def sort_cards_desc(cards: List[Card]) -> List[Card]:
    return sorted(cards, key=lambda c: c.rank_index, reverse=True)


def is_flush(cards: List[Card]) -> bool:
    suits = {c.suit for c in cards}
    return len(suits) == 1


def is_straight(cards: List[Card]) -> bool:
    """
    Kiểm tra sảnh với quy tắc:

    - Các rank liên tiếp nhau (theo RANK_ORDER).
    - Hoặc A-2-3-4-5 (A đóng vai trò 1) là sảnh nhỏ nhất.

    Hàm này chỉ trả về True/False, việc xác định "high card"
    sẽ được xử lý chi tiết trong evaluate_5cards để A2345
    luôn là sảnh nhỏ nhất đúng luật Mậu Binh.
    """
    ranks = sorted([c.rank_index for c in cards])
    # Chuỗi liên tiếp bình thường
    if all(ranks[i] == ranks[0] + i for i in range(len(ranks))):
        return True
    # Wheel: A-2-3-4-5 (2,3,4,5,A)
    if ranks == [0, 1, 2, 3, len(RANK_ORDER) - 1]:
        return True
    return False


def count_ranks(cards: List[Card]) -> dict:
    d = {}
    for c in cards:
        d[c.rank] = d.get(c.rank, 0) + 1
    return d


def evaluate_5cards(cards: List[Card]) -> Tuple[int, List[int]]:
    """
    Đánh giá hạng bài 5 lá, trả về:

        (hand_type, detail_vector)

    hand_type:
        0 = Mậu thầu (High card)
        1 = Đôi (One pair)
        2 = Thú / Two pair
        3 = Xám / Three of a kind
        4 = Sảnh / Straight
        5 = Thùng / Flush
        6 = Cù lũ / Full house
        7 = Tứ quý / Four of a kind
        8 = Thùng phá sảnh / Straight flush

    Quy tắc đặc biệt cho Sảnh:

    - A-2-3-4-5 (A đóng vai trò 1) là Sảnh nhỏ nhất.
    - 10-J-Q-K-A là Sảnh lớn nhất.
    - Khi so sánh 2 sảnh, chỉ so "high card" của sảnh:
        detail = [high_straight_rank_index]

      → đảm bảo A2345 luôn yếu hơn mọi sảnh khác.
    """
    cards_sorted = sort_cards_desc(cards)
    counts = count_ranks(cards)
    is_flush_ = is_flush(cards)
    is_straight_ = is_straight(cards)

    def rank_to_idx(r: str) -> int:
        return RANK_ORDER.index(r)

    # Chuẩn bị thông tin về straight để xử lý đúng luật A2345
    ranks_asc = sorted(c.rank_index for c in cards)
    is_wheel = ranks_asc == [0, 1, 2, 3, len(RANK_ORDER) - 1]

    high_straight_val: int | None = None
    if is_straight_:
        if is_wheel:
            # A-2-3-4-5 → high card là 5 (index 3 trong RANK_ORDER)
            # ranks_asc = [2,3,4,5,A] theo index = [0,1,2,3,12]
            # nên lấy ranks_asc[3] = index của 5.
            high_straight_val = ranks_asc[3]
        else:
            # Các sảnh bình thường: 2-3-4-5-6, ..., 10-J-Q-K-A
            high_straight_val = ranks_asc[-1]

    # Thùng phá sảnh
    if is_flush_ and is_straight_:
        # So sánh bằng high card của sảnh
        return 8, [high_straight_val]

    # Tứ quý
    if 4 in counts.values():
        four_rank = max(r for r, c in counts.items() if c == 4)
        kicker = max(r for r, c in counts.items() if c == 1)
        return 7, [rank_to_idx(four_rank), rank_to_idx(kicker)]

    # Cù lũ
    if 3 in counts.values() and 2 in counts.values():
        three_rank = max(r for r, c in counts.items() if c == 3)
        pair_rank = max(r for r, c in counts.items() if c == 2)
        return 6, [rank_to_idx(three_rank), rank_to_idx(pair_rank)]

    # Thùng
    if is_flush_:
        # Với Thùng, vẫn so full 5 lá giảm dần như cũ
        return 5, [c.rank_index for c in cards_sorted]

    # Sảnh
    if is_straight_:
        # Chỉ cần high card để so sánh; A2345 sẽ có high_straight_val nhỏ nhất
        return 4, [high_straight_val]

    # Xám
    if 3 in counts.values():
        three_rank = max(r for r, c in counts.items() if c == 3)
        kickers = [rank_to_idx(r) for r, c in counts.items() if c == 1]
        kickers.sort(reverse=True)
        return 3, [rank_to_idx(three_rank)] + kickers

    # Thú (2 đôi)
    if list(counts.values()).count(2) == 2:
        pairs = [r for r, c in counts.items() if c == 2]
        pairs.sort(key=rank_to_idx, reverse=True)
        kicker = max(r for r, c in counts.items() if c == 1)
        return 2, [
            rank_to_idx(pairs[0]),
            rank_to_idx(pairs[1]),
            rank_to_idx(kicker),
        ]

    # Đôi
    if 2 in counts.values():
        pair_rank = max(r for r, c in counts.items() if c == 2)
        kickers = [rank_to_idx(r) for r, c in counts.items() if c == 1]
        kickers.sort(reverse=True)
        return 1, [rank_to_idx(pair_rank)] + kickers

    # Mậu thầu
    return 0, [c.rank_index for c in cards_sorted]
