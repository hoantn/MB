# kendz/engine/hand_types.py
"""Các cấu trúc dữ liệu biểu diễn chi/bộ bài trong Mậu Binh.

Tách riêng:
- PokerHandType: loại 5 lá theo luật poker (thùng, sảnh, tứ quý...).
- Chi3, Chi5: một chi trong thế bài Mậu Binh.
- ArrangedHand: kết quả xếp 13 lá thành 3 chi.

Lưu ý:
- Đánh giá sức mạnh chi5 dựa trên evaluate_poker5 trong evaluator.
- Chi3 dùng evaluate_chi3.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional

from .cards import Card, format_cards


class PokerHandType(IntEnum):
    """Các loại bài 5 lá chuẩn poker.

    Sử dụng IntEnum để dễ so sánh:
    - HIGH_CARD  < ONE_PAIR < TWO_PAIR < ...
    """

    HIGH_CARD = 0
    ONE_PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8


@dataclass
class Chi3:
    """Chi 3 lá (chi trên cùng)."""

    cards: List[Card]
    strength_key: tuple[int, ...]


@dataclass
class Chi5:
    """Chi 5 lá (chi giữa, chi dưới)."""

    cards: List[Card]
    hand_type: PokerHandType
    strength_key: tuple[int, ...]


@dataclass
class ArrangedHand:
    """Thế bài 13 lá sau khi xếp thành 3 chi."""

    chi1: Chi3
    chi2: Chi5
    chi3: Chi5
    is_lung: bool = False  # Binh lủng?
    notes: str = ""
    special_type: Optional[str] = None  # tên bài đặc biệt, nếu có

    def to_str(self) -> str:
        """Chuỗi mô tả ngắn gọn thế bài (phục vụ log)."""
        extra = f" | Special={self.special_type}" if self.special_type else ""
        return (
            f"Chi1 (3 lá): {format_cards(self.chi1.cards)} | "
            f"Chi2 (5 lá): {format_cards(self.chi2.cards)} | "
            f"Chi3 (5 lá): {format_cards(self.chi3.cards)} | "
            f"Lủng={self.is_lung}{extra} | Ghi chú={self.notes}"
        )
