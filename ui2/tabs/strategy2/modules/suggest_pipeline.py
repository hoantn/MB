from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Callable

from engine.card import Card
from engine.arranger import arrange_cards, ArrangeStrategy


@dataclass(frozen=True)
class PipelineSnapshot:
    # key -> 13 codes (slot-order)
    snapshot: Dict[str, List[str]]
    # ordered keys that should be scheduled
    ordered_keys: List[str]


class SuggestPipeline:
    """
    Suggestion build pipeline extracted from StrategyTab.

    Responsibilities:
    - Build snapshot for {P1,P2,P3,(NGU)}.
    - Provide base suggestion for MAX/MONEY.
    - Filter extras from full suggestion list.
    - Hash helpers.
    """

    def __init__(self, profiles: List[str], full_deck: List[str]):
        self.profiles = list(profiles)
        self.full_deck = list(full_deck)

    @staticmethod
    def hand_hash(codes: List[str]) -> str:
        m = hashlib.md5()
        for c in codes:
            m.update(str(c).encode())
            m.update(b"|")
        return m.hexdigest()

    def build_snapshot(
        self,
        *,
        codes_slot_order: Dict[str, List[str]],
        ngu_codes13: Optional[List[str]],
    ) -> PipelineSnapshot:
        snapshot: Dict[str, List[str]] = {}

        for pid in self.profiles:
            codes = codes_slot_order.get(pid) or []
            if len(codes) == 13:
                snapshot[pid] = list(codes)

        if ngu_codes13 and len(ngu_codes13) == 13:
            snapshot["NGU"] = list(ngu_codes13)

        ordered_keys: List[str] = []
        if "NGU" in snapshot:
            ordered_keys.append("NGU")
        ordered_keys.extend([p for p in self.profiles if p in snapshot])

        return PipelineSnapshot(snapshot=snapshot, ordered_keys=ordered_keys)

    @staticmethod
    def build_base_suggestion(key: str, codes: List[str], kind: str) -> Optional[dict]:
        """
        kind: 'MAX' or 'MONEY'
        Returns suggestion dict identical to StrategyTab._build_base_suggestion.
        """
        try:
            cards = [Card.from_code(c) for c in codes]
            if kind == "MAX":
                c1, c2, c3 = arrange_cards(cards, strategy=ArrangeStrategy.MAX_STRENGTH)
                mode = "max"
                label = "[Max]"
            else:
                # DÙNG ENGINE MỚI: BEAUTY_TEMPLATE
                c1, c2, c3 = arrange_cards(cards, strategy=ArrangeStrategy.BEAUTY_TEMPLATE)
                # Để tránh đụng chỗ khác, tạm giữ nguyên mode/label là "money"
                # Anh có thể đổi label thành "[Đẹp]" nếu muốn.
                mode = "money"
                label = "[Tiền]"

            return {
                "pid": key,
                "mode": mode,
                "variant": 0,
                "label": label,
                "chi1_codes": [x.to_code() for x in c1],
                "chi2_codes": [x.to_code() for x in c2],
                "chi3_codes": [x.to_code() for x in c3],
            }
        except Exception:
            return None

    @staticmethod
    def filter_extras(full: List[dict]) -> List[dict]:
        """
        NO-FILTER: không còn lọc extra theo mode/variant nữa.
        Trả về toàn bộ danh sách full (copy).
        """
        if not full:
            return []
        return list(full)

