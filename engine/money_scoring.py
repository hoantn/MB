from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple, Optional

from .card import Card
from .rules import evaluate_5cards, is_straight, is_flush
from core.constants import RANK_ORDER
from engine.foul_rules import evaluate_top_for_foul, is_no_foul


# ============================================================
#  ĐÁNH GIÁ CHI 3 LÁ (CHI TRÊN)
# ============================================================


def evaluate_3cards(cards: List[Card]) -> Tuple[int, List[int]]:
    """
    Đánh giá hạng bài cho CHI 3 (3 lá):

        0 = Mậu thầu (high card)
        1 = Đôi
        2 = Xám (three of a kind)

    detail: vector rank_index để so sánh khi cùng hạng.
    """
    assert len(cards) == 3, "Chi 3 phải có đúng 3 lá"

    ranks = [c.rank_index for c in cards]
    ranks_sorted = sorted(ranks, reverse=True)

    # Đếm số lá theo rank
    count_by_rank: dict[int, int] = {}
    for r in ranks:
        count_by_rank[r] = count_by_rank.get(r, 0) + 1

    counts = list(count_by_rank.values())
    if 3 in counts:
        # Xám
        trip_rank = max(r for r, c in count_by_rank.items() if c == 3)
        return 2, [trip_rank]

    if 2 in counts:
        # Đôi
        pair_rank = max(r for r, c in count_by_rank.items() if c == 2)
        kicker_rank = max(r for r, c in count_by_rank.items() if c == 1)
        return 1, [pair_rank, kicker_rank]

    # Mậu thầu
    return 0, ranks_sorted


# ============================================================
#  SO SÁNH HAI HAND (cùng loại evaluate_5 / evaluate_3)
# ============================================================


def _cmp_hand(
    my_type: int, my_detail: List[int], opp_type: int, opp_detail: List[int]
) -> int:
    """
    So sánh 2 hand cùng kiểu evaluate_*:

        >0  → my > opp
        <0  → my < opp
        =0  → hòa
    """
    if my_type != opp_type:
        return 1 if my_type > opp_type else -1

    # So sánh detail lexicographic
    for a, b in zip(my_detail, opp_detail):
        if a != b:
            return 1 if a > b else -1

    # Nếu độ dài khác nhau mà prefix bằng nhau → ai dài hơn coi như mạnh hơn
    if len(my_detail) != len(opp_detail):
        return 1 if len(my_detail) > len(opp_detail) else -1

    return 0


# ============================================================
#  BÀI ĐẶC BIỆT 13 LÁ
# ============================================================


class Special13Type(Enum):
    SIX_PAIRS = "six_pairs"             # 6 đôi
    THREE_STRAIGHTS = "three_straights" # 3 sảnh
    THREE_FLUSHES = "three_flushes"     # 3 thùng
    FIVE_PAIRS_ONE_TRIPS = "five_pairs_one_trips"  # 5 đôi 1 xám
    ALL_SAME_COLOR = "all_same_color"   # Đồng hoa (13 lá đồng màu)
    DRAGON = "dragon"                   # Sảnh rồng 2–A
    DRAGON_COLOR = "dragon_color"       # Sảnh rồng đồng hoa


_SPECIAL_13_BONUS: dict[Special13Type, int] = {
    Special13Type.SIX_PAIRS: 8,
    Special13Type.THREE_STRAIGHTS: 8,
    Special13Type.THREE_FLUSHES: 8,
    Special13Type.FIVE_PAIRS_ONE_TRIPS: 10,
    Special13Type.ALL_SAME_COLOR: 30,
    Special13Type.DRAGON: 50,
    Special13Type.DRAGON_COLOR: 100,
}

def get_special_13_bonus(t: Optional[Special13Type]) -> int:
    """Public helper: trả về số chi thưởng của bài đặc biệt."""
    return _SPECIAL_13_BONUS.get(t, 0)

def _eval_top_for_foul(cs3: List[Card]) -> Tuple[int, List[int]]:
    """Compatibility wrapper; luật chuẩn nằm tại engine.foul_rules."""
    return evaluate_top_for_foul(cs3)

def _no_foul(chi1: List[Card], chi2: List[Card], chi3: List[Card]) -> bool:
    """Compatibility wrapper; không binh lủng khi chi1 >= chi2 >= chi3."""
    return is_no_foul(chi1, chi2, chi3)

