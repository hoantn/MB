from __future__ import annotations

from typing import Sequence, Tuple


def _hand_type(ev: Tuple[int, ...]) -> int:
    try:
        return int(ev[0])
    except Exception:
        return 0


def _detail(ev: Tuple[int, ...]) -> Sequence[int]:
    try:
        d = ev[1]  # type: ignore[index]
    except Exception:
        return ()
    if isinstance(d, (list, tuple)):
        return tuple(int(x) for x in d)
    return ()


def _rank_norm(rank_index: int) -> float:
    # RANK_ORDER is 2..A, so 12 is ace.
    return max(0.0, min(1.0, float(rank_index) / 12.0))


def _rank_bucket(rank_index: int) -> int:
    if rank_index >= 11:  # K/A
        return 4
    if rank_index >= 9:  # J/Q
        return 3
    if rank_index >= 7:  # 9/T
        return 2
    if rank_index >= 4:  # 6/7/8
        return 1
    return 0


def _top_pair_value(pair_rank: int, kicker_rank: int = 0) -> float:
    """
    Rank-sensitive value for chi3 pair.

    Small top pairs are real but cheap; premium top pairs can justify taking
    force from chi1/chi2.
    """
    bucket = _rank_bucket(pair_rank)
    base_by_bucket = {
        0: 2.2,  # 2-5
        1: 3.0,  # 6-8
        2: 4.0,  # 9/T
        3: 5.2,  # J/Q
        4: 6.6,  # K/A
    }
    return base_by_bucket[bucket] + _rank_norm(pair_rank) * 0.45 + _rank_norm(kicker_rank) * 0.15


def _three_hand_value(t_top: int, d_top: Sequence[int]) -> float:
    if t_top >= 3:  # mapped trips
        trip = d_top[0] if d_top else 0
        return 10.5 + _rank_norm(trip) * 1.8
    if t_top == 1:
        pair = d_top[0] if d_top else 0
        kicker = d_top[1] if len(d_top) > 1 else 0
        return _top_pair_value(pair, kicker)

    high = d_top[0] if d_top else 0
    second = d_top[1] if len(d_top) > 1 else 0
    third = d_top[2] if len(d_top) > 2 else 0
    return -1.6 + _rank_norm(high) * 1.6 + _rank_norm(second) * 0.45 + _rank_norm(third) * 0.15


def _five_hand_value(street: str, t: int, d: Sequence[int]) -> float:
    """
    Practical value of a 5-card chi by type and rank.

    street is "bottom" or "middle"; middle gets a little more pressure because
    abandoning chi2 is expensive in real play.
    """
    first = d[0] if d else 0
    second = d[1] if len(d) > 1 else 0

    if t == 8:  # straight flush
        value = 17.0 + _rank_norm(first) * 2.2
    elif t == 7:  # four of a kind
        value = 15.0 + _rank_norm(first) * 2.0
    elif t == 6:  # full house
        value = 11.2 + _rank_norm(first) * 1.2 + _rank_norm(second) * 0.5
    elif t == 5:  # flush
        value = 7.6 + _rank_norm(first) * 1.4
    elif t == 4:  # straight
        value = 7.1 + _rank_norm(first) * 1.3
    elif t == 3:  # trips
        value = 5.6 + _rank_norm(first) * 1.0
    elif t == 2:  # two pair
        value = 4.0 + _rank_norm(first) * 0.85 + _rank_norm(second) * 0.35
    elif t == 1:  # one pair
        value = 2.2 + _rank_norm(first) * 0.85
    else:
        value = -1.3 + _rank_norm(first) * 0.9

    if street == "middle":
        if t >= 6:
            value += 1.0
        elif t >= 3:
            value += 0.6
        elif t >= 1:
            value += 0.35

    return value


def _official_bonus_score(t_bottom: int, t_mid: int, t_top: int) -> float:
    bonus = 0.0
    if t_top >= 3:  # trips on chi3
        bonus += 6.0
    if t_mid == 6:  # full house on chi2
        bonus += 4.0
    if t_mid == 7:  # four of a kind on chi2
        bonus += 16.0
    if t_mid == 8:  # straight flush on chi2
        bonus += 20.0
    if t_bottom == 7:  # four of a kind on chi1
        bonus += 8.0
    if t_bottom == 8:  # straight flush on chi1
        bonus += 10.0
    return bonus


