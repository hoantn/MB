from typing import List, Tuple
from .card import Card
from .rules import evaluate_5cards


# =========================================================
# ENGINE A: ĐIỂM "ĐẸP NỘI BỘ" 3 CHI (GIỮ NGUYÊN CHO COMPAT)
# =========================================================

def score_three_chi(chi1: List[Card], chi2: List[Card], chi3: List[Card]) -> Tuple[int, dict]:
    """
    Đánh giá độ đẹp nội bộ của 3 chi (không so với đối thủ).

    - chi1, chi2: 5 lá → dùng evaluate_5cards (hand_type 0..8 + tie-break).
    - chi3: 3 lá → tạm thời dùng tổng rank_index làm "sức mạnh".

    Trả về:
        total_score: số nguyên để sort / so sánh sơ bộ
        meta: dict thông tin chi tiết.
    """
    r1, d1 = evaluate_5cards(chi1)
    r2, d2 = evaluate_5cards(chi2)
    r3_score = sum(c.rank_index for c in chi3)

    total_score = r1 * 100 + r2 * 10 + r3_score

    return total_score, {
        "chi1": (r1, d1),
        "chi2": (r2, d2),
        "chi3_strength": r3_score,
    }


# =========================================================
# ENGINE B: SO CHI & TÍNH ĐIỂM ĐỐI ĐẦU VỚI ĐỐI THỦ
# =========================================================

def evaluate_3cards(chi: List[Card]) -> Tuple[int, List[int]]:
    """
    Đánh giá 3 lá (chi trên) theo Mậu Binh:
      hand_type:
        0: mậu thầu
        1: đôi
        2: sám
    Trả về (hand_type, [tie-breakers theo rank_index]).
    """
    if len(chi) != 3:
        raise ValueError("evaluate_3cards: chi trên phải có đúng 3 lá")

    vals = sorted([c.rank_index for c in chi], reverse=True)
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1

    # sắp theo (count, value) để tìm bộ chính
    groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    main_val, main_cnt = groups[0]

    if main_cnt == 3:
        # sám: type 2, tie-break = rank của bộ 3
        return 2, [main_val]
    if main_cnt == 2:
        # đôi: type 1, tie-break = rank đôi, rồi kicker
        pair_val = main_val
        kicker = max(v for v in vals if v != pair_val)
        return 1, [pair_val, kicker]

    # mậu thầu: type 0, tie-break = 3 lá giảm dần
    return 0, vals


def compare_5cards(a: List[Card], b: List[Card]) -> int:
    """
    So sánh 2 chi 5 lá.
    Trả về:
      >0 nếu a > b
       0 nếu a == b
      <0 nếu a < b
    """
    ra, da = evaluate_5cards(a)
    rb, db = evaluate_5cards(b)

    if ra != rb:
        return 1 if ra > rb else -1

    # tie-break theo list chi tiết
    # so lexicographic: list lớn hơn → chi mạnh hơn
    if da > db:
        return 1
    if da < db:
        return -1
    return 0


def compare_3cards(a: List[Card], b: List[Card]) -> int:
    """
    So sánh 2 chi 3 lá (chi trên).
    Trả về:
      >0 nếu a > b
       0 nếu a == b
      <0 nếu a < b
    """
    ta, da = evaluate_3cards(a)
    tb, db = evaluate_3cards(b)

    if ta != tb:
        return 1 if ta > tb else -1

    if da > db:
        return 1
    if da < db:
        return -1
    return 0


def score_matchup(
    my_chi1: List[Card],
    my_chi2: List[Card],
    my_chi3: List[Card],
    opp_chi1: List[Card],
    opp_chi2: List[Card],
    opp_chi3: List[Card],
    collapse_multiplier: int = 2,
) -> int:
    """
    Tính điểm đối đầu 3 chi của mình so với đối thủ.

    Quy ước:
      - Mỗi chi:
          thắng → +1
          thua  → -1
          hoà   →  0
      - Nếu THẮNG CẢ 3 CHI (đối thủ bị sập 3 chi):
          tổng điểm nhân collapse_multiplier (mặc định 2 → +6/-6).
      - Ở đây KHÔNG xử lý binh đặc biệt (rồng, 6 đôi, ...) để giữ đơn giản,
        có thể bổ sung sau bằng hệ số thưởng riêng.

    Lưu ý:
      - my_chi1, my_chi2: 5 lá (chi dưới, chi giữa)
      - my_chi3: 3 lá (chi trên)
      - opp_chi* tương tự.
    """

    # chi dưới
    s1 = compare_5cards(my_chi1, opp_chi1)
    # chi giữa
    s2 = compare_5cards(my_chi2, opp_chi2)
    # chi trên
    s3 = compare_3cards(my_chi3, opp_chi3)

    win1 = 1 if s1 > 0 else (-1 if s1 < 0 else 0)
    win2 = 1 if s2 > 0 else (-1 if s2 < 0 else 0)
    win3 = 1 if s3 > 0 else (-1 if s3 < 0 else 0)

    raw = win1 + win2 + win3

    # Sập 3 chi / bị sập 3 chi → nhân đôi
    if raw == 3 or raw == -3:
        return raw * collapse_multiplier

    return raw
