# engine/arranger_parts/arrange.py
from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Tuple, Optional, Iterable
from collections import OrderedDict
from threading import RLock

from enum import Enum

from engine.card import Card
from engine.rules import evaluate_5cards
from engine.scorer import evaluate_3cards
from engine.arranger_parts.money_score import _score_max_money
from engine.arranger_parts.human_choice import HumanChoiceCandidate, select_human_choice
from core.constants import RANK_ORDER


class ArrangeStrategy(Enum):
    STYLE_BRUTEFORCE_ALL = "style_bruteforce_all"
    BEAUTY_TEMPLATE = "beauty_template"
# ============================
# Cross-call LRU cache (giảm CPU tối đa nhưng KHÔNG đổi kết quả)
# - Cache theo đúng THỨ TỰ cards input (rank_index, suit) để đảm bảo mapping idx chuẩn.
# - Cache theo strategy. max_candidates chỉ slice trên kết quả đã cache.
# - Giá trị cache lưu dưới dạng LIST indices để không giữ reference Card cũ.
# ============================

_ARRANGE_LRU_MAX = 256  # tăng/giảm theo RAM (256 ván là rất đủ cho UI)
_arrange_lru: "OrderedDict[Tuple[Tuple[Tuple[int, int], ...], str], List[Tuple[Tuple[int, int, int, int, int], Tuple[int, int, int, int, int], Tuple[int, int, int]]]]" = OrderedDict()
_arrange_money_lru = OrderedDict()
_arrange_lock = RLock()

_arrange_cache_hits = 0
_arrange_cache_misses = 0


def _arrange_cache_key(cards: List[Card], strategy: ArrangeStrategy) -> Tuple[Tuple[Tuple[int, int], ...], str]:
    # Key theo đúng thứ tự input list để đảm bảo idx mapping ra đúng cards[].
    sig = tuple((c.rank_index, c.suit) for c in cards)
    return sig, str(strategy.value)


def _arrange_cache_get(key):
    global _arrange_cache_hits, _arrange_cache_misses
    with _arrange_lock:
        v = _arrange_lru.get(key)
        if v is None:
            _arrange_cache_misses += 1
            return None
        # LRU refresh
        _arrange_lru.move_to_end(key)
        _arrange_cache_hits += 1
        return v


def _arrange_cache_set(key, value):
    with _arrange_lock:
        _arrange_lru[key] = value
        _arrange_lru.move_to_end(key)
        # enforce maxsize
        while len(_arrange_lru) > _ARRANGE_LRU_MAX:
            old_key, _ = _arrange_lru.popitem(last=False)
            _arrange_money_lru.pop(old_key, None)


def _arrange_money_cache_get(key):
    with _arrange_lock:
        return _arrange_money_lru.get(key)


def _arrange_money_cache_set(key, value):
    with _arrange_lock:
        if value is None:
            _arrange_money_lru.pop(key, None)
            return
        _arrange_money_lru[key] = value
        _arrange_money_lru.move_to_end(key)


def arrange_cache_clear():
    """Xoá toàn bộ cache arrange (dùng khi bạn muốn test A/B hoặc nghi ngờ stale)."""
    global _arrange_cache_hits, _arrange_cache_misses
    with _arrange_lock:
        _arrange_lru.clear()
        _arrange_money_lru.clear()
        _arrange_cache_hits = 0
        _arrange_cache_misses = 0


def arrange_cache_stats() -> Dict[str, int]:
    """Trả về thống kê cache để bạn kiểm tra có ăn cache không."""
    with _arrange_lock:
        return {
            "size": len(_arrange_lru),
            "money_size": len(_arrange_money_lru),
            "max": _ARRANGE_LRU_MAX,
            "hits": _arrange_cache_hits,
            "misses": _arrange_cache_misses,
        }

# ============================================================
# Helpers: so sánh hand theo (type, detail) đã evaluate sẵn
# ============================================================

def _cmp_lex(a: List[int], b: List[int]) -> int:
    if a > b:
        return 1
    if a < b:
        return -1
    return 0


def _cmp_5_eval(a: Tuple[int, List[int]], b: Tuple[int, List[int]]) -> int:
    """So 2 hand 5 lá bằng (type, detail)."""
    ta, da = a
    tb, db = b
    if ta != tb:
        return 1 if ta > tb else -1
    return _cmp_lex(da, db)


def _map_3_to_5_scale(t3: int) -> int:
    """
    Map type 3 lá sang "thang type 5 lá" để foul-check chi2 >= chi3:

      3 lá:
        0: mậu thầu  -> 0
        1: đôi       -> 1
        2: sám       -> 3   (vì 5 lá: 3 = xám)

    (Logic này tương thích với hệ thống type hiện tại của bạn.) 
    """
    if t3 == 2:
        return 3
    return t3


