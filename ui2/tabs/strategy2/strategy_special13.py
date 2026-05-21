from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from engine.card import Card


def _card_rank_suit(code: str) -> Tuple[Optional[int], Optional[str]]:
    """Return (rank_int, suit_str) for the given code.

    - Prefer Card.from_code to stay consistent with the engine.
    - Fallback to a minimal parse if Card mapping changes or code is already string-like.
    """
    try:
        c = Card.from_code(code)
        r = getattr(c, "rank", None) or getattr(c, "r", None) or getattr(c, "value", None)
        s = getattr(c, "suit", None) or getattr(c, "s", None)

        # Chuẩn hóa rank về 2..14
        r_int: Optional[int] = None
        if r is None:
            # Fallback theo chuẩn engine: rank_index (0..12) => 2..14
            ri0 = getattr(c, "rank_index", None)
            if ri0 is not None:
                try:
                    r_int = int(ri0) + 2
                except Exception:
                    r_int = None
        else:
            if isinstance(r, str):
                mp = {
                    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
                    "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
                }
                r_int = mp.get(r.upper(), None)
            else:
                try:
                    r_int = int(r)
                except Exception:
                    r_int = None

        s_str = str(s) if s is not None else None
        return r_int, s_str

    except Exception:
        try:
            t = str(code).strip()
            if len(t) >= 2:
                rk = t[0].upper()
                st = t[1].upper()
                mp = {
                    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
                    "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
                }
                return mp.get(rk, None), st
        except Exception:
            pass
        return None, None


def _can_make_3_flushes_5_5_3(suit_counts: Dict[str, int]) -> bool:
    """Whether 13 cards can be split into 5/5/3 where each hand is a flush (suits may repeat)."""
    suits = list(suit_counts.keys())
    if not suits:
        return False
    need = [5, 5, 3]
    for a in range(len(suits)):
        for b in range(len(suits)):
            for c in range(len(suits)):
                use = {s: 0 for s in suits}
                use[suits[a]] += need[0]
                use[suits[b]] += need[1]
                use[suits[c]] += need[2]
                if all(use[s] <= suit_counts.get(s, 0) for s in suits):
                    return True
    return False


def _all_straights_of_len(ranks_multiset: Dict[int, int], L: int) -> List[List[int]]:
    """Generate all rank sequences of length L that exist in the multiset.

    Supports A-low for L in {5,3} (A2345 / A23).
    """
    seqs: List[List[int]] = []

    for st in range(2, 15):  # 2..14
        seq = [st + i for i in range(L)]
        if seq[-1] > 14:
            continue

        need: Dict[int, int] = {}
        ok = True
        for r in seq:
            need[r] = need.get(r, 0) + 1
        for r, cnt in need.items():
            if ranks_multiset.get(r, 0) < cnt:
                ok = False
                break
        if ok:
            seqs.append(seq)

    if L in (5, 3):
        low = [14] + list(range(2, 2 + (L - 1)))  # A,2,3,4,5 or A,2,3
        need = {}
        ok = True
        for r in low:
            need[r] = need.get(r, 0) + 1
        for r, cnt in need.items():
            if ranks_multiset.get(r, 0) < cnt:
                ok = False
                break
        if ok:
            seqs.append(low)

    return seqs


def _can_make_3_straights_5_5_3(ranks_multiset: Dict[int, int]) -> bool:
    """Whether 13 cards can be split into 5/5/3 where each hand is a straight (using multiset subtraction)."""
    s3 = _all_straights_of_len(ranks_multiset, 3)
    if not s3:
        return False
    s5 = _all_straights_of_len(ranks_multiset, 5)
    if len(s5) < 2:
        return False

    def sub(ms: Dict[int, int], seq: List[int]) -> Optional[Dict[int, int]]:
        out = dict(ms)
        for r in seq:
            if out.get(r, 0) <= 0:
                return None
            out[r] -= 1
        return out

    for a in s5:
        ms1 = sub(ranks_multiset, a)
        if ms1 is None:
            continue
        for b in s5:
            ms2 = sub(ms1, b)
            if ms2 is None:
                continue
            for c in s3:
                ms3 = sub(ms2, c)
                if ms3 is not None:
                    return True
    return False


