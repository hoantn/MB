from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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


def _eval_vs_opp(my: ThreeChi, opp: ThreeChi) -> _EvalInfo:
    total = score_money_vs_opp(my, opp)
    c1 = _base_cmp_no_bonus(my.chi1, opp.chi1, 1)
    c2 = _base_cmp_no_bonus(my.chi2, opp.chi2, 2)
    c3 = _base_cmp_no_bonus(my.chi3, opp.chi3, 3)
    return _EvalInfo(total_money=total, base_cmp_c1=c1, base_cmp_c2=c2, base_cmp_c3=c3)


def _anti_collapse_objective(info: _EvalInfo) -> int:
    penalty = 0
    if info.lose_all:
        penalty += 2000
    if info.base_cmp_c1 < 0:
        penalty += 350
    if info.base_cmp_c2 < 0:
        penalty += 140
    if info.base_cmp_c3 < 0:
        penalty += 60
    return info.total_money - penalty


def _swap_one(a: List[str], i: int, b: List[str], j: int) -> None:
    a[i], b[j] = b[j], a[i]


def _candidate_swaps(
    chi1: List[str], chi2: List[str], chi3: List[str],
    *,
    max_candidates: int = 80
) -> List[Tuple[List[str], List[str], List[str]]]:
    out: List[Tuple[List[str], List[str], List[str]]] = []

    for i in range(5):
        for j in range(5):
            c1 = list(chi1); c2 = list(chi2); c3 = list(chi3)
            _swap_one(c1, i, c2, j)
            out.append((c1, c2, c3))
            if len(out) >= max_candidates:
                return out

    for i in range(5):
        for j in range(3):
            c1 = list(chi1); c2 = list(chi2); c3 = list(chi3)
            _swap_one(c2, i, c3, j)
            out.append((c1, c2, c3))
            if len(out) >= max_candidates:
                return out

    for i in range(5):
        for j in range(3):
            c1 = list(chi1); c2 = list(chi2); c3 = list(chi3)
            _swap_one(c1, i, c3, j)
            out.append((c1, c2, c3))
            if len(out) >= max_candidates:
                return out

    return out


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
    label_prefix: str = "Chống sập",
    max_out: int = 3,
) -> List[dict]:
    my_three0 = _codes_to_threechi(my_base)
    opp_three = _codes_to_threechi(opp_base)
    if my_three0 is None or opp_three is None:
        return []

    chi1_0 = list(my_base.get("chi1_codes") or [])
    chi2_0 = list(my_base.get("chi2_codes") or [])
    chi3_0 = list(my_base.get("chi3_codes") or [])

    base_info = _eval_vs_opp(my_three0, opp_three)
    base_obj = _anti_collapse_objective(base_info)

    best_pool: Dict[Tuple[str, ...], Tuple[int, _EvalInfo, Tuple[List[str], List[str], List[str]]]] = {}

    def _try_add(c1: List[str], c2: List[str], c3: List[str]) -> None:
        key = tuple(c1 + c2 + c3)
        if key in best_pool:
            return
        try:
            tc1 = [Card.from_code(x) for x in c1]
            tc2 = [Card.from_code(x) for x in c2]
            tc3 = [Card.from_code(x) for x in c3]
            if _is_foul(tc1, tc2, tc3):
                return
            my_three = ThreeChi(tc1, tc2, tc3)
            info = _eval_vs_opp(my_three, opp_three)
            obj = _anti_collapse_objective(info)
            best_pool[key] = (obj, info, (c1, c2, c3))
        except Exception:
            return

    _try_add(chi1_0, chi2_0, chi3_0)
    cur_best = (base_obj, base_info, (chi1_0, chi2_0, chi3_0))

    for _ in range(2):
        c1, c2, c3 = cur_best[2]
        for n1, n2, n3 in _candidate_swaps(c1, c2, c3, max_candidates=80):
            _try_add(n1, n2, n3)
        cur_best = max(best_pool.values(), key=lambda t: t[0])

    ranked = sorted(best_pool.values(), key=lambda t: t[0], reverse=True)

    out: List[dict] = []
    used = set()

    for obj, info, (c1, c2, c3) in ranked:
        key = tuple(c1 + c2 + c3)
        if key in used:
            continue
        used.add(key)

        if (c1 == chi1_0 and c2 == chi2_0 and c3 == chi3_0) and len(out) > 0:
            continue

        out.append(
            {
                "mode": "anti_sap",
                # StrategyTab sẽ overwrite label thành "[Chống sập i]" để đồng bộ UI
                "label": f"[{label_prefix}]",
                "chi1_codes": list(c1),
                "chi2_codes": list(c2),
                "chi3_codes": list(c3),
                "_anti_obj": int(obj),
                "_anti_total": int(info.total_money),
                "_anti_cmp": (int(info.base_cmp_c1), int(info.base_cmp_c2), int(info.base_cmp_c3)),
            }
        )
        if len(out) >= max_out:
            break

    return out
