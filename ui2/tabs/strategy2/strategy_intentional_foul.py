from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Dict, List, Optional

from engine.card import Card
from ui2.tabs.strategy2.strategy_anti_sap import _is_foul


def _is_553(suggestion: Optional[dict]) -> bool:
    if not suggestion:
        return False
    return (
        len(list(suggestion.get("chi1_codes") or [])) == 5
        and len(list(suggestion.get("chi2_codes") or [])) == 5
        and len(list(suggestion.get("chi3_codes") or [])) == 3
    )


def is_intentional_foul_suggestion(suggestion: Optional[dict], ws_codes: List[str]) -> bool:
    """Validate card integrity and confirm that a generated 5-5-3 split is foul."""
    if not _is_553(suggestion):
        return False

    chi1 = list((suggestion or {}).get("chi1_codes") or [])
    chi2 = list((suggestion or {}).get("chi2_codes") or [])
    chi3 = list((suggestion or {}).get("chi3_codes") or [])
    if Counter(map(str, chi1 + chi2 + chi3)) != Counter(map(str, ws_codes or [])):
        return False

    try:
        return _is_foul(
            [Card.from_code(code) for code in chi1],
            [Card.from_code(code) for code in chi2],
            [Card.from_code(code) for code in chi3],
        )
    except Exception:
        return False


def build_intentional_foul_suggestion(
    money_suggestion: Optional[dict],
    ws_codes: List[str],
) -> Optional[Dict[str, object]]:
    """
    Lazily build a foul split from the existing Money split.

    The common path only tries cheap one-card swaps. A bounded 10-card
    bottom/middle repartition is the fallback, so this never starts a 72k scan.
    """
    if not _is_553(money_suggestion):
        return None

    chi1 = list((money_suggestion or {}).get("chi1_codes") or [])
    chi2 = list((money_suggestion or {}).get("chi2_codes") or [])
    chi3 = list((money_suggestion or {}).get("chi3_codes") or [])
    if Counter(map(str, chi1 + chi2 + chi3)) != Counter(map(str, ws_codes or [])):
        return None

    def _candidate(c1: List[str], c2: List[str], c3: List[str]) -> Optional[Dict[str, object]]:
        suggestion: Dict[str, object] = {
            "mode": "intentional_foul",
            "label": "[BINH LỦNG]",
            "chi1_codes": list(c1),
            "chi2_codes": list(c2),
            "chi3_codes": list(c3),
            "_auto_intentional_foul": True,
        }
        return suggestion if is_intentional_foul_suggestion(suggestion, ws_codes) else None

    # Prefer the smallest possible mutation: one swap between two rows.
    for left, right, fixed, kind in (
        (chi1, chi2, chi3, "12"),
        (chi2, chi3, chi1, "23"),
        (chi1, chi3, chi2, "13"),
    ):
        for i in range(len(left)):
            for j in range(len(right)):
                a, b = list(left), list(right)
                a[i], b[j] = b[j], a[i]
                if kind == "12":
                    found = _candidate(a, b, fixed)
                elif kind == "23":
                    found = _candidate(fixed, a, b)
                else:
                    found = _candidate(a, fixed, b)
                if found is not None:
                    return found

    # Strong deterministic fallback: swap the complete bottom and middle rows.
    found = _candidate(chi2, chi1, chi3)
    if found is not None:
        return found

    # Rare tie-shaped hands: repartition only the existing 10 bottom/middle cards.
    # This is bounded at C(10, 5)=252 candidates and remains cheap.
    bottom_middle = chi1 + chi2
    for bottom_indices in combinations(range(10), 5):
        bottom_set = set(bottom_indices)
        c1 = [bottom_middle[i] for i in bottom_indices]
        c2 = [bottom_middle[i] for i in range(10) if i not in bottom_set]
        found = _candidate(c1, c2, chi3)
        if found is not None:
            return found

    return None
