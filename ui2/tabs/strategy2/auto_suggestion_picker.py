from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from engine.card import Card
from engine.rules import evaluate_5cards
from engine.scorer import evaluate_3cards


AUTO_PROFILE_FLAG = "_auto_profile_money"
AUTO_OPP_FLAG = "_auto_opp_money"

# Exact-hand escape hatch for rare hands that should not become broad rules.
# Item format: (sorted_13_codes_key, preferred_template_key)
# template_key = (chi1_type, chi2_type, chi3_type)
EXACT_HAND_TEMPLATE_PREFERENCES: Tuple[Tuple[str, Tuple[int, int, int]], ...] = ()


@dataclass(frozen=True)
class ScoreParts:
    equity: float = 0.0
    hand_shape: float = 0.0
    rule_bonus: float = 0.0
    rank: float = 0.0
    balance: float = 0.0
    top_value: float = 0.0
    penalty: float = 0.0
    strategy: float = 0.0
    position: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.equity
            +
            self.hand_shape
            + self.rule_bonus
            + self.rank
            + self.balance
            + self.top_value
            + self.penalty
            + self.strategy
            + self.position
        )


@dataclass(frozen=True)
class SuggestionContext:
    t1: int
    t2: int
    t3: int
    r1: int
    r2: int
    r3: int
    d1: Tuple[int, ...]
    d2: Tuple[int, ...]
    d3: Tuple[int, ...]
    score: float
    tie: Tuple[int, ...]


@dataclass(frozen=True)
class ChoiceOverrideRule:
    name: str
    current_matches: Callable[[SuggestionContext], bool]
    challenger_matches: Callable[[SuggestionContext, SuggestionContext], bool]
    key: Callable[[SuggestionContext, int], Tuple[float, ...]]


@dataclass(frozen=True)
class RowStrength:
    row: str
    hand_type: int
    detail: Tuple[int, ...]
    main_rank: int
    equity: float


@dataclass(frozen=True)
class CandidateAnalysis:
    suggestion: dict
    bottom: RowStrength
    middle: RowStrength
    top: RowStrength
    law_bonus: int
    live_count: int
    score_parts: ScoreParts
    score: float
    tie: Tuple[int, ...]


def has_playable_split(suggestion: Optional[dict]) -> bool:
    if not suggestion:
        return False
    return (
        len(list(suggestion.get("chi1_codes") or [])) == 5
        and len(list(suggestion.get("chi2_codes") or [])) == 5
        and len(list(suggestion.get("chi3_codes") or [])) == 3
    )


def split_key(suggestion: Optional[dict]) -> str:
    if not suggestion:
        return ""
    try:
        c1 = tuple(sorted(map(str, suggestion.get("chi1_codes") or [])))
        c2 = tuple(sorted(map(str, suggestion.get("chi2_codes") or [])))
        c3 = tuple(sorted(map(str, suggestion.get("chi3_codes") or [])))
        if len(c1) != 5 or len(c2) != 5 or len(c3) != 3:
            return ""
        return "|".join([",".join(c3), ",".join(c2), ",".join(c1)])
    except Exception:
        return ""


def _hand_key_from_suggestion(suggestion: Optional[dict]) -> str:
    if not suggestion:
        return ""
    try:
        codes = (
            list(map(str, suggestion.get("chi1_codes") or []))
            + list(map(str, suggestion.get("chi2_codes") or []))
            + list(map(str, suggestion.get("chi3_codes") or []))
        )
        if len(codes) != 13:
            return ""
        return ",".join(sorted(codes))
    except Exception:
        return ""


def _cards(codes: Sequence[str]) -> List[Card]:
    return [Card.from_code(str(code)) for code in codes]


def _eval_suggestion(suggestion: dict):
    c1 = _cards(list(suggestion.get("chi1_codes") or []))
    c2 = _cards(list(suggestion.get("chi2_codes") or []))
    c3 = _cards(list(suggestion.get("chi3_codes") or []))
    if len(c1) != 5 or len(c2) != 5 or len(c3) != 3:
        return None
    return evaluate_5cards(c1), evaluate_5cards(c2), evaluate_3cards(c3)


def _template_key(suggestion: dict) -> Tuple[int, int, int]:
    ev = _eval_suggestion(suggestion)
    if ev is None:
        return (-1, -1, -1)
    e1, e2, e3 = ev
    return (int(e1[0]), int(e2[0]), int(e3[0]))


def _rule_bonus_chi(t1: int, t2: int, t3: int) -> int:
    """Bonus chi theo luật Mậu Binh cho từng vị trí chi.

    Chi 1 là chi dưới 5 lá, chi 2 là chi giữa 5 lá, chi 3 là chi trên 3 lá.
    """
    bonus = 0
    if t3 == 2:      # xám chi 3
        bonus += 6
    if t2 == 6:      # cù lũ chi giữa
        bonus += 4
    elif t2 == 7:    # tứ quý chi giữa
        bonus += 16
    elif t2 == 8:    # thùng phá sảnh chi giữa
        bonus += 20
    if t1 == 7:      # tứ quý chi dưới
        bonus += 8
    elif t1 == 8:    # thùng phá sảnh chi dưới
        bonus += 10
    return bonus