def _anchor_combo_value(
    t_bottom: int,
    t_mid: int,
    t_top: int,
    d_bottom: Sequence[int],
    d_mid: Sequence[int],
    d_top: Sequence[int],
) -> float:
    """Protect strong chi1/chi2 structures unless the top gain is premium."""
    adj = 0.0
    top_pair = d_top[0] if t_top == 1 and d_top else -1

    if t_bottom == 6:
        adj += 1.4
        if t_mid >= 4:  # full house + straight/flush or better
            adj += 3.6
        elif t_mid == 3:
            adj += 2.4
        elif t_mid == 2:
            adj += 1.6
        elif t_mid == 1:
            adj += 0.6

        if t_top == 0:
            adj += 1.0
        elif t_top == 1 and top_pair <= 6:  # pair 2-8
            adj -= 0.8

    if t_bottom in (4, 5) and t_mid >= 2 and t_top >= 1:
        adj += 1.2
    if t_bottom in (4, 5) and t_mid in (4, 5) and t_top == 1:
        # Two made 5-card chi plus a live top pair is a strong three-chi line.
        adj += 5.8
    if t_bottom in (4, 5) and t_mid >= 1 and t_top == 1:
        if top_pair >= 11:  # K/A top pair makes the 3-live-chi line strong.
            adj += 2.0
        elif top_pair >= 9:  # J/Q is not premium alone, but good with live chi2.
            adj += 1.2
        if t_mid == 3:
            adj += 1.0
        elif t_mid == 1 and top_pair >= 9:
            mid_pair = d_mid[0] if d_mid else 0
            if mid_pair >= 9:
                adj += 1.2
            if top_pair >= 10:  # Q/K/A top pair: prefer 3 live chi.
                adj += 1.0
    if t_bottom in (4, 5) and t_mid == 0 and t_top == 0:
        adj -= 5.0

    if t_bottom == 2 and t_mid == 2 and t_top == 1:
        adj += 3.0  # two-pair / two-pair / pair is a very human layout.
    if t_bottom == 2 and t_mid == 1 and t_top == 1:
        mid_pair = d_mid[0] if d_mid else 0
        bottom_high_pair = d_bottom[0] if d_bottom else 0
        if bottom_high_pair >= 5 and top_pair >= 4 and mid_pair >= 6:
            adj += 2.0  # keep three live chi over two-pair/two-pair/mau.
    if t_bottom == 1 and t_mid == 1 and t_top == 1:
        adj += 1.4
    if t_bottom == 6 and t_mid == 1 and t_top == 1:
        # Full-house + pair + pair keeps the bottom anchor without killing
        # chi3. It should beat trips/two-pair/pair in many rank-balanced hands.
        adj += 4.0
        trip_rank = d_bottom[0] if d_bottom else 0
        if trip_rank >= 11:
            adj += 4.5

    return adj


