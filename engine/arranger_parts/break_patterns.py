from __future__ import annotations

from typing import List, Tuple, Optional, Any, Dict, Iterable, TYPE_CHECKING
from collections import Counter, defaultdict
from itertools import combinations, permutations

from engine.card import Card
from engine.arranger_parts.eval_utils import _rank_val
from engine.arranger_parts.splits import _validate_no_foul
from engine.arranger_parts.beauty_laws import _normalize_kicker_distribution

if TYPE_CHECKING:
    # Tránh vòng lặp import ở runtime – chỉ dùng cho type hint
    from engine.arranger_parts.arrange import HandProfile

ThreeChi = Tuple[List[Card], List[Card], List[Card]]
Rank = str
Suit = str


def _card_codes(cards: Iterable[Card]) -> Tuple[str, ...]:
    """
    Trả về tuple code ổn định cho 1 tập lá – dùng để dedup.
    Dùng to_code() để thống nhất với toàn bộ engine.
    """
    return tuple(sorted(c.to_code() for c in cards))


def _split_signature(chi1: List[Card], chi2: List[Card], chi3: List[Card]) -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]:
    """
    Signature theo từng chi (chi1, chi2, chi3).
    Dùng để tránh trùng đúng 1 thế bẻ cụ thể (3 chi giống hệt nhau),
    nhưng vẫn cho phép nhiều cách bẻ khác nhau trên cùng 13 lá.
    """
    sig1 = _card_codes(chi1)
    sig2 = _card_codes(chi2)
    sig3 = _card_codes(chi3)
    return sig1, sig2, sig3
    
def _is_high_card_5(hand: List[Card]) -> bool:
    # Mậu thầu 5 lá: không đôi/xám/cù/tứ quý, không thùng, không sảnh
    if len(hand) != 5:
        return False

    # rank values
    vals = sorted((_rank_val(c.rank) for c in hand), reverse=True)
    # nếu có trùng rank => không phải mậu thầu
    if len(set(vals)) != 5:
        return False

    # flush?
    if len({c.suit for c in hand}) == 1:
        return False

    # straight? (có xử lý wheel A2345)
    vals2 = sorted(set(vals))
    # wheel A2345: {14,5,4,3,2}
    if set(vals2) == {14, 5, 4, 3, 2}:
        return False
    if max(vals2) - min(vals2) == 4 and len(vals2) == 5:
        return False

    return True

def _append_variant(out, seen, chi1, chi2, chi3):
    if len(chi1) != 5 or len(chi2) != 5 or len(chi3) != 3:
        return

    chi1, chi2, chi3 = _normalize_kicker_distribution(list(chi1), list(chi2), list(chi3))

    # Chỉ loại trường hợp quá rác: cả chi1 và chi2 đều mậu thầu 5 lá.
    if _is_high_card_5(chi1) and _is_high_card_5(chi2):
        return

    if not _validate_no_foul(chi1, chi2, chi3):
        return

    sig = _split_signature(chi1, chi2, chi3)
    if sig in seen:
        return
    seen.add(sig)
    out.append((list(chi1), list(chi2), list(chi3)))

# ---------------------------------------------------------------------------
# Helpers dùng chung để phân tích cấu trúc 13 lá
# ---------------------------------------------------------------------------

def _build_simple_profile(cards: List[Card]) -> Dict[str, Any]:
    """
    Profile đơn giản để phục vụ break-pattern, không phụ thuộc HandProfile.
    """
    rank_cnt: Counter = Counter(c.rank for c in cards)
    suit_cnt: Counter = Counter(c.suit for c in cards)

    rank_to_cards: Dict[Rank, List[Card]] = defaultdict(list)
    for c in cards:
        rank_to_cards[c.rank].append(c)

    quads: List[List[Card]] = []
    trips: List[List[Card]] = []
    pairs: List[List[Card]] = []
    singles: List[Card] = []

    for r, n in rank_cnt.items():
        group = sorted(rank_to_cards[r], key=lambda c: _rank_val(c.rank), reverse=True)
        if n >= 4:
            quads.append(group[:4])
            if n == 5:
                singles.append(group[4])
        elif n == 3:
            trips.append(group)
        elif n == 2:
            pairs.append(group)
        else:
            singles.append(group[0])

    suit_groups: Dict[Suit, List[Card]] = defaultdict(list)
    for c in cards:
        suit_groups[c.suit].append(c)
    flush_suits = [s for s, grp in suit_groups.items() if len(grp) >= 5]

    # tạm thời: dải rank liên tiếp đơn giản – không phân biệt A2345/A2345K đặc biệt,
    # việc này BEAUTY đã xử lý ở chỗ khác.
    rank_order = "23456789TJQKA"
    have_rank = {c.rank for c in cards}
    straight_segments: List[List[Rank]] = []
    cur: List[Rank] = []
    for ch in rank_order:
        if ch in have_rank:
            cur.append(ch)
        else:
            if len(cur) >= 5:
                straight_segments.append(cur[:])
            cur = []
    if len(cur) >= 5:
        straight_segments.append(cur[:])

    return {
        "quads": quads,
        "trips": trips,
        "pairs": pairs,
        "singles": singles,
        "suit_groups": suit_groups,
        "flush_suits": flush_suits,
        "straight_segments": straight_segments,
    }

def _build_rank_map(cards: List[Card]) -> Dict[Rank, List[Card]]:
    """
    Map rank -> list Card, sort giảm dần theo rank để ưu tiên lá mạnh.
    """
    rank_map: Dict[Rank, List[Card]] = defaultdict(list)
    for c in cards:
        rank_map[c.rank].append(c)
    for r in rank_map:
        rank_map[r].sort(key=lambda c: _rank_val(c.rank), reverse=True)
    return rank_map


def _pick_combo_from_ranks(
    ranks: List[Rank],
    rank_map: Dict[Rank, List[Card]],
    used_ids: Optional[set] = None,
) -> Optional[List[Card]]:
    """
    Từ 1 list rank (liên tiếp), chọn mỗi rank 1 lá, tránh trùng với used_ids.
    Nếu không pick đủ thì trả về None.
    """
    if used_ids is None:
        used_ids = set()
    res: List[Card] = []
    for r in ranks:
        if r not in rank_map:
            return None
        chosen: Optional[Card] = None
        for c in rank_map[r]:
            if id(c) not in used_ids:
                chosen = c
                break
        if chosen is None:
            return None
        used_ids.add(id(chosen))
        res.append(chosen)
    return res

