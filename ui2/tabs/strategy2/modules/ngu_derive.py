from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# FULL_DECK is currently imported from dashboard_constants in StrategyTab.
# To keep behavior identical, we will pass FULL_DECK in from StrategyTab.


@dataclass(frozen=True)
class NGUDeriveResult:
    codes13: List[str]
    key: str  # md5 of the 13 codes (joined by |)


class NGUDeriver:
    """
    Derive NGU 13 cards from 3 profiles (P1,P2,P3), exactly like existing StrategyTab logic.

    - Requires all 3 profiles to have 13 usable cards.
    - Ensures 39 unique across 3P.
    - NGU = FULL_DECK - union(3P).
    - Stable sort by FULL_DECK order (same as current).
    """

    def __init__(self, profiles: Sequence[str]):
        self.profiles = list(profiles)

    @staticmethod
    def _md5_key(codes13: List[str]) -> str:
        return hashlib.md5("|".join(codes13).encode()).hexdigest()

    def derive(
        self,
        codes_slot_order: Dict[str, List[str]],
        full_deck: Sequence[str],
    ) -> Optional[NGUDeriveResult]:
        all_codes: List[str] = []

        for pid in self.profiles:
            codes = codes_slot_order.get(pid) or []
            usable = [c for c in codes if c and c not in ("--", "??")]
            if len(usable) != 13:
                return None
            all_codes.extend(usable)

        # Must be 39 unique
        if len(set(all_codes)) != 39:
            return None

        deck = set(full_deck)
        rem = list(deck - set(all_codes))
        if len(rem) != 13:
            return None

        # Sort by FULL_DECK order (preserve current behavior)
        idx = {c: i for i, c in enumerate(full_deck)}
        rem.sort(key=lambda c: idx.get(c, 9999))

        return NGUDeriveResult(codes13=rem, key=self._md5_key(rem))