def _tradeoff_adjustment(
    t_bottom: int,
    t_mid: int,
    t_top: int,
    d_bottom: Sequence[int],
    d_mid: Sequence[int],
    d_top: Sequence[int],
) -> float:
    """
    Penalize paying too much in chi1/chi2 for too little top value.

    This is deliberately soft: premium top pairs can still win, small top pairs
    cannot easily break strong bottom/middle anchors.
    """
    adj = 0.0
    top_pair = d_top[0] if t_top == 1 and d_top else -1

    if t_top == 1:
        if top_pair <= 3:  # pair 2-5
            adj -= 2.2
        elif top_pair <= 6:  # pair 6-8
            adj -= 1.0
        elif top_pair >= 12:  # pair A
            adj += 4.0
        elif top_pair >= 11:  # pair K
            adj += 2.0
        elif top_pair >= 10:  # pair Q is good, but not premium enough.
            adj += 0.4

    # Straight/flush + trips + small pair is often an overpayment when a
    # full-house + made middle exists in the same 13-card family.
    if t_bottom in (4, 5) and t_mid == 3 and t_top == 1 and top_pair <= 6:
        adj -= 4.6

    # Trips + two-pair + high-card commonly loses to full-house + pair + high-card.
    if t_bottom == 3 and t_mid == 2 and t_top == 0:
        adj -= 3.0
    if t_bottom == 3 and t_mid == 2 and t_top == 1:
        # Do not overpay for turning chi2 into two-pair when the cost is
        # breaking a possible bottom full-house.
        adj -= 2.2

    if t_bottom in (4, 5) and t_mid == 1 and t_top == 1:
        high = d_bottom[0] if d_bottom else 0
        if high >= 11:  # A/K-high straight/flush plus two live pairs.
            adj += 4.5
        elif high >= 10:
            adj += 1.6

    if t_bottom in (4, 5) and t_mid == 3 and t_top >= 3:
        # Bonus-backed three-live-chi shape: flush/straight + trips + trips.
        adj += 7.0
    if t_bottom in (4, 5) and t_mid == 3 and t_top == 0:
        high_top = d_top[0] if d_top else 0
        if high_top >= 9:  # Q/K/A-high mau keeps chi3 from being pure trash.
            adj += 5.0
    if t_bottom in (4, 5) and t_mid in (4, 5) and t_top == 0:
        high_top = d_top[0] if d_top else 0
        if high_top >= 9:
            adj += 5.2
    if t_bottom in (4, 5) and t_mid == 2 and t_top == 0:
        high_top = d_top[0] if d_top else 0
        high_pair = d_mid[0] if d_mid else 0
        if high_top >= 9 and high_pair < 12:
            adj += 7.0
    if t_bottom in (4, 5) and t_mid == 2 and t_top == 1:
        high_pair = d_mid[0] if d_mid else 0
        if t_bottom == 5 and top_pair >= 9:
            adj += 1.4
        if high_pair >= 10:
            adj += 2.2
        elif high_pair >= 8:
            adj += 1.2
    if t_bottom == 5 and t_mid == 1 and t_top == 0:
        high = d_bottom[0] if d_bottom else 0
        if high < 10:
            adj -= 5.2
    if t_bottom == 5 and t_mid == 1 and t_top == 1:
        mid_pair = d_mid[0] if d_mid else 0
        if mid_pair >= 12 and top_pair == 10:
            adj += 0.8
    if t_bottom == 4 and t_mid == 1 and t_top == 0:
        high = d_bottom[0] if d_bottom else 0
        mid_pair = d_mid[0] if d_mid else 0
        if high <= 8 and mid_pair <= 4:
            adj -= 5.0

    if t_top == 1 and top_pair <= 6:
        mid_pair = d_mid[0] if d_mid else 0
        bottom_high = d_bottom[0] if d_bottom else 0
        if t_mid == 1 and mid_pair < 10 and not (t_bottom == 5 and bottom_high >= 12):
            adj -= 4.2
            if t_bottom == 4:
                adj -= 3.2
        elif t_bottom == 2 and t_mid == 1:
            adj -= 3.0

    # If chi3 is dead, don't overprice a small chi2 upgrade unless bottom is a
    # protected anchor.
    if t_top == 0 and t_mid == 2 and t_bottom < 6:
        adj -= 0.8

    return adj


def _distribution_value(t_bottom: int, t_mid: int, t_top: int) -> float:
    live = int(t_bottom >= 1) + int(t_mid >= 1) + int(t_top >= 1)
    score = live * 0.85
    if t_mid >= 1 and t_top >= 1:
        score += 0.9
    if t_mid >= 2 and t_top >= 1:
        score += 0.6
    if t_mid == 0 and t_top == 0:
        score -= 2.6
    return score


def _score_max_money(
    eval_bottom: Tuple[int, ...],
    eval_mid: Tuple[int, ...],
    eval_top: Tuple[int, ...],
) -> float:
    """
    Rank-sensitive human Money score used by both profile Money and OPP Money.

    The score values each chi by type + rank, then adjusts for practical
    tradeoffs: small top pairs cannot easily justify breaking strong bottom and
    middle anchors, while premium top pairs can.
    """
    t_bottom = _hand_type(eval_bottom)
    t_mid = _hand_type(eval_mid)
    t_top = _hand_type(eval_top)
    d_bottom = _detail(eval_bottom)
    d_mid = _detail(eval_mid)
    d_top = _detail(eval_top)

    score = 0.0
    score += _five_hand_value("bottom", t_bottom, d_bottom)
    score += _five_hand_value("middle", t_mid, d_mid)
    score += _three_hand_value(t_top, d_top)
    score += _official_bonus_score(t_bottom, t_mid, t_top)
    score += _anchor_combo_value(t_bottom, t_mid, t_top, d_bottom, d_mid, d_top)
    score += _tradeoff_adjustment(t_bottom, t_mid, t_top, d_bottom, d_mid, d_top)
    score += _distribution_value(t_bottom, t_mid, t_top)

    return float(score)