def _hand_shape_score(t1: int, t2: int, t3: int) -> float:
    v5 = {
        8: 95.0,
        7: 82.0,
        6: 58.0,
        5: 47.0,
        4: 45.0,
        3: 30.0,
        2: 22.0,
        1: 13.0,
        0: 0.0,
    }
    v3 = {
        2: 78.0,
        1: 24.0,
        0: 0.0,
    }
    return v5.get(t1, 0.0) + v5.get(t2, 0.0) + v3.get(t3, 0.0)


def _rank_score(t1: int, t2: int, t3: int, r1: int, r2: int, r3: int) -> float:
    return (
        max(r1, 0) * 1.8
        + max(r2, 0) * 1.25
        + max(r3, 0) * (1.7 if t3 >= 1 else 1.0)
    )


def _detail_value(detail: Sequence[int], weights: Sequence[float]) -> float:
    score = 0.0
    for rank, weight in zip(detail, weights):
        score += max(int(rank), 0) * float(weight)
    return score


def _five_card_row_equity(t: int, detail: Sequence[int], *, row: str) -> float:
    """Value a 5-card hand in its actual row, not as an abstract hand name."""
    if row == "bottom":
        base = {
            8: 168.0,
            7: 150.0,
            6: 108.0,
            5: 86.0,
            4: 82.0,
            3: 54.0,
            2: 38.0,
            1: 21.0,
            0: 0.0,
        }
        rank_weights = {
            8: (3.8,),
            7: (4.2, 1.0),
            6: (5.4, 1.8),
            5: (2.8, 1.7, 1.1, 0.7, 0.4),
            4: (4.0,),
            3: (4.4, 0.8, 0.5),
            2: (3.2, 1.6, 0.4),
            1: (2.7, 0.6, 0.35, 0.2),
            0: (0.9, 0.55, 0.35, 0.2, 0.1),
        }
    else:
        base = {
            8: 132.0,
            7: 118.0,
            6: 86.0,
            5: 66.0,
            4: 63.0,
            3: 50.0,
            2: 39.0,
            1: 25.0,
            0: 0.0,
        }
        rank_weights = {
            8: (3.2,),
            7: (3.4, 0.8),
            6: (4.1, 1.4),
            5: (2.4, 1.5, 1.0, 0.6, 0.3),
            4: (3.3,),
            3: (4.2, 0.8, 0.5),
            2: (3.5, 1.8, 0.5),
            1: (3.0, 0.7, 0.4, 0.2),
            0: (0.8, 0.5, 0.3, 0.18, 0.1),
        }
    return base.get(t, 0.0) + _detail_value(detail, rank_weights.get(t, ()))


def _top_row_equity(t: int, detail: Sequence[int]) -> float:
    """Value the 3-card top row in its own 3-card world."""
    if t == 2:
        return 132.0 + _detail_value(detail, (6.0,))
    if t == 1:
        pair_rank = int(detail[0]) if detail else -1
        kicker = int(detail[1]) if len(detail) > 1 else -1
        # Pair K/A is premium, Q/J is good, tiny pairs should not dominate
        # a much stronger bottom/middle structure.
        premium = 16.0 if pair_rank >= 11 else (10.0 if pair_rank >= 9 else 0.0)
        tiny_penalty = -12.0 if pair_rank <= 3 else 0.0
        return 54.0 + pair_rank * 5.0 + max(kicker, 0) * 0.8 + premium + tiny_penalty
    # High-card top: A/K/Q high can be "enough"; low mậu is a real weakness.
    high = int(detail[0]) if detail else -1
    second = int(detail[1]) if len(detail) > 1 else -1
    third = int(detail[2]) if len(detail) > 2 else -1
    score = max(high, 0) * 3.4 + max(second, 0) * 1.2 + max(third, 0) * 0.5
    if high >= 12:
        score += 26.0
    elif high >= 11:
        score += 17.0
    elif high >= 10:
        score += 10.0
    elif high < 8:
        score -= 14.0
    return score


def _balance_score(t1: int, t2: int, t3: int) -> float:
    live = int(t1 >= 1) + int(t2 >= 1) + int(t3 >= 1)
    score = live * 10.0
    if live == 3:
        score += 8.0
    elif live == 2 and t1 >= 1 and t2 >= 1:
        score += 6.0
    return score


def _top_value_score(t3: int, r3: int) -> float:
    if t3 == 1:
        if r3 >= 12:      # A
            return 18.0
        if r3 >= 11:      # K
            return 14.0
        if r3 >= 10:      # Q
            return 10.0
        if r3 >= 8:       # T/J
            return 5.0
        return 2.0
    if t3 == 2:
        return 18.0 + max(r3, 0) * 1.5
    return 0.0


