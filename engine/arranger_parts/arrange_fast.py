from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from engine.card import Card
from engine.arranger_parts.arrange import (
    ArrangeStrategy,
    arrange_13_cards as _arrange_13_cards_stable,
    arrange_cached_money_split as _arrange_cached_money_split_stable,
)


def arrange_13_cards_fast(
    cards: List[Card],
    *,
    strategy: ArrangeStrategy = ArrangeStrategy.STYLE_BRUTEFORCE_ALL,
    max_candidates: Optional[int] = None,
) -> List[Tuple[List[Card], List[Card], List[Card]]]:
    """Phase-0 fast engine adapter.

    It intentionally delegates to the stable arranger until the A/B harness
    proves the whole Strategy2 pipeline can swap engines without changing
    output. Real micro-optimizations will land here, behind the same API.
    """
    return _arrange_13_cards_stable(
        cards,
        strategy=strategy,
        max_candidates=max_candidates,
    )


def arrange_cached_money_split_fast(
    cards: List[Card],
    *,
    strategy: ArrangeStrategy = ArrangeStrategy.STYLE_BRUTEFORCE_ALL,
) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    return _arrange_cached_money_split_stable(cards, strategy=strategy)


def arrange_fast_cache_clear() -> None:
    """Reserved for the future independent fast cache."""
    return None


def arrange_fast_cache_stats() -> Dict[str, int]:
    return {"size": 0, "money_size": 0, "max": 0, "hits": 0, "misses": 0}
