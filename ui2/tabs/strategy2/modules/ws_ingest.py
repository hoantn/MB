from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Callable, Tuple

from core.logger import log
from engine.ws_card_mapping import cards_to_tool_slot_order

@dataclass(frozen=True)
class WSUpdate:
    pid: str
    raw_cards: List[str]       # as received from ws_card_store
    codes_slot_order: List[str]  # slot 1..13 theo mapper WS chung
    hand_hash: str
    is_new_hand: bool
    hand_context: Any = None


class WSIngest:
    """
    Pure WS ingest + dedup + new-hand detection.

    Key behavior:
    - If snapshot is unchanged: skip.
    - If snapshot changed AND hand_hash changed: emit update (is_new_hand=True).
    - If snapshot changed BUT hand_hash same: emit update (is_new_hand=False) so UI can correct order
      without triggering heavy recompute.
    """

    def __init__(self, profiles: Sequence[str], reverse_like_dashboard: bool = True):
        self.profiles = list(profiles)
        self.reverse_like_dashboard = bool(reverse_like_dashboard)

    def poll(
        self,
        *,
        ws_get_last_cards: Callable[[str], Optional[List[str]]],
        ws_snapshot: Dict[str, Optional[List[str]]],
        last_hand_hash: Dict[str, Optional[str]],
        hand_hash_fn: Callable[[List[str]], str],
        ws_get_last_hand_context: Optional[Callable[[str], Any]] = None,
    ) -> Tuple[List[WSUpdate], List[str]]:
        """
        Returns:
          - updates: list[WSUpdate] for profiles that changed
          - waiting: list[pid] that currently has no 13 cards (for UI status "Chờ bài…")
        """
        updates: List[WSUpdate] = []
        waiting: List[str] = []

        for pid in self.profiles:
            cards = ws_get_last_cards(pid)
            if not cards or len(cards) != 13:
                waiting.append(pid)
                continue

            prev = ws_snapshot.get(pid)
            if prev is not None and list(prev) == list(cards):
                # snapshot unchanged -> skip
                continue

            # snapshot changed
            raw = list(cards)
            codes = cards_to_tool_slot_order(raw) if self.reverse_like_dashboard else list(raw)

            h = hand_hash_fn(codes)
            prev_h = last_hand_hash.get(pid)
            hand_context = None
            if callable(ws_get_last_hand_context):
                try:
                    hand_context = ws_get_last_hand_context(pid)
                except Exception:
                    hand_context = None

            log.debug(
                "[WSIngest] pid=%s cards=%d prev_hash=%s new_hash=%s is_new_hand=%s first3=%s",
                pid,
                len(raw),
                (prev_h[:6] if prev_h else None),
                h[:6],
                (prev_h != h),
                codes[:3],
            )
            if prev_h == h:
                # SAME HAND (by hash) but snapshot/order changed -> still emit update so UI can correct.
                updates.append(
                    WSUpdate(
                        pid=pid,
                        raw_cards=raw,
                        codes_slot_order=codes,
                        hand_hash=h,
                        is_new_hand=False,
                        hand_context=hand_context,
                    )
                )
                continue

            updates.append(
                WSUpdate(
                    pid=pid,
                    raw_cards=raw,
                    codes_slot_order=codes,
                    hand_hash=h,
                    is_new_hand=True,
                    hand_context=hand_context,
                )
            )

        return updates, waiting