def _penalty_score(t1: int, t2: int, t3: int, r1: int, r3: int) -> float:
    score = 0.0
    if t3 == 0:
        # Mậu A/K/Q/J is still a usable top row when the lower rows improve.
        score -= 14.0 if r3 >= 9 else 30.0
        if t2 == 0:
            score -= 30.0
    if t2 == 0:
        score -= 28.0
    live = int(t1 >= 1) + int(t2 >= 1) + int(t3 >= 1)
    if t1 == 6 and live < 3:
        score -= 18.0
        if r1 <= 6:
            score -= 12.0
    return score


def _strategy_score(t1: int, t2: int, t3: int, r1: int, r2: int, r3: int) -> float:
    score = 0.0

    # A strong lower package can be worth more than preserving a tiny top pair:
    # e.g. Cu-Xam-Mau should beat Xam-Xam-Doi when the top pair is only small.
    if t1 >= 6 and t2 >= 3 and t3 == 0:
        score += 112.0
        if r3 >= 12:
            score += 14.0
        if t1 >= 7:
            score += 18.0

    # Two already-made lower chi (straight/flush or better) are a common human
    # choice even with a dead top, especially when the top still has broadway
    # cards. This prevents over-valuing a weak three-live row that breaks both.
    if t1 in (4, 5) and t2 in (4, 5) and t3 == 0:
        score += 112.0
        if t1 == 5 and t2 == 5:
            score += 18.0
        if r3 >= 9:
            score += 18.0

    # A real bottom straight/flush plus a premium middle pair and A/K-high top
    # is often preferred over three weak live pairs.
    if t1 in (4, 5) and t2 == 1 and t3 == 0 and r2 >= 10 and r3 >= 11:
        score += 118.0
        if r3 >= 12:
            score += 14.0
        if t1 == 5:
            score += 8.0

    # If the bottom is already a real straight/flush, upgrading the middle from
    # one pair to two-pair while keeping A-high on top is often worth more than
    # preserving a J-or-lower top pair.
    if t1 in (4, 5) and t2 == 2 and t3 == 0 and r3 >= 12:
        score += 130.0
        if t1 == 5:
            score += 8.0

    # When the bottom already keeps a bonus hand (quads/SF), a two-pair middle
    # with K/A-high top should beat keeping a tiny top pair with a one-pair
    # middle. This covers Tu-quy/Thu/Mau K over Tu-quy/Doi/Doi 2.
    if t1 >= 7 and t2 == 2 and t3 == 0 and r3 >= 11:
        score += 120.0

    return score


def _position_tradeoff_score(t1: int, t2: int, t3: int, r1: int, r2: int, r3: int) -> float:
    """Reward human-like trade-offs by seat position: bottom > middle > top.

    This layer only ranks already-visible suggestions. It does not create a new
    split; it prevents high top/middle preservation from over-shadowing a much
    stronger bottom hand when the remaining two rows are still usable.
    """
    score = 0.0

    # Full-house bottom with a usable middle pair and broadway top is often a
    # better practical choice than keeping a straight/trips bottom plus two-pair
    # middle. Do not apply this to tiny full-houses or dead middle/top rows.
    if t1 == 6 and r1 >= 7 and t2 >= 1 and r2 >= 6 and t3 == 0 and r3 >= 10:
        score += 158.0
        score += (r1 - 7) * 5.0
        score += min(max(r2 - 6, 0), 6) * 2.0
        if r3 >= 12:
            score += 10.0

    # More general positional value: the bottom row is the base, then middle,
    # then top. This keeps weak "three live" rows from beating a stronger
    # bottom/middle structure just because the top has a small pair.
    bottom_weight = {
        8: 74.0,
        7: 62.0,
        6: 50.0,
        5: 37.0,
        4: 35.0,
        3: 21.0,
        2: 15.0,
        1: 8.0,
        0: 0.0,
    }
    middle_weight = {
        8: 48.0,
        7: 42.0,
        6: 34.0,
        5: 25.0,
        4: 24.0,
        3: 17.0,
        2: 12.0,
        1: 7.0,
        0: 0.0,
    }
    top_weight = {
        2: 28.0,
        1: 9.0,
        0: 0.0,
    }
    score += bottom_weight.get(t1, 0.0)
    score += middle_weight.get(t2, 0.0)
    score += top_weight.get(t3, 0.0)
    score += max(r1, 0) * 1.5
    score += max(r2, 0) * 0.9
    score += max(r3, 0) * (0.7 if t3 >= 1 else 0.8)

    return score


def _row_strength(row: str, hand_type: int, detail: Sequence[int]) -> RowStrength:
    d = tuple(int(v) for v in detail)
    main_rank = int(d[0]) if d else -1
    if row == "bottom":
        equity = _five_card_row_equity(hand_type, d, row="bottom")
    elif row == "middle":
        equity = _five_card_row_equity(hand_type, d, row="middle")
    else:
        equity = _top_row_equity(hand_type, d)
    return RowStrength(
        row=row,
        hand_type=int(hand_type),
        detail=d,
        main_rank=main_rank,
        equity=equity,
    )