def _score_split(chi1: List[Card], chi2: List[Card], chi3: List[Card]) -> Tuple:
    """Chấm điểm để chọn split tốt nhất (ưu tiên mạnh)."""
    t1, d1 = evaluate_5cards(chi1)
    t2, d2 = evaluate_5cards(chi2)
    t3, d3 = _eval_top_for_foul(chi3)
    return (t1, d1, t2, d2, t3, d3)

def _card_color(suit: str) -> str:
    """
    Chuyển suit → màu theo hệ suit của tool:

        - ĐỎ  : R (Rô), C (Cơ)  [Diamonds/Hearts]
        - ĐEN : B (Bích), T (Tép) [Spades/Clubs]

    Đồng thời vẫn hỗ trợ các ký hiệu quốc tế H/D/S/C nếu có.
    """
    if not suit:
        return "BLACK"
    s = suit.upper()[0]

    # Hệ suit Việt (tool của anh)
    if s in ("R", "C"):
        return "RED"
    if s in ("B", "T"):
        return "BLACK"

    # Hệ suit quốc tế (fallback)
    if s in ("H", "D"):
        return "RED"
    return "BLACK"


def detect_special_13(cards: List[Card]) -> Optional[Special13Type]:
    """
    Phát hiện bài đặc biệt 13 lá theo luật:

        - 6 đôi               → 8 chi
        - 3 sảnh              → 8 chi
        - 3 thùng             → 8 chi
        - 5 đôi 1 xám         → 10 chi
        - Đồng hoa (13 lá đồng màu: đỏ hoặc đen)  → 30 chi
        - Sảnh rồng (2–A)     → 50 chi
        - Sảnh rồng đồng hoa  → 100 chi
    """
    if len(cards) != 13:
        return None

    from collections import Counter

    ranks = [c.rank_index for c in cards]   # 0..12 (2..A)
    suits = [c.suit for c in cards]

    rank_counter = Counter(ranks)

    # =========================================================
    # 1) DRAGON / ALL SAME COLOR (ƯU TIÊN CAO NHẤT)
    # =========================================================
    colors = {_card_color(s) for s in suits}
    all_same_color = (len(colors) == 1)

    sorted_ranks = sorted(ranks)
    is_dragon = (sorted_ranks == list(range(len(RANK_ORDER))))  # 0..12

    if is_dragon and all_same_color:
        return Special13Type.DRAGON_COLOR
    if is_dragon:
        return Special13Type.DRAGON
    if all_same_color:
        return Special13Type.ALL_SAME_COLOR

    # =========================================================
    # 2) 5 ĐÔI 1 XÁM / 6 ĐÔI (TÍNH TỨ QUÝ = 2 ĐÔI)
    # =========================================================
    counts = list(rank_counter.values())
    num_pairs = sum(1 for v in counts if v == 2)
    num_trips = sum(1 for v in counts if v == 3)

    # "đơn vị đôi": tứ quý(4) -> 2 đôi, xám(3) -> 1 đôi, đôi(2) -> 1 đôi
    pair_units = sum(v // 2 for v in counts)

    # 5 đôi 1 xám: đúng 1 xám, và tổng đơn vị đôi = 6 (5 đôi + xám góp 1 đôi)
    # QUAN TRỌNG: loại trường hợp có tứ quý lẫn vào (v==4) để tránh hiểu sai.
    has_quads = any(v == 4 for v in counts)
    if (num_trips == 1) and (not has_quads) and (pair_units == 6):
        return Special13Type.FIVE_PAIRS_ONE_TRIPS

    # 6 đôi: KHÔNG có xám, và tổng đơn vị đôi = 6
    # -> trường hợp "4 đôi + 1 tứ quý" sẽ có pair_units = 4 + 2 = 6 => nhận đúng.
    if (num_trips == 0) and (pair_units == 6):
        return Special13Type.SIX_PAIRS

    # =========================================================
    # 3) 3 THÙNG (5-5-3 đều flush, suit có thể trùng)
    # =========================================================
    suit_counts = Counter(suits)

    def can_make_3_flushes_5_5_3(sc: Counter) -> bool:
        # thử mọi cách gán suit cho 3 chi (có thể trùng suit)
        suits_list = list(sc.keys())
        if not suits_list:
            return False
        need = [5, 5, 3]
        for a in range(len(suits_list)):
            for b in range(len(suits_list)):
                for c in range(len(suits_list)):
                    use = Counter()
                    use[suits_list[a]] += need[0]
                    use[suits_list[b]] += need[1]
                    use[suits_list[c]] += need[2]
                    ok = True
                    for s, cnt in use.items():
                        if sc.get(s, 0) < cnt:
                            ok = False
                            break
                    if ok:
                        return True
        return False

    if can_make_3_flushes_5_5_3(suit_counts):
        return Special13Type.THREE_FLUSHES

    # =========================================================
    # 4) 3 SẢNH (5-5-3 đều straight theo multiset ranks)
    #    - 5 lá: liên tiếp hoặc A2345
    #    - 3 lá: liên tiếp hoặc A23 hoặc QKA
    # =========================================================
    ranks_ms = Counter(ranks)

    def _all_straights_of_len(ms: Counter, L: int) -> List[List[int]]:
        seqs: List[List[int]] = []
        # normal consecutive sequences
        for st in range(0, 13):  # rank_index 0..12
            seq = [st + i for i in range(L)]
            if seq[-1] > 12:
                continue
            need = Counter(seq)
            if all(ms.get(r, 0) >= cnt for r, cnt in need.items()):
                seqs.append(seq)

        # special A-low
        if L in (5, 3):
            # A2345 => [12,0,1,2,3]
            low = [12] + list(range(0, L - 1))
            need = Counter(low)
            if all(ms.get(r, 0) >= cnt for r, cnt in need.items()):
                seqs.append(low)

        # special QKA for 3 cards => [10,11,12]
        if L == 3:
            qka = [10, 11, 12]
            need = Counter(qka)
            if all(ms.get(r, 0) >= cnt for r, cnt in need.items()):
                seqs.append(qka)

        return seqs

    def _sub(ms: Counter, seq: List[int]) -> Optional[Counter]:
        out = Counter(ms)
        for r in seq:
            if out.get(r, 0) <= 0:
                return None
            out[r] -= 1
        return out

    s3 = _all_straights_of_len(ranks_ms, 3)
    s5 = _all_straights_of_len(ranks_ms, 5)

    if s3 and len(s5) >= 2:
        # ưu tiên sảnh cao trước để reduce loop sớm
        s5_sorted = sorted(s5, key=lambda seq: max(seq), reverse=True)
        s3_sorted = sorted(s3, key=lambda seq: max(seq), reverse=True)

        found = False
        for a in s5_sorted:
            ms1 = _sub(ranks_ms, a)
            if ms1 is None:
                continue
            for b in s5_sorted:
                ms2 = _sub(ms1, b)
                if ms2 is None:
                    continue
                for cseq in s3_sorted:
                    ms3 = _sub(ms2, cseq)
                    if ms3 is not None:
                        found = True
                        break
                if found:
                    break
            if found:
                break

        if found:
            return Special13Type.THREE_STRAIGHTS

    return None


# ============================================================
#  ĐẠI DIỆN 3 CHI (5-5-3) ĐỂ TÍNH TIỀN
# ============================================================


@dataclass(frozen=True)
class ThreeChi:
    chi1: List[Card]  # 5 lá
    chi2: List[Card]  # 5 lá
    chi3: List[Card]  # 3 lá

    @property
    def all_cards(self) -> List[Card]:
        return self.chi1 + self.chi2 + self.chi3


# ============================================================
#  BONUS CHI THEO TỪNG CHI
# ============================================================


def _chi_bonus(hand_type: int, chi_index: int) -> int:
    """
    Bonus cho từng chi theo luật:

        - Xám chi cuối: 6 chi.      (xử lý riêng ở chi_index == 3)
        - Cù lũ chi giữa: 4 chi.
        - Tứ quý chi đầu: 8 chi.
        - Tứ quý chi giữa: 16 chi.
        - Thùng phá sảnh chi đầu: 10 chi.
        - Thùng phá sảnh chi giữa: 20 chi.

    hand_type dùng mapping của evaluate_5cards:

        0 = Mậu thầu
        1 = Đôi
        2 = Thú
        3 = Xám
        4 = Sảnh
        5 = Thùng
        6 = Cù
        7 = Tứ quý
        8 = Thùng phá sảnh
    """
    if chi_index == 1:
        if hand_type == 7:  # Tứ quý chi đầu
            return 8
        if hand_type == 8:  # Thùng phá sảnh chi đầu
            return 10
        return 0

    if chi_index == 2:
        if hand_type == 6:  # Cù lũ chi giữa
            return 4
        if hand_type == 7:  # Tứ quý chi giữa
            return 16
        if hand_type == 8:  # Thùng phá sảnh chi giữa
            return 20
        return 0

    # Chi 3 dùng rule riêng (Xám chi cuối) xử lý ở ngoài
    return 0


# ============================================================
#  TÍNH TIỀN CHO 1 CHI RIÊNG
# ============================================================


def score_money_single_chi(
    my_cards: List[Card],
    opp_cards: List[Card],
    chi_index: int,
) -> int:
    """
    Tính số chi của 1 chi riêng lẻ giữa P và OPP, bao gồm:

        - +1 / -1 / 0 theo mạnh yếu.
        - Bonus chi đặc biệt cho từng bên (cộng cho mình, trừ cho đối thủ).

    chi_index: 1, 2 hoặc 3.
    """
    if chi_index not in (1, 2, 3):
        raise ValueError("chi_index phải là 1, 2 hoặc 3")

    # Đánh giá hand
    if chi_index in (1, 2):
        my_type, my_detail = evaluate_5cards(my_cards)
        opp_type, opp_detail = evaluate_5cards(opp_cards)
    else:
        my_type, my_detail = evaluate_3cards(my_cards)
        opp_type, opp_detail = evaluate_3cards(opp_cards)

    # Base ±1/chi
    cmp_val = _cmp_hand(my_type, my_detail, opp_type, opp_detail)
    base = cmp_val  # 1, -1 hoặc 0

    # Bonus chi
    bonus = 0
    if chi_index == 3:
        # Xám chi cuối
        if my_type == 2:
            bonus += 6
        if opp_type == 2:
            bonus -= 6
    else:
        bonus += _chi_bonus(my_type, chi_index)
        bonus -= _chi_bonus(opp_type, chi_index)

    return base + bonus


# ============================================================
#  TÍNH TIỀN TỔNG 3 CHI (P vs OPP)
# ============================================================


def score_money_vs_opp(
    my_three_chi: ThreeChi,
    opp_three_chi: ThreeChi,
    *,
    allow_special_13: bool = True,
    allow_sap_ham: bool = True,
) -> int:
    """
    Tính tổng số chi P ăn/thua so với OPP theo LUẬT CHUẨN:

        1) Nếu 1 trong 2 bên có bài đặc biệt 13 lá:
           - P có  → +bonus
           - OPP có → -bonus
           - Cả 2 có → chênh lệch bonus
           (mặc định: nếu có bài đặc biệt thì KHÔNG so tiếp 3 chi).

        2) Nếu không có bài đặc biệt:
           - So từng chi (1,2,3):
             +1 / -1 / 0 + bonus chi.

        3) Sập hầm:
           - Nếu P thắng cả 3 chi  → *2 tổng chi.
           - Nếu P thua cả 3 chi → *2 tổng chi.
    """
    # 1. Bài đặc biệt 13 lá
    if allow_special_13:
        my_sp = detect_special_13(my_three_chi.all_cards)
        opp_sp = detect_special_13(opp_three_chi.all_cards)

        if my_sp or opp_sp:
            my_bonus = _SPECIAL_13_BONUS.get(my_sp, 0)
            opp_bonus = _SPECIAL_13_BONUS.get(opp_sp, 0)
            return my_bonus - opp_bonus

    # 2. So từng chi
    chi1 = score_money_single_chi(my_three_chi.chi1, opp_three_chi.chi1, 1)
    chi2 = score_money_single_chi(my_three_chi.chi2, opp_three_chi.chi2, 2)
    chi3 = score_money_single_chi(my_three_chi.chi3, opp_three_chi.chi3, 3)

    total = chi1 + chi2 + chi3

    # 3. Sập hầm (dựa trên base ±1/chi, không dùng bonus)
    if allow_sap_ham:
        # Tính lại base thắng/thua từng chi (không bonus) để kiểm tra sập hầm
        my1_t, my1_d = evaluate_5cards(my_three_chi.chi1)
        opp1_t, opp1_d = evaluate_5cards(opp_three_chi.chi1)
        c1 = _cmp_hand(my1_t, my1_d, opp1_t, opp1_d)

        my2_t, my2_d = evaluate_5cards(my_three_chi.chi2)
        opp2_t, opp2_d = evaluate_5cards(opp_three_chi.chi2)
        c2 = _cmp_hand(my2_t, my2_d, opp2_t, opp2_d)

        my3_t, my3_d = evaluate_3cards(my_three_chi.chi3)
        opp3_t, opp3_d = evaluate_3cards(opp_three_chi.chi3)
        c3 = _cmp_hand(my3_t, my3_d, opp3_t, opp3_d)

        wins = sum(1 for v in (c1, c2, c3) if v > 0)
        losses = sum(1 for v in (c1, c2, c3) if v < 0)

        if wins == 3 or losses == 3:
            total *= 2

    return total
