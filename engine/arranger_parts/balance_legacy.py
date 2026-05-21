from __future__ import annotations

from typing import Tuple, List

from engine.card import Card

def _major_rank_5(eval5: Tuple[int, ...]) -> int:
    """
    Lấy 'major rank' đại diện sức mạnh (để dàn đều) cho 5 lá:
    - High/Flush: high card đầu
    - Pair: rank đôi
    - Two-pair: đôi lớn
    - Trips: rank sám
    - Straight/StraightFlush: high straight
    - Full house: rank trips
    - Four: rank tứ
    """
    t = eval5[0]
    if t in (0, 5):  # high / flush
        return eval5[1]
    if t == 1:  # pair
        return eval5[1]
    if t == 2:  # two pair
        return eval5[1]  # pair1 (đôi lớn)
    if t == 3:  # trips
        return eval5[1]
    if t in (4, 8):  # straight / straight flush
        return eval5[1]
    if t == 6:  # full house
        return eval5[1]  # trips
    if t == 7:  # four
        return eval5[1]
    return eval5[1]
def _major_rank_top(eval3: Tuple[int, ...]) -> int:
    """
    Major rank cho 3 lá:
    - High: high card
    - Pair: rank đôi
    - Trips: rank sám
    """
    t = eval3[0]
    if t == 0:
        return eval3[1]
    if t == 1:
        return eval3[1]
    if t == 3:
        return eval3[1]
    return eval3[1]
def _top_kickers_eval5(eval5: Tuple[int, ...], k: int = 3) -> Tuple[int, ...]:
    """
    Trích top kicker/vals để tie-break 'dàn đều' ở mậu thầu/đôi.
    Trả về tuple độ dài k (thiếu thì pad -1).
    """
    t = eval5[0]
    vals: List[int] = []
    if t in (0, 5):  # high/flush: (t, v1, v2, v3, v4, v5)
        vals = list(eval5[1:])
    elif t == 1:  # pair: (1, pair, k1, k2, k3)
        vals = [eval5[2], eval5[3], eval5[4]]
    elif t == 2:  # two pair: (2, pair_hi, pair_lo, kicker)
        vals = [eval5[3], eval5[2], eval5[1]]  # kicker, pair_lo, pair_hi (để so chi tiết)
    elif t == 3:  # trips: (3, trips, k1, k2)
        vals = [eval5[2], eval5[3], eval5[1]]
    elif t in (4, 8):  # straight / sf
        vals = [eval5[1]]
    elif t == 6:  # full house: (6, trips, pair)
        vals = [eval5[2], eval5[1]]
    elif t == 7:  # four: (7, quad, kicker)
        vals = [eval5[2], eval5[1]]
    else:
        vals = list(eval5[1:])

    # pad
    while len(vals) < k:
        vals.append(-1)
    return tuple(vals[:k])
def _top_kickers_eval3(eval3: Tuple[int, ...], k: int = 3) -> Tuple[int, ...]:
    """
    Trích top kicker/vals cho 3 lá.
    """
    t = eval3[0]
    vals: List[int] = []
    if t == 0:  # high: (0, v1, v2, v3)
        vals = list(eval3[1:])
    elif t == 1:  # pair: (1, pair, kicker)
        vals = [eval3[2], eval3[1]]
    elif t == 3:  # trips: (3, trips)
        vals = [eval3[1]]
    else:
        vals = list(eval3[1:])

    while len(vals) < k:
        vals.append(-1)
    return tuple(vals[:k])

def _kicker_resource_eval5(eval5: Tuple[int, ...]) -> Tuple[int, ...]:
    """Kickers/rác theo cấu trúc hand (5-card), dùng cho 'dồn lực'."""
    t = eval5[0]
    if t == 7:  # four: (7, quad, kicker)
        return (eval5[2],)
    if t == 6:  # full house: (6, trips, pair) -> no kicker
        return tuple()
    if t == 3:  # trips: (3, trips, k1, k2)
        return tuple(sorted(eval5[2:4], reverse=True))
    if t == 2:  # two pair: (2, hi, lo, kicker)
        return (eval5[3],)
    if t == 1:  # pair: (1, pair, k1, k2, k3)
        return tuple(sorted(eval5[2:5], reverse=True))
    if t == 4 or t == 8:  # straight / straight flush: (4, high) or (8, high)
        return (eval5[1],)
    # high (0) / flush (5): (t, v1, v2, v3, v4, v5)
    return tuple(sorted(eval5[1:6], reverse=True))


def _kicker_resource_eval3(eval3: Tuple[int, ...]) -> Tuple[int, ...]:
    """Kickers/rác theo cấu trúc hand (3-card), dùng cho 'dồn lực'."""
    t = eval3[0]
    if t == 3:  # trips: (3, trips)
        return tuple()
    if t == 1:  # pair: (1, pair, kicker)
        return (eval3[2],)
    # high: (0, v1, v2, v3)
    return tuple(sorted(eval3[1:4], reverse=True))