def _risk_adjustment(bottom: RowStrength, middle: RowStrength, top: RowStrength) -> float:
    score = 0.0
    if top.hand_type == 0:
        top_high = top.main_rank
        if top_high >= 12:
            score -= 4.0
        elif top_high >= 10:
            score -= 12.0
        elif top_high >= 8:
            score -= 22.0
        else:
            score -= 42.0
    if middle.hand_type == 0:
        score -= 34.0
    if bottom.hand_type == 6 and bottom.main_rank <= 3:
        score -= 22.0
    if top.hand_type == 1 and top.main_rank <= 3:
        score -= 26.0
    if middle.hand_type == 1 and middle.main_rank <= 4:
        score -= 11.0
    return score


def _practical_tradeoff_adjustment(
    bottom: RowStrength,
    middle: RowStrength,
    top: RowStrength,
) -> float:
    score = 0.0

    # A made bottom with a real middle and usable A/K/Q top is often better
    # than protecting tiny top pairs. This is the normal path, before rules.
    if bottom.hand_type >= 6 and middle.hand_type >= 3 and top.hand_type == 0:
        score += 62.0
        if top.main_rank >= 12:
            score += 16.0
        if bottom.hand_type >= 7:
            score += 18.0

    if bottom.hand_type == 6:
        if bottom.main_rank >= 7:
            score += 44.0
        elif bottom.main_rank <= 3:
            # Small full-house is not automatically better than a premium
            # flush/straight line that keeps middle/top ranks high.
            score -= 26.0

    if bottom.hand_type in (4, 5) and bottom.main_rank >= 11 and middle.hand_type >= 1:
        score += 28.0
        if top.hand_type >= 1:
            score += 18.0
    if bottom.hand_type in (4, 5) and middle.hand_type == 1 and middle.main_rank >= 10:
        if top.hand_type == 0 and top.main_rank >= 12:
            score += 34.0

    if middle.hand_type >= 3 and top.hand_type == 0 and top.main_rank >= 10:
        score += 20.0
    if middle.hand_type == 2 and middle.main_rank >= 10 and top.hand_type == 1 and top.main_rank >= 10:
        score += 26.0

    live = int(bottom.hand_type >= 1) + int(middle.hand_type >= 1) + int(top.hand_type >= 1)
    if live == 3:
        score += 8.0
        if top.hand_type == 1 and top.main_rank <= 4:
            score -= 16.0
    elif live == 2 and bottom.hand_type >= 1 and middle.hand_type >= 1:
        score += 6.0
    return score


def _score_candidate_parts(
    bottom: RowStrength,
    middle: RowStrength,
    top: RowStrength,
) -> ScoreParts:
    t1, t2, t3 = bottom.hand_type, middle.hand_type, top.hand_type
    r1, r2, r3 = bottom.main_rank, middle.main_rank, top.main_rank
    rule_bonus = _rule_bonus_chi(t1, t2, t3)
    equity = (
        bottom.equity * 1.18
        + middle.equity * 1.03
        + top.equity * 0.82
        + _risk_adjustment(bottom, middle, top)
        + _practical_tradeoff_adjustment(bottom, middle, top)
    )
    return ScoreParts(
        equity=equity,
        hand_shape=_hand_shape_score(t1, t2, t3) * 0.35,
        rule_bonus=(rule_bonus * 16.0) + (18.0 if rule_bonus else 0.0),
        rank=_rank_score(t1, t2, t3, r1, r2, r3) * 0.45,
        balance=_balance_score(t1, t2, t3) * 0.25,
        top_value=_top_value_score(t3, r3),
        penalty=_penalty_score(t1, t2, t3, r1, r3) * 0.65,
        strategy=_strategy_score(t1, t2, t3, r1, r2, r3) * 0.25,
        position=_position_tradeoff_score(t1, t2, t3, r1, r2, r3) * 0.18,
    )


def _analyze_suggestion(suggestion: dict) -> Optional[CandidateAnalysis]:
    try:
        ev = _eval_suggestion(suggestion)
    except Exception:
        ev = None
    if ev is None:
        return None

    e1, e2, e3 = ev
    bottom = _row_strength("bottom", int(e1[0]), e1[1] if len(e1) > 1 else [])
    middle = _row_strength("middle", int(e2[0]), e2[1] if len(e2) > 1 else [])
    top = _row_strength("top", int(e3[0]), e3[1] if len(e3) > 1 else [])
    live = int(bottom.hand_type >= 1) + int(middle.hand_type >= 1) + int(top.hand_type >= 1)
    rule_bonus = _rule_bonus_chi(bottom.hand_type, middle.hand_type, top.hand_type)
    parts = _score_candidate_parts(bottom, middle, top)
    score = parts.total
    tie = (
        rule_bonus,
        bottom.hand_type,
        bottom.main_rank,
        middle.hand_type,
        middle.main_rank,
        top.hand_type,
        top.main_rank,
        live,
        int(suggestion.get("variant") or 0),
    )
    return CandidateAnalysis(
        suggestion=suggestion,
        bottom=bottom,
        middle=middle,
        top=top,
        law_bonus=rule_bonus,
        live_count=live,
        score_parts=parts,
        score=score,
        tie=tie,
    )


