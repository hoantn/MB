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
            _arrange_lru.popitem(last=False)


def arrange_cache_clear():
    """Xoá toàn bộ cache arrange (dùng khi bạn muốn test A/B hoặc nghi ngờ stale)."""
    global _arrange_cache_hits, _arrange_cache_misses
    with _arrange_lock:
        _arrange_lru.clear()
        _arrange_cache_hits = 0
        _arrange_cache_misses = 0


def arrange_cache_stats() -> Dict[str, int]:
    """Trả về thống kê cache để bạn kiểm tra có ăn cache không."""
    with _arrange_lock:
        return {
            "size": len(_arrange_lru),
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
    
def _generate_flush_straight_variants(idx5, related, ranks13, suits13, kind, max_variants=3):
    """
    Sinh các phương án chọn 5 lá khác nhau từ idx5 + related.
    BẮT BUỘC: variant phải GIỮ ĐÚNG LOẠI hand ban đầu (kind: "flush" | "straight").
    """
    base = list(idx5)
    all_cards = list(set(base) | set(related))

    # sort ưu tiên thay thế theo rank cao -> thấp (giữ hành vi gần nhất code cũ)
    all_cards.sort(key=lambda i: ranks13[i], reverse=True)

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

    variants = []
    # 1) Giữ nguyên (luôn hợp lệ)
    variants.append(tuple(sorted(base)))

    # 2) Thử hy sinh lá cao (drop theo rank cao -> thấp), thay bằng lá từ related/all_cards
    for drop in sorted(base, key=lambda i: ranks13[i], reverse=True):
        candidate4 = [i for i in base if i != drop]

        for add in all_cards:
            if add in candidate4:
                continue

            new5 = candidate4 + [add]
            if len(set(new5)) != 5:
                continue

            # BẮT BUỘC: giữ đúng loại hand ban đầu
            if not _match_kind(new5):
                continue

            variants.append(tuple(sorted(new5)))
            break

        if len(variants) >= max_variants:
            break
        # nếu không tìm được add hợp lệ cho drop này, thử drop tiếp theo

    # Dedup & giới hạn
    out = []
    seen = set()
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
        if len(out) >= max_variants:
            break

    return out

def arrange_13_cards(
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
    def _style_tuple(idx1, idx2, idx3) -> List[int]:
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

        return part_chi3 + part_chi2 + part_chi1

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

        # prune theo (t1,t2): khi đã lấy đủ t3 hợp lệ cho t2 thì skip các chi2 còn lại cùng t2
        # seen_t3_by_t2: Dict[int, set[int]] = {}
        for idx2, _e2 in chi2_candidates:
            variants2 = [idx2]

            info = _analyze_flush_straight(
                idx2,
                ranks13,
                suits13,
                rank_to_indices,
                suit_to_indices,
            )

            if info:
                variants2 = _generate_flush_straight_variants(
                    idx2,
                    info["related"],
                    ranks13,
                    suits13,
                    info["type"],
                )

            for v_idx2 in variants2:
                e2 = _eval5(v_idx2)
                t2 = e2[0]

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

                t1 = e1[0]
                t3 = e3[0]
                struct_key = (t1, t2, t3)

                sc = _score_tuple(e1, e2, e3)

                # QUAN TRỌNG: style phải dùng v_idx2 (variant), KHÔNG dùng idx2 gốc
                st = _style_tuple(idx1, v_idx2, idx3)

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

    # sort theo score tuple sc desc
    reps.sort(key=lambda it: it[3], reverse=True)
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
    _arrange_cache_set(cache_key, reps_idx_full)

    if max_candidates and max_candidates > 0:
        reps = reps[: int(max_candidates)]

    out: List[Tuple[List[Card], List[Card], List[Card]]] = []
    for _e1, _e2, _e3, _sc, _st, idx1, idx2, idx3 in reps:
        c1 = [cards[i] for i in idx1]
        c2 = [cards[i] for i in idx2]
        c3 = [cards[i] for i in idx3]

        out.append((c1, c2, c3))
    return out

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
