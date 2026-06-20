from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from engine.card import Card
from engine.arranger_parts.arrange import (
    ArrangeStrategy,
    _arrange_13_cards_impl,
    _arrange_cached_money_split_impl,
    arrange_cache_clear as _arrange_cache_clear,
    arrange_cache_stats as _arrange_cache_stats,
)

_FAST_CACHE_VARIANT = "fast_combo_v1"


def arrange_13_cards_fast(
    cards: List[Card],
    *,
    strategy: ArrangeStrategy = ArrangeStrategy.STYLE_BRUTEFORCE_ALL,
    max_candidates: Optional[int] = None,
) -> List[Tuple[List[Card], List[Card], List[Card]]]:
    """Fast-v1 arranger.

    The hand-ranking, filtering, style, and money-choice logic stays shared
    with stable. This path only swaps in static 13-card combination tables and
    an isolated cache namespace, so A/B compare can validate it independently.
    """
    return _arrange_13_cards_impl(
        cards,
        strategy=strategy,
        max_candidates=max_candidates,
        _use_static_combos=True,
        _cache_variant=_FAST_CACHE_VARIANT,
    )


def arrange_cached_money_split_fast(
    cards: List[Card],
    *,
    strategy: ArrangeStrategy = ArrangeStrategy.STYLE_BRUTEFORCE_ALL,
) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    return _arrange_cached_money_split_impl(
        cards,
        strategy=strategy,
        _cache_variant=_FAST_CACHE_VARIANT,
    )


def arrange_fast_cache_clear() -> None:
    """Clear the shared arranger LRU storage used by the fast cache variant."""
    _arrange_cache_clear()


def arrange_fast_cache_stats() -> Dict[str, int]:
    return _arrange_cache_stats()
