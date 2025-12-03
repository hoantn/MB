from typing import List, Tuple
from .card import Card
from core.constants import RANK_ORDER

def sort_cards_desc(cards: List[Card]) -> List[Card]:
    return sorted(cards, key=lambda c: c.rank_index, reverse=True)

def is_flush(cards: List[Card]) -> bool:
    suits = {c.suit for c in cards}
    return len(suits) == 1

def is_straight(cards: List[Card]) -> bool:
    ranks = sorted([c.rank_index for c in cards])
    if all(ranks[i] == ranks[0] + i for i in range(len(ranks))):
        return True
    if ranks == [0, 1, 2, 3, len(RANK_ORDER) - 1]:
        return True
    return False

def count_ranks(cards: List[Card]) -> dict:
    d = {}
    for c in cards:
        d[c.rank] = d.get(c.rank, 0) + 1
    return d

def evaluate_5cards(cards: List[Card]) -> Tuple[int, List[int]]:
    cards_sorted = sort_cards_desc(cards)
    counts = count_ranks(cards)
    is_flush_ = is_flush(cards)
    is_straight_ = is_straight(cards)

    def rank_to_idx(r: str) -> int:
        return RANK_ORDER.index(r)

    if is_flush_ and is_straight_:
        return 8, [c.rank_index for c in cards_sorted]

    if 4 in counts.values():
        four_rank = max(r for r, c in counts.items() if c == 4)
        kicker = max(r for r, c in counts.items() if c == 1)
        return 7, [rank_to_idx(four_rank), rank_to_idx(kicker)]

    if 3 in counts.values() and 2 in counts.values():
        three_rank = max(r for r, c in counts.items() if c == 3)
        pair_rank = max(r for r, c in counts.items() if c == 2)
        return 6, [rank_to_idx(three_rank), rank_to_idx(pair_rank)]

    if is_flush_:
        return 5, [c.rank_index for c in cards_sorted]

    if is_straight_:
        return 4, [c.rank_index for c in cards_sorted]

    if 3 in counts.values():
        three_rank = max(r for r, c in counts.items() if c == 3)
        kickers = [rank_to_idx(r) for r, c in counts.items() if c == 1]
        kickers.sort(reverse=True)
        return 3, [rank_to_idx(three_rank)] + kickers

    if list(counts.values()).count(2) == 2:
        pairs = [r for r, c in counts.items() if c == 2]
        pairs.sort(key=rank_to_idx, reverse=True)
        kicker = max(r for r, c in counts.items() if c == 1)
        return 2, [rank_to_idx(pairs[0]), rank_to_idx(pairs[1]), rank_to_idx(kicker)]

    if 2 in counts.values():
        pair_rank = max(r for r, c in counts.items() if c == 2)
        kickers = [rank_to_idx(r) for r, c in counts.items() if c == 1]
        kickers.sort(reverse=True)
        return 1, [rank_to_idx(pair_rank)] + kickers

    return 0, [c.rank_index for c in cards_sorted]