def _human_choice_score(suggestion: dict) -> Tuple[float, Tuple[int, ...]]:
    """Score one existing final-list suggestion.

    This is not an arranger. It only ranks rows that already survived the UI
    suggestion pipeline by row position, rank, law bonus, risk, and trade-off.
    """
    analysis = _analyze_suggestion(suggestion)
    if analysis is None:
        return (-1_000_000.0, ())
    return (analysis.score, analysis.tie)


def _suggestion_context(suggestion: dict) -> Optional[SuggestionContext]:
    analysis = _analyze_suggestion(suggestion)
    if analysis is None:
        return None
    bottom, middle, top = analysis.bottom, analysis.middle, analysis.top
    return SuggestionContext(
        t1=bottom.hand_type,
        t2=middle.hand_type,
        t3=top.hand_type,
        r1=bottom.main_rank,
        r2=middle.main_rank,
        r3=top.main_rank,
        d1=bottom.detail,
        d2=middle.detail,
        d3=top.detail,
        score=analysis.score,
        tie=analysis.tie,
    )


def _is_weak_three_pair_context(ctx: SuggestionContext) -> bool:
    if not (ctx.t1 == 1 and ctx.t2 == 1 and ctx.t3 == 1):
        return False
    # The bottom pair can be high, but if top and middle pairs are small this
    # line is usually not worth protecting over a real made bottom hand.
    return ctx.r3 <= 6 and ctx.r2 <= 6


def _is_weak_three_live_context(ctx: SuggestionContext) -> bool:
    if not (ctx.t3 == 1 and ctx.t2 == 1 and ctx.t1 in (1, 2)):
        return False
    # Pair Q/K/A on top is valuable enough to protect. J or lower can be
    # sacrificed when the alternative keeps A/K-high top and greatly improves
    # the bottom hand.
    return ctx.r3 <= 9 and ctx.r2 <= 6


def _beats_weak_three_pairs_context(ctx: SuggestionContext) -> bool:
    if ctx.t3 != 0:
        return False
    if ctx.r3 < 9:  # J/Q/K/A-high top, not trash.
        return False
    if ctx.t1 < 4:  # bottom must be straight/flush/full-house/quads/SF.
        return False
    if ctx.t2 < 1:  # middle must still have at least a pair.
        return False
    return True


def _is_tiny_top_pair_three_pairs_context(ctx: SuggestionContext) -> bool:
    if not (ctx.t1 == 1 and ctx.t2 == 1 and ctx.t3 == 1):
        return False
    # Pair 2/3/4 on top is too small to over-protect when another visible row
    # keeps a real straight/flush bottom and a premium middle pair.
    return ctx.r3 <= 2


def _beats_tiny_top_pair_three_pairs_context(ctx: SuggestionContext) -> bool:
    if ctx.t3 != 0:
        return False
    if ctx.t1 not in (4, 5):  # straight/flush bottom; keep this rule narrow.
        return False
    if ctx.t2 != 1 or ctx.r2 < 10:  # Q/K/A middle pair.
        return False
    if ctx.r3 < 10:  # Q/K/A high-card top, not low trash.
        return False
    return True


def _beats_weak_three_live_context(ctx: SuggestionContext) -> bool:
    if ctx.t3 != 0:
        return False
    if ctx.r3 < 11:  # K/A-high top, not trash.
        return False
    if ctx.t1 not in (4, 5):  # this rule is for straight/flush bottom.
        return False
    if ctx.t2 < 1:  # middle must still have at least a pair.
        return False
    return True


def _is_top_pair_protected_but_bottom_underpowered(ctx: SuggestionContext) -> bool:
    if ctx.t3 != 1:
        return False
    if ctx.r3 < 10:  # Q/K/A top pair is valuable, but not always worth overprotecting.
        return False
    if ctx.t2 != 1:
        return False
    if ctx.t1 not in (2, 3):  # two-pair/trips bottom, but not full-house.
        return False
    return True


def _beats_top_pair_with_big_full_house_context(ctx: SuggestionContext) -> bool:
    if ctx.t1 != 6:  # full house bottom
        return False
    if ctx.r1 < 8:   # trips T/J/Q/K/A-ish, avoid broad low full-house rule.
        return False
    if ctx.t2 != 1 or ctx.r2 < 10:  # keep a Q/K/A pair in the middle
        return False
    if ctx.t3 != 0 or ctx.r3 < 10:  # Q/K/A-high top, not trash.
        return False
    return True


def _is_trips_two_pair_top_pair_overprotected(ctx: SuggestionContext) -> bool:
    if ctx.t1 != 3:  # trips bottom
        return False
    if ctx.r1 < 10:  # Q/K/A trips only; avoid broad low-trips reshuffles.
        return False
    if ctx.t2 != 2:  # middle two-pair remains useful.
        return False
    if ctx.t3 != 1 or ctx.r3 < 10:  # Q/K/A top pair is valuable, but not absolute.
        return False
    return True


