# engine/phom/analyzer.py
from __future__ import annotations

from typing import List, Set, Tuple, Dict, Optional
from dataclasses import dataclass
from itertools import combinations

from .constants import TOTAL_CARDS

# ---- Tiện ích bài ----

def rank_of(card: int) -> int:
    """A=1, 2..10, J=11, Q=12, K=13"""
    return (card // 4) + 1

def suit_of(card: int) -> int:
    """0..3"""
    return card % 4

def card_id(rank: int, suit: int) -> int:
    """rank: 1..13, suit: 0..3 -> card int"""
    return (rank - 1) * 4 + suit

def card_point(card: int) -> int:
    """Điểm rác theo luật Phỏm chuẩn"""
    r = rank_of(card)
    if r >= 11:
        return r  # J=11, Q=12, K=13
    return r      # A=1, 2..10

# ---- Nhận diện PHỎM ----

def find_set_melds(hand: Set[int]) -> List[Set[int]]:
    """Bộ: >=3 lá cùng rank"""
    by_rank: Dict[int, List[int]] = {}
    for c in hand:
        by_rank.setdefault(rank_of(c), []).append(c)

    melds: List[Set[int]] = []
    for cards in by_rank.values():
        if len(cards) >= 3:
            melds.append(set(cards))
    return melds


def find_run_melds(hand: Set[int]) -> List[Set[int]]:
    """Sảnh: >=3 lá liên tiếp cùng suit"""
    by_suit: Dict[int, List[int]] = {}
    for c in hand:
        by_suit.setdefault(suit_of(c), []).append(c)

    melds: List[Set[int]] = []

    for suit, cards in by_suit.items():
        cards_sorted = sorted(cards, key=rank_of)
        ranks = [rank_of(c) for c in cards_sorted]

        start = 0
        for i in range(1, len(cards_sorted) + 1):
            if i == len(cards_sorted) or ranks[i] != ranks[i-1] + 1:
                length = i - start
                if length >= 3:
                    run = set(cards_sorted[start:i])
                    melds.append(run)
                start = i
    return melds

# ---- Sinh mọi cách tách phỏm ----

def enumerate_meld_splits(hand: Set[int], melds: List[Set[int]]) -> List[Tuple[List[Set[int]], Set[int]]]:
    """
    Trả về danh sách:
    (list_phom, trash_set)
    """
    results: List[Tuple[List[Set[int]], Set[int]]] = []

    for r in range(1, len(melds) + 1):
        for combo in combinations(melds, r):
            used: Set[int] = set()
            valid = True
            for m in combo:
                if used & m:
                    valid = False
                    break
                used |= m
            if not valid:
                continue

            trash = set(hand) - used
            results.append((list(combo), trash))

    results.append(([], set(hand)))
    return results

# ---- Chấm điểm ----

def score_split(melds: List[Set[int]], trash: Set[int]) -> Tuple[int, int, int]:
    """
    Score tuple để so sánh:
    (num_melds, -trash_point, -num_trash)
    """
    num_melds = len(melds)
    trash_point = sum(card_point(c) for c in trash)
    num_trash = len(trash)
    return (num_melds, -trash_point, -num_trash)

# ---- Safe discard (Known-only) ----

def compute_discard_risk_known_only(card: int, known_cards: Set[int]) -> int:
    """
    Risk "bị ăn" theo SAFE MODE:
    - Chỉ dựa trên known_cards (toàn bộ lá đã xuất hiện).
    - Không dùng history ăn/bốc của đối thủ.
    """
    all_cards = set(range(TOTAL_CARDS))
    unseen = all_cards - set(known_cards)

    r = rank_of(card)
    s = suit_of(card)

    risk = 0

    # (A) Rủi ro sảnh: (r-2,r-1) / (r-1,r+1) / (r+1,r+2)
    patterns = [(r - 2, r - 1), (r - 1, r + 1), (r + 1, r + 2)]
    for a, b in patterns:
        if 1 <= a <= 13 and 1 <= b <= 13:
            ca = card_id(a, s)
            cb = card_id(b, s)
            if ca in unseen and cb in unseen:
                risk += 1

    # (B) Rủi ro bộ: cần 2 lá cùng rank khác suit
    others = [card_id(r, su) for su in range(4) if su != s]
    n = sum(1 for c in others if c in unseen)
    if n >= 2:
        risk += (n * (n - 1)) // 2  # C(n,2)

    return risk

def pick_safe_discard_known_only(hand: Set[int], candidates: Set[int], known_cards: Set[int]) -> Tuple[Optional[int], Optional[int], List[Tuple[int, int]]]:
    """
    Trả về (best_card, best_risk, all_risks_sorted)
    - best_card: risk thấp nhất
    - tie-break: ưu tiên bỏ lá điểm rác CAO hơn (để giảm điểm rác của mình)
    """
    if not hand:
        return None, None, []

    pool = set(candidates) if candidates else set(hand)

    risks: List[Tuple[int, int]] = []
    for c in pool:
        risks.append((c, compute_discard_risk_known_only(c, known_cards)))

    risks_sorted = sorted(risks, key=lambda x: (x[1], -card_point(x[0]), x[0]))
    best_card, best_risk = risks_sorted[0]
    return best_card, best_risk, risks_sorted

# ---- Kết quả phân tích ----

@dataclass
class AnalysisResult:
    melds: List[Set[int]]
    trash: Set[int]
    trash_point: int
    suggest_discard: int | None

    # thêm cho SAFE MODE (không phá tương thích)
    suggest_discard_risk: int | None = None
    suggest_discard_risks: List[Tuple[int, int]] | None = None


def analyze_hand(hand: Set[int], known_cards: Optional[Set[int]] = None) -> AnalysisResult:
    """
    Phân tích bài của MÌNH theo Phase 2A.
    Nếu có known_cards: override gợi ý đánh theo SAFE MODE (khó bị ăn nhất dựa trên known).
    """
    all_melds: List[Set[int]] = []
    all_melds.extend(find_set_melds(hand))
    all_melds.extend(find_run_melds(hand))

    splits = enumerate_meld_splits(hand, all_melds)

    best = None
    best_score = None

    for melds, trash in splits:
        score = score_split(melds, trash)
        if best is None or score > best_score:
            best = (melds, trash)
            best_score = score

    assert best is not None
    best_melds, best_trash = best
    trash_point = sum(card_point(c) for c in best_trash)

    # --- NOTE: bỏ hoàn toàn "lá gợi ý" (suggest_discard) ---
    suggest: int | None = None
    suggest_risk: int | None = None
    risks_sorted: List[Tuple[int, int]] | None = None

    return AnalysisResult(
        melds=best_melds,
        trash=best_trash,
        trash_point=trash_point,
        suggest_discard=suggest,
        suggest_discard_risk=suggest_risk,
        suggest_discard_risks=risks_sorted
    )