# ---------------------------------------------------------------------------
# Nhóm 1: Bẻ từ cấu trúc QUAD / FULL HOUSE (Cù)
# ---------------------------------------------------------------------------
def _generate_break_from_quads(cards: List[Card], profile: Dict[str, Any]) -> List[ThreeChi]:
    """
    Các thế bẻ khi bài có TỨ QUÝ:
      - Tứ quý -> 2 ĐÔI phân bố cho chi1/chi2/chi3.
      - Tứ quý -> XÁM + MẬU THẦU, đẩy lá lẻ sang chi khác.
    """
    out: List[ThreeChi] = []
    seen: set = set()

    quads: List[List[Card]] = profile["quads"]
    if not quads:
        return out

    others: List[Card] = cards[:]
    # thử từng tứ quý một
    for quad in quads:
        if len(quad) < 4:
            continue
        # remove 4 lá tứ quý tạm thời
        tmp_others = [c for c in others if c not in quad]
        if len(tmp_others) != 9:
            continue

        # --- Kiểu 1: tứ quý -> 2 đôi (2+2) ---
        a, b, c, d = quad  # đã sort theo value giảm dần
        # đôi lớn + đôi nhỏ
        pair_big = [a, b]
        pair_small = [c, d]

        # ý tưởng: dùng đôi lớn cho chi2, đôi nhỏ cho chi3, hoặc ngược lại.
        # ta sẽ gán:
        #   chi1: lấy 5 lá mạnh nhất còn lại
        #   chi2: pair_big + 3 lá bất kỳ
        #   chi3: pair_small + 1 lá bất kỳ
        other_sorted = sorted(tmp_others, key=lambda x: _rank_val(x.rank), reverse=True)

        # để tránh bùng
        # phương án 1: chi2 = big, chi3 = small
        if len(other_sorted) >= 5:
            base_chi1 = other_sorted[:5]
            remain = other_sorted[5:]  # 4 lá
            if len(remain) >= 4:
                # chi2: big + 3 lá
                for comb3 in combinations(remain, 3):
                    used3 = set(id(x) for x in comb3)
                    chi2 = pair_big + list(comb3)
                    # chi3: small + 1 lá còn lại
                    remain_for_chi3 = [x for x in remain if id(x) not in used3]
                    if len(remain_for_chi3) >= 1:
                        chi3 = pair_small + [remain_for_chi3[0]]
                        _append_variant(out, seen, base_chi1, chi2, chi3)

                # phương án 2: chi2 = small, chi3 = big (đổi vai)
                for comb3 in combinations(remain, 3):
                    used3 = set(id(x) for x in comb3)
                    chi2 = pair_small + list(comb3)
                    remain_for_chi3 = [x for x in remain if id(x) not in used3]
                    if len(remain_for_chi3) >= 1:
                        chi3 = pair_big + [remain_for_chi3[0]]
                        _append_variant(out, seen, base_chi1, chi2, chi3)

        # --- Kiểu 2: tứ quý -> xám + (chi3 mậu thầu hoặc đôi nếu tình cờ có) ---
        # xám: 3 lá lớn nhất của tứ quý
        trips = quad[:3]
        kicker = quad[3]

        # FIX: pool còn lại phải loại TOÀN BỘ 4 lá tứ quý khỏi 13 lá,
        # nếu không sẽ bị trùng lá giữa các chi hoặc bị loại bởi validate/dedup.
        quad_ids = {id(c) for c in quad}
        tmp_others2 = [c for c in cards if id(c) not in quad_ids]
        if len(tmp_others2) != 9:
            continue

        other_sorted2 = sorted(tmp_others2, key=lambda x: _rank_val(x.rank), reverse=True)
        base_chi1 = other_sorted2[:5]
        rem = other_sorted2[5:]
        # rem lúc này phải còn đúng 4 lá để cấp cho chi2 (2 lá) và chi3 (2 lá)
        if len(base_chi1) == 5 and len(rem) == 4:
            chi2 = trips + rem[:2]          # 3 + 2
            chi3 = [kicker] + rem[2:4]      # 1 + 2
            _append_variant(out, seen, base_chi1, chi2, chi3)

    return out

