# engine/phom/card.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

# Quy ước (giống ws_card_mapping.py nhưng TÁCH RIÊNG để không phụ thuộc MB)
RANKS = ["A","2","3","4","5","6","7","8","9","T","J","Q","K"]
SUITS = ["B","T","R","C"]  # Bích, Tép, Rô, Cơ

@dataclass(frozen=True)
class Card:
    ws_code: int  # 0..51

    @property
    def rank_index(self) -> int:
        return int(self.ws_code) // 4

    @property
    def suit_index(self) -> int:
        return int(self.ws_code) % 4

    @property
    def rank(self) -> str:
        return RANKS[self.rank_index]

    @property
    def suit(self) -> str:
        return SUITS[self.suit_index]

    @property
    def code(self) -> str:
        # ví dụ: 'AB' = A Bích
        return f"{self.rank}{self.suit}"

    @property
    def sort_key(self) -> Tuple[int,int]:
        return (self.rank_index, self.suit_index)


def ws_code_to_card_code(ws_code: int) -> str:
    return Card(ws_code).code
