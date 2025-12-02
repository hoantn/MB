# kendz/engine/special_rules.py
"""Rule nhận diện bài đặc biệt 13 lá (Mậu Binh).

Hỗ trợ các loại bài đặc biệt phổ biến:

1. SẢNH RỒNG:
   - 13 lá từ 2 -> A (mỗi rank xuất hiện đúng 1 lần).

2. 6 ĐÔI:
   - Có đúng 6 rank xuất hiện 2 lần và 1 rank xuất hiện 1 lần.

3. 5 ĐÔI 1 SÁM:
   - Có đúng 5 rank xuất hiện 2 lần và 1 rank xuất hiện 3 lần.

4. 4 SÁM CÔ:
   - Có đúng 4 rank xuất hiện 3 lần và 1 rank xuất hiện 1 lần.

5. 3 SẢNH:
   - Có thể chia 13 lá thành 3 sảnh (mỗi sảnh >= 3 lá).
   - Ở đây dùng heuristic đơn giản: kiểm tra tổng thể khả năng xếp được
     3 sảnh theo rank, không xét hết mọi tổ hợp hiếm gặp.

6. 3 THÙNG:
   - Có thể chia 13 lá thành 3 thùng (mỗi thùng >= 3 lá).
   - Sử dụng heuristic trên phân bố suit: nếu phân bố suit đủ dày và
     có thể chia thành 3 nhóm mỗi nhóm >= 3 lá cùng suit thì coi là 3 thùng.

7. CÙNG MÀU ĐỎ / CÙNG MÀU ĐEN:
   - 13 lá cùng màu đỏ (♥,♦) hoặc cùng màu đen (♠,♣).

Hàm chính:
- detect_special_13(cards) -> (special_type, meta)
  + special_type: tên chuỗi (ví dụ "SẢNH RỒNG", "6 ĐÔI"...) hoặc None.
  + meta: dict phụ (có thể dùng khi mở rộng).
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Tuple

from .cards import Card, RANK_ORDER


def _is_sanh_rong(ranks: List[int]) -> bool:
    """Kiểm tra 13 lá có phải SẢNH RỒNG (2..A mỗi rank 1 lá)."""
    if len(ranks) != 13:
        return False
    unique = sorted(set(ranks))
    return unique == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] and all(
        ranks.count(v) == 1 for v in unique
    )


def _is_6_doi(rank_counts: Counter) -> bool:
    pairs = [r for r, c in rank_counts.items() if c == 2]
    singles = [r for r, c in rank_counts.items() if c == 1]
    return len(pairs) == 6 and len(singles) == 1


def _is_5_doi_1_sam(rank_counts: Counter) -> bool:
    pairs = [r for r, c in rank_counts.items() if c == 2]
    triples = [r for r, c in rank_counts.items() if c == 3]
    return len(pairs) == 5 and len(triples) == 1


def _is_4_sam_co(rank_counts: Counter) -> bool:
    triples = [r for r, c in rank_counts.items() if c == 3]
    singles = [r for r, c in rank_counts.items() if c == 1]
    # 4 x 3 + 1 = 13
    return len(triples) == 4 and len(singles) == 1


def _is_3_sanh(ranks: List[int]) -> bool:
    """Heuristic kiểm tra 3 SẢNH.

    Ý tưởng:
    - Dùng sorted unique ranks.
    - Thử tách thành các đoạn liên tiếp >= 3 lá.
    - Nếu tổng số lá trong 3 đoạn lớn nhất >= 13 -> coi là 3 sảnh.
    (chấp nhận có thể bỏ sót một số thế bài rất hiếm).
    """
    ranks_sorted = sorted(ranks)
    segments: List[List[int]] = []
    current = [ranks_sorted[0]]
    for v in ranks_sorted[1:]:
        if v == current[-1] or v == current[-1] + 1:
            # Cho phép trùng rank, ta vẫn nối vào segment hiện tại
            current.append(v)
        else:
            segments.append(current)
            current = [v]
    segments.append(current)

    # Lọc các segment có độ dài >= 3 (có thể tạo sảnh >= 3 lá)
    candidates = [seg for seg in segments if len(seg) >= 3]
    if len(candidates) < 3:
        return False
    # Lấy 3 segment dài nhất
    candidates.sort(key=len, reverse=True)
    total_len = sum(len(seg) for seg in candidates[:3])
    return total_len >= 13


def _is_3_thung(suits: List[str]) -> bool:
    """Heuristic kiểm tra 3 THÙNG.

    Ý tưởng đơn giản:
    - Đếm số lá mỗi suit.
    - Nếu:
      + Có >= 3 suit, mỗi suit >= 3 lá
         -> Rất dễ chia thành 3 thùng.
      + Hoặc có 2 suit nhiều (>= 5 lá) và tổng >= 13
         -> thường cũng có thể chia được 3 thùng.
    """
    from collections import Counter

    cnt = Counter(suits)
    suit_counts = sorted(cnt.values(), reverse=True)

    # 3 suit đều >= 3 lá
    if len([c for c in suit_counts if c >= 3]) >= 3:
        return True

    # 2 suit lớn, 1 suit nhỏ vẫn có thể tách 3 nhóm >=3
    if len(suit_counts) >= 2 and suit_counts[0] >= 5 and suit_counts[1] >= 5:
        # 5 + 5 = 10, còn 3 lá còn lại (có thể là suit bất kỳ) -> vẫn chia 3 thùng được
        return True

    return False


def _is_cung_mau(suits: List[str]) -> Optional[str]:
    """Kiểm tra 13 lá có cùng màu đỏ/đen không."""
    red_suits = {"H", "D"}
    black_suits = {"S", "C"}

    reds = sum(1 for s in suits if s in red_suits)
    blacks = sum(1 for s in suits if s in black_suits)

    if reds == 13:
        return "CÙNG MÀU ĐỎ"
    if blacks == 13:
        return "CÙNG MÀU ĐEN"
    return None


def detect_special_13(cards: List[Card]) -> tuple[Optional[str], Dict]:
    """Nhận diện bài đặc biệt 13 lá, nếu có.

    Trả về:
    - (special_type, meta)
    - special_type = None nếu không phải bài đặc biệt.
    """
    if len(cards) != 13:
        return None, {}

    ranks = [c.rank_value for c in cards]
    suits = [c.suit for c in cards]
    rank_counts = Counter(ranks)

    # 1) Sảnh rồng
    if _is_sanh_rong(ranks):
        return "SẢNH RỒNG", {}

    # 2) 6 đôi
    if _is_6_doi(rank_counts):
        return "6 ĐÔI", {}

    # 3) 5 đôi 1 sám
    if _is_5_doi_1_sam(rank_counts):
        return "5 ĐÔI 1 SÁM", {}

    # 4) 4 sám cô
    if _is_4_sam_co(rank_counts):
        return "4 SÁM CÔ", {}

    # 5) 3 sảnh
    if _is_3_sanh(ranks):
        return "3 SẢNH", {}

    # 6) 3 thùng
    if _is_3_thung(suits):
        return "3 THÙNG", {}

    # 7) Cùng màu đỏ / cùng màu đen
    cung_mau = _is_cung_mau(suits)
    if cung_mau:
        return cung_mau, {}

    # Không phải bài đặc biệt
    return None, {}