def _generate_break_from_fullhouses(cards: List[Card], profile: Dict[str, Any]) -> List[ThreeChi]:
    """
    Các thế bẻ khi có CÙ (Full House = 3+2) / nhiều TRIPS:
      - Sinh đúng nghĩa các fullhouse candidates (trip + pair).
      - Sinh các template:
          + Cù ở chi1
          + Cù ở chi2
          + 2 Cù (nếu tạo được 2 fullhouse không trùng lá)
          + Cù + Thú (nếu phần còn lại có >= 2 đôi)
          + Cù + Xám + Đôi (nếu phần còn lại có trip + pair)
    """
    out: List[ThreeChi] = []
    seen: set = set()

    trips: List[List[Card]] = profile["trips"]
    pairs: List[List[Card]] = profile["pairs"]

    if not trips:
        return out

    # -----------------------------
    # Helper: gom tất cả "pair candidates"
    # - pair thật từ profile["pairs"]
    # - pair "cắt từ trip khác" (2 lá đầu của trip)
    # -----------------------------
    def _pair_candidates(except_trip: List[Card]) -> List[List[Card]]:
        cand: List[List[Card]] = []
        # pair thật
        for p in pairs:
            if len(p) >= 2:
                cand.append(p[:2])

        # pair cắt từ trip khác
        for t in trips:
            if t is except_trip:
                continue
            if len(t) >= 3:
                cand.append(t[:2])

        # dedup theo code (tránh trùng candidate do trùng nguồn)
        seen_sig = set()
        uniq: List[List[Card]] = []
        for p2 in cand:
            sig = _card_codes(p2)
            if sig in seen_sig:
                continue
            seen_sig.add(sig)
            uniq.append(p2)
        return uniq

    # -----------------------------
    # 1) Build toàn bộ fullhouse candidates (FH = trip(3) + pair(2))
    #    Lưu kèm trip_used/pair_used để còn sinh biến thể.
    # -----------------------------
    fh_candidates: List[Tuple[List[Card], List[Card], List[Card]]] = []  # (fh5, trip3, pair2)

    for t in trips:
        # lấy các pair candidate (pair thật + pair cắt từ trip khác)
        for p2 in _pair_candidates(t):
            used_ids = set(id(c) for c in t)
            # đảm bảo pair không trùng lá với trip
            if any(id(c) in used_ids for c in p2):
                continue
            fh = list(t) + list(p2)  # đúng nghĩa Cù = 3 + 2
            if len(fh) != 5:
                continue
            fh_candidates.append((fh, list(t), list(p2)))

    if not fh_candidates:
        return out

    # -----------------------------
    # 2) Sinh template cơ bản: Cù ở chi1 / Cù ở chi2
    # -----------------------------
    for fh, trip_used, pair_used in fh_candidates:
        used = set(id(c) for c in fh)
        rem_cards = [c for c in cards if id(c) not in used]
        if len(rem_cards) != 8:
            continue

        rem_sorted = sorted(rem_cards, key=lambda c: _rank_val(c.rank), reverse=True)

        # (FH-1) chi1 = Cù
        chi1 = list(fh)
        chi2 = rem_sorted[:5]
        chi3 = rem_sorted[5:8]
        _append_variant(out, seen, chi1, chi2, chi3)

        # (FH-2) chi2 = Cù
        chi1b = rem_sorted[:5]
        chi2b = list(fh)
        chi3b = rem_sorted[5:8]
        _append_variant(out, seen, chi1b, chi2b, chi3b)

        # -----------------------------
        # 3) Biến thể: "Bẻ Cù -> Xám + Đôi"
        #    (Giữ lại ý tưởng Pattern C3 của bạn, nhưng bám theo FH đúng nghĩa)
        #    - chi2: trip + 2 rác
        #    - chi3: pair + 1 rác
        #    - chi1: 5 lá mạnh nhất còn lại
        # -----------------------------
        # rem_sorted có 8 lá. Ta dùng 5 lá mạnh làm chi1 trước.
        base_chi1 = rem_sorted[:5]
        pool = rem_sorted[5:]  # còn 3 lá

        if len(pool) >= 3:
            # chi2: trip_used (3) + 2 lá từ pool
            chi2c = list(trip_used) + pool[:2]
            # chi3: pair_used (2) + 1 lá còn lại
            chi3c = list(pair_used) + pool[2:3]
            _append_variant(out, seen, base_chi1, chi2c, chi3c)

        # -----------------------------
        # 4) Biến thể: Cù + Thú (nếu phần còn lại có >= 2 đôi)
        #    - chiX: Cù
        #    - chiY: Thú (2 đôi + 1 kicker)
        #    - chi3: 3 lá còn lại
        # -----------------------------
        rem_profile = _build_simple_profile(rem_cards)
        rem_pairs: List[List[Card]] = rem_profile["pairs"]
        if len(rem_pairs) >= 2:
            p1 = rem_pairs[0][:2]
            p2 = rem_pairs[1][:2]

            used2 = set(id(c) for c in fh)
            used2.update(id(c) for c in p1)
            used2.update(id(c) for c in p2)

            # cần 1 kicker để đủ 5 lá cho Thú
            kickers = [c for c in cards if id(c) not in used2]
            kickers_sorted = sorted(kickers, key=lambda c: _rank_val(c.rank), reverse=True)
            if len(kickers_sorted) >= 1:
                beast = list(p1) + list(p2) + [kickers_sorted[0]]

                used3 = set(id(c) for c in fh + beast)
                rem3 = [c for c in cards if id(c) not in used3]
                if len(beast) == 5 and len(rem3) == 3:
                    # Cù ở chi1, Thú ở chi2
                    _append_variant(out, seen, list(fh), beast, rem3)
                    # Thú ở chi1, Cù ở chi2
                    _append_variant(out, seen, beast, list(fh), rem3)

    # -----------------------------
    # 5) Sinh 2 Cù (2 fullhouse không trùng lá)
    #    Chỉ khi có đủ cấu trúc thật sự (disjoint 5+5 để còn 3 lá).
    # -----------------------------
    for a in range(len(fh_candidates)):
        fhA, _, _ = fh_candidates[a]
        usedA = set(id(c) for c in fhA)
        for b in range(a + 1, len(fh_candidates)):
            fhB, _, _ = fh_candidates[b]
            usedB = set(id(c) for c in fhB)
            if usedA & usedB:
                continue

            used = usedA | usedB
            rem = [c for c in cards if id(c) not in used]
            if len(rem) != 3:
                continue

            # 2 cấu hình: đổi vị trí chi1/chi2
            _append_variant(out, seen, list(fhA), list(fhB), rem)
            _append_variant(out, seen, list(fhB), list(fhA), rem)

    return out
# ---------------------------------------------------------------------------
# Nhóm 2: Bẻ từ cấu trúc THÙNG / SẢNH
# ---------------------------------------------------------------------------
def _find_flush_combos(suit_group: List[Card], min_len: int = 5) -> List[List[Card]]:
    """
    Tìm một vài combination thùng từ group cùng chất.
    Mục tiêu: sinh nhiều combo hơn khi >5 lá để có cơ hội "giữ lại" đôi/xám bên ngoài.
    Vẫn giới hạn để tránh bùng nổ.
    """
    sorted_grp = sorted(suit_group, key=lambda c: _rank_val(c.rank), reverse=True)
    if len(sorted_grp) < min_len:
        return []

    combos: List[List[Card]] = []

    # Base: top-5
    combos.append(sorted_grp[:5])

    # Nếu dài hơn: tạo thêm vài biến thể bỏ 1 lá trong top để lấy 1 lá thấp hơn
    # (giữ lại một số rank ngoài flush để tạo đôi/xám)
    if len(sorted_grp) >= 6:
        combos.append(sorted_grp[1:6])  # bỏ lá mạnh nhất
        combos.append([sorted_grp[0]] + sorted_grp[2:6])  # bỏ lá #2

    if len(sorted_grp) >= 7:
        combos.append([sorted_grp[0], sorted_grp[1]] + sorted_grp[3:6])  # bỏ #3
        combos.append([sorted_grp[0]] + sorted_grp[3:7])  # giữ A, kéo 4 lá sau

    # Nếu rất dài, thêm 1–2 combo “cắt giữa”
    if len(sorted_grp) >= 8:
        combos.append([sorted_grp[0]] + sorted_grp[4:8])
        combos.append(sorted_grp[2:7])

    # Dedup theo code
    seen_codes = set()
    uniq: List[List[Card]] = []
    for g in combos:
        if len(g) != 5:
            continue
        sig = _card_codes(g)
        if sig in seen_codes:
            continue
        seen_codes.add(sig)
        uniq.append(g)
    return uniq

