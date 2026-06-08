from __future__ import annotations

from typing import List, Sequence, Tuple

from engine.card import Card
from engine.rules import evaluate_5cards


HandEval = Tuple[int, List[int]]


def evaluate_top_for_foul(cards: Sequence[Card]) -> HandEval:
    """
    Danh gia chi tren ba la de so binh lung.

    Chi tren chi co mau thau, doi va xam. Ba la lien tiep hoac dong chat
    khong duoc tinh la sanh/thung khi kiem tra binh lung.
    """
    cards = list(cards)
    if len(cards) != 3:
        raise ValueError("Chi tren phai co dung 3 la")

    counts: dict[int, int] = {}
    for card in cards:
        rank = int(card.rank_index)
        counts[rank] = counts.get(rank, 0) + 1

    groups = sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
    rank, count = groups[0]
    if count == 3:
        return 3, [rank]
    if count == 2:
        kicker = groups[1][0]
        return 1, [rank, kicker]
    return 0, sorted(counts.keys(), reverse=True)


def compare_eval(left: HandEval, right: HandEval) -> int:
    """Tra ve -1/0/1 khi so sanh hai ket qua danh gia cung thang diem."""
    left_type, left_detail = left
    right_type, right_detail = right
    if left_type != right_type:
        return 1 if left_type > right_type else -1
    if left_detail == right_detail:
        return 0
    return 1 if tuple(left_detail) > tuple(right_detail) else -1


def is_no_foul(bottom: Sequence[Card], middle: Sequence[Card], top: Sequence[Card]) -> bool:
    """Dung khi bottom >= middle >= top."""
    bottom = list(bottom)
    middle = list(middle)
    top = list(top)
    if (len(bottom), len(middle), len(top)) != (5, 5, 3):
        return False
    return (
        compare_eval(evaluate_5cards(bottom), evaluate_5cards(middle)) >= 0
        and compare_eval(evaluate_5cards(middle), evaluate_top_for_foul(top)) >= 0
    )


def is_no_foul_codes(
    bottom_codes: Sequence[str],
    middle_codes: Sequence[str],
    top_codes: Sequence[str],
) -> bool:
    """Bien the dung ma la cho cac lop UI/Auto."""
    try:
        return is_no_foul(
            [Card.from_code(code) for code in bottom_codes],
            [Card.from_code(code) for code in middle_codes],
            [Card.from_code(code) for code in top_codes],
        )
    except Exception:
        return False


def is_no_foul_slot_layout(slot_codes: Sequence[str]) -> bool:
    """Kiem tra layout tren ban theo thu tu slot 3-5-5: top, middle, bottom."""
    codes = list(slot_codes)
    if len(codes) != 13:
        return False
    return is_no_foul_codes(codes[8:13], codes[3:8], codes[0:3])
