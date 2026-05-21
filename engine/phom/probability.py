# engine/phom/probability.py
from __future__ import annotations

from typing import Set, Dict

def compute_uniform_card_probability(unseen: Set[int], opp_hand_size_guess: int) -> Dict[int, float]:
    """Giai đoạn 1: xác suất đồng đều cho mọi lá unseen.
    P(card in opp hand) ≈ H / |unseen|
    """
    u = len(unseen)
    if u <= 0:
        return {}
    h = max(0, int(opp_hand_size_guess))
    p = min(1.0, max(0.0, h / float(u)))
    return {c: p for c in unseen}