def _generate_break_from_flush_and_pairs(cards: List[Card], profile: Dict[str, Any]) -> List[ThreeChi]:
    """
    Bẻ theo THÙNG (Flush) kết hợp với đôi/xám/thú.

    Mục tiêu: sinh đủ family để beauty_flow chọn, không cố tối ưu tuyệt đối.
    """
    out: List[ThreeChi] = []
    seen: set = set()

    flush_suits = profile["flush_suits"]
    if not flush_suits:
        return out

    # build map suit -> cards sorted
    suit_map: Dict[Any, List[Card]] = defaultdict(list)
    for c in cards:
        suit_map[c.suit].append(c)
    for s in suit_map:
        suit_map[s] = sorted(suit_map[s], key=lambda x: _rank_val(x.rank), reverse=True)

    def _sorted_cards(cs: List[Card]) -> List[Card]:
        return sorted(cs, key=lambda x: _rank_val(x.rank), reverse=True)

    # Sinh candidate flush5 (có thử hoán đổi để cứu đôi/xám – nhẹ, tránh nổ)
    flush_choices: List[List[Card]] = []
    for s in flush_suits:
        grp = suit_map.get(s, [])
        if len(grp) < 5:
            continue
        top = grp[:5]
        flush_choices.append(list(top))

        # nếu có dư, thử thay 1 lá trong top5 bằng lá dư để cứu đôi/xám
        tail = grp[5:]
        if tail:
            for drop_idx in range(min(2, len(top))):
                alt = list(top)
                alt[drop_idx] = tail[0]
                alt = _sorted_cards(alt)
                flush_choices.append(alt)

    # dedup theo code
    seen_fc = set()
    uniq_flush_choices: List[List[Card]] = []
    for f5 in flush_choices:
        sig = _card_codes(f5)
        if sig in seen_fc:
            continue
        seen_fc.add(sig)
        uniq_flush_choices.append(f5)

    # cap để tránh nổ
    uniq_flush_choices = uniq_flush_choices[:10]

    for flush in uniq_flush_choices:
        used_flush = set(id(c) for c in flush)
        rem_cards = [c for c in cards if id(c) not in used_flush]
        if len(rem_cards) != 8:
            continue

        rem_profile = _build_simple_profile(rem_cards)
        rem_trips: List[List[Card]] = rem_profile["trips"]
        rem_pairs: List[List[Card]] = rem_profile["pairs"]
        rem_sorted = _sorted_cards(rem_cards)

        # =========================
        # (A) Flush ở chi1
        # =========================

        # A1: Flush + Xám(5) + Đôi(3)
        if rem_trips and rem_pairs:
            t = rem_trips[0][:3]
            p = rem_pairs[0][:2]
            used_tp = set(id(c) for c in t + p)
            others = [c for c in rem_cards if id(c) not in used_tp]
            others = _sorted_cards(others)
            if len(others) >= 3:
                chi1 = list(flush)
                chi2 = list(t) + others[:2]
                chi3 = list(p) + [others[2]]
                _append_variant(out, seen, chi1, chi2, chi3)

        # A2: Flush + Xám(5) + 3 lá (khi có xám)
        if rem_trips:
            t = rem_trips[0][:3]
            used_t = set(id(c) for c in t)
            others = [c for c in rem_cards if id(c) not in used_t]
            others = _sorted_cards(others)
            if len(others) >= 5:
                chi1 = list(flush)
                chi2 = list(t) + others[:2]
                chi3 = others[2:5]
                _append_variant(out, seen, chi1, chi2, chi3)

        # A3: Flush + Đôi(5) + 3 lá (khi có 1 đôi)
        if rem_pairs:
            p = rem_pairs[0][:2]
            used_p = set(id(c) for c in p)
            others = [c for c in rem_cards if id(c) not in used_p]
            others = _sorted_cards(others)
            if len(others) >= 6:
                chi1 = list(flush)
                chi2 = list(p) + others[:3]
                chi3 = others[3:6]
                _append_variant(out, seen, chi1, chi2, chi3)

        # A4: Flush + Sảnh (thực chiến)  [chỉ hợp lệ khi Flush ở chi1]
        # Nếu 8 lá còn lại có thể tạo sảnh 5 lá thì sinh thêm:
        #   chi1 = flush(5)
        #   chi2 = straight(5)
        #   chi3 = 3 lá còn lại
        # (Không sinh trường hợp chi2=flush, chi1=straight vì sẽ foul: thùng > sảnh)
        def _find_best_straights_5(rem8: List[Card], limit: int = 2) -> List[List[Card]]:
            rank_map_local: Dict[Any, List[Card]] = defaultdict(list)
            for cc in rem8:
                rank_map_local[cc.rank].append(cc)
            for rr in list(rank_map_local.keys()):
                rank_map_local[rr] = sorted(rank_map_local[rr], key=lambda x: _rank_val(x.rank), reverse=True)

            uniq_ranks_local = list(rank_map_local.keys())
            uniq_sorted = sorted(uniq_ranks_local, key=lambda r: _rank_val(r))
            val_to_rank_local = {_rank_val(r): r for r in uniq_sorted}

            seqs: List[List[Any]] = []
            for start_v in range(2, 11):
                vals = list(range(start_v, start_v + 5))
                if all(v in val_to_rank_local for v in vals):
                    seqs.append([val_to_rank_local[v] for v in vals])

            # wheel A2345
            if 14 in val_to_rank_local and all(v in val_to_rank_local for v in [2, 3, 4, 5]):
                seqs.append([val_to_rank_local[14], val_to_rank_local[2], val_to_rank_local[3], val_to_rank_local[4], val_to_rank_local[5]])

            def _seq_key(rs: List[Any]) -> Tuple[int, ...]:
                return tuple(sorted((_rank_val(r) for r in rs), reverse=True))

            seqs = sorted(seqs, key=_seq_key, reverse=True)

            out_st: List[List[Card]] = []
            seen_sig = set()
            for rs in seqs:
                sig = tuple(_rank_val(r) for r in rs)
                if sig in seen_sig:
                    continue
                seen_sig.add(sig)

                st: List[Card] = []
                used_ids = set()
                ok = True
                for r in rs:
                    picked = None
                    for cand in rank_map_local[r]:
                        if id(cand) not in used_ids:
                            picked = cand
                            break
                    if picked is None:
                        ok = False
                        break
                    used_ids.add(id(picked))
                    st.append(picked)
                if not ok:
                    continue
                if len(st) == 5:
                    out_st.append(st)
                if len(out_st) >= limit:
                    break
            return out_st

        for st5 in _find_best_straights_5(rem_cards, limit=2):
            used2 = set(id(c) for c in st5)
            rest3 = [c for c in rem_cards if id(c) not in used2]
            if len(rest3) == 3:
                chi1 = list(flush)
                chi2 = list(st5)
                chi3 = rest3
                _append_variant(out, seen, chi1, chi2, chi3)

        # =========================
        # (B) Flush ở chi2 (hoán vị mạnh thực chiến)
        # =========================

        # cố build chi1 không mậu thầu từ rem, chi3 là 3 lá còn lại
        chi1_core = _best_5_from_rem(rem_cards)
        if chi1_core is not None:
            used = set(id(c) for c in chi1_core) | used_flush
            rem3 = [c for c in cards if id(c) not in used]
            if len(rem3) == 3:
                _append_variant(out, seen, chi1_core, list(flush), rem3)

    return out

