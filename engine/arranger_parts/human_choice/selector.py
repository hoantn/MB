from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


Eval5 = Tuple[int, List[int]]
Eval3 = Tuple[int, List[int]]


@dataclass(frozen=True)
class HumanChoiceCandidate:
    idx1: Tuple[int, int, int, int, int]
    idx2: Tuple[int, int, int, int, int]
    idx3: Tuple[int, int, int]
    e1: Eval5
    e2: Eval5
    e3: Eval3
    score_tuple: List[int]
    style_tuple: List[int]
    money_score: float


def _detail(ev: Tuple[int, Sequence[int]]) -> Sequence[int]:
    return ev[1] if len(ev) > 1 else []


def _main_rank(ev: Tuple[int, Sequence[int]]) -> int:
    d = _detail(ev)
    return int(d[0]) if d else -1


def _top_pair_rank(c: HumanChoiceCandidate) -> int:
    return _main_rank(c.e3) if c.e3[0] == 1 else -1


def _hard_prefix(c: HumanChoiceCandidate) -> int:
    return int(c.style_tuple[0]) if c.style_tuple else 1


def _legacy_key(c: HumanChoiceCandidate):
    return (_hard_prefix(c), c.money_score, tuple(c.style_tuple), tuple(c.score_tuple))


def _official_bonus_hint(c: HumanChoiceCandidate) -> int:
    t1, t2, t3 = c.e1[0], c.e2[0], c.e3[0]
    bonus = 0
    if t3 == 2:
        bonus += 80
    if t2 == 6:
        bonus += 35
    if t2 == 7:
        bonus += 60
    if t2 == 8:
        bonus += 70
    if t1 == 7:
        bonus += 35
    if t1 == 8:
        bonus += 45
    return bonus


def _live_value(c: HumanChoiceCandidate) -> int:
    t1, t2, t3 = c.e1[0], c.e2[0], c.e3[0]
    return int(t1 >= 1) + int(t2 >= 1) + int(t3 >= 1)


def _family_hint(c: HumanChoiceCandidate) -> int:
    """Rank strategic families before per-card refinement.

    This is intentionally not a replacement for Money. It is a human-choice
    layer used inside a Money-near band so one-off score tweaks do not decide
    every close layout.
    """
    t1, t2, t3 = c.e1[0], c.e2[0], c.e3[0]
    top_pair = _top_pair_rank(c)
    hint = _official_bonus_hint(c)

    if t1 >= 1 and t2 >= 1 and t3 >= 1:
        hint += 34
    elif t1 >= 1 and t2 >= 1:
        hint += 16

    if t1 == 6 and t2 >= 1 and t3 >= 1:
        hint += 20
    if t1 in (4, 5) and t2 >= 1 and t3 >= 1:
        hint += 18
    if t1 == 2 and t2 >= 1 and t3 >= 1:
        hint += 16
    if t1 in (4, 5) and t2 in (4, 5) and t3 == 0:
        hint += 10

    if t3 == 1:
        if top_pair >= 11:  # K/A
            hint += 14
        elif top_pair >= 9:  # J/Q
            hint += 8
        elif top_pair >= 4:
            hint += 4
        else:
            hint += 2
    elif t3 == 2:
        hint += 24

    return hint


def _rank_balance_key(c: HumanChoiceCandidate):
    return (
        _main_rank(c.e1),
        _main_rank(c.e2),
        _main_rank(c.e3),
        tuple(c.style_tuple),
    )


def _policy_key(c: HumanChoiceCandidate):
    return (
        _family_hint(c),
        _live_value(c),
        _rank_balance_key(c),
        c.money_score,
        tuple(c.score_tuple),
    )


def _same_anchor_live_top_override(
    legacy: HumanChoiceCandidate,
    candidates: Sequence[HumanChoiceCandidate],
    *,
    max_score_cost: float,
) -> Optional[HumanChoiceCandidate]:
    """Prefer a live top when chi1/chi2 keep the same hand classes.

    This captures the human rule behind examples like straight/two-pair/high
    card versus straight/two-pair/pair: if the lower anchors are still the same
    classes, a real chi3 is usually the line a player will choose.
    """
    if legacy.e3[0] != 0:
        return None

    viable: List[HumanChoiceCandidate] = []
    for c in candidates:
        if c.e3[0] <= legacy.e3[0]:
            continue
        if c.e1[0] != legacy.e1[0] or c.e2[0] != legacy.e2[0]:
            continue
        if legacy.money_score - c.money_score > max_score_cost:
            continue
        viable.append(c)

    if not viable:
        return None
    return max(viable, key=_policy_key)


def select_human_choice(
    candidates: Sequence[HumanChoiceCandidate],
    *,
    anchor_live_top_cost: float = 12.0,
) -> Optional[HumanChoiceCandidate]:
    """Select the layout most likely to be chosen by a human-style Money policy.

    Generator/manual suggestion ordering remains outside this module. This
    selector is for cached Auto Money/OPP Money split selection only.
    """
    if not candidates:
        return None

    legacy = max(candidates, key=_legacy_key)
    hard = _hard_prefix(legacy)
    hard_candidates = [c for c in candidates if _hard_prefix(c) == hard]
    if not hard_candidates:
        return legacy

    override = _same_anchor_live_top_override(
        legacy,
        hard_candidates,
        max_score_cost=anchor_live_top_cost,
    )
    if override is not None:
        return override

    return legacy
