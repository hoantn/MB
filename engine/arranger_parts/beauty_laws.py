from __future__ import annotations

from typing import List, Tuple
from collections import Counter

from engine.card import Card
from engine.arranger_parts.splits import _validate_no_foul
from itertools import combinations


def _normalize_kicker_distribution(
    chi1: List[Card],
    chi2: List[Card],
    chi3: List[Card],
) -> Tuple[List[Card], List[Card], List[Card]]:
    # lazy import để tránh vòng lặp: beauty_flow cũng import beauty_laws
    from engine.arranger_parts.beauty_flow import _rv, _trash_law_key

    # ---- helper: xác định kicker theo ĐÚNG logic cũ ----
    def _kickers_5(hand: List[Card]) -> List[Card]:
        if len(hand) != 5:
            return []

        cnt = Counter(_rv(c) for c in hand)
        values = sorted(cnt.values(), reverse=True)

        # Cù: 0 rác
        if values == [3, 2]:
            return []

        # Các hand có lá lẻ: rác = các lá count=1
        if values in ([4, 1], [3, 1, 1], [2, 2, 1], [2, 1, 1, 1]):
            single_ranks = {r for r, n in cnt.items() if n == 1}
            return [c for c in hand if _rv(c) in single_ranks]

        # [1,1,1,1,1] => có thể là flush / straight / straight-flush / hoặc high-card 5
        if values == [1, 1, 1, 1, 1]:
            # flush?
            is_flush = (len({c.suit for c in hand}) == 1)

            # straight? (bao gồm A2345)
            idxs = sorted({_rv(c) for c in hand})
            is_wheel = (idxs == [0, 1, 2, 3, 12])  # A2345 nếu A là index 12
            is_normal = (len(idxs) == 5 and all(idxs[i] + 1 == idxs[i + 1] for i in range(4)))
            is_straight = is_wheel or is_normal

            # flush/straight => 0 rác (không phá bộ)
            if is_flush or is_straight:
                return []

            # high-card 5 => 5 rác
            return list(hand)

        # fallback an toàn
        return []

    def _kickers_3(hand: List[Card]) -> List[Card]:
        if len(hand) != 3:
            return []
        cnt = Counter(_rv(c) for c in hand)
        values = sorted(cnt.values(), reverse=True)

        if values == [3]:      # xám
            return []
        if values == [2, 1]:   # đôi
            single_ranks = {r for r, n in cnt.items() if n == 1}
            return [c for c in hand if _rv(c) in single_ranks]

        # [1,1,1] mậu 3 lá => cả 3 là rác
        return list(hand)

    # ---- tách core + kicker ----
    k1 = _kickers_5(chi1)
    k2 = _kickers_5(chi2)
    k3 = _kickers_3(chi3)

    # nếu không có gì để dọn → trả nguyên
    if not (k1 or k2 or k3):
        return chi1, chi2, chi3

    def _code(c: Card) -> str:
        return c.to_code()

    k1_codes = {_code(c) for c in k1}
    k2_codes = {_code(c) for c in k2}
    k3_codes = {_code(c) for c in k3}

    core1 = [c for c in chi1 if _code(c) not in k1_codes]
    core2 = [c for c in chi2 if _code(c) not in k2_codes]
    core3 = [c for c in chi3 if _code(c) not in k3_codes]

    all_kickers = k1 + k2 + k3

    need1, need2, need3 = len(k1), len(k2), len(k3)

    best_key = None
    best_split = (chi1, chi2, chi3)

    # ---- phân phối lại kicker theo đúng số lượng từng chi ----
    for ks1 in combinations(all_kickers, need1):
        ks1_codes = {_code(c) for c in ks1}
        rest1 = [c for c in all_kickers if _code(c) not in ks1_codes]

        for ks2 in combinations(rest1, need2):
            ks2_codes = {_code(c) for c in ks2}
            ks3 = [c for c in rest1 if _code(c) not in ks2_codes]

            if len(ks3) != need3:
                continue

            n1 = core1 + list(ks1)
            n2 = core2 + list(ks2)
            n3 = core3 + list(ks3)

            if not _validate_no_foul(n1, n2, n3):
                continue

            key = _trash_law_key(n1, n2, n3)
            if best_key is None or key > best_key:
                best_key = key
                best_split = (n1, n2, n3)

    return best_split