def _beats_trips_two_pair_top_pair_with_full_house_context(ctx: SuggestionContext) -> bool:
    if ctx.t1 != 6:  # full house bottom
        return False
    if ctx.r1 < 10:  # Q/K/A full-house anchor.
        return False
    if ctx.t2 != 2:  # keep the middle as two-pair.
        return False
    if ctx.t3 != 0 or ctx.r3 < 10:  # Q/K/A-high top, not dead trash.
        return False
    return True


def _is_trips_pair_small_top_pair_overprotected(ctx: SuggestionContext) -> bool:
    if ctx.t1 != 3:  # trips bottom
        return False
    if ctx.t2 != 1:  # middle keeps only one pair
        return False
    if ctx.t3 != 1:
        return False
    # Pair 2-6 on top is not valuable enough to dominate a playable full-house
    # route when the middle pair and dead top cards stay useful.
    return ctx.r3 <= 4


def _beats_trips_pair_small_top_pair_with_full_house_context(
    current: SuggestionContext,
    ctx: SuggestionContext,
) -> bool:
    if ctx.t1 != 6:  # full house bottom
        return False
    if ctx.r1 < current.r1:  # do not trade down the trips rank into a weaker full-house.
        return False
    if ctx.t2 != 1:
        return False
    if ctx.r2 < max(9, current.r2 - 1):  # keep a J/Q/K/A-ish middle pair.
        return False
    if ctx.t3 != 0:
        return False
    if ctx.r3 < 10:  # Q/K/A-high top, not dead trash.
        return False
    return True


def _is_bottom_underpowered_against_playable_full_house(ctx: SuggestionContext) -> bool:
    if ctx.t1 >= 6:
        return False
    # This covers the common over-protection mistake: preserving a two-pair
    # middle/top-looking row while the bottom remains only trips/straight/flush.
    return ctx.t2 <= 2


def _beats_underpowered_bottom_with_playable_full_house_context(ctx: SuggestionContext) -> bool:
    if ctx.t1 != 6:  # full house bottom
        return False
    if ctx.t2 != 1:
        return False
    if ctx.t3 != 0:
        return False
    # Pair Q/K/A in the middle is clearly playable. Pair 9/J/T can also be
    # enough when the top remains A/K-high, which covers Cu-Doi-Mau over
    # Sanh/Xam-Doi-Doi without making low-pair middle hands too broad.
    if ctx.r2 < 10 and not (ctx.r2 >= 7 and ctx.r3 >= 11):
        return False
    if ctx.r3 < 10:  # Q/K/A-high top, not dead trash.
        return False
    return True


def _is_bottom_underpowered_with_live_middle_context(ctx: SuggestionContext) -> bool:
    if ctx.t1 >= 6:
        return False
    return ctx.t2 >= 1


def _beats_underpowered_bottom_with_full_house_live_middle_context(
    current: SuggestionContext,
    ctx: SuggestionContext,
) -> bool:
    if ctx.t1 != 6:  # full house bottom
        return False
    if ctx.t2 < 1:
        return False
    # The full-house line must keep middle broadly comparable. It can trade
    # two-pair down to a stronger one-pair line only when the top remains high.
    if ctx.t2 < current.t2 - 1:
        return False
    if ctx.t2 == current.t2 - 1 and ctx.r2 < max(5, current.r2):
        return False
    if ctx.t3 == 0:
        return ctx.r3 >= 9  # J/Q/K/A-high top is usable.
    if ctx.t3 >= current.t3:
        return True
    return ctx.t3 == 1 and ctx.r3 >= 10


def _is_full_house_trips_middle_high_top_context(ctx: SuggestionContext) -> bool:
    if ctx.t1 != 6:
        return False
    if ctx.t2 != 3:
        return False
    if ctx.t3 != 0:
        return False
    return ctx.r3 >= 9


def _beats_full_house_trips_middle_with_flush_middle_context(
    current: SuggestionContext,
    ctx: SuggestionContext,
) -> bool:
    if ctx.t1 != 6:
        return False
    if ctx.t2 != 5:
        return False
    if ctx.t3 != 0:
        return False
    # Middle is the deciding row here. Flush must beat trips in a 5-card row
    # unless it damages the full-house anchor or leaves a weak top row.
    if ctx.r1 < current.r1 - 1:
        return False
    if ctx.r3 < max(9, current.r3 - 2):
        return False
    return True


def _is_full_house_pair_small_top_pair_context(ctx: SuggestionContext) -> bool:
    if ctx.t1 != 6:
        return False
    if ctx.t2 != 1:
        return False
    if ctx.t3 != 1:
        return False
    # Pair 2-7 on top should not dominate a two-pair middle when the top can
    # remain A/K/Q-high. Pair 8+ is no longer a tiny protection target.
    return ctx.r3 <= 5