def _generate_break_from_multi_flushes(
    cards: List[Card],
    profile: Dict[str, Any],
) -> List[ThreeChi]:
    """
    Bẻ khi bài có TIỀM NĂNG 2 THÙNG (hoặc 1 chất rất dài):
      - 2 thùng 5 lá (chi1, chi2) + chi3 mậu thầu.
      - Nếu 1 chất >= 10 lá: tách thành 2 thùng cùng chất.
    Không cố tối ưu tuyệt đối, chỉ cung cấp thêm thế bẻ '2 thùng' đặc thù.
    """
    out: List[ThreeChi] = []
    seen: set = set()

    suit_groups: Dict[Suit, List[Card]] = profile["suit_groups"]
    if not suit_groups:
        return out

    # Chuẩn hoá: sort từng group giảm dần
    sorted_suits: Dict[Suit, List[Card]] = {
        s: sorted(grp, key=lambda c: _rank_val(c.rank), reverse=True)
        for s, grp in suit_groups.items()
    }

    suits = list(sorted_suits.keys())

    # Case 1: 2 chất khác nhau có đủ >= 5 lá => 2 thùng khác chất
    for i in range(len(suits)):
        for j in range(i + 1, len(suits)):
            s1, s2 = suits[i], suits[j]
            g1, g2 = sorted_suits[s1], sorted_suits[s2]
            if len(g1) < 5 or len(g2) < 5:
                continue

            chi1 = g1[:5]
            chi2 = g2[:5]
            used_ids = set(id(c) for c in chi1 + chi2)
            rem = [c for c in cards if id(c) not in used_ids]
            if len(rem) != 3:
                continue
            chi3 = rem
            _append_variant(out, seen, chi1, chi2, chi3)

    # Case 2: 1 chất rất dài (>= 10 lá) -> tách thành 2 thùng cùng chất
    for s, grp in sorted_suits.items():
        if len(grp) < 10:
            continue
        chi1 = grp[:5]
        chi2 = grp[5:10]
        used_ids = set(id(c) for c in chi1 + chi2)
        rem = [c for c in cards if id(c) not in used_ids]
        if len(rem) != 3:
            continue
        chi3 = rem
        _append_variant(out, seen, chi1, chi2, chi3)

    return out

