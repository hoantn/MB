# engine/ws_card_mapping.py
from __future__ import annotations

from typing import Dict, List

# Quy ước trong TOOL:
# - Rank: A,2,3,4,5,6,7,8,9,T,J,Q,K  (T = 10)
# - Suit: B = Bích, T = Tép, R = Rô, C = Cơ
#
# Quy ước trong GAME (WebSocket 0..51):
# - code // 4  -> rank_index (0..12)  : A..K
# - code % 4   -> suit_index (0..3)   : Bích, Tép, Rô, Cơ


RANKS: List[str] = [
    "A",  # 0
    "2",  # 1
    "3",  # 2
    "4",  # 3
    "5",  # 4
    "6",  # 5
    "7",  # 6
    "8",  # 7
    "9",  # 8
    "T",  # 9  (10)
    "J",  # 10
    "Q",  # 11
    "K",  # 12
]

# 0..3 → Bích / Tép / Rô / Cơ
SUIT_INDEX_TO_CODE: Dict[int, str] = {
    0: "B",  # Bích
    1: "T",  # Tép (Chuồn)
    2: "R",  # Rô
    3: "C",  # Cơ
}

# Map cứng 52 quân: code (0..51) → "rank+suit" (ví dụ "2B", "TT", "AC", ...)
WS_CODE_TO_CARD: Dict[int, str] = {}


def _build_mapping() -> None:
    """
    Khởi tạo WS_CODE_TO_CARD theo quy luật game:
    - code // 4  -> rank_index
    - code % 4   -> suit_index
    """
    for code in range(52):
        rank_index = code // 4
        suit_index = code % 4

        rank = RANKS[rank_index]
        suit_code = SUIT_INDEX_TO_CODE[suit_index]

        card_code = f"{rank}{suit_code}"
        WS_CODE_TO_CARD[code] = card_code


# Build mapping khi import module
_build_mapping()

# Map ngược: "2B" -> 4, "AC" -> 3, ... (nếu cần)
CARD_TO_WS_CODE: Dict[str, int] = {v: k for k, v in WS_CODE_TO_CARD.items()}


def ws_code_to_card(code: int) -> str:
    """
    Chuyển 1 mã WS (0..51) sang mã lá bài của TOOL (2B, TT, AC,...).
    Nếu code không hợp lệ, raise ValueError.
    """
    try:
        return WS_CODE_TO_CARD[code]
    except KeyError as exc:
        raise ValueError(f"Invalid WS card code: {code}") from exc


def ws_codes_to_cards(codes: List[int]) -> List[str]:
    """
    Chuyển list mã WS (0..51) sang list mã lá bài TOOL.
    """
    return [ws_code_to_card(c) for c in codes]


def cards_to_tool_slot_order(cards: List[str]) -> List[str]:
    """
    Chuan hoa 13 la WS ve thu tu slot 1..13 cua tool.

    HAR thuc te cho thay cmd=600 va cmd=606 dung chung raw order. Vi vay tat ca
    nguon WS phai di qua cung mot rule; neu cmd600/cmd606 map khac nhau thi
    repair se keo sai la lap lai.
    """
    values = list(cards or [])
    if len(values) != 13:
        return values
    return list(reversed(values))


def ws_codes_to_tool_slot_order(codes: List[int]) -> List[str]:
    """Convert WS raw card codes 0..51 thanh slot order 1..13 cua tool."""
    return cards_to_tool_slot_order(ws_codes_to_cards(list(codes or [])))


__all__ = [
    "WS_CODE_TO_CARD",
    "CARD_TO_WS_CODE",
    "ws_code_to_card",
    "ws_codes_to_cards",
    "cards_to_tool_slot_order",
    "ws_codes_to_tool_slot_order",
]