def _beats_full_house_pair_small_top_pair_with_two_pair_middle(
    current: SuggestionContext,
    ctx: SuggestionContext,
) -> bool:
    if ctx.t1 != 6:
        return False
    if ctx.r1 < current.r1:
        return False
    if ctx.t2 != 2:
        return False
    if ctx.r2 < current.r2:  # do not trade to a weaker main middle pair.
        return False
    if ctx.t3 != 0 or ctx.r3 < 10:  # keep Q/K/A-high top.
        return False
    return True


def _rule_key_weak_three_pairs(ctx: SuggestionContext, idx: int) -> Tuple[float, ...]:
    return (ctx.score, ctx.t1, ctx.t2, ctx.r3, ctx.r2, -idx)


def _rule_key_real_bottom(ctx: SuggestionContext, idx: int) -> Tuple[float, ...]:
    return (ctx.t1, ctx.r1, ctx.r2, ctx.r3, -idx)


def _rule_key_ranked_full_house(ctx: SuggestionContext, idx: int) -> Tuple[float, ...]:
    return (ctx.r1, ctx.r2, ctx.r3, -idx)


def _rule_key_full_house_score(ctx: SuggestionContext, idx: int) -> Tuple[float, ...]:
    return (ctx.r1, ctx.r2, ctx.r3, ctx.score, -idx)


def _rule_key_playable_full_house(ctx: SuggestionContext, idx: int) -> Tuple[float, ...]:
    return (ctx.r2, ctx.r3, ctx.r1, ctx.score, -idx)


def _rule_key_flush_middle(ctx: SuggestionContext, idx: int) -> Tuple[float, ...]:
    return (ctx.r2, ctx.r1, ctx.r3, ctx.score, -idx)


def _rule_key_big_full_house(ctx: SuggestionContext, idx: int) -> Tuple[float, ...]:
    return (ctx.score, ctx.r1, ctx.r3, ctx.r2, -idx)


CHOICE_OVERRIDE_RULES: Tuple[ChoiceOverrideRule, ...] = (
    ChoiceOverrideRule(
        name="weak_three_pairs_to_real_bottom",
        current_matches=_is_weak_three_pair_context,
        challenger_matches=lambda current, ctx: _beats_weak_three_pairs_context(ctx),
        key=_rule_key_weak_three_pairs,
    ),
    ChoiceOverrideRule(
        name="tiny_top_three_pairs_to_straight_or_flush",
        current_matches=_is_tiny_top_pair_three_pairs_context,
        challenger_matches=lambda current, ctx: _beats_tiny_top_pair_three_pairs_context(ctx),
        key=_rule_key_real_bottom,
    ),
    ChoiceOverrideRule(
        name="trips_two_pair_top_pair_to_full_house_two_pair",
        current_matches=_is_trips_two_pair_top_pair_overprotected,
        challenger_matches=lambda current, ctx: _beats_trips_two_pair_top_pair_with_full_house_context(ctx),
        key=_rule_key_ranked_full_house,
    ),
    ChoiceOverrideRule(
        name="trips_pair_small_top_pair_to_full_house_pair",
        current_matches=_is_trips_pair_small_top_pair_overprotected,
        challenger_matches=_beats_trips_pair_small_top_pair_with_full_house_context,
        key=_rule_key_full_house_score,
    ),
    ChoiceOverrideRule(
        name="underpowered_bottom_to_full_house_live_middle",
        current_matches=_is_bottom_underpowered_with_live_middle_context,
        challenger_matches=_beats_underpowered_bottom_with_full_house_live_middle_context,
        key=_rule_key_playable_full_house,
    ),
    ChoiceOverrideRule(
        name="full_house_trips_middle_to_flush_middle",
        current_matches=_is_full_house_trips_middle_high_top_context,
        challenger_matches=_beats_full_house_trips_middle_with_flush_middle_context,
        key=_rule_key_flush_middle,
    ),
    ChoiceOverrideRule(
        name="underpowered_bottom_to_playable_full_house",
        current_matches=_is_bottom_underpowered_against_playable_full_house,
        challenger_matches=lambda current, ctx: _beats_underpowered_bottom_with_playable_full_house_context(ctx),
        key=_rule_key_playable_full_house,
    ),
    ChoiceOverrideRule(
        name="full_house_pair_small_top_pair_to_two_pair_middle",
        current_matches=_is_full_house_pair_small_top_pair_context,
        challenger_matches=_beats_full_house_pair_small_top_pair_with_two_pair_middle,
        key=_rule_key_full_house_score,
    ),
    ChoiceOverrideRule(
        name="top_pair_underpowered_bottom_to_big_full_house",
        current_matches=_is_top_pair_protected_but_bottom_underpowered,
        challenger_matches=lambda current, ctx: _beats_top_pair_with_big_full_house_context(ctx),
        key=_rule_key_big_full_house,
    ),
    ChoiceOverrideRule(
        name="weak_three_live_to_straight_or_flush",
        current_matches=_is_weak_three_live_context,
        challenger_matches=lambda current, ctx: _beats_weak_three_live_context(ctx),
        key=_rule_key_weak_three_pairs,
    ),
)