def _generate_break_from_straights(cards: List[Card], profile: Dict[str, Any]) -> List[ThreeChi]:
    """
    Bẻ theo SẢNH:
      (1) 2 sảnh (5-5) + 3 lá còn lại (logic cũ)
      (2) 1 sảnh (chi1 hoặc chi2) + phần còn lại cố tạo thú/xám/đôi cho chi còn lại
      (3) Hỗ trợ Wheel A2345

    Không cố tối ưu tuyệt đối, chỉ sinh đủ family để beauty_flow chọn.
    """
    out: List[ThreeChi] = []
    seen: set = set()

    # rank -> list cards
    rank_map: Dict[Any, List[Card]] = defaultdict(list)
    for c in cards:
        rank_map[c.rank].append(c)
    for r in rank_map:
        rank_map[r] = sorted(rank_map[r], key=lambda x: _rank_val(x.rank), reverse=True)

    def _sorted_cards(cs: List[Card]) -> List[Card]:
        return sorted(cs, key=lambda x: _rank_val(x.rank), reverse=True)

    # (1) 2 sảnh (5-5) + 3 lá còn lại (logic cũ)
    segments: List[List[Any]] = profile["straight_segments"]
    for seg in segments:
        if len(seg) < 10:
            continue
        s1_ranks = seg[:5]
        s2_ranks = seg[-5:]

        def build_straight(ranks5: List[Any]) -> Optional[List[Card]]:
            used_ids = set()
            picked: List[Card] = []
            for rr in ranks5:
                if rr not in rank_map:
                    return None
                cand = None
                for c in rank_map[rr]:
                    if id(c) not in used_ids:
                        cand = c
                        break
                if cand is None:
                    return None
                used_ids.add(id(cand))
                picked.append(cand)
            return picked

        s1 = build_straight(s1_ranks)
        s2 = build_straight(s2_ranks)
        if not s1 or not s2:
            continue

        used = set(id(c) for c in s1 + s2)
        rem3 = [c for c in cards if id(c) not in used]
        if len(rem3) == 3:
            _append_variant(out, seen, list(s1), list(s2), rem3)
            _append_variant(out, seen, list(s2), list(s1), rem3)

    # (2) 1 sảnh (chi1 hoặc chi2) + phần còn lại
    straight_candidates: List[List[Card]] = []
    uniq_ranks = list(rank_map.keys())
    uniq_sorted = sorted(uniq_ranks, key=lambda r: _rank_val(r))
    val_to_rank = {_rank_val(r): r for r in uniq_sorted}

    for start_v in range(2, 11):
        vals = list(range(start_v, start_v + 5))
        if all(v in val_to_rank for v in vals):
            ranks5 = [val_to_rank[v] for v in vals]
            s = []
            used_ids = set()
            ok = True
            for rr in ranks5:
                picked = None
                for cand in rank_map[rr]:
                    if id(cand) not in used_ids:
                        picked = cand
                        break
                if picked is None:
                    ok = False
                    break
                used_ids.add(id(picked))
                s.append(picked)
            if ok and len(s) == 5:
                straight_candidates.append(s)

    # wheel A2345
    if 14 in val_to_rank and all(v in val_to_rank for v in [2, 3, 4, 5]):
        ranks5 = [val_to_rank[14], val_to_rank[2], val_to_rank[3], val_to_rank[4], val_to_rank[5]]
        s = []
        used_ids = set()
        ok = True
        for rr in ranks5:
            picked = None
            for cand in rank_map[rr]:
                if id(cand) not in used_ids:
                    picked = cand
                    break
            if picked is None:
                ok = False
                break
            used_ids.add(id(picked))
            s.append(picked)
        if ok and len(s) == 5:
            straight_candidates.append(s)

    # dedup straight candidates
    seen_st = set()
    uniq_st: List[List[Card]] = []
    for s in straight_candidates:
        sig = _card_codes(s)
        if sig in seen_st:
            continue
        seen_st.add(sig)
        uniq_st.append(s)

    # cap để tránh nổ
    uniq_st = uniq_st[:12]

    for s in uniq_st:
        used_s = set(id(c) for c in s)
        rem_cards = [c for c in cards if id(c) not in used_s]
        if len(rem_cards) != 8:
            continue

        rem_sorted = _sorted_cards(rem_cards)

        # (B1) chi1 = sảnh
        _append_variant(out, seen, list(s), rem_sorted[:5], rem_sorted[5:8])

        # (B2) chi2 = sảnh (chi1 cố build mạnh từ rem)
        chi1_core = _best_5_from_rem(rem_cards)
        if chi1_core is not None:
            used = set(id(c) for c in chi1_core) | used_s
            rem3 = [c for c in cards if id(c) not in used]
            if len(rem3) == 3:
                _append_variant(out, seen, chi1_core, list(s), rem3)

        # (B2X) chi2 = sảnh + chi1 = thùng (thực chiến)
        # Nếu 8 lá còn lại (rem_cards) có thể tạo THÙNG 5 lá,
        # sinh thêm biến thể: chi1=flush(5), chi2=straight(5), chi3=3 lá còn lại.
        # (Tránh sinh straight ở chi1 + flush ở chi2 vì sẽ foul: thùng > sảnh)
        suit_map: Dict[Any, List[Card]] = defaultdict(list)
        for cc in rem_cards:
            suit_map[cc.suit].append(cc)

        flush_cands: List[List[Card]] = []
        for s_suit, grp in suit_map.items():
            if len(grp) >= 5:
                grp_sorted = sorted(grp, key=lambda x: _rank_val(x.rank), reverse=True)
                flush_cands.append(grp_sorted[:5])

        # chỉ lấy tối đa 2 candidate mạnh nhất để tránh nổ
        flush_cands = sorted(flush_cands, key=lambda cs: [_rank_val(c.rank) for c in cs], reverse=True)[:2]

        for f5 in flush_cands:
            used2 = set(id(c) for c in f5) | used_s
            rem3 = [c for c in cards if id(c) not in used2]
            if len(rem3) == 3:
                _append_variant(out, seen, list(f5), list(s), rem3)

        # (B3) sảnh + thú (nếu rem có >=2 đôi)
        rem_profile = _build_simple_profile(rem_cards)
        rem_pairs: List[List[Card]] = rem_profile["pairs"]
        if len(rem_pairs) >= 2:
            p1 = rem_pairs[0][:2]
            p2 = rem_pairs[1][:2]
            used_p = set(id(c) for c in p1 + p2) | used_s
            kickers = [c for c in cards if id(c) not in used_p]
            kickers = _sorted_cards(kickers)
            if kickers:
                beast = list(p1) + list(p2) + [kickers[0]]
                used2 = set(id(c) for c in beast) | used_s
                rem3 = [c for c in cards if id(c) not in used2]
                if len(rem3) == 3:
                    _append_variant(out, seen, list(s), beast, rem3)

    return out

def _generate_break_from_dragon_and_long_straights(
    cards: List[Card],
    profile: Dict[str, Any],
) -> List[ThreeChi]:
    """
    Bẻ khi có SẢNH rất dài / SẢNH RỒNG (dải rank >= 9, đặc biệt 13):
      - Ưu tiên sinh ra:
        + 3 SẢNH: chi1 5 lá, chi2 5 lá, chi3 3 lá (nếu đủ).
        + Trường hợp đặc biệt Sảnh Rồng (dải 13 rank).
    Chỉ sinh vài cấu hình tiêu biểu để tránh bùng nổ.
    """
    out: List[ThreeChi] = []
    seen: set = set()

    segments: List[List[Rank]] = profile["straight_segments"]
    if not segments:
        return out

    rank_map = _build_rank_map(cards)

    for seg in segments:
        seg_len = len(seg)
        # Trường hợp SẢNH RỒNG: dải đủ 13 rank (2..A)
        if seg_len >= 13:
            # Pattern DRAGON-1:
            #   chi1: 5 rank cao nhất
            #   chi2: 5 rank kế tiếp
            #   chi3: 3 rank thấp nhất
            high5 = seg[-5:]
            mid5 = seg[-10:-5]
            low3 = seg[:3]

            used = set()
            chi1 = _pick_combo_from_ranks(high5, rank_map, used)
            chi2 = _pick_combo_from_ranks(mid5, rank_map, used) if chi1 else None
            chi3 = _pick_combo_from_ranks(low3, rank_map, used) if chi2 else None

            if chi1 and chi2 and chi3:
                _append_variant(out, seen, chi1, chi2, chi3)

            # Pattern DRAGON-2:
            #   dồn chi3: 3 rank cao nhất, chi1/chi2 ở giữa/thấp hơn
            high3 = seg[-3:]
            mid5_2 = seg[-8:-3]
            low5_2 = seg[:5]

            used = set()
            chi3b = _pick_combo_from_ranks(high3, rank_map, used)
            chi2b = _pick_combo_from_ranks(mid5_2, rank_map, used) if chi3b else None
            chi1b = _pick_combo_from_ranks(low5_2, rank_map, used) if chi2b else None

            if chi1b and chi2b and chi3b:
                _append_variant(out, seen, chi1b, chi2b, chi3b)

        # Trường hợp SẢNH DÀI (>= 9): ưu tiên 3 sảnh 5-5-3 nếu có thể
        elif seg_len >= 9:
            # Ta lấy đuôi mạnh nhất để tránh rối:
            #  chi1: 5 rank cao nhất
            #  chi2: 5 rank bắt đầu lùi 1
            #  chi3: 3 rank thấp nhất
            high5 = seg[-5:]
            mid5 = seg[-6:-1]   # lệch 1 rank so với high5
            low3 = seg[:3]

            used = set()
            chi1 = _pick_combo_from_ranks(high5, rank_map, used)
            chi2 = _pick_combo_from_ranks(mid5, rank_map, used) if chi1 else None
            chi3 = _pick_combo_from_ranks(low3, rank_map, used) if chi2 else None

            if chi1 and chi2 and chi3:
                _append_variant(out, seen, chi1, chi2, chi3)

    return out
