from __future__ import annotations

from collections import Counter
from typing import Iterable, Optional, Sequence

from core.constants import RANK_ORDER
from engine.card import Card
from engine.money_scoring import evaluate_3cards, evaluate_5cards


def _codes(values: Iterable[object]) -> list[str]:
    return [str(v).strip().upper() for v in list(values or []) if str(v).strip()]


def _cards(codes: Sequence[str]) -> list[Card]:
    out: list[Card] = []
    for code in _codes(codes):
        try:
            out.append(Card.from_code(code))
        except Exception:
            pass
    return out


def _multiset_similarity(a: Counter, b: Counter) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    inter = sum(min(a.get(k, 0), b.get(k, 0)) for k in keys)
    union = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
    return float(inter / union) if union else 1.0


def _rank_counts(cards: Sequence[Card]) -> Counter:
    return Counter(c.rank_index for c in cards)


def _suit_counts(cards: Sequence[Card]) -> Counter:
    return Counter(c.suit for c in cards)


def _shape_counts(cards: Sequence[Card]) -> dict[str, int]:
    counts = list(_rank_counts(cards).values())
    return {
        "pairs": sum(1 for v in counts if v == 2),
        "trips": sum(1 for v in counts if v == 3),
        "quads": sum(1 for v in counts if v == 4),
        "pair_units": sum(v // 2 for v in counts),
        "max_suit": max(_suit_counts(cards).values() or [0]),
    }


def _shape_similarity(a: dict[str, int], b: dict[str, int]) -> float:
    keys = ("pairs", "trips", "quads", "pair_units", "max_suit")
    score = 0.0
    for key in keys:
        av = int(a.get(key, 0) or 0)
        bv = int(b.get(key, 0) or 0)
        maxv = max(av, bv, 1)
        score += 1.0 - min(1.0, abs(av - bv) / maxv)
    return score / len(keys)


def _eval_chi(codes: Sequence[str], chi_idx: int) -> tuple[int, list[int]]:
    cards = _cards(codes)
    try:
        if chi_idx == 3 and len(cards) == 3:
            t, d = evaluate_3cards(cards)
        elif len(cards) == 5:
            t, d = evaluate_5cards(cards)
        else:
            return -1, []
        return int(t), [int(x) for x in list(d or [])]
    except Exception:
        return -1, []


def _rank_detail_similarity(a: Sequence[int], b: Sequence[int]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    n = max(len(a), len(b))
    score = 0.0
    max_rank = max(1, len(RANK_ORDER) - 1)
    for i in range(n):
        av = int(a[i]) if i < len(a) else -1
        bv = int(b[i]) if i < len(b) else -1
        if av < 0 or bv < 0:
            score += 0.0
        else:
            score += 1.0 - min(1.0, abs(av - bv) / max_rank)
    return score / n


def suggestion_template(suggestion: Optional[dict]) -> str:
    if not suggestion:
        return ""
    t1, _ = _eval_chi(list(suggestion.get("chi1_codes") or []), 1)
    t2, _ = _eval_chi(list(suggestion.get("chi2_codes") or []), 2)
    t3, _ = _eval_chi(list(suggestion.get("chi3_codes") or []), 3)
    if min(t1, t2, t3) < 0:
        return ""
    return f"{t1}-{t2}-{t3}"


def extract_hand_features(codes: Sequence[str]) -> dict:
    cards = _cards(codes)
    ranks = _rank_counts(cards)
    suits = _suit_counts(cards)
    return {
        "codes": sorted(c.to_code().upper() for c in cards),
        "ranks": {str(k): int(v) for k, v in ranks.items()},
        "suits": {str(k): int(v) for k, v in suits.items()},
        "shape": _shape_counts(cards),
    }


def extract_suggestion_features(suggestion: Optional[dict]) -> dict:
    suggestion = suggestion or {}
    c1 = _codes(suggestion.get("chi1_codes") or [])
    c2 = _codes(suggestion.get("chi2_codes") or [])
    c3 = _codes(suggestion.get("chi3_codes") or [])
    t1, d1 = _eval_chi(c1, 1)
    t2, d2 = _eval_chi(c2, 2)
    t3, d3 = _eval_chi(c3, 3)
    return {
        "template": f"{t1}-{t2}-{t3}" if min(t1, t2, t3) >= 0 else "",
        "chi": {
            "1": {"type": t1, "detail": d1, "codes": c1},
            "2": {"type": t2, "detail": d2, "codes": c2},
            "3": {"type": t3, "detail": d3, "codes": c3},
        },
        "codes": sorted(c1 + c2 + c3),
    }


def hand_similarity(saved_features: dict, current_features: dict) -> float:
    saved_codes = set(_codes(saved_features.get("codes") or []))
    current_codes = set(_codes(current_features.get("codes") or []))
    card_sim = (len(saved_codes & current_codes) / len(saved_codes | current_codes)) if (saved_codes or current_codes) else 1.0

    saved_ranks = Counter({int(k): int(v) for k, v in dict(saved_features.get("ranks") or {}).items()})
    current_ranks = Counter({int(k): int(v) for k, v in dict(current_features.get("ranks") or {}).items()})
    rank_sim = _multiset_similarity(saved_ranks, current_ranks)

    saved_suits = Counter(dict(saved_features.get("suits") or {}))
    current_suits = Counter(dict(current_features.get("suits") or {}))
    suit_sim = _multiset_similarity(saved_suits, current_suits)

    shape_sim = _shape_similarity(dict(saved_features.get("shape") or {}), dict(current_features.get("shape") or {}))
    return (card_sim * 0.20) + (rank_sim * 0.35) + (shape_sim * 0.35) + (suit_sim * 0.10)


def suggestion_similarity(saved_features: dict, current_features: dict) -> float:
    if not saved_features or not current_features:
        return 0.0
    saved_template = str(saved_features.get("template") or "")
    current_template = str(current_features.get("template") or "")
    template_sim = 1.0 if saved_template and saved_template == current_template else 0.0

    chi_weights = {"1": 0.40, "2": 0.34, "3": 0.26}
    chi_score = 0.0
    saved_chi = dict(saved_features.get("chi") or {})
    current_chi = dict(current_features.get("chi") or {})
    for key, weight in chi_weights.items():
        a = dict(saved_chi.get(key) or {})
        b = dict(current_chi.get(key) or {})
        type_a = int(a.get("type", -1) or -1)
        type_b = int(b.get("type", -1) or -1)
        type_score = 1.0 if type_a == type_b and type_a >= 0 else max(0.0, 1.0 - abs(type_a - type_b) / 8.0)
        detail_score = _rank_detail_similarity(list(a.get("detail") or []), list(b.get("detail") or []))
        chi_score += weight * ((type_score * 0.68) + (detail_score * 0.32))

    return (template_sim * 0.35) + (chi_score * 0.65)


def combined_similarity(saved_hand: dict, current_hand: dict, saved_choice: dict, current_choice: dict) -> float:
    return (hand_similarity(saved_hand, current_hand) * 0.40) + (
        suggestion_similarity(saved_choice, current_choice) * 0.60
    )
