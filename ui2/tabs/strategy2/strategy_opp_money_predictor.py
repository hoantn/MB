from __future__ import annotations

from collections import Counter
from typing import List, Optional, Tuple

from core.constants import RANK_ORDER
from engine.card import Card
from engine.foul_rules import evaluate_top_for_foul, is_no_foul
from engine.money_scoring import evaluate_3cards
from engine.rules import evaluate_5cards


Split553 = Tuple[List[Card], List[Card], List[Card]]


def _rank_idx(card: Card) -> int:
    return int(card.rank_index)


def _cmp_eval(left: Tuple[int, List[int]], right: Tuple[int, List[int]]) -> int:
    left_type, left_detail = left
    right_type, right_detail = right
    if left_type != right_type:
        return 1 if left_type > right_type else -1
    for a, b in zip(left_detail, right_detail):
        if a != b:
            return 1 if a > b else -1
    if len(left_detail) != len(right_detail):
        return 1 if len(left_detail) > len(right_detail) else -1
    return 0


def _top_eval_for_foul(cards3: List[Card]) -> Tuple[int, List[int]]:
    return evaluate_top_for_foul(cards3)


def _no_foul(chi1: List[Card], chi2: List[Card], chi3: List[Card]) -> bool:
    return is_no_foul(chi1, chi2, chi3)


def _pair_rank(cards: List[Card]) -> Optional[int]:
    counts = Counter(card.rank for card in cards)
    pair_ranks = [RANK_ORDER.index(rank) for rank, count in counts.items() if count == 2]
    if len(pair_ranks) != 1:
        return None
    return int(pair_ranks[0])


def _pair_cards(cards: List[Card], rank_idx: int) -> List[Card]:
    return [card for card in cards if _rank_idx(card) == rank_idx]


def _single_cards(cards: List[Card], rank_idx: int) -> List[Card]:
    return [card for card in cards if _rank_idx(card) != rank_idx]


def _same_cards(left: List[Card], right: List[Card]) -> bool:
    return Counter(card.to_code() for card in left) == Counter(card.to_code() for card in right)


def _is_one_pair_5(cards: List[Card]) -> bool:
    return len(cards) == 5 and evaluate_5cards(cards)[0] == 1


def _is_two_pair_5(cards: List[Card]) -> bool:
    return len(cards) == 5 and evaluate_5cards(cards)[0] == 2


def _is_high_card_3(cards: List[Card]) -> bool:
    return len(cards) == 3 and evaluate_3cards(cards)[0] == 0


def optimize_opp_money_split(cards13: List[Card], money_split: Optional[Split553]) -> Optional[Split553]:
    """
    Predict a more human-like OPP Money split for one narrow case.

    Rule:
    - Only for Money splits where chi2 is one pair and chi3 is one pair under 9.
    - Move the chi3 pair up into chi2.
    - Move the two highest chi2 kickers down into chi3.
    - Keep the candidate only if chi2 becomes two pair and chi3 becomes K/A high-card.

    This function is intentionally O(1): no brute force, no arranger call.
    """
    if money_split is None:
        return None

    chi1, chi2, chi3 = money_split
    chi1 = list(chi1 or [])
    chi2 = list(chi2 or [])
    chi3 = list(chi3 or [])
    original_cards = chi1 + chi2 + chi3

    if not (len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3):
        return money_split
    if len(cards13) == 13 and not _same_cards(list(cards13), original_cards):
        return money_split
    if evaluate_5cards(chi1)[0] == 6:
        # The shared Money scorer now protects full-house + pair + pair shapes.
        # Do not let the old narrow OPP predictor break that anchor into
        # full-house + two-pair + high-card.
        return money_split
    if not (_is_one_pair_5(chi2) and evaluate_3cards(chi3)[0] == 1):
        return money_split

    pair2_rank = _pair_rank(chi2)
    pair3_rank = _pair_rank(chi3)
    if pair2_rank is None or pair3_rank is None:
        return money_split

    # Under 9 means 2..8 in the engine's 2..A rank index scale.
    if pair3_rank >= RANK_ORDER.index("9"):
        return money_split

    chi2_pair = _pair_cards(chi2, pair2_rank)
    chi3_pair = _pair_cards(chi3, pair3_rank)
    chi2_kickers = sorted(_single_cards(chi2, pair2_rank), key=_rank_idx, reverse=True)
    chi3_single = _single_cards(chi3, pair3_rank)
    if len(chi2_pair) != 2 or len(chi3_pair) != 2 or len(chi2_kickers) != 3 or len(chi3_single) != 1:
        return money_split

    moved_to_top = chi2_kickers[:2]
    leftover_mid = chi2_kickers[2:]
    new_chi2 = chi2_pair + chi3_pair + leftover_mid
    new_chi3 = sorted(moved_to_top + chi3_single, key=_rank_idx, reverse=True)

    if not (_is_two_pair_5(new_chi2) and _is_high_card_3(new_chi3)):
        return money_split
    if max(_rank_idx(card) for card in new_chi3) < RANK_ORDER.index("K"):
        return money_split

    candidate_cards = chi1 + new_chi2 + new_chi3
    if not _same_cards(original_cards, candidate_cards):
        return money_split
    if not _no_foul(chi1, new_chi2, new_chi3):
        return money_split

    return chi1, new_chi2, new_chi3