def _cmp_5_vs_3(
    e5: Tuple[int, List[int]],
    e3: Tuple[int, List[int]],
) -> int:
    """
    So chi 5 lá (chi2) với chi 3 lá (chi3) để foul-check.

    Nguyên tắc:
      - So theo type sau khi map 3->5 (sám 3 lá ~ xám 5 lá).
      - Nếu cùng type:
          + Mậu thầu: so 3 lá cao nhất của chi5 với 3 lá của chi3.
          + Đôi: so (pair, kicker) rồi dùng kicker phụ của chi5 để phá hòa (nếu cần).
          + Xám/sám: so rank bộ; chi5 có kicker nên thường mạnh hơn nếu cùng rank.
    """
    t5, d5 = e5
    t3, d3 = e3
    t3m = _map_3_to_5_scale(t3)

    if t5 != t3m:
        return 1 if t5 > t3m else -1

    # cùng type (0 hoặc 1 hoặc 3)
    if t5 == 0:
        # d5: 5 lá giảm dần; d3: 3 lá giảm dần
        a = d5[:3]
        b = d3[:3]
        return _cmp_lex(a, b)

    if t5 == 1:
        # d5: [pair, k1, k2, k3], d3: [pair, kicker]
        # so pair -> so kicker chính -> rồi đến kicker phụ của chi5
        a = [d5[0], d5[1], d5[2], d5[3]]
        b = [d3[0], d3[1], -1, -1]
        return _cmp_lex(a, b)

    if t5 == 3:
        # d5: [trip, k1, k2], d3: [trip]
        a = [d5[0], d5[1], d5[2]]
        b = [d3[0], -1, -1]
        return _cmp_lex(a, b)

    # fallback: nếu có case lạ, coi như hòa
    return 0


def _allowed_t3_for_middle(t2_5: int) -> set[int]:
    """
    Với chi2 là 5 lá có type t2_5, chi3 (3 lá) có thể hợp lệ tối đa đến đâu
    để KHÔNG binh lủng (chi2 >= chi3).

    - Nếu chi2 là mậu thầu (0): chi3 chỉ được mậu (0)
    - Nếu chi2 là đôi (1) hoặc thú (2): chi3 chỉ được mậu/đôi (0/1)
      (vì sám 3 lá map ~ xám(3) > thú(2))
    - Nếu chi2 >= xám(3): chi3 có thể mậu/đôi/sám (0/1/2)
    """
    if t2_5 <= 0:
        return {0}
    if t2_5 <= 2:
        return {0, 1}
    return {0, 1, 2}


# ============================================================
# Core: arrange_13_cards theo mô hình 2 tầng
#   - FULL coverage split 5–5–3
#   - Dedup theo STRUCT ngay trong loop (mỗi struct 1 đại diện)
# ============================================================
def _analyze_flush_straight(idx5, ranks13, suits13, rank_to_indices, suit_to_indices):
    """
    Phân tích 1 chi 5 lá có phải là THÙNG hoặc SẢNH bán khóa hay không.
    Trả về:
      {
        "type": "flush" | "straight" | None,
        "base": list idx5,
        "related": list index các lá liên quan ngoài chi
      }
    """
    base = set(idx5)
    related = set()

    # --- CHECK FLUSH ---
    s0 = suits13[idx5[0]]
    is_flush = True
    for i in idx5[1:]:
        if suits13[i] != s0:
            is_flush = False
            break

    if is_flush:
        for j in suit_to_indices.get(s0, []):
            if j not in base:
                related.add(j)
        if related:
            return {
                "type": "flush",
                "base": list(idx5),
                "related": list(related),
            }

    # --- CHECK STRAIGHT ---
    uniq = sorted(set(ranks13[i] for i in idx5))
    straight_ranks = None

    if len(uniq) == 5 and (uniq[-1] - uniq[0] == 4):
        straight_ranks = uniq
    else:
        # Wheel A2345
        IDX_2 = RANK_ORDER.index("2")
        IDX_3 = RANK_ORDER.index("3")
        IDX_4 = RANK_ORDER.index("4")
        IDX_5 = RANK_ORDER.index("5")
        IDX_A = RANK_ORDER.index("A")
        wheel = {IDX_A, IDX_2, IDX_3, IDX_4, IDX_5}
        if set(uniq) == wheel:
            straight_ranks = list(wheel)

    if straight_ranks:
        for r in straight_ranks:
            for j in rank_to_indices.get(r, []):
                if j not in base:
                    related.add(j)
        if related:
            return {
                "type": "straight",
                "base": list(idx5),
                "related": list(related),
            }

    return None
    
def _generate_flush_straight_variants(
    idx5,
    related,
    ranks13,
    suits13,
    kind,
    max_variants: Optional[int] = None,
    variant_cache: Optional[
        Dict[Tuple[str, Tuple[int, ...]], List[Tuple[int, int, int, int, int]]]
    ] = None,
):
    """
    Sinh các phương án chọn 5 lá khác nhau từ idx5 + related.
    BẮT BUỘC: variant phải GIỮ ĐÚNG LOẠI hand ban đầu (kind: "flush" | "straight").
    """
    base = tuple(sorted(idx5))
    all_cards = tuple(sorted(set(base) | set(related)))
    cache_key = (str(kind), all_cards)
    if variant_cache is not None and cache_key in variant_cache:
        cached = variant_cache[cache_key]
        if max_variants and max_variants > 0:
            return cached[: int(max_variants)]
        return cached

    # sort ưu tiên thay thế theo rank cao -> thấp (giữ hành vi gần nhất code cũ)

    def _is_flush(idx_list):
        s0 = suits13[idx_list[0]]
        for i in idx_list[1:]:
            if suits13[i] != s0:
                return False
        return True

    def _is_straight(idx_list):
        uniq = sorted(set(ranks13[i] for i in idx_list))
        if len(uniq) != 5:
            return False
        if uniq[-1] - uniq[0] == 4:
            return True
        # Wheel A2345
        IDX_2 = RANK_ORDER.index("2")
        IDX_3 = RANK_ORDER.index("3")
        IDX_4 = RANK_ORDER.index("4")
        IDX_5 = RANK_ORDER.index("5")
        IDX_A = RANK_ORDER.index("A")
        return set(uniq) == {IDX_A, IDX_2, IDX_3, IDX_4, IDX_5}

    def _match_kind(idx_list):
        if kind == "flush":
            return _is_flush(idx_list)
        if kind == "straight":
            return _is_straight(idx_list)
        return True  # fallback an toàn

    variants = [base]
    for comb5 in combinations(all_cards, 5):
        v = tuple(sorted(comb5))
        if v == base:
            continue
        if _match_kind(v):
            variants.append(v)

    # 1) Giữ nguyên (luôn hợp lệ)

    # 2) Thử hy sinh lá cao (drop theo rank cao -> thấp), thay bằng lá từ related/all_cards
            # BẮT BUỘC: giữ đúng loại hand ban đầu
        # nếu không tìm được add hợp lệ cho drop này, thử drop tiếp theo

    # Dedup & giới hạn
    out = []
    seen = set()
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
        if max_variants and max_variants > 0 and len(out) >= max_variants:
            break

    if variant_cache is not None and not (max_variants and max_variants > 0):
        variant_cache[cache_key] = out

    return out