def _generate_break_from_straight_flushes(
    cards: List[Card],
    profile: Dict[str, Any],
) -> List[ThreeChi]:
    """
    Bẻ THÙNG PHÁ SẢNH (straight flush) khi chuỗi cùng chất liên tiếp >= 6:
      - chi1: thùng phá sảnh 5 lá cao nhất.
      - chi2: 1 sảnh (hoặc thùng) nữa cắt lệch 1 rank.
      - chi3: 3 lá còn lại.
    Chỉ nhắm tới pattern 'đặc thù special', không cố exhaust toàn bộ.
    """
    out: List[ThreeChi] = []
    seen: set = set()

    suit_groups: Dict[Suit, List[Card]] = profile["suit_groups"]
    if not suit_groups:
        return out

    rank_order = "23456789TJQKA"
    rank_index = {r: i for i, r in enumerate(rank_order)}

    for suit, grp in suit_groups.items():
        if len(grp) < 6:
            continue

        # Build rank -> cards cho từng suit
        suit_rank_map: Dict[Rank, List[Card]] = defaultdict(list)
        for c in grp:
            suit_rank_map[c.rank].append(c)
        for r in suit_rank_map:
            suit_rank_map[r].sort(key=lambda c: _rank_val(c.rank), reverse=True)

        # Tìm segment liên tiếp theo rank trong cùng chất
        have_rank = sorted({c.rank for c in grp}, key=lambda r: rank_index[r])
        segments: List[List[Rank]] = []
        cur: List[Rank] = []
        for r in rank_order:
            if r in suit_rank_map:
                if not cur or rank_index[r] == rank_index[cur[-1]] + 1:
                    cur.append(r)
                else:
                    if len(cur) >= 5:
                        segments.append(cur[:])
                    cur = [r]
        if len(cur) >= 5:
            segments.append(cur[:])

        if not segments:
            continue

        for seg in segments:
            if len(seg) < 6:
                continue

            # chi1: 5 rank cao nhất trong segment => thùng phá sảnh mạnh nhất
            sf1_ranks = seg[-5:]
            # chi2: 5 rank lệch 1 (nếu đủ)
            if len(seg) >= 7:
                sf2_ranks = seg[-6:-1]
            else:
                sf2_ranks = seg[-5:]  # fallback: có thể trùng rank nhưng cố gắng pick lá khác

            used = set()
            chi1 = _pick_combo_from_ranks(sf1_ranks, suit_rank_map, used)
            chi2 = _pick_combo_from_ranks(sf2_ranks, suit_rank_map, used) if chi1 else None
            if not chi1 or not chi2:
                continue

            used_ids = set(id(c) for c in chi1 + chi2)
            rem = [c for c in cards if id(c) not in used_ids]
            if len(rem) != 3:
                continue

            chi3 = rem
            _append_variant(out, seen, chi1, chi2, chi3)

    return out

# ---------------------------------------------------------------------------
# Nhóm 3: Nhiều đôi / xám (5 đôi 1 sám, Lục phé bôn, 3 Thú, ...)
# ---------------------------------------------------------------------------