def _apply_override_rule(
    rule: ChoiceOverrideRule,
    candidates: List[Tuple[int, dict, SuggestionContext]],
    current_idx: int,
    current: SuggestionContext,
) -> int:
    if not rule.current_matches(current):
        return current_idx

    best: Optional[Tuple[Tuple[float, ...], int]] = None
    for idx, _item, ctx in candidates:
        if idx == current_idx:
            continue
        if not rule.challenger_matches(current, ctx):
            continue
        key = rule.key(ctx, idx)
        if best is None or key > best[0]:
            best = (key, idx)
    return current_idx if best is None else int(best[1])


def _pairwise_override_index(
    candidates: List[Tuple[int, dict, SuggestionContext]],
    current_idx: int,
) -> int:
    current = next((ctx for idx, _item, ctx in candidates if idx == current_idx), None)
    if current is None:
        return current_idx

    for rule in CHOICE_OVERRIDE_RULES:
        override_idx = _apply_override_rule(rule, candidates, current_idx, current)
        if override_idx != current_idx:
            return override_idx
    return current_idx


def clear_auto_flags(suggestions: Iterable[dict]) -> None:
    for item in list(suggestions or []):
        if isinstance(item, dict):
            item.pop(AUTO_PROFILE_FLAG, None)
            item.pop(AUTO_OPP_FLAG, None)


def pick_auto_suggestion_index(
    suggestions: List[dict],
    *,
    is_special_row: Optional[Callable[[dict], bool]] = None,
) -> int:
    """Pick one existing final-list suggestion for Auto.

    The list order is already the UI-filtered/sorted strategy output. The picker
    therefore starts conservatively: choose the first playable non-special row.
    Future human-choice rules must still pick from this same list.
    """
    if EXACT_HAND_TEMPLATE_PREFERENCES:
        preferred_by_hand = dict(EXACT_HAND_TEMPLATE_PREFERENCES)
        for idx, item in enumerate(list(suggestions or [])):
            if not isinstance(item, dict) or not has_playable_split(item):
                continue
            try:
                if is_special_row is not None and is_special_row(item):
                    continue
            except Exception:
                pass
            hand_key = _hand_key_from_suggestion(item)
            preferred_template = preferred_by_hand.get(hand_key)
            if preferred_template is not None and _template_key(item) == preferred_template:
                return idx

    best: Optional[Tuple[Tuple[float, Tuple[int, ...], int], int]] = None
    contexts: List[Tuple[int, dict, SuggestionContext]] = []
    for idx, item in enumerate(list(suggestions or [])):
        if not isinstance(item, dict) or not has_playable_split(item):
            continue
        try:
            if is_special_row is not None and is_special_row(item):
                continue
        except Exception:
            pass
        ctx = _suggestion_context(item)
        if ctx is None:
            continue
        contexts.append((idx, item, ctx))
        score, tie = ctx.score, ctx.tie
        # Earlier rows remain a final tie-breaker, not the primary selector.
        key = (score, tie, -idx)
        if best is None or key > best[0]:
            best = (key, idx)
    if best is not None:
        return _pairwise_override_index(contexts, int(best[1]))
    for idx, item in enumerate(list(suggestions or [])):
        if isinstance(item, dict) and has_playable_split(item):
            return idx
    return -1


def mark_auto_suggestion(
    base_suggestions: List[dict],
    final_suggestions: List[dict],
    *,
    policy: str,
    is_special_row: Optional[Callable[[dict], bool]] = None,
) -> int:
    """Mark the selected Auto row in the final list and matching base list.

    Returns the selected index in ``final_suggestions``. No new split is created.
    If the final row does not exist in the base list, a copy is appended so
    existing Auto Play code that reads ``_suggestions`` can still find it.
    """
    flag = AUTO_OPP_FLAG if str(policy).lower() == "opp" else AUTO_PROFILE_FLAG
    clear_auto_flags(base_suggestions)
    clear_auto_flags(final_suggestions)

    idx = pick_auto_suggestion_index(final_suggestions, is_special_row=is_special_row)
    if idx < 0:
        return -1

    selected = final_suggestions[idx]
    selected[flag] = True
    selected["_auto_from_final_suggestions"] = True
    if str(selected.get("mode", "")).lower() == "money":
        selected["mode"] = "max"

    key = split_key(selected)
    matched = False
    for item in list(base_suggestions or []):
        if key and split_key(item) == key:
            item[flag] = True
            item["_auto_from_final_suggestions"] = True
            if str(item.get("mode", "")).lower() == "money":
                item["mode"] = "max"
            matched = True
            break

    if not matched and base_suggestions is not None:
        copied = dict(selected)
        copied[flag] = True
        copied["_auto_from_final_suggestions"] = True
        base_suggestions.append(copied)

    return idx
