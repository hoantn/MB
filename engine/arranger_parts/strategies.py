from enum import Enum

class ArrangeStrategy(Enum):
    """
    Chiến lược xếp bài:

    - MAX_STRENGTH: tối đa sức mạnh nội bộ (chi1, chi2, chi3).
    - MAX_MONEY: tối ưu heuristic "ăn chi / ăn tiền" khi chưa có bài đối thủ.
    - MAX_MONEY_VS_OPP: tối ưu số chi ăn/thua theo luật tiền khi đã biết bài đối thủ.
    - VS_OPPONENT: dùng Engine B cũ (score_matchup) để so sánh tương đối với 3 chi của đối thủ.
    - BEAUTY_TEMPLATE: xếp bài theo template 3 chi, sau đó ưu tiên bài đẹp (dồn rác) – không dùng heuristic tiền.
    """
    MAX_STRENGTH = "max_strength"
    MAX_MONEY = "max_money"
    MAX_MONEY_VS_OPP = "max_money_vs_opp"
    VS_OPPONENT = "vs_opp"
    BEAUTY_TEMPLATE = "beauty_template"


# ====================================
# HEURISTIC "MAX_MONEY" TỰ THÂN
# ====================================
