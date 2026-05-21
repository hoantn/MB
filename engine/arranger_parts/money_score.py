from __future__ import annotations

from typing import Tuple

def _score_max_money(
    eval_bottom: Tuple[int, ...],
    eval_mid: Tuple[int, ...],
    eval_top: Tuple[int, ...],
) -> float:
    """
    Heuristic "ăn chi / ăn tiền" dựa trên luật:

    - Base: strength chi1 > chi2 > chi3 (trọng số 1.0 / 0.8 / 0.4).
    - Bonus:
        +6  nếu sám chi 3
        +4  nếu cù lũ chi 2
        +8  nếu tứ quý chi 1
        +16 nếu tứ quý chi 2
        +10 nếu thùng phá sảnh chi 1
        +20 nếu thùng phá sảnh chi 2
    - Penalty nhẹ nếu chi 3 quá yếu (mậu thầu toàn rác).
    """
    t_bottom = eval_bottom[0]
    t_mid = eval_mid[0]
    t_top_raw = eval_top[0]
    # map trips(3 lá) -> 5-card scale trips=3 để tính base/penalty nhất quán
    t_top = t_top_raw

    # Base score: ưu tiên chi1 > chi2 > chi3
    base = (
        t_bottom * 1.0
        + t_mid * 0.8
        + t_top * 0.4
    )

    bonus = 0.0

    # Chi 3: sám chi cuối +6
    if t_top_raw == 3:  # sám 3 lá
        bonus += 6.0

    # Chi giữa:
    if t_mid == 6:  # cù lũ
        bonus += 4.0
    if t_mid == 7:  # tứ quý
        bonus += 16.0
    if t_mid == 8:  # thùng phá sảnh
        bonus += 20.0

    # Chi 1:
    if t_bottom == 7:  # tứ quý
        bonus += 8.0
    if t_bottom == 8:  # thùng phá sảnh
        bonus += 10.0

    # Penalty nhẹ nếu chi 3 quá yếu (mậu thầu)
    if t_top == 0:
        bonus -= 0.5

    return base + bonus


# =====================================================================
# RULE PHỤ (DÀN ĐỀU) – CHỈ DÙNG ĐỂ PHÁ HOÀ / CHỌN GIỮA CÁC SPLIT HỢP LỆ
# Giữ nguyên rule chính: brute-force + ràng buộc không binh lủng + primary score.
# =====================================================================