def _generate_break_from_many_pairs(cards: List[Card], profile: Dict[str, Any]) -> List[ThreeChi]:
    """
    Bẻ khi có rất nhiều đôi / xám:
      - 3 Thú + 1 chi mậu thầu.
      - 2 Thú + 1 Cù.
    Bao trùm các thế kiểu 5 Đôi 1 Sám, Lục Phé Bôn... nhưng sinh ra
    NHIỀU cấu hình khác nhau (không chỉ 1).
    """
    out: List[ThreeChi] = []
    seen: set = set()

    pairs: List[List[Card]] = profile["pairs"]
    trips: List[List[Card]] = profile["trips"]
    if len(pairs) + len(trips) < 4:
        return out

    # Chuẩn hóa list thú (các group >=2, ưu tiên dài, rank lớn)
    beasts: List[List[Card]] = []
    beasts.extend(trips)
    beasts.extend(pairs)
    beasts_sorted = sorted(
        beasts,
        key=lambda grp: (len(grp), max(_rank_val(c.rank) for c in grp)),
        reverse=True,
    )

    # -------------------------------------------------------------
    # Pattern 1: 3 Thú + 1 chi mậu thầu
    # Chọn mọi bộ 3 group từ 4–5 group mạnh nhất để tránh bùng nổ.
    # -------------------------------------------------------------
    max_groups = min(len(beasts_sorted), 5)
    if max_groups >= 3:
        idx_range = range(max_groups)
        for i, j, k in combinations(idx_range, 3):
            b1 = beasts_sorted[i]
            b2 = beasts_sorted[j]
            b3 = beasts_sorted[k]
            used = set(id(c) for g in (b1, b2, b3) for c in g)
            rem_cards = [c for c in cards if id(c) not in used]

            need_total = (5 - len(b1)) + (5 - len(b2)) + (3 - len(b3))
            if len(rem_cards) < need_total:
                continue

            rem_sorted = sorted(rem_cards, key=lambda c: _rank_val(c.rank), reverse=True)

            def fill(group: List[Card], need: int, pool: List[Card]) -> Tuple[List[Card], List[Card]]:
                take = pool[:need]
                return group + take, pool[need:]

            # Hai cách dồn thú:
            #  - C1: thú lớn cho chi1, thú vừa chi2, thú nhỏ chi3
            #  - C2: thú lớn đẩy về chi3 (dồn chi3), thú nhỏ chi1
            for order in ((b1, b2, b3), (b3, b2, b1)):
                g1, g2, g3 = order
                pool = list(rem_sorted)
                chi1, pool = fill(list(g1), 5 - len(g1), pool)
                chi2, pool = fill(list(g2), 5 - len(g2), pool)
                chi3, pool = fill(list(g3), 3 - len(g3), pool)
                _append_variant(out, seen, chi1, chi2, chi3)

    # -------------------------------------------------------------
    # Pattern 2: 2 Thú + 1 Cù (nếu có trips)
    # -------------------------------------------------------------
    if trips:
        # duyệt mọi lựa chọn 1 trips t, và 2 beasts khác (có thể là đôi hoặc trips)
        for ti in range(len(trips)):
            t = trips[ti]
            for i, j in combinations(range(len(beasts_sorted)), 2):
                b1 = beasts_sorted[i]
                b2 = beasts_sorted[j]
                if b1 is t or b2 is t:
                    # bỏ qua cấu hình mà thú b1/b2 chính là t (đã tính riêng)
                    continue
                used = set(id(c) for g in (t, b1, b2) for c in g)
                rem_cards = [c for c in cards if id(c) not in used]

                # cần:
                #   - 5 - len(b1) cho chi1
                #   - 5 - len(b2) cho chi2
                #   - 3 - len(t)  cho chi3 (Cù)
                need_total = (5 - len(b1)) + (5 - len(b2)) + (3 - len(t))
                if len(rem_cards) < need_total:
                    continue

                rem_sorted = sorted(rem_cards, key=lambda c: _rank_val(c.rank), reverse=True)

                def fill(group: List[Card], need: int, pool: List[Card]) -> Tuple[List[Card], List[Card]]:
                    take = pool[:need]
                    return group + take, pool[need:]

                # Hai hướng:
                #  - H1: chi1, chi2 là thú; chi3 là Cù (t + 2 rác)
                #  - H2: chi1 là Cù; chi2, chi3 là thú
                # H1:
                pool = list(rem_sorted)
                chi1, pool = fill(list(b1), 5 - len(b1), pool)
                chi2, pool = fill(list(b2), 5 - len(b2), pool)
                chi3 = list(t) + pool[: (3 - len(t))]
                _append_variant(out, seen, chi1, chi2, chi3)

                # H2:
                pool = list(rem_sorted)
                chi1_cu = list(t) + pool[: (5 - len(t))]
                pool2 = pool[(5 - len(t)) :]
                chi2_cu, pool2 = fill(list(b1), 5 - len(b1), pool2)
                # chi3_cu: nếu group b2 dài hơn 3, chỉ lấy 3 lá mạnh nhất
                if len(b2) > 3:
                    chi3_cu = sorted(b2, key=lambda c: _rank_val(c.rank), reverse=True)[:3]
                else:
                    chi3_cu, pool2 = fill(list(b2), 3 - len(b2), pool2)

                if len(chi2_cu) == 5 and len(chi3_cu) == 3:
                    _append_variant(out, seen, chi1_cu, chi2_cu, chi3_cu)

    return out


# ---------------------------------------------------------------------------
# HÀM CHÍNH: sinh các thế bẻ bài từ 13 lá
# ---------------------------------------------------------------------------

def generate_break_variants(
    cards: List[Card],
    special_type: Optional[Any] = None,
    profile: Optional["HandProfile"] = None,
    profile_group: Optional[str] = None,
) -> List[ThreeChi]:
    """
    Hàm chính được gọi từ arrange_beauty_topk để sinh thêm các THẾ BẺ BÀI.

    Thiết kế:
      - Chỉ dựa trên 13 lá + thông tin profile đơn giản.
      - Mỗi nhóm pattern tự đảm bảo:
          + Không binh lủng (dùng _validate_no_foul).
          + Không trùng đúng cùng 3 chi.
      - Không phụ thuộc vào cách BEAUTY chia chi trước đó, để tránh vòng lặp phức tạp.
    """
    if len(cards) != 13:
        return []

    # Dự phòng: nếu profile từ arrange không truyền xuống, tự build lại profile đơn giản
    base_profile = _build_simple_profile(cards)

    variants: List[ThreeChi] = []

    # Nhóm 1: QUADS / FULL HOUSE
    variants.extend(_generate_break_from_quads(cards, base_profile))
    variants.extend(_generate_break_from_fullhouses(cards, base_profile))

    # Nhóm 2: THÙNG / SẢNH
    variants.extend(_generate_break_from_flush_and_pairs(cards, base_profile))
    variants.extend(_generate_break_from_straights(cards, base_profile))

    # Nhóm 3: NHIỀU ĐÔI / XÁM (5 ĐÔI 1 SÁM, LỤC PHÉ BÔN, ...)
    variants.extend(_generate_break_from_many_pairs(cards, base_profile))
    
    # Nhóm 4: SPECIAL – SẢNH RỒNG / THÙNG PHÁ SẢNH / 2–3 THÙNG / 3 SẢNH
    variants.extend(_generate_break_from_dragon_and_long_straights(cards, base_profile))
    variants.extend(_generate_break_from_straight_flushes(cards, base_profile))
    variants.extend(_generate_break_from_multi_flushes(cards, base_profile))

    # Sau này nếu muốn dùng special_type/profile_group để kích hoạt pattern riêng cho từng special,
    # ta có thể thêm vào đây. Hiện tại base_profile đã bao trùm đa số trường hợp bẻ có ý nghĩa.
    return variants
