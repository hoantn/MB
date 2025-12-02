# kendz/engine/cards.py
"""Định nghĩa lá bài (Card) và bộ bài 52 lá cho Mậu Binh Engine.

Quy ước:
- rank: 2 3 4 5 6 7 8 9 T J Q K A
- suit: S (♠), H (♥), D (♦), C (♣)
- Mã lá bài dạng chuỗi: "AS", "TD", "7C"...

Mục tiêu:
- Cung cấp lớp Card/Deck và các hàm parse/format để các module khác dùng.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

# Thứ tự rank dùng chung cho toàn bộ engine
RANK_ORDER = "23456789TJQKA"
RANK_TO_VALUE = {r: i + 2 for i, r in enumerate(RANK_ORDER)}
VALUE_TO_RANK = {v: r for r, v in RANK_TO_VALUE.items()}

# Thứ tự suit, chỉ dùng để sinh full_deck và tie-break phụ (nếu cần)
SUIT_ORDER = "SHDC"  # ♠ ♥ ♦ ♣


@dataclass(frozen=True)
class Card:
    """Lá bài cơ bản.

    - rank: ký tự trong RANK_ORDER ("2".."A")
    - suit: một trong "S","H","D","C"
    """

    rank: str
    suit: str

    @property
    def rank_value(self) -> int:
        """Giá trị số của rank (2..14)."""
        return RANK_TO_VALUE[self.rank]

    def to_code(self) -> str:
        """Mã dạng chuỗi, ví dụ "AS", "7D"."""
        return f"{self.rank}{self.suit}"

    @classmethod
    def from_code(cls, code: str) -> "Card":
        return parse_card(code)


def parse_card(code: str) -> Card:
    """Parse chuỗi mã lá bài thành Card.

    Ví dụ:
    - "AS" -> A♠
    - "7d" -> 7♦ (không phân biệt hoa/thường).
    """
    code = code.strip().upper()
    if len(code) != 2:
        raise ValueError(f"Mã lá bài không hợp lệ: {code!r}")
    rank, suit = code[0], code[1]
    if rank not in RANK_TO_VALUE:
        raise ValueError(f"Rank không hợp lệ: {rank} trong {code!r}")
    if suit not in {"S", "H", "D", "C"}:
        raise ValueError(f"Suit không hợp lệ: {suit} trong {code!r}")
    return Card(rank=rank, suit=suit)


def parse_cards_list(text: str) -> List[Card]:
    """Parse chuỗi dạng "AS,KH,7D,..." thành danh sách Card."""
    parts = [p for p in text.replace(";", ",").split(",") if p.strip()]
    return [parse_card(p) for p in parts]


def format_cards(cards: List[Card]) -> str:
    """Format danh sách Card thành chuỗi "AS,KH,7D,..."."""
    return ",".join(card.to_code() for card in cards)


def full_deck() -> List[Card]:
    """Sinh bộ bài 52 lá chuẩn."""
    return [Card(rank=r, suit=s) for r in RANK_ORDER for s in SUIT_ORDER]