def _golden_kicker_key(
    eval_bottom: Tuple[int, ...],
    eval_mid: Tuple[int, ...],
    eval_top: Tuple[int, ...],
) -> Tuple[int, ...]:
    """Quy luật vàng 'dồn rác/kicker': ưu tiên Chi3 -> Chi2 -> Chi1.

    - Chi3 (top, 3 cards) nhận kicker/rác to nhất.
    - Chi2 nhận tiếp theo.
    - Chi1 (bottom) tránh giữ kicker to (đặc biệt khi chi1 đã là hand mạnh như tứ/cù).
    Đây là TIE-BREAK: không phá rule chính (primary).
    """
    k1 = list(_kicker_resource_eval5(eval_bottom))
    k2 = list(_kicker_resource_eval5(eval_mid))
    k3 = list(_kicker_resource_eval3(eval_top))

    k3.sort(reverse=True)
    k2.sort(reverse=True)
    k1.sort()  # ascending, because we want small in bottom

    # Full-house bottom: prefer smaller pair inside full house (waste smallest pair)
    fh_pair_bonus = 0
    if eval_bottom[0] == 6 and len(eval_bottom) >= 3:
        fh_pair_bonus = -eval_bottom[2]

    # Quads bottom: prefer smaller kicker
    quad_kicker_bonus = 0
    if eval_bottom[0] == 7 and len(eval_bottom) >= 3:
        quad_kicker_bonus = -eval_bottom[2]

    return tuple([fh_pair_bonus, quad_kicker_bonus] + k3 + k2 + [-x for x in k1])

def _secondary_balance_key(
    eval_bottom: Tuple[int, ...],
    eval_mid: Tuple[int, ...],
    eval_top: Tuple[int, ...],
) -> Tuple[int, ...]:
    """
    Secondary key (rule phụ) – dùng để 'dàn đều' nhưng không bao giờ phá rule chính.

    Tư tưởng:
    - Ưu tiên dàn đều giữa chi2 và chi3 trước (vì chi1 thường đã mạnh/định hình).
    - Khi chi1 là cù/tứ: ưu tiên dùng 'lá/đôi nhỏ' làm phần đệm (giải phóng lực).
    - Khi chi2 & chi3 đều là đôi: maximize (pair2, pair3, kicker_top) nhưng luôn hợp lệ do rule chính.
    - Khi mậu thầu: maximize min(high2, high3) rồi maximize sum(high2+high3), sau đó kickers.
    """
    t1 = eval_bottom[0]
    t2 = eval_mid[0]
    t3 = eval_top[0]

    major2 = _major_rank_5(eval_mid)
    major3 = _major_rank_top(eval_top)

    # dàn đều trọng tâm chi2/chi3
    min23 = min(major2, major3)
    sum23 = major2 + major3

    # Ưu tiên: tăng min trước, rồi sum, rồi chi3 (đỡ rác), rồi kickers
    key: List[int] = [min23, sum23, major3]

    # Nhánh cụ thể: chi2 đôi & chi3 đôi (đã không binh lủng do rule chính)
    if t2 == 1 and t3 == 1:
        pair2 = eval_mid[1]
        pair3 = eval_top[1]
        topk3 = _top_kickers_eval3(eval_top, 1)[0]
        key.extend([pair2, pair3, topk3])

    # Nhánh: chi2 đôi, chi3 mậu thầu -> ưu tiên top high chi3 + kicker
    if t2 == 1 and t3 == 0:
        key.extend(list(_top_kickers_eval3(eval_top, 3)))

    # Nhánh: chi2 mậu thầu, chi3 mậu thầu -> dàn đều theo kickers
    if t2 == 0 and t3 == 0:
        k2 = _top_kickers_eval5(eval_mid, 3)
        k3 = _top_kickers_eval3(eval_top, 3)
        # maximize min-high đã có; thêm tổng kicker để 'mượt'
        key.extend([k2[0] + k3[0], k2[1] + k3[1], k2[2] + k3[2]])

    # Nhánh: chi1 là cù -> pair trong cù càng nhỏ càng tốt (giải phóng đôi lớn)
    if t1 == 6:
        # eval_bottom = (6, trips, pair)
        pair_in_fullhouse = eval_bottom[2]
        # muốn pair nhỏ -> dùng -pair để "lớn hơn là tốt hơn"
        key.append(-pair_in_fullhouse)

    # Nhánh: chi1 là tứ -> kicker của tứ càng nhỏ càng tốt
    if t1 == 7:
        # eval_bottom = (7, quad, kicker)
        kicker = eval_bottom[2]
        key.append(-kicker)

    # Cuối: thêm kickers chi2 để phá hòa nhẹ, không làm lệch primary
    key.extend(list(_top_kickers_eval5(eval_mid, 2)))
    key.extend(list(_top_kickers_eval3(eval_top, 2)))

    return tuple(key)


# =====================================================================
# SINH TẤT CẢ CÁC SPLIT 5–5–3 HỢP LỆ
# =====================================================================
