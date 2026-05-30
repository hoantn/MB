from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Dict, Iterable, List, Optional, Tuple

from engine.card import Card
from engine.money_scoring import (
    ThreeChi,
    score_money_vs_opp,
    evaluate_5cards,
    evaluate_3cards,
)

from engine.arranger import _map_eval_top_to_5scale  # type: ignore


def _cmp_hand(my_type: int, my_detail: List[int], opp_type: int, opp_detail: List[int]) -> int:
    if my_type != opp_type:
        return 1 if my_type > opp_type else -1
    for a, b in zip(my_detail, opp_detail):
        if a != b:
            return 1 if a > b else -1
    if len(my_detail) != len(opp_detail):
        return 1 if len(my_detail) > len(opp_detail) else -1
    return 0


def _base_cmp_no_bonus(my_cards: List[Card], opp_cards: List[Card], chi_index: int) -> int:
    if chi_index in (1, 2):
        my_t, my_d = evaluate_5cards(my_cards)
        op_t, op_d = evaluate_5cards(opp_cards)
        return _cmp_hand(my_t, my_d, op_t, op_d)
    my_t, my_d = evaluate_3cards(my_cards)
    op_t, op_d = evaluate_3cards(opp_cards)
    return _cmp_hand(my_t, my_d, op_t, op_d)


def _is_foul(chi1: List[Card], chi2: List[Card], chi3: List[Card]) -> bool:
    if not (len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3):
        return True

    e1 = evaluate_5cards(chi1)
    e2 = evaluate_5cards(chi2)
    e3 = evaluate_3cards(chi3)

    eval1 = (e1[0], *e1[1])
    eval2 = (e2[0], *e2[1])
    eval3 = (e3[0], *e3[1])

    top_mapped = _map_eval_top_to_5scale(eval3)  # type: ignore[arg-type]

    if tuple(top_mapped) > tuple(eval2):
        return True
    if tuple(eval2) > tuple(eval1):
        return True
    return False


@dataclass(frozen=True)
class _EvalInfo:
    total_money: int
    base_cmp_c1: int
    base_cmp_c2: int
    base_cmp_c3: int

    @property
    def lose_all(self) -> bool:
        return self.base_cmp_c1 < 0 and self.base_cmp_c2 < 0 and self.base_cmp_c3 < 0

    @property
    def win_all(self) -> bool:
        return self.base_cmp_c1 > 0 and self.base_cmp_c2 > 0 and self.base_cmp_c3 > 0

    @property
    def wins(self) -> int:
        return (1 if self.base_cmp_c1 > 0 else 0) + (1 if self.base_cmp_c2 > 0 else 0) + (1 if self.base_cmp_c3 > 0 else 0)

    @property
    def losses(self) -> int:
        return (1 if self.base_cmp_c1 < 0 else 0) + (1 if self.base_cmp_c2 < 0 else 0) + (1 if self.base_cmp_c3 < 0 else 0)

    @property
    def draws(self) -> int:
        return 3 - self.wins - self.losses


def _eval_vs_opp(my: ThreeChi, opp: ThreeChi, *, allow_special_13: bool = True) -> _EvalInfo:
    total = score_money_vs_opp(my, opp, allow_special_13=allow_special_13)
    c1 = _base_cmp_no_bonus(my.chi1, opp.chi1, 1)
    c2 = _base_cmp_no_bonus(my.chi2, opp.chi2, 2)
    c3 = _base_cmp_no_bonus(my.chi3, opp.chi3, 3)
    return _EvalInfo(total_money=total, base_cmp_c1=c1, base_cmp_c2=c2, base_cmp_c3=c3)


def _anti_score(info: _EvalInfo, changed_slots: int) -> Tuple[int, int, int, int, int, int, int]:
    """
    Smart permutation target.

    The first priority is the actual table outcome, not cosmetic hand strength:
    win all if possible, never lose all if avoidable, then maximize won chis and
    minimize lost chis. Total money is only a tie-breaker after chi outcome.
    """
    return (
        1 if info.win_all else 0,
        1 if not info.lose_all else 0,
        int(info.wins),
        -int(info.losses),
        int(info.draws),
        int(info.total_money),
        -int(changed_slots),
    )


def _swap_one(a: List[str], i: int, b: List[str], j: int) -> None:
    a[i], b[j] = b[j], a[i]


def _changed_slots(
    base: Tuple[List[str], List[str], List[str]],
    cand: Tuple[List[str], List[str], List[str]],
) -> int:
    b = base[0] + base[1] + base[2]
    c = cand[0] + cand[1] + cand[2]
    return sum(1 for x, y in zip(b, c) if x != y)