def detect_special_13(codes13: List[str]) -> Optional[Tuple[str, int]]:
    """Detect special 13-card hands (Bài đặc biệt).

    Return (name, chi_points) or None.

    Priority:
    - Sảnh rồng đồng hoa
    - Sảnh rồng
    - Đồng hoa
    - 5 đôi 1 xám
    - 6 đôi / 3 sảnh / 3 thùng
    """
    if not codes13 or len(codes13) != 13:
        return None

    ranks_ms: Dict[int, int] = {}
    suit_counts: Dict[str, int] = {}
    suits: List[str] = []

    for cd in codes13:
        r, s = _card_rank_suit(cd)
        if r is None or s is None:
            return None
        ranks_ms[int(r)] = ranks_ms.get(int(r), 0) + 1
        suit_counts[str(s)] = suit_counts.get(str(s), 0) + 1
        suits.append(str(s))

    is_all_same_suit = (len(set(suits)) == 1)
    is_dragon = (len(ranks_ms) == 13 and all(ranks_ms.get(x, 0) == 1 for x in range(2, 15)))

    if is_dragon and is_all_same_suit:
        return ("Sảnh rồng đồng hoa", 100)
    if is_dragon:
        return ("Sảnh rồng", 50)
    if is_all_same_suit:
        return ("Đồng hoa", 30)

    pairs = sum(1 for _, c in ranks_ms.items() if c == 2)
    trips = sum(1 for _, c in ranks_ms.items() if c == 3)

    # RẼ NHANH: tứ quý (4 lá) = 2 đôi
    pair_units = sum(c // 2 for c in ranks_ms.values())

    if pairs == 5 and trips == 1:
        return ("5 đôi 1 xám", 10)

    # 6 đôi = tổng đơn vị đôi == 6, KHÔNG có xám
    if trips == 0 and pair_units == 6:
        return ("6 đôi", 8)


    if _can_make_3_flushes_5_5_3(suit_counts):
        return ("3 thùng", 8)

    if _can_make_3_straights_5_5_3(ranks_ms):
        return ("3 sảnh", 8)

    return None
# =========================
# BUILD SPLIT FOR SPECIAL13
# =========================

def _sort_cards_high(cards: List[Card]) -> List[Card]:
    def rk(c: Card) -> int:
        r = getattr(c, "rank", None) or getattr(c, "r", None) or getattr(c, "value", None) or 0
        try:
            return int(r)
        except Exception:
            # Fallback rank string
            mp = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
                  "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
            v = mp.get(str(r).upper(), None)
            if v is not None:
                return int(v)

            # Fallback theo chuẩn engine: rank_index (0..12) => 2..14
            ri0 = getattr(c, "rank_index", None)
            if ri0 is not None:
                try:
                    return int(ri0) + 2
                except Exception:
                    pass

            return 0

    return sorted(list(cards), key=rk, reverse=True)

def _rank_int(c: Card) -> Optional[int]:
    r = getattr(c, "rank", None) or getattr(c, "r", None) or getattr(c, "value", None)

    if r is None:
        ri0 = getattr(c, "rank_index", None)
        if ri0 is None:
            return None
        try:
            return int(ri0) + 2
        except Exception:
            return None

    if isinstance(r, str):
        mp = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
              "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
        return mp.get(r.upper(), None)

    try:
        return int(r)
    except Exception:
        return None

def _take_rank(pool_by_rank: Dict[int, List[Card]], r: int) -> Optional[Card]:
    lst = pool_by_rank.get(r) or []
    if not lst:
        return None
    return lst.pop()


def _build_dragon_split(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    # Dragon: ranks 2..A unique. Dựng 5-5-3 thành 2 sảnh 5 + 1 sảnh 3 để “ăn chắc” kích hoạt.
    # chi1 (dưới) mạnh nhất: A K Q J T
    # chi2 (giữa): 9 8 7 6 5
    # chi3 (trên 3 lá): 4 3 2 (coi như sảnh 3)
    pool: Dict[int, List[Card]] = {}
    for c in cards:
        ri = _rank_int(c)
        if ri is None:
            return None
        pool.setdefault(ri, []).append(c)

    seq1 = [14, 13, 12, 11, 10]
    seq2 = [9, 8, 7, 6, 5]
    seq3 = [4, 3, 2]

    c1: List[Card] = []
    c2: List[Card] = []
    c3: List[Card] = []

    for r in seq1:
        x = _take_rank(pool, r)
        if not x: return None
        c1.append(x)
    for r in seq2:
        x = _take_rank(pool, r)
        if not x: return None
        c2.append(x)
    for r in seq3:
        x = _take_rank(pool, r)
        if not x: return None
        c3.append(x)

    if len(c1) == 5 and len(c2) == 5 and len(c3) == 3:
        return (c1, c2, c3)
    return None


def _build_all_same_suit_split(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    # Đồng hoa / Sảnh rồng đồng hoa: 13 lá cùng suit -> chia 5-5-3 theo rank (dưới mạnh nhất)
    s = {getattr(c, "suit", None) or getattr(c, "s", None) for c in cards}
    if len(s) != 1:
        return None
    cs = _sort_cards_high(cards)
    return (cs[:5], cs[5:10], cs[10:13])


def _build_three_flushes_split(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    # 3 thùng: tồn tại cách chia 5-5-3 đều flush (3 lá cũng cùng suit)
    by_suit: Dict[str, List[Card]] = {}
    for c in cards:
        su = getattr(c, "suit", None) or getattr(c, "s", None)
        if su is None:
            return None
        by_suit.setdefault(str(su), []).append(c)

    for k in list(by_suit.keys()):
        by_suit[k] = _sort_cards_high(by_suit[k])

    suits = list(by_suit.keys())
    need = [5, 5, 3]

    # thử mọi tổ hợp suit (có thể trùng) như detect của bạn
    for a in suits:
        for b in suits:
            for c in suits:
                if len(by_suit[a]) < need[0] or len(by_suit[b]) < need[1] or len(by_suit[c]) < need[2]:
                    continue

                used = set()
                chi1 = []
                for x in by_suit[a]:
                    if id(x) in used: continue
                    chi1.append(x); used.add(id(x))
                    if len(chi1) == 5: break
                if len(chi1) != 5: continue

                chi2 = []
                for x in by_suit[b]:
                    if id(x) in used: continue
                    chi2.append(x); used.add(id(x))
                    if len(chi2) == 5: break
                if len(chi2) != 5: continue

                chi3 = []
                for x in by_suit[c]:
                    if id(x) in used: continue
                    chi3.append(x); used.add(id(x))
                    if len(chi3) == 3: break
                if len(chi3) != 3: continue

                return (chi1, chi2, chi3)

    return None


def _build_three_straights_split(cards: List[Card]) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    # 3 sảnh: tồn tại 5-5-3 đều là sảnh theo định nghĩa multiset rank của detect
    pool_by_rank: Dict[int, List[Card]] = {}
    ranks_ms: Dict[int, int] = {}
    for c in cards:
        r = getattr(c, "rank", None) or getattr(c, "r", None) or getattr(c, "value", None)

        ri: Optional[int] = None
        if r is None:
            ri0 = getattr(c, "rank_index", None)
            if ri0 is None:
                return None
            try:
                ri = int(ri0) + 2
            except Exception:
                return None
        else:
            if isinstance(r, str):
                mp = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
                      "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
                ri = mp.get(r.upper(), None)
                if ri is None:
                    return None
            else:
                try:
                    ri = int(r)
                except Exception:
                    return None

        pool_by_rank.setdefault(ri, []).append(c)
        ranks_ms[ri] = ranks_ms.get(ri, 0) + 1

    # để lấy bài ổn định, sort mỗi rank theo suit/ẩn danh không quan trọng
    for r in pool_by_rank:
        pool_by_rank[r] = list(pool_by_rank[r])

    s3 = _all_straights_of_len(ranks_ms, 3)
    s5 = _all_straights_of_len(ranks_ms, 5)
    if not s3 or len(s5) < 2:
        return None

    def sub(ms: Dict[int, int], seq: List[int]) -> Optional[Dict[int, int]]:
        out = dict(ms)
        for rr in seq:
            if out.get(rr, 0) <= 0:
                return None
            out[rr] -= 1
        return out

    # try build: pick 2 straights len5 + 1 straight len3 (ưu tiên sảnh cao trước)
    s5_sorted = sorted(s5, key=lambda seq: max(seq), reverse=True)
    s3_sorted = sorted(s3, key=lambda seq: max(seq), reverse=True)

    for a in s5_sorted:
        ms1 = sub(ranks_ms, a)
        if ms1 is None: continue
        for b in s5_sorted:
            ms2 = sub(ms1, b)
            if ms2 is None: continue
            for cseq in s3_sorted:
                ms3 = sub(ms2, cseq)
                if ms3 is None:
                    continue

                # dựng cards thật từ pool_by_rank (copy pool)
                tmp = {k: list(v) for k, v in pool_by_rank.items()}

                def take_seq(seq: List[int]) -> Optional[List[Card]]:
                    out: List[Card] = []
                    for rr in seq:
                        x = _take_rank(tmp, rr)
                        if not x:
                            return None
                        out.append(x)
                    return out

                chi1 = take_seq(a)
                if not chi1: continue
                chi2 = take_seq(b)
                if not chi2: continue
                chi3 = take_seq(cseq)
                if not chi3: continue

                if len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3:
                    return (chi1, chi2, chi3)

    return None


def _build_pairs_trips_split(cards: List[Card], *, need_pairs: int, need_trips: int) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    # Dựng split "an toàn" để kích hoạt special (6 đôi / 5 đôi 1 xám):
    # - chi1: 2 đôi lớn + 1 rác lớn
    # - chi2: 2 đôi tiếp + 1 rác tiếp
    # - chi3: đôi còn lại + 1 rác lớn (3 lá)
    by_rank: Dict[int, List[Card]] = {}
    for c in cards:
        ri = _rank_int(c)
        if ri is None:
            return None
        by_rank.setdefault(ri, []).append(c)

    pairs_r = sorted([r for r, lst in by_rank.items() if len(lst) == 2], reverse=True)
    trips_r = sorted([r for r, lst in by_rank.items() if len(lst) == 3], reverse=True)
    quads_r = sorted([r for r, lst in by_rank.items() if len(lst) == 4], reverse=True)

    # case chuẩn (giữ nguyên)
    if len(pairs_r) == need_pairs and len(trips_r) == need_trips:
        expanded_pairs_r = list(pairs_r)

    # RẼ NHANH: 6 đôi = 4 đôi + 1 tứ quý
    elif (
        need_pairs == 6
        and need_trips == 0
        and len(pairs_r) == 4
        and len(trips_r) == 0
        and len(quads_r) == 1
    ):
        # tứ quý xuất hiện 2 lần = 2 đôi
        expanded_pairs_r = sorted(
            pairs_r + [quads_r[0], quads_r[0]],
            reverse=True
        )

    else:
        return None


    # pool copy
    pool = {r: list(lst) for r, lst in by_rank.items()}

    def take_n(r: int, n: int) -> Optional[List[Card]]:
        lst = pool.get(r) or []
        if len(lst) < n:
            return None
        out = lst[:n]
        pool[r] = lst[n:]
        return out

    # collect singles from remaining
    def pop_best_single(exclude_ranks: set) -> Optional[Card]:
        singles: List[Card] = []
        for r, lst in pool.items():
            if r in exclude_ranks:
                continue
            for c in lst:
                singles.append(c)
        if not singles:
            return None
        singles = _sort_cards_high(singles)
        x = singles[0]
        # remove x from pool
        xr = _rank_int(x)
        if xr is None:
            return None
        pool[xr].remove(x)

        return x

    # build
    chi1: List[Card] = []
    chi2: List[Card] = []
    chi3: List[Card] = []

    # chi1: 2 pair highest
    for r in expanded_pairs_r[:2]:
        got = take_n(r, 2)
        if not got: return None
        chi1 += got
    k1 = pop_best_single(set(expanded_pairs_r) | set(trips_r))
    if not k1: return None
    chi1.append(k1)

    # chi2: next 2 pairs
    for r in expanded_pairs_r[2:4]:
        got = take_n(r, 2)
        if not got: return None
        chi2 += got
    k2 = pop_best_single(set(expanded_pairs_r) | set(trips_r))
    if not k2: return None
    chi2.append(k2)

    # chi3: remaining pair (and trip if any -> lấy 2 lá bất kỳ làm đôi để vẫn “khớp” special logic 13 lá)
    remain_pairs = expanded_pairs_r[4:]
    if remain_pairs:
        r = remain_pairs[0]
        got = take_n(r, 2)
        if not got: return None
        chi3 += got
    elif trips_r:
        # 5 đôi 1 xám: còn 1 trips, lấy 2 lá làm "đôi" (3 lá chi3 không nhất thiết phải đôi, nhưng xếp vậy dễ hợp lệ)
        r = trips_r[0]
        got = take_n(r, 2)
        if not got: return None
        chi3 += got
    else:
        return None

    k3 = pop_best_single(set(expanded_pairs_r) | set(trips_r))
    if not k3: return None
    chi3.append(k3)

    if len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3:
        return (chi1, chi2, chi3)
    return None


def build_special_split(cards13: List[Card], special_name: str) -> Optional[Tuple[List[Card], List[Card], List[Card]]]:
    """
    Build a concrete 5-5-3 split to APPLY so that the UI can click the special row
    and the table will recognize the special 13-card hand.

    Input:
      - cards13: List[Card] length 13
      - special_name: name returned by detect_special_13()

    Output: (chi1, chi2, chi3) or None
    """
    if not cards13 or len(cards13) != 13:
        return None

    name = (special_name or "").strip().lower()

    if "sảnh rồng" in name:
        # handles both "sảnh rồng" and "sảnh rồng đồng hoa"
        sp = _build_dragon_split(cards13)
        if sp:
            return sp
        # fallback nếu không dựng được: chia theo rank
        return (_sort_cards_high(cards13)[:5], _sort_cards_high(cards13)[5:10], _sort_cards_high(cards13)[10:13])

    if "đồng hoa" in name:
        sp = _build_all_same_suit_split(cards13)
        if sp:
            return sp
        return (_sort_cards_high(cards13)[:5], _sort_cards_high(cards13)[5:10], _sort_cards_high(cards13)[10:13])

    if "3 thùng" in name:
        return _build_three_flushes_split(cards13)

    if "3 sảnh" in name:
        return _build_three_straights_split(cards13)

    if "6 đôi" in name:
        return _build_pairs_trips_split(cards13, need_pairs=6, need_trips=0)

    if "5 đôi 1 xám" in name:
        return _build_pairs_trips_split(cards13, need_pairs=5, need_trips=1)

    return None
