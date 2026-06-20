from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import List, Optional, Tuple

from core.constants import LOG_DIR
from core.logger import log
from engine.card import Card
from engine.arranger_parts.arrange import (
    ArrangeStrategy,
    arrange_13_cards as _arrange_13_cards_stable,
    arrange_cached_money_split as _arrange_cached_money_split_stable,
)
from engine.arranger_parts.arrange_fast import (
    arrange_13_cards_fast as _arrange_13_cards_fast,
    arrange_cached_money_split_fast as _arrange_cached_money_split_fast,
)


STABLE_MODE = "stable"
FAST_MODE = "fast"
COMPARE_MODE = "compare"
DEFAULT_ENGINE_MODE = STABLE_MODE


@dataclass(frozen=True)
class SuggestEngineOutput:
    splits: List[Tuple[List[Card], List[Card], List[Card]]]
    money_split: Optional[Tuple[List[Card], List[Card], List[Card]]]
    mode: str
    returned_mode: str
    compare_equal: Optional[bool] = None


def normalize_engine_mode(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("fast", "new", "optimized", "optimised"):
        return FAST_MODE
    if raw in ("compare", "ab", "a/b", "debug"):
        return COMPARE_MODE
    return STABLE_MODE


def configured_engine_mode_for_slot(slot: int = 1) -> str:
    try:
        from core.config import load_config

        cfg = load_config(int(slot or 1))
        ui = cfg.get("ui", {}) if isinstance(cfg, dict) else {}
        strategy2 = ui.get("strategy2", {}) if isinstance(ui, dict) else {}
        return normalize_engine_mode(strategy2.get("suggest_engine_mode"))
    except Exception:
        return DEFAULT_ENGINE_MODE


def build_suggest_engine_output(
    cards: List[Card],
    *,
    strategy: ArrangeStrategy = ArrangeStrategy.STYLE_BRUTEFORCE_ALL,
    max_candidates: Optional[int] = None,
    engine_mode: str = DEFAULT_ENGINE_MODE,
    profile_id: str = "",
    hand_hash: str = "",
) -> SuggestEngineOutput:
    mode = normalize_engine_mode(engine_mode)
    if mode == FAST_MODE:
        splits = _arrange_13_cards_fast(cards, strategy=strategy, max_candidates=max_candidates)
        money = _arrange_cached_money_split_fast(cards, strategy=strategy)
        return SuggestEngineOutput(splits=splits, money_split=money, mode=mode, returned_mode=FAST_MODE)

    if mode == COMPARE_MODE:
        stable_splits = _arrange_13_cards_stable(cards, strategy=strategy, max_candidates=max_candidates)
        stable_money = _arrange_cached_money_split_stable(cards, strategy=strategy)
        fast_splits = _arrange_13_cards_fast(cards, strategy=strategy, max_candidates=max_candidates)
        fast_money = _arrange_cached_money_split_fast(cards, strategy=strategy)
        equal = _split_signature(stable_splits) == _split_signature(fast_splits)
        money_equal = _money_signature(stable_money) == _money_signature(fast_money)
        if not (equal and money_equal):
            _log_compare_mismatch(
                profile_id=profile_id,
                hand_hash=hand_hash,
                stable_splits=stable_splits,
                stable_money=stable_money,
                fast_splits=fast_splits,
                fast_money=fast_money,
            )
        return SuggestEngineOutput(
            splits=stable_splits,
            money_split=stable_money,
            mode=mode,
            returned_mode=STABLE_MODE,
            compare_equal=bool(equal and money_equal),
        )

    splits = _arrange_13_cards_stable(cards, strategy=strategy, max_candidates=max_candidates)
    money = _arrange_cached_money_split_stable(cards, strategy=strategy)
    return SuggestEngineOutput(splits=splits, money_split=money, mode=STABLE_MODE, returned_mode=STABLE_MODE)


def _codes(cards: List[Card]) -> Tuple[str, ...]:
    return tuple(c.to_code() for c in list(cards or []))


def _split_signature(
    splits: List[Tuple[List[Card], List[Card], List[Card]]]
) -> Tuple[Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]], ...]:
    return tuple((_codes(c1), _codes(c2), _codes(c3)) for c1, c2, c3 in list(splits or []))


def _money_signature(
    split: Optional[Tuple[List[Card], List[Card], List[Card]]]
) -> Optional[Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]]:
    if not split:
        return None
    c1, c2, c3 = split
    return (_codes(c1), _codes(c2), _codes(c3))


def _log_compare_mismatch(
    *,
    profile_id: str,
    hand_hash: str,
    stable_splits: List[Tuple[List[Card], List[Card], List[Card]]],
    stable_money: Optional[Tuple[List[Card], List[Card], List[Card]]],
    fast_splits: List[Tuple[List[Card], List[Card], List[Card]]],
    fast_money: Optional[Tuple[List[Card], List[Card], List[Card]]],
) -> None:
    payload = {
        "profile_id": str(profile_id or ""),
        "hand_hash": str(hand_hash or ""),
        "stable_count": len(stable_splits or []),
        "fast_count": len(fast_splits or []),
        "stable_money": _money_signature(stable_money),
        "fast_money": _money_signature(fast_money),
        "stable_first": _split_signature(list(stable_splits or [])[:5]),
        "fast_first": _split_signature(list(fast_splits or [])[:5]),
    }
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, "strategy_engine_compare.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass
    try:
        log.warning(
            "[Strategy2][engine-compare] mismatch profile=%s hand=%s stable=%s fast=%s",
            payload["profile_id"],
            payload["hand_hash"],
            payload["stable_count"],
            payload["fast_count"],
        )
    except Exception:
        pass