def _ordered_pairs_for_state(info: _EvalInfo) -> List[Tuple[int, int]]:
    """
    Build swap directions from the current result.

    Losing chis are touched first because the goal is to rescue a lost chi or
    turn a near-win into a scoop. Remaining directions are kept as fallback so
    the search stays complete inside its small budget.
    """
    cmps = {1: info.base_cmp_c1, 2: info.base_cmp_c2, 3: info.base_cmp_c3}
    losing = [idx for idx, cmpv in cmps.items() if cmpv < 0]
    donors = [idx for idx, cmpv in cmps.items() if cmpv >= 0]

    ordered: List[Tuple[int, int]] = []
    for lost in losing:
        for donor in donors:
            if donor != lost:
                ordered.append((donor, lost))

    # Fallback directions allow attack mode when the base hand is already good.
    for pair in [(1, 2), (2, 3), (1, 3), (2, 1), (3, 2), (3, 1)]:
        if pair not in ordered:
            ordered.append(pair)
    return ordered


def _swap_between(
    hands: Tuple[List[str], List[str], List[str]],
    a_idx: int,
    b_idx: int,
    ia: int,
    ib: int,
) -> Tuple[List[str], List[str], List[str]]:
    out = [list(hands[0]), list(hands[1]), list(hands[2])]
    a = out[a_idx - 1]
    b = out[b_idx - 1]
    _swap_one(a, ia, b, ib)
    return (out[0], out[1], out[2])


def _swap_two_between(
    hands: Tuple[List[str], List[str], List[str]],
    a_idx: int,
    b_idx: int,
    ia_pair: Tuple[int, int],
    ib_pair: Tuple[int, int],
) -> Tuple[List[str], List[str], List[str]]:
    out = [list(hands[0]), list(hands[1]), list(hands[2])]
    a = out[a_idx - 1]
    b = out[b_idx - 1]
    for ia, ib in zip(ia_pair, ib_pair):
        _swap_one(a, ia, b, ib)
    return (out[0], out[1], out[2])


def _iter_smart_swaps(
    hands: Tuple[List[str], List[str], List[str]],
    info: _EvalInfo,
    *,
    include_double: bool,
    max_candidates: int,
) -> Iterable[Tuple[List[str], List[str], List[str]]]:
    """
    Generate local permutations with a hard budget.

    Layer 1 swaps one card and is cheap. Layer 2 swaps two cards only when the
    hand is in danger or close to a scoop; this is the minimum needed to move a
    small pair/combo without falling back to full 13-card generation.
    """
    yielded = 0
    seen = set()

    def _emit(cand: Tuple[List[str], List[str], List[str]]):
        nonlocal yielded
        key = tuple(cand[0] + cand[1] + cand[2])
        if key in seen:
            return None
        seen.add(key)
        yielded += 1
        return cand

    lens = {1: len(hands[0]), 2: len(hands[1]), 3: len(hands[2])}
    for a_idx, b_idx in _ordered_pairs_for_state(info):
        for ia in range(lens[a_idx]):
            for ib in range(lens[b_idx]):
                cand = _emit(_swap_between(hands, a_idx, b_idx, ia, ib))
                if cand is not None:
                    yield cand
                    if yielded >= max_candidates:
                        return

    if not include_double:
        return

    for a_idx, b_idx in _ordered_pairs_for_state(info):
        if lens[a_idx] < 2 or lens[b_idx] < 2:
            continue
        for ia_pair in combinations(range(lens[a_idx]), 2):
            for ib_pair in combinations(range(lens[b_idx]), 2):
                cand = _emit(_swap_two_between(hands, a_idx, b_idx, ia_pair, ib_pair))
                if cand is not None:
                    yield cand
                    if yielded >= max_candidates:
                        return


def _codes_to_threechi(s: dict) -> Optional[ThreeChi]:
    chi1 = list(s.get("chi1_codes") or [])
    chi2 = list(s.get("chi2_codes") or [])
    chi3 = list(s.get("chi3_codes") or [])
    if not (len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3):
        return None
    try:
        c1 = [Card.from_code(x) for x in chi1]
        c2 = [Card.from_code(x) for x in chi2]
        c3 = [Card.from_code(x) for x in chi3]
        if _is_foul(c1, c2, c3):
            return None
        return ThreeChi(c1, c2, c3)
    except Exception:
        return None