def _arrange_13_cards_impl(
    cards: List[Card],
    *,
    strategy: ArrangeStrategy = ArrangeStrategy.STYLE_BRUTEFORCE_ALL,
    max_candidates: Optional[int] = None,
) -> List[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Brute-force 72k split 5-5-3, lọc foul, rồi dedup theo struct_key=(t1,t2,t3).
    Với mỗi struct_key chỉ giữ 1 đại diện, nhưng đại diện được chọn theo PHONG CÁCH:
      - so _style_tuple (dồn đôi + dồn rác theo Chi3 -> Chi2 -> Chi1)
    Sau đó sort các struct theo _score_tuple để trả ra danh sách.
    """

    if not cards or len(cards) != 13:
        return []

    # Quy ước:
    #   - None hoặc 0 => không giới hạn (trả FULL struct)
    #   - >0 => giới hạn số struct trả về sau khi sort
    if max_candidates is None:
        max_candidates = 0
    # ---- Cross-call cache (giữ nguyên kết quả) ----
    # Lưu/đọc cache theo đúng thứ tự input cards để idx mapping chuẩn.
    cache_key = _arrange_cache_key(cards, strategy)
    cached = _arrange_cache_get(cache_key)
    if cached is not None:
        # cached là list idx tuples: [(idx1,idx2,idx3), ...]
        reps_idx = cached
        if max_candidates and max_candidates > 0:
            reps_idx = reps_idx[: int(max_candidates)]
        out: List[Tuple[List[Card], List[Card], List[Card]]] = []
        for idx1, idx2, idx3 in reps_idx:
            out.append(([cards[i] for i in idx1], [cards[i] for i in idx2], [cards[i] for i in idx3]))
        return out

    # ---- cache evaluator theo tuple index (rẻ & ổn định) ----
    eval5_cache: Dict[Tuple[int, int, int, int, int], Tuple[int, List[int]]] = {}
    eval3_cache: Dict[Tuple[int, int, int], Tuple[int, List[int]]] = {}
    variant_cache: Dict[
        Tuple[str, Tuple[int, ...]],
        List[Tuple[int, int, int, int, int]],
    ] = {}
    variant_subset_cache: Dict[
        Tuple[str, Tuple[int, ...], Tuple[int, ...]],
        List[Tuple[int, int, int, int, int]],
    ] = {}
    # ---- Precompute ranks/suits/index maps (dùng cho _style_tuple, giảm CPU) ----
    ranks13: List[int] = [c.rank_index for c in cards]
    suits13: List[int] = [c.suit for c in cards]

    suit_to_indices: Dict[int, List[int]] = {}
    rank_to_indices: Dict[int, List[int]] = {}
    # ---- Rank index constants (KHÔNG giả định) ----
    IDX_2 = RANK_ORDER.index("2")
    IDX_3 = RANK_ORDER.index("3")
    IDX_4 = RANK_ORDER.index("4")
    IDX_5 = RANK_ORDER.index("5")
    IDX_A = RANK_ORDER.index("A")

    for i in range(13):
        s = suits13[i]
        r = ranks13[i]
        suit_to_indices.setdefault(s, []).append(i)
        rank_to_indices.setdefault(r, []).append(i)

    # Cache base (cnt/pairs/singles) theo idx tuple để reuse trong vòng 72k
    # Key có thể là idx5 hoặc idx3 (tuple length 5 hoặc 3)
    _base_ps_cache: Dict[Tuple[int, ...], Tuple[Dict[int, int], Tuple[int, ...], Tuple[int, ...]]] = {}
    _flush_straight_info_cache: Dict[Tuple[int, int, int, int, int], Optional[dict]] = {}
    _style_extras_cache: Dict[Tuple[int, ...], Tuple[int, ...]] = {}
    _money_score_cache: Dict[Tuple[int, Tuple[int, ...], int, Tuple[int, ...], int, Tuple[int, ...]], float] = {}
    _is_flush_idx_cache: Dict[Tuple[int, int, int, int, int], bool] = {}

    def _eval5(idx5: Tuple[int, int, int, int, int]) -> Tuple[int, List[int]]:
        v = eval5_cache.get(idx5)
        if v is not None:
            return v
        hand = (cards[idx5[0]], cards[idx5[1]], cards[idx5[2]], cards[idx5[3]], cards[idx5[4]])
        v = evaluate_5cards(list(hand))
        eval5_cache[idx5] = v
        return v

    def _eval3(idx3: Tuple[int, int, int]) -> Tuple[int, List[int]]:
        v = eval3_cache.get(idx3)
        if v is not None:
            return v
        hand = (cards[idx3[0]], cards[idx3[1]], cards[idx3[2]])
        v = evaluate_3cards(list(hand))
        eval3_cache[idx3] = v
        return v

    # ---- Precompute chi1 candidates (1287) và sort mạnh→yếu ----
    chi1_candidates: List[Tuple[Tuple[int, int, int, int, int], Tuple[int, List[int]]]] = []
    for comb5 in combinations(range(13), 5):
        idx5 = tuple(sorted(comb5))  # type: ignore
        e = _eval5(idx5)
        chi1_candidates.append((idx5, e))

    # sort by (type, detail) desc
    chi1_candidates.sort(key=lambda it: (it[1][0], it[1][1]), reverse=True)

    # ---- Dedup theo struct ngay trong nguồn ----
    # struct_key = (t1_5, t2_5, t3_3)
    best_by_struct: Dict[
        Tuple[int, int, int],
        Tuple[
            Tuple[int, List[int]],  # e1
            Tuple[int, List[int]],  # e2
            Tuple[int, List[int]],  # e3
            List[int],              # sc
            List[int],              # st
            Tuple[int, int, int, int, int],  # idx1
            Tuple[int, int, int, int, int],  # idx2
            Tuple[int, int, int],            # idx3
        ],
    ] = {}
    best_money_key = None
    best_money_idx = None
    money_candidates: List[HumanChoiceCandidate] = []

    # Lưu thêm score tuple để sort sau: [t1]+d1+[t2]+d2+[t3m]+d3padded
    # score dùng list[int] để so lexicographic rẻ.
    def _score_tuple(e1, e2, e3) -> List[int]:
        t1, d1 = e1
        t2, d2 = e2
        t3, d3 = e3
        t3m = _map_3_to_5_scale(t3)
        # pad d3 cho ổn định (tối đa 3 phần tử)
        d3p = (d3 + [-1, -1, -1])[:3]
        return [t1] + d1 + [t2] + d2 + [t3m] + d3p

    def _style_hard_prefix(st: List[int]) -> int:
        return int(st[0]) if st else 1

    def _display_sort_key(sc: List[int], st: List[int]):
        # Hard style prefix is only for global rules such as Chi2 flush/straight
        # overflow. After that, keep the original strength-first UI ordering.
        return (_style_hard_prefix(st), tuple(sc), tuple(st))

    def _money_sort_key(money_score: float, sc: List[int], st: List[int]):
        # Money remains the main Auto Money score, but it cannot override a hard
        # style rule that marks a flush/straight overflow variant as bad.
        return (_style_hard_prefix(st), money_score, tuple(st), tuple(sc))

    def _style_tuple(idx1, idx2, idx3, overflow_context=None) -> List[int]:
        # Style ưu tiên: pair mạnh và rác mạnh dồn về chi3 -> chi2 -> chi1
        # So sánh bằng lexicographic list[int]: list lớn hơn => hợp style hơn.

        def _get_base_pairs_singles(ch_idx: Tuple[int, ...]) -> Tuple[Dict[int, int], Tuple[int, ...], Tuple[int, ...]]:
            """
            Cache base theo idx tuple:
              - cnt: dict rank->count trong chi
              - pairs: tuple ranks có count==2 (desc)
              - singles: tuple ranks có count==1 (desc)
            """
            v = _base_ps_cache.get(ch_idx)
            if v is not None:
                return v

            cnt: Dict[int, int] = {}
            for i in ch_idx:
                r = ranks13[i]
                cnt[r] = cnt.get(r, 0) + 1

            pairs = sorted([r for r, n in cnt.items() if n == 2], reverse=True)
            singles = sorted([r for r, n in cnt.items() if n == 1], reverse=True)

            out = (cnt, tuple(pairs), tuple(singles))
            _base_ps_cache[ch_idx] = out
            return out

        def _extras_from_flush_straight(ch_idx: Tuple[int, ...]) -> List[int]:
            """
            Tối ưu extras:
              - Flush: lấy indices cùng suit từ suit_to_indices, loại các index thuộc chi.
              - Straight (chỉ áp cho 5 lá): lấy indices theo rank_to_indices trong biên straight.
            Kết quả là list rank_index extras (có thể trùng, sẽ dedup sau).
            """
            cached = _style_extras_cache.get(ch_idx)
            if cached is not None:
                return list(cached)

            ch_set = set(ch_idx)
            extras: List[int] = []

            # --- FLUSH: nếu tất cả cùng suit ---
            s0 = suits13[ch_idx[0]]
            is_flush = True
            for i in ch_idx[1:]:
                if suits13[i] != s0:
                    is_flush = False
                    break
            if is_flush:
                for j in suit_to_indices.get(s0, []):
                    if j not in ch_set:
                        extras.append(ranks13[j])

            # --- STRAIGHT: chỉ check nếu là 5 lá ---
            if len(ch_idx) == 5:
                uniq = sorted(set(ranks13[i] for i in ch_idx))
                straight_ranks = None
                if len(uniq) == 5 and (uniq[-1] - uniq[0] == 4):
                    # Straight thường (bao gồm 10JQKA nếu mapping trong RANK_ORDER là liên tiếp)
                    straight_ranks = uniq
                else:
                    # Wheel A2345: dùng index thật theo RANK_ORDER (KHÔNG giả định)
                    wheel_set = {IDX_A, IDX_2, IDX_3, IDX_4, IDX_5}
                    if len(uniq) == 5 and set(uniq) == wheel_set:
                        # giữ thứ tự ranks để loop lấy extras; thứ tự không quan trọng vì extras sẽ dedup/sort sau
                        straight_ranks = [IDX_A, IDX_2, IDX_3, IDX_4, IDX_5]

                if straight_ranks is not None:
                    for r in straight_ranks:
                        for j in rank_to_indices.get(r, []):
                            if j not in ch_set:
                                extras.append(ranks13[j])

            _style_extras_cache[ch_idx] = tuple(extras)
            return extras

        def build(ch_idx: Tuple[int, ...], allow_extras: bool) -> Tuple[List[int], List[int]]:
            cnt, pairs0, singles0 = _get_base_pairs_singles(ch_idx)

            if not allow_extras:
                return list(pairs0), list(singles0)

            # dùng set để tránh trùng, giống logic cuối hàm cũ (sorted(set(...)))
            pairs = set(pairs0)
            singles = set(singles0)

            extras = _extras_from_flush_straight(ch_idx)
            for r in extras:
                if r in cnt:
                    if cnt[r] == 1:
                        pairs.add(r)
                else:
                    singles.add(r)

            pairs_list = sorted(pairs, reverse=True)
            singles_list = sorted(singles, reverse=True)
            return pairs_list, singles_list

        p1, s1 = build(idx1, allow_extras=False)
        p2, s2 = build(idx2, allow_extras=True)
        p3, s3 = build(idx3, allow_extras=False)

        def pad(lst: List[int], n: int) -> List[int]:
            return (lst + [-1] * n)[:n]

        part_chi3 = pad(p3, 1) + pad(s3, 3)
        part_chi2 = pad(p2, 2) + pad(s2, 5)
        part_chi1 = pad(p1, 2) + pad(s1, 5)
        real_hand_gain = pad(p3, 1) + pad(p2, 2)
        trash_distribution = pad(s3, 3) + pad(s2, 5) + part_chi1

        def protected_bottom_run_strength() -> List[int]:
            """
            When the bottom hand is a straight/flush/straight-flush, keep its
            real strength ahead of trash distribution. Otherwise the style
            sorter can pick a lower straight/flush only to move a high card into
            another chi as a kicker.
            """
            e1 = _eval5(idx1)
            hand_type, detail = e1
            if hand_type not in (4, 5, 8):
                return []
            return [hand_type] + pad(list(detail), 5)

        bottom_run = protected_bottom_run_strength()
        if bottom_run:
            # Same-template flush/straight overflow should protect the bottom
            # run from pure trash/kicker swaps, but not from real gains such as
            # improving a top/middle pair. Example: use a lower flush card to
            # free T and upgrade chi3 from pair 5 to pair T.
            base_style = real_hand_gain + bottom_run + trash_distribution
        else:
            base_style = part_chi3 + part_chi2 + part_chi1
        if not overflow_context:
            return [1] + base_style

        # Hard style rule for Chi2 flush/straight overflow:
        # prefer the strongest base flush/straight, and only allow sacrificing it
        # when another chi gains real hand value. This keeps every caller
        # (manual Max, profile Money, OPP Auto Money) on one shared style source.
        style_prefix = _flush_straight_style_prefix(
            overflow_context.get("kind"),
            overflow_context.get("base_record"),
            overflow_context.get("current_record"),
        )
        return style_prefix + base_style

    def _chi3_has_real_gain(base_e3, cur_e3) -> bool:
        base_type, base_detail = base_e3
        cur_type, cur_detail = cur_e3
        if cur_type > base_type:
            return True
        if cur_type != base_type:
            return False
        if cur_type == 1:
            # Pair gain means pair rank improves. Kicker is treated as trash.
            return bool(cur_detail and base_detail and cur_detail[0] > base_detail[0])
        if cur_type == 2:
            # Trips gain means trips rank improves.
            return bool(cur_detail and base_detail and cur_detail[0] > base_detail[0])
        return False

    def _mau_swap_gain_allowed(kind, base_idx2, cur_idx2, base_idx3, cur_idx3, base_e2, base_e3, cur_e3) -> bool:
        if base_e3[0] != 0 or cur_e3[0] != 0:
            return False
        if not cur_e3[1] > base_e3[1]:
            return False

        moved_to_chi3 = set(base_idx2) - set(cur_idx2)
        moved_to_chi2 = set(base_idx3) - set(cur_idx3)
        if len(moved_to_chi3) != 1 or len(moved_to_chi2) != 1:
            return False

        moved_idx = next(iter(moved_to_chi3))
        replaced_idx = next(iter(moved_to_chi2))
        moved_rank = ranks13[moved_idx]
        replaced_rank = ranks13[replaced_idx]
        base_chi3_ranks = [ranks13[i] for i in base_idx3]

        if kind == "flush":
            base_ranks = sorted((ranks13[i] for i in base_idx2), reverse=True)
            if len(base_ranks) < 2 or moved_rank != base_ranks[1]:
                return False
            base_without_moved = set(base_idx2) - {moved_idx}
            valid_replacements = [
                i for i in base_idx3
                if _is_flush_idx(tuple(sorted(base_without_moved | {i})))
            ]
            if not valid_replacements:
                return False
            min_valid_rank = min(ranks13[i] for i in valid_replacements)
            return replaced_rank == min_valid_rank

        if kind == "straight":
            straight_high = base_e2[1][0] if base_e2[1] else -1
            if moved_rank != straight_high:
                return False
            base_without_moved = set(base_idx2) - {moved_idx}
            valid_replacements = [
                i for i in base_idx3
                if _eval5(tuple(sorted(base_without_moved | {i})))[0] == 4
            ]
            if not valid_replacements:
                return False
            min_valid_rank = min(ranks13[i] for i in valid_replacements)
            return replaced_rank == min_valid_rank

        return False

    def _flush_straight_style_prefix(kind, base_record, cur_record) -> List[int]:
        if not kind or base_record is None:
            return [1]

        base_idx2, base_e2, base_idx3, base_e3 = base_record
        cur_idx2, _cur_e2, cur_idx3, cur_e3 = cur_record
        if tuple(cur_idx2) == tuple(base_idx2):
            return [1]

        if _chi3_has_real_gain(base_e3, cur_e3):
            return [1]

        if _mau_swap_gain_allowed(
            kind,
            base_idx2,
            cur_idx2,
            base_idx3,
            cur_idx3,
            base_e2,
            base_e3,
            cur_e3,
        ):
            return [1]

        return [0]

    def _is_flush_idx(idx5: Tuple[int, int, int, int, int]) -> bool:
        cached = _is_flush_idx_cache.get(idx5)
        if cached is not None:
            return cached
        suit = suits13[idx5[0]]
        value = all(suits13[i] == suit for i in idx5[1:])
        _is_flush_idx_cache[idx5] = value
        return value

    def _overflow_kind_for_idx2(
        idx5: Tuple[int, int, int, int, int],
        e5: Tuple[int, List[int]],
        info_kind: Optional[str] = None,
    ) -> Optional[str]:
        if info_kind:
            return info_kind
        if _is_flush_idx(idx5):
            return "flush"
        if e5[0] == 4:
            return "straight"
        return None

    def _rem8_flush_straight_bases(
        candidates: List[Tuple[Tuple[int, int, int, int, int], Tuple[int, List[int]]]],
        rem8_list: List[int],
    ) -> Dict[str, Tuple[Tuple[int, int, int, int, int], Tuple[int, List[int]], Tuple[int, int, int], Tuple[int, List[int]]]]:
        bases: Dict[str, Tuple[Tuple[int, int, int, int, int], Tuple[int, List[int]], Tuple[int, int, int], Tuple[int, List[int]]]] = {}
        best_keys: Dict[str, Tuple[int, List[int]]] = {}

        for b_idx2, b_e2 in candidates:
            b_set2 = set(b_idx2)
            b_rem3 = [i for i in rem8_list if i not in b_set2]
            if len(b_rem3) != 3:
                continue
            b_idx3 = tuple(sorted(b_rem3))  # type: ignore
            b_e3 = _eval3(b_idx3)
            if _cmp_5_vs_3(b_e2, b_e3) < 0:
                continue

            kinds: List[str] = []
            if _is_flush_idx(b_idx2):
                kinds.append("flush")
            if b_e2[0] == 4:
                kinds.append("straight")

            for kind in kinds:
                key = (b_e2[0], b_e2[1])
                if kind not in best_keys or key > best_keys[kind]:
                    best_keys[kind] = key
                    bases[kind] = (b_idx2, b_e2, b_idx3, b_e3)

        return bases

    def _analyze_flush_straight_cached(
        idx5: Tuple[int, int, int, int, int],
    ) -> Optional[dict]:
        if idx5 in _flush_straight_info_cache:
            return _flush_straight_info_cache[idx5]
        info = _analyze_flush_straight(
            idx5,
            ranks13,
            suits13,
            rank_to_indices,
            suit_to_indices,
        )
        _flush_straight_info_cache[idx5] = info
        return info

    def _variants_for_rem8(
        idx2: Tuple[int, int, int, int, int],
        info: dict,
        rem8_list: List[int],
    ) -> List[Tuple[int, int, int, int, int]]:
        variants = _generate_flush_straight_variants(
            idx2,
            info["related"],
            ranks13,
            suits13,
            info["type"],
            variant_cache=variant_cache,
        )
        if len(variants) <= 1:
            return variants

        rem8_key = tuple(rem8_list)
        all_cards_key = tuple(sorted(set(idx2) | set(info["related"])))
        subset_key = (str(info["type"]), rem8_key, all_cards_key)
        cached = variant_subset_cache.get(subset_key)
        if cached is not None:
            return cached

        rem8_set = set(rem8_key)
        filtered = [v for v in variants if all(i in rem8_set for i in v)]
        variant_subset_cache[subset_key] = filtered
        return filtered

    def _cached_money_score(e1, e2, e3_mapped) -> float:
        key = (
            int(e1[0]),
            tuple(int(x) for x in e1[1]),
            int(e2[0]),
            tuple(int(x) for x in e2[1]),
            int(e3_mapped[0]),
            tuple(int(x) for x in e3_mapped[1]),
        )
        cached = _money_score_cache.get(key)
        if cached is not None:
            return cached
        value = float(_score_max_money(e1, e2, e3_mapped))
        _money_score_cache[key] = value
        return value

    # ---- main loop: chi1 (1287) x chi2 (56) = 72k ----

    for idx1, e1 in chi1_candidates:
        set1 = set(idx1)
        rem8 = [i for i in range(13) if i not in set1]  # size 8

        # Với chi1 cố định, ta chỉ cần 56 chi2 combos.
        # Ta sẽ tạo list chi2 candidate + eval và sort theo mạnh→yếu để "đại diện đầu" tốt.
        chi2_candidates: List[Tuple[Tuple[int, int, int, int, int], Tuple[int, List[int]]]] = []
        for comb5 in combinations(rem8, 5):
            idx2 = tuple(sorted(comb5))  # type: ignore
            e2 = _eval5(idx2)
            # prune thô: chi2 mạnh hơn chi1 => chắc chắn foul
            if e2[0] > e1[0]:
                continue
            chi2_candidates.append((idx2, e2))

        chi2_candidates.sort(key=lambda it: (it[1][0], it[1][1]), reverse=True)
        rem8_base_by_kind = _rem8_flush_straight_bases(chi2_candidates, rem8)
        processed_variant_keys = set()

        # prune theo (t1,t2): khi đã lấy đủ t3 hợp lệ cho t2 thì skip các chi2 còn lại cùng t2
        # seen_t3_by_t2: Dict[int, set[int]] = {}
        for idx2, _e2 in chi2_candidates:
            variants2 = [idx2]

            info = _analyze_flush_straight_cached(idx2)

            if info:
                variants2 = _variants_for_rem8(idx2, info, rem8)

            variant_records = []
            for v_idx2 in variants2:
                if info:
                    variant_key = (str(info["type"]), v_idx2)
                    if variant_key in processed_variant_keys:
                        continue
                    processed_variant_keys.add(variant_key)
                e2 = _eval5(v_idx2)
                set2 = set(v_idx2)
                rem3 = [i for i in rem8 if i not in set2]
                if len(rem3) != 3:
                    continue
                idx3 = tuple(sorted(rem3))  # type: ignore
                e3 = _eval3(idx3)

                # foul check:
                #   chi1 >= chi2  (5 vs 5)
                if _cmp_5_eval(e1, e2) < 0:
                    continue
                #   chi2 >= chi3  (5 vs 3)
                if _cmp_5_vs_3(e2, e3) < 0:
                    continue

                variant_records.append((v_idx2, e2, idx3, e3))

            for v_idx2, e2, idx3, e3 in variant_records:
                t2 = e2[0]
                t1 = e1[0]
                t3 = e3[0]
                struct_key = (t1, t2, t3)

                sc = _score_tuple(e1, e2, e3)

                # QUAN TRỌNG: style phải dùng v_idx2 (variant), KHÔNG dùng idx2 gốc
                overflow_kind = _overflow_kind_for_idx2(
                    v_idx2,
                    e2,
                    info["type"] if info else None,
                )
                base_variant_record = (
                    rem8_base_by_kind.get(overflow_kind)
                    if overflow_kind
                    else None
                )
                overflow_context = {
                    "kind": overflow_kind,
                    "base_record": base_variant_record,
                    "current_record": (v_idx2, e2, idx3, e3),
                }
                st = _style_tuple(idx1, v_idx2, idx3, overflow_context)

                # Capture the best self-money split inside the existing scan.
                # Auto Play can reuse it without starting another 72k pass.
                money_e3 = (_map_3_to_5_scale(e3[0]), e3[1])
                money_score = _cached_money_score(e1, e2, money_e3)
                money_candidates.append(
                    HumanChoiceCandidate(
                        idx1=idx1,
                        idx2=v_idx2,
                        idx3=idx3,
                        e1=e1,
                        e2=e2,
                        e3=e3,
                        score_tuple=sc,
                        style_tuple=st,
                        money_score=money_score,
                    )
                )
                money_key = _money_sort_key(money_score, sc, st)
                if best_money_key is None or money_key > best_money_key:
                    best_money_key = money_key
                    best_money_idx = (idx1, v_idx2, idx3)

                prev = best_by_struct.get(struct_key)
                if prev is None:
                    # QUAN TRỌNG: lưu v_idx2 vào best_by_struct
                    best_by_struct[struct_key] = (e1, e2, e3, sc, st, idx1, v_idx2, idx3)
                else:
                    _e10, _e20, _e30, _sc0, st0, _i1, _i2, _i3 = prev
                    if st > st0:
                        best_by_struct[struct_key] = (e1, e2, e3, sc, st, idx1, v_idx2, idx3)

    # ---- Build output list ----
    reps = list(best_by_struct.values())

    # --- dominance filter: khi chi3 là MẬU (t3==0), không hy sinh chi2 chỉ để tăng kicker mậu ---
    filtered = []
    best_mau_by_e1 = {}  # key: (t1, tuple(d1)) -> rep

    for rep in reps:
        e1, e2, e3, sc, st, idx1, idx2, idx3 = rep
        if e3[0] != 0:
            filtered.append(rep)
            continue

        k = (e1[0], tuple(e1[1]))  # group theo sức chi1 (mọi chi2 type đều bị so nhau khi chi3=mậu)
        prev = best_mau_by_e1.get(k)
        if prev is None:
            best_mau_by_e1[k] = rep
        else:
            _e1p, e2p, e3p, _scp, _stp, *_ = prev

            # Khi chi3 là MẬU: KHÔNG ưu tiên kicker chi2.
            # Chỉ ưu tiên TYPE chi2; nếu cùng TYPE thì để STYLE quyết định dọn rác.
            if e2[0] > e2p[0]:
                best_mau_by_e1[k] = rep
            elif e2[0] == e2p[0]:
                if st > _stp:
                    best_mau_by_e1[k] = rep
                elif st == _stp and e3[1] > e3p[1]:
                    best_mau_by_e1[k] = rep

    filtered.extend(best_mau_by_e1.values())
    reps = filtered

    # sort theo final display key: hard style rule -> score tuple -> style.
    reps.sort(key=lambda it: _display_sort_key(it[3], it[4]), reverse=True)
    # --- hard filter: nếu chi3 là MẬU, không giữ những rep có chi2 type thấp hơn rep tốt nhất
    # group theo (chi1 eval, chi3 type) => ở đây chi3 type luôn 0, nhưng để rõ ràng
    best_t2_by_e1_for_mau: Dict[Tuple[int, Tuple[int, ...]], int] = {}

    for rep in reps:
        e1, e2, e3, sc, st, idx1, idx2, idx3 = rep
        if e3[0] != 0:
            continue
        k1 = (e1[0], tuple(e1[1]))
        t2 = e2[0]
        prev_t2 = best_t2_by_e1_for_mau.get(k1)
        if prev_t2 is None or t2 > prev_t2:
            best_t2_by_e1_for_mau[k1] = t2

    reps2 = []
    for rep in reps:
        e1, e2, e3, sc, st, idx1, idx2, idx3 = rep
        if e3[0] != 0:
            reps2.append(rep)
            continue
        k1 = (e1[0], tuple(e1[1]))
        best_t2 = best_t2_by_e1_for_mau.get(k1)
        if best_t2 is None:
            reps2.append(rep)
        else:
            # chỉ giữ các rep có chi2 type = type cao nhất trong nhóm chi1 khi chi3=mậu
            if e2[0] == best_t2:
                reps2.append(rep)

    reps = reps2
    # ---- Save full reps indices to cache (không phụ thuộc max_candidates) ----
    # Lưu sau khi đã:
    #   - dedup theo struct_key
    #   - dominance filter
    #   - sort theo _score_tuple
    reps_idx_full: List[Tuple[Tuple[int, int, int, int, int], Tuple[int, int, int, int, int], Tuple[int, int, int]]] = [
        (idx1, idx2, idx3) for _e1, _e2, _e3, _sc, _st, idx1, idx2, idx3 in reps
    ]
    human_money = select_human_choice(money_candidates)
    if human_money is not None:
        best_money_idx = (human_money.idx1, human_money.idx2, human_money.idx3)
    _arrange_cache_set(cache_key, reps_idx_full)
    _arrange_money_cache_set(cache_key, best_money_idx)

    if max_candidates and max_candidates > 0:
        reps = reps[: int(max_candidates)]

    out: List[Tuple[List[Card], List[Card], List[Card]]] = []
    for _e1, _e2, _e3, _sc, _st, idx1, idx2, idx3 in reps:
        c1 = [cards[i] for i in idx1]
        c2 = [cards[i] for i in idx2]
        c3 = [cards[i] for i in idx3]

        out.append((c1, c2, c3))
    return out


def arrange_13_cards(
    cards: List[Card],
    *,
    strategy: ArrangeStrategy = ArrangeStrategy.STYLE_BRUTEFORCE_ALL,
    max_candidates: Optional[int] = None,
) -> List[Tuple[List[Card], List[Card], List[Card]]]:
    return _arrange_13_cards_impl(
        cards,
        strategy=strategy,
        max_candidates=max_candidates,
    )


def arrange_cached_money_split(
    cards: List[Card],
    *,
    strategy: ArrangeStrategy = ArrangeStrategy.STYLE_BRUTEFORCE_ALL,
) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Return the money-optimal split captured by arrange_13_cards().

    This helper never starts a scan. Call arrange_13_cards() first so Auto Play
    reuses the same 72k pass already required for normal suggestions.
    """
    if not cards or len(cards) != 13:
        return None
    cached = _arrange_money_cache_get(_arrange_cache_key(cards, strategy))
    if cached is None:
        return None
    idx1, idx2, idx3 = cached
    return (
        [cards[i] for i in idx1],
        [cards[i] for i in idx2],
        [cards[i] for i in idx3],
    )


def arrange_cards(
    cards: List[Card],
    *,
    strategy: ArrangeStrategy = ArrangeStrategy.STYLE_BRUTEFORCE_ALL,
) -> Tuple[List[Card], List[Card], List[Card]]:
    """
    Trả về 1 gợi ý tốt nhất (đại diện mạnh nhất theo sort của arrange_13_cards).
    Giữ để compat với các nơi gọi fallback.
    """
    res = arrange_13_cards(cards, strategy=strategy, max_candidates=1)
    if res:
        return res[0]
    return [], [], []

def arrange_vs_opp(
    cards: List[Card],
    *,
    strategy: ArrangeStrategy = ArrangeStrategy.STYLE_BRUTEFORCE_ALL,
    max_candidates: Optional[int] = None,
) -> List[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Compat function: hệ thống đang import arrange_vs_opp từ arranger_parts.
    Hiện tại cho OPP dùng cùng engine với P để đảm bảo không lỗi và đồng nhất.
    """
    return arrange_13_cards(cards, strategy=strategy, max_candidates=max_candidates)
def _normalize_kicker_distribution(c1, c2, c3):
    """
    DEPRECATED / COMPAT SHIM:
    Trước đây dùng để normalize dồn đôi/dồn rác sau khi chọn đại diện.
    Hiện đã chuyển sang best-of-struct theo style trong loop 72k, nên hàm này giữ lại
    chỉ để tránh ImportError từ các module cũ.
    """
    return c1, c2, c3
