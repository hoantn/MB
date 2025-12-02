# kendz/engine/arranger.py
"""Xếp bài 13 lá thành 3 chi (engine cơ bản + nâng cao).

Phase 4 – Hoàn thiện:

- arrange_basic:
  + Chiến lược đơn giản: sắp xếp theo rank, chia chi3 (dưới) mạnh nhất.
- arrange_advanced:
  + Dò bài đặc biệt 13 lá (sảnh rồng, 6 đôi, 5 đôi 1 sám, cùng màu, 4 sám cô,
    3 sảnh, 3 thùng...).
  + Nếu là bài đặc biệt -> vẫn xếp chi bằng heuristic, gắn cờ `special_type`.
  + Nếu không phải bài đặc biệt -> dùng brute-force heuristic:
    * Duyệt toàn bộ cách chia 13 lá thành (3,5,5).
    * Loại bỏ mọi thế bài Binh lủng (chi3 < chi2).
    * Chọn thế bài có bộ (chi3, chi2, chi1) mạnh nhất (lexicographic).

Mục tiêu:
- Tạo rule Mậu Binh tương đối đầy đủ, ổn định để dùng lâu dài.
- Code rõ ràng, có thể chỉnh heuristic dễ dàng.
"""

from __future__ import annotations

import itertools
from typing import Iterable, List, Optional, Tuple

from .cards import Card
from .evaluator import (
    compare_chi3,
    compare_poker5,
    evaluate_chi3,
    evaluate_poker5,
)
from .hand_types import ArrangedHand, Chi3, Chi5, PokerHandType
from .special_rules import detect_special_13


def arrange_basic(cards: List[Card]) -> ArrangedHand:
    """Chiến lược cơ bản: chia theo rank giảm dần.

    Cách làm:
    - Sort 13 lá giảm dần theo rank_value.
    - Lấy:
      + chi3 (dưới): 5 lá mạnh nhất.
      + chi2 (giữa): 5 lá tiếp theo.
      + chi1 (trên): 3 lá còn lại.
    """
    if len(cards) != 13:
        raise ValueError(f"arrange_basic cần đúng 13 lá, hiện có {len(cards)}")

    sorted_cards = sorted(cards, key=lambda c: c.rank_value, reverse=True)
    chi3_cards = sorted_cards[:5]
    chi2_cards = sorted_cards[5:10]
    chi1_cards = sorted_cards[10:]

    chi3_type, chi3_key = evaluate_poker5(chi3_cards)
    chi2_type, chi2_key = evaluate_poker5(chi2_cards)
    chi1_key = evaluate_chi3(chi1_cards)

    chi1 = Chi3(cards=chi1_cards, strength_key=chi1_key)
    chi2 = Chi5(cards=chi2_cards, hand_type=chi2_type, strength_key=chi2_key)
    chi3 = Chi5(cards=chi3_cards, hand_type=chi3_type, strength_key=chi3_key)

    is_lung = compare_poker5((chi3_type, chi3_key), (chi2_type, chi2_key)) < 0

    notes = "arrange_basic: chia theo rank giảm dần; chiến lược đơn giản."

    special_type, _ = detect_special_13(cards)

    return ArrangedHand(
        chi1=chi1,
        chi2=chi2,
        chi3=chi3,
        is_lung=is_lung,
        notes=notes,
        special_type=special_type,
    )


def _score_arrangement(
    chi1: Chi3,
    chi2: Chi5,
    chi3: Chi5,
) -> tuple:
    """Tính điểm cho một thế bài.

    Dùng tuple để so sánh lexicographic:
    - Ưu tiên chi3 > chi2 > chi1.

    Ta encode:
    (
      chi3_hand_type, chi3_strength_key...,
      chi2_hand_type, chi2_strength_key...,
      chi1_strength_key...
    )
    """
    key3 = (int(chi3.hand_type),) + tuple(chi3.strength_key)
    key2 = (int(chi2.hand_type),) + tuple(chi2.strength_key)
    key1 = tuple(chi1.strength_key)
    return key3 + key2 + key1


def arrange_advanced(cards: List[Card]) -> ArrangedHand:
    """Chiến lược nâng cao cho 13 lá.

    - Dò bài đặc biệt bằng detect_special_13.
    - Dùng brute-force duyệt mọi cách chia (3,5,5) hợp lệ (không lủng).
    - Chọn thế bài có score cao nhất.
    """
    if len(cards) != 13:
        raise ValueError(f"arrange_advanced cần đúng 13 lá, hiện có {len(cards)}")

    special_type, _ = detect_special_13(cards)

    # Tạo index 0..12 để duyệt tổ hợp
    indices = list(range(13))
    best_arr: Optional[ArrangedHand] = None
    best_score: Optional[tuple] = None

    # Duyệt mọi cách chọn chi1 (3 lá)
    for chi1_idx in itertools.combinations(indices, 3):
        remaining_for_10 = [i for i in indices if i not in chi1_idx]

        # Duyệt mọi cách chọn chi2 (5 lá) từ 10 lá còn lại
        for chi2_idx in itertools.combinations(remaining_for_10, 5):
            chi3_idx = [i for i in remaining_for_10 if i not in chi2_idx]

            chi1_cards = [cards[i] for i in chi1_idx]
            chi2_cards = [cards[i] for i in chi2_idx]
            chi3_cards = [cards[i] for i in chi3_idx]

            chi3_type, chi3_key = evaluate_poker5(chi3_cards)
            chi2_type, chi2_key = evaluate_poker5(chi2_cards)
            chi1_key = evaluate_chi3(chi1_cards)

            # Binh lủng: chi3 yếu hơn chi2 -> bỏ
            if compare_poker5((chi3_type, chi3_key), (chi2_type, chi2_key)) < 0:
                continue

            chi1_obj = Chi3(cards=chi1_cards, strength_key=chi1_key)
            chi2_obj = Chi5(cards=chi2_cards, hand_type=chi2_type, strength_key=chi2_key)
            chi3_obj = Chi5(cards=chi3_cards, hand_type=chi3_type, strength_key=chi3_key)

            score = _score_arrangement(chi1_obj, chi2_obj, chi3_obj)

            if best_score is None or score > best_score:
                best_score = score
                best_arr = ArrangedHand(
                    chi1=chi1_obj,
                    chi2=chi2_obj,
                    chi3=chi3_obj,
                    is_lung=False,
                    notes="arrange_advanced: brute-force (3,5,5) không lủng, ưu tiên chi3>chi2>chi1.",
                    special_type=special_type,
                )

    # Nếu vì lý do nào đó không tìm được arrangement hợp lệ -> fallback basic
    if best_arr is None:
        return arrange_basic(cards)

    return best_arr