def build_anti_sap_suggestions(
    *,
    my_base: dict,
    opp_base: dict,
    label_prefix: str = "Tối ưu",
    max_out: int = 3,
) -> List[dict]:
    """
    Smart local optimization versus NGU/current opponent.

    Keep the existing generator intact. This function only rearranges the P
    hand supplied in my_base against a fixed opp_base (NGU/current opponent).
    """
    my_three0 = _codes_to_threechi(my_base)
    opp_three = _codes_to_threechi(opp_base)
    if my_three0 is None or opp_three is None:
        return []

    chi1_0 = list(my_base.get("chi1_codes") or [])
    chi2_0 = list(my_base.get("chi2_codes") or [])
    chi3_0 = list(my_base.get("chi3_codes") or [])

    base_hands = (chi1_0, chi2_0, chi3_0)
    base_info = _eval_vs_opp(my_three0, opp_three)
    base_score = _anti_score(base_info, 0)

    best_pool: Dict[
        Tuple[str, ...],
        Tuple[
            Tuple[int, int, int, int, int, int, int],
            _EvalInfo,
            Tuple[List[str], List[str], List[str]],
            int,
        ],
    ] = {}
    card_cache: Dict[str, Card] = {}

    def _card(code: str) -> Card:
        cached = card_cache.get(code)
        if cached is not None:
            return cached
        parsed = Card.from_code(code)
        card_cache[code] = parsed
        return parsed

    def _try_add(c1: List[str], c2: List[str], c3: List[str]) -> None:
        key = tuple(c1 + c2 + c3)
        if key in best_pool:
            return
        try:
            tc1 = [_card(x) for x in c1]
            tc2 = [_card(x) for x in c2]
            tc3 = [_card(x) for x in c3]
            if _is_foul(tc1, tc2, tc3):
                return
            my_three = ThreeChi(tc1, tc2, tc3)
            info = _eval_vs_opp(my_three, opp_three)
            changed = _changed_slots(base_hands, (c1, c2, c3))
            score = _anti_score(info, changed)
            best_pool[key] = (score, info, (c1, c2, c3), changed)
        except Exception:
            return

    _try_add(chi1_0, chi2_0, chi3_0)

    # Layer 1: cheap, directed one-card swaps from the current arrangement.
    for n1, n2, n3 in _iter_smart_swaps(
        base_hands,
        base_info,
        include_double=False,
        max_candidates=90,
    ):
        _try_add(n1, n2, n3)

    # Layer 2: open pair/two-card swaps only when useful.
    # Danger mode rescues a losing hand; attack mode tries to convert 2 wins to 3.
    should_expand = base_info.losses >= 2 or base_info.wins >= 2
    if should_expand:
        for n1, n2, n3 in _iter_smart_swaps(
            base_hands,
            base_info,
            include_double=True,
            max_candidates=180,
        ):
            _try_add(n1, n2, n3)

    # Layer 3: short two-step search from the best local seeds.
    ranked_seeds = sorted(best_pool.values(), key=lambda t: t[0], reverse=True)[:3]
    for _score, info, (s1, s2, s3), _changed in ranked_seeds:
        for n1, n2, n3 in _iter_smart_swaps(
            (s1, s2, s3),
            info,
            include_double=False,
            max_candidates=45,
        ):
            _try_add(n1, n2, n3)

    ranked = sorted(best_pool.values(), key=lambda t: t[0], reverse=True)

    out: List[dict] = []
    used = set()
    base_key = tuple(chi1_0 + chi2_0 + chi3_0)

    for score, info, (c1, c2, c3), changed in ranked:
        key = tuple(c1 + c2 + c3)
        if key in used:
            continue
        used.add(key)

        # Do not show the unchanged base when another permutation is available.
        if key == base_key and len(ranked) > 1:
            continue

        # "Toi uu" must be objectively better than the current base.
        # Equal or worse permutations add noise and should not be shown.
        if score <= base_score:
            continue

        out.append(
            {
                "mode": "optimize_vs_ngu",
                # StrategyTab/render layer overwrites label with "[Tối ưu] Gợi ý i".
                "label": f"[{label_prefix}]",
                "chi1_codes": list(c1),
                "chi2_codes": list(c2),
                "chi3_codes": list(c3),
                "_anti_obj": int(score[5]),
                "_anti_score": tuple(int(x) for x in score),
                "_anti_total": int(info.total_money),
                "_anti_cmp": (int(info.base_cmp_c1), int(info.base_cmp_c2), int(info.base_cmp_c3)),
                "_anti_wins": int(info.wins),
                "_anti_losses": int(info.losses),
                "_anti_draws": int(info.draws),
                "_anti_changed_slots": int(changed),
            }
        )
        if len(out) >= max_out:
            break

    return out

