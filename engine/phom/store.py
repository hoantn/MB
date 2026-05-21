# engine/phom/store.py
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Optional, Set

from .constants import TOTAL_CARDS, CMD_DEAL, CMD_DISCARD, CMD_HAND_SNAPSHOT
from .state import PhomState
from .ws_parser import parse_phom_payload, PhomEvent
from .analyzer import analyze_hand

_UID_RE = re.compile(r"^\d+_\d+$")


def _append_debug_line(line: str) -> None:
    """Ghi log ra txt để debug (an toàn, không crash nếu lỗi IO)."""
    try:
        path = os.path.join(os.getcwd(), "phom_debug.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass


@dataclass
class PhomVisibilitySnapshot:
    known: Set[int]
    unseen: Set[int]


class PhomVisibilityStore:
    def __init__(self):
        self.state = PhomState()

    def update_from_ws_event(self, profile_id: str, raw_payload: Any) -> Optional[PhomEvent]:
        ev = parse_phom_payload(raw_payload)
        if ev is None:
            return None

        # debug thô để bạn nhìn schema (chỉ log cmd quan trọng)
        if ev.cmd in (851, 852, 853, 854):
            uids = set()
            _collect_uids(ev.payload, uids)
            msg = (
                f"[PHOM][CMD {ev.cmd}] "
                f"keys={list(ev.payload.keys()) if isinstance(ev.payload, dict) else type(ev.payload)} "
                f"uids={sorted(uids)} payload={ev.payload}"
            )
            print(msg)
            _append_debug_line(msg)

        st = self.state.get_profile(profile_id)

        st.events.append({"cmd": ev.cmd, "payload": ev.payload})
        if len(st.events) > 500:
            st.events.pop(0)

        # cmd=850: đầu ván mới -> reset state profile cho sạch
        if ev.cmd == CMD_DEAL:
            st.hand.clear()
            st.discards.clear()
            st.init_seen.clear()
            st.analysis = None

            # (0) Lưu thứ tự vòng đánh từ cmd=850
            turn_uids: list[str] = []
            seen: set[str] = set()
            _collect_uids_in_order(ev.payload, turn_uids, seen)
            if len(turn_uids) >= 2:
                self.state.turn_order_uids = turn_uids
                msg = f"[PHOM][TURN] order={self.state.turn_order_uids}"
                print(msg)
                _append_debug_line(msg)

            cs = ev.payload.get("cs")
            if isinstance(cs, list):
                # (1) lưu init_seen
                for x in cs:
                    if isinstance(x, int):
                        st.init_seen.add(x)

                # (2) coi cs như bài được chia -> set hand ngay
                st.hand = set(st.init_seen)

                # (3) SAFE MODE: phân tích bài + lá nên đánh dựa trên known-only
                vis = self.compute_known_unseen("ALL")
                st.analysis = analyze_hand(set(st.hand), known_cards=vis.known)

            # (4) cập nhật "đánh cho ai"
            st.play_for = self.compute_play_for(profile_id)
            msg = f"[PHOM][PLAY_FOR] {profile_id} uid={st.my_uid} -> {st.play_for}"
            print(msg)
            _append_debug_line(msg)

            return ev

        # cmd=852: snapshot bài trên tay (sAC) -> cập nhật hand + chạy Phase 2A
        if ev.cmd == CMD_HAND_SNAPSHOT:
            sAC = ev.payload.get("sAC")
            if isinstance(sAC, list):
                st.hand = set(
                    int(x) for x in sAC
                    if isinstance(x, int) or (isinstance(x, str) and x.isdigit())
                )

            # SAFE MODE: phân tích bài + lá nên đánh dựa trên known-only
            vis = self.compute_known_unseen("ALL")
            st.analysis = analyze_hand(set(st.hand), known_cards=vis.known)

            return ev

        # cmd=851: đánh ra (dCs) - FACT trên bàn
        if ev.cmd == CMD_DISCARD:
            fP = ev.payload.get("fP")
            if isinstance(fP, dict):
                dcs = fP.get("dCs")
                if isinstance(dcs, int):
                    st.discards.add(dcs)
            return ev

        return ev

    def update_self_info(self, profile_id: str, payload) -> None:
        st = self.state.get_profile(profile_id)
        if not isinstance(payload, dict):
            return

        uid = None
        for k in ("uid", "u"):
            v = payload.get(k)
            if isinstance(v, str) and _UID_RE.match(v):
                uid = v
                break

        dn = payload.get("dn")

        gold = payload.get("gold")
        if gold is None and isinstance(payload.get("As"), dict):
            gold = payload["As"].get("gold")

        if isinstance(uid, str) and uid:
            st.my_uid = uid
            self.state.uid_to_profile[uid] = profile_id

            st.play_for = self.compute_play_for(profile_id)
            msg = f"[PHOM][PLAY_FOR] {profile_id} uid={st.my_uid} -> {st.play_for}"
            print(msg)
            _append_debug_line(msg)

        if isinstance(dn, str) and dn:
            st.my_dn = dn
        if isinstance(gold, int):
            st.my_gold = gold

    def set_play_for(self, profile_id: str, target: str) -> None:
        st = self.state.get_profile(profile_id)
        if target in ("P1", "P2", "P3", "OPP"):
            st.play_for = target

    def compute_play_for(self, profile_id: str) -> str:
        st = self.state.get_profile(profile_id)

        if not st.my_uid:
            return "OPP"

        order = getattr(self.state, "turn_order_uids", [])
        if not isinstance(order, list) or not order:
            return "OPP"

        if st.my_uid not in order:
            return "OPP"

        idx = order.index(st.my_uid)
        next_uid = order[(idx + 1) % len(order)]
        return self.state.uid_to_profile.get(next_uid, "OPP")

    def compute_known_unseen(self, scope_profile: str = "ALL") -> PhomVisibilitySnapshot:
        all_cards = set(range(TOTAL_CARDS))

        if scope_profile and scope_profile != "ALL":
            st = self.state.get_profile(scope_profile)
            known = set(st.hand) | set(st.discards) | set(st.init_seen)
            unseen = all_cards - known
            return PhomVisibilitySnapshot(known=known, unseen=unseen)

        known: Set[int] = set()
        for st in self.state.profiles.values():
            known |= set(st.hand)
            known |= set(st.discards)
            known |= set(st.init_seen)

        unseen = all_cards - known
        return PhomVisibilitySnapshot(known=known, unseen=unseen)

    # =========================
    # TEAM COACH (text guidance)
    # =========================

    def compute_team_mode(self, profile_id: str) -> str:
        """
        SUPPORT: đánh cho đồng đội (P1/P2/P3)
        SUPPRESS: triệt đối thủ
        """
        st = self.state.get_profile(profile_id)
        target = getattr(st, "play_for", "OPP") or "OPP"
        if target in ("P1", "P2", "P3") and target != "OPP":
            return "SUPPORT"
        return "SUPPRESS"

    def _need_cards_for_profile(self, profile_id: str) -> set[int]:
        """
        Tính tập 'lá mà profile này đang thiếu' để hoàn thiện phỏm
        (rule-based, không đoán mò).
        - Bộ: có 2 lá cùng rank -> thiếu 2 lá còn lại của rank đó
        - Sảnh: có 2 lá liên tiếp cùng suit -> thiếu 1 đầu/đuôi
        """
        from .card import Card  # dùng đúng Card(ws_code) hệ bạn

        st = self.state.get_profile(profile_id)
        hand = set(getattr(st, "hand", set()) or set())

        need: set[int] = set()

        # --- 1) NEED cho BỘ (pair -> missing suits)
        by_rank: dict[int, set[int]] = {}
        for ws in hand:
            c = Card(int(ws))
            by_rank.setdefault(c.rank_index, set()).add(c.suit_index)

        for r, suits_have in by_rank.items():
            if len(suits_have) >= 2 and len(suits_have) < 4:
                for s in range(4):
                    if s not in suits_have:
                        need.add(r * 4 + s)

        # --- 2) NEED cho SẢNH (2 consecutive same suit -> missing end)
        by_suit: dict[int, set[int]] = {0: set(), 1: set(), 2: set(), 3: set()}
        for ws in hand:
            c = Card(int(ws))
            by_suit[c.suit_index].add(c.rank_index)

        for suit_idx, ranks in by_suit.items():
            rs = sorted(ranks)
            rs_set = set(rs)
            # xét mọi cặp consecutive (r, r+1)
            for r in rs:
                if (r + 1) in rs_set:
                    # thiếu đầu: r-1
                    if r - 1 >= 0:
                        need.add((r - 1) * 4 + suit_idx)
                    # thiếu đuôi: r+2
                    if r + 2 <= 12:
                        need.add((r + 2) * 4 + suit_idx)

        return need
        
    def _avoid_cards_for_suppress(self, my_hand: set[int]) -> tuple[list[int], list[int]]:
        """
        TRIỆT OPP (không đoán mò):
        Dùng known/unseen toàn bàn để suy ra "nguy cơ bị ăn" theo liên kết.
        - Nguy cơ bộ (3 cùng rank): nếu cùng rank còn nhiều lá chưa lộ -> nguy cơ cao
        - Nguy cơ sảnh (±1 cùng suit): nếu lá kề còn chưa lộ -> nguy cơ cao

        Trả về:
          (avoid_strong, avoid_medium) là list ws_code (đã sort).
        """
        from .card import Card

        vis = self.compute_known_unseen("ALL")
        known = set(getattr(vis, "known", set()) or set())
        unseen = set(getattr(vis, "unseen", set()) or set())

        # Đếm số lá đã biết theo rank (0..12)
        known_rank_cnt = [0] * 13
        for ws in known:
            c = Card(int(ws))
            if 0 <= c.rank_index <= 12:
                known_rank_cnt[c.rank_index] += 1

        avoid_strong: list[int] = []
        avoid_medium: list[int] = []

        for ws in my_hand:
            c = Card(int(ws))
            r = c.rank_index
            s = c.suit_index

            # 1) Nguy cơ BỘ: cùng rank còn bao nhiêu lá chưa lộ?
            # (4 lá / rank)
            remain_same_rank = 0
            if 0 <= r <= 12:
                remain_same_rank = max(0, 4 - known_rank_cnt[r])

            # 2) Nguy cơ SẢNH: lá kề (r-1, r+1) cùng suit còn nằm trong unseen không?
            neigh = 0
            if (r - 1) >= 0:
                if ((r - 1) * 4 + s) in unseen:
                    neigh += 1
            if (r + 1) <= 12:
                if ((r + 1) * 4 + s) in unseen:
                    neigh += 1

            # Chấm mức né (đơn giản, đúng “mắt người chơi”):
            # - Né mạnh nếu: có 2 lá kề đều chưa lộ (nguy cơ sảnh rất cao)
            #   hoặc cùng rank còn 3-4 lá chưa lộ (nguy cơ bộ cao)
            # - Né vừa nếu: có 1 lá kề chưa lộ hoặc cùng rank còn 2 lá chưa lộ
            if neigh >= 2 or remain_same_rank >= 3:
                avoid_strong.append(int(ws))
            elif neigh >= 1 or remain_same_rank >= 2:
                avoid_medium.append(int(ws))

        # sort cho UI dễ nhìn (theo sort_key sẵn của Card)
        avoid_strong = sorted(avoid_strong, key=lambda x: Card(int(x)).sort_key)
        avoid_medium = sorted(avoid_medium, key=lambda x: Card(int(x)).sort_key)

        return avoid_strong, avoid_medium
        
    def _safe_cards_for_suppress(self, my_hand: set[int]) -> tuple[list[int], list[int], list[int]]:
        """
        TRIỆT OPP (HIỂN THỊ LÁ AN TOÀN ĐỂ ĐÁNH):
        - safe_best: các lá đối thủ "khó ăn nhất" (ưu tiên đánh)
        - safe_ok:   các lá tương đối an toàn (cân nhắc đánh)
        - avoid:     các lá rủi ro cao (để debug nếu cần)

        Dựa 100% vào known/unseen ALL (đúng tiêu chí 'lá đã biết').
        """
        from .card import Card

        vis = self.compute_known_unseen("ALL")
        known = set(getattr(vis, "known", set()) or set())
        unseen = set(getattr(vis, "unseen", set()) or set())

        # Đếm số lá đã biết theo rank (0..12)
        known_rank_cnt = [0] * 13
        for ws in known:
            c = Card(int(ws))
            if 0 <= c.rank_index <= 12:
                known_rank_cnt[c.rank_index] += 1

        scored: list[tuple[int, int]] = []  # (risk, ws)
        avoid: list[int] = []

        for ws in my_hand:
            c = Card(int(ws))
            r = c.rank_index
            s = c.suit_index

            # cùng rank còn bao nhiêu lá chưa lộ? (càng nhiều => càng dễ bị ăn thành bộ)
            remain_same_rank = 0
            if 0 <= r <= 12:
                remain_same_rank = max(0, 4 - known_rank_cnt[r])

            # lá kề sảnh (r-1, r+1) cùng suit còn nằm trong unseen? (càng nhiều => càng dễ bị ăn thành sảnh)
            neigh = 0
            if (r - 1) >= 0 and ((r - 1) * 4 + s) in unseen:
                neigh += 1
            if (r + 1) <= 12 and ((r + 1) * 4 + s) in unseen:
                neigh += 1

            # ===== chấm risk (thực dụng, đúng "mắt người chơi") =====
            risk = 0

            # sảnh nguy hiểm mạnh hơn vì chỉ cần 1 lá để ăn ngay
            if neigh >= 2:
                risk += 3
            elif neigh == 1:
                risk += 1

            # bộ: cùng rank còn nhiều lá chưa lộ thì tăng risk
            if remain_same_rank >= 3:
                risk += 2
            elif remain_same_rank == 2:
                risk += 1

            scored.append((risk, int(ws)))

            # rủi ro cao để debug (không bắt buộc hiển thị)
            if risk >= 3:
                avoid.append(int(ws))

        # sort theo risk tăng dần (an toàn trước), sau đó theo sort_key để nhìn đẹp
        scored.sort(key=lambda t: (t[0], Card(int(t[1])).sort_key))

        ordered = [ws for _, ws in scored]

        safe_best = ordered[:4]
        safe_ok = ordered[4:8]

        # sort avoid cũng cho đẹp (optional)
        avoid = sorted(avoid, key=lambda x: Card(int(x)).sort_key)

        return safe_best, safe_ok, avoid

    def build_team_coach_text(self, profile_id: str) -> str:
        """
        Trả về text ngắn: hỗ trợ đồng đội / triệt đối thủ theo vòng đánh.
        Không chọn 1 lá cụ thể (đúng chủ trương bỏ 'lá gợi ý').
        """
        st = self.state.get_profile(profile_id)
        target = getattr(st, "play_for", "OPP") or "OPP"
        mode = self.compute_team_mode(profile_id)

        lines: list[str] = []

        if mode == "SUPPORT":
            # tính lá mà đồng đội đang thiếu để hoàn thiện phỏm
            need = self._need_cards_for_profile(target) if target in ("P1","P2","P3") else set()

            # giao với bài hiện tại của mình => mình có thể đánh ra để đồng đội ăn
            my_hand = set(getattr(st, "hand", set()) or set())
            can_feed = sorted(list(my_hand & need))

            if can_feed:
                # chỉ liệt kê tối đa 6 lá để UI gọn
                can_feed = can_feed[:6]
                lines.append(f"Có thể NUÔI: {can_feed}  (đồng đội đang thiếu để vào phỏm)")
            else:
                lines.append("Có thể NUÔI: (không thấy lá nào khớp 'thiếu phỏm' của đồng đội)")

        else:
            my_hand = set(getattr(st, "hand", set()) or set())
            safe_best, safe_ok, avoid = self._safe_cards_for_suppress(my_hand)

            vis = self.compute_known_unseen("ALL")
            unseen_cnt = len(getattr(vis, "unseen", set()) or set())

            if safe_best:
                lines.append(f"Đối thủ khó ăn nhất: {safe_best}")
            else:
                lines.append("Ưu tiên đánh (khó ăn nhất): (không có)")

        return "\n".join(lines)

def _collect_uids(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for _, v in obj.items():
            if isinstance(v, str) and _UID_RE.match(v):
                out.add(v)
            else:
                _collect_uids(v, out)
    elif isinstance(obj, list):
        for x in obj:
            _collect_uids(x, out)


def _collect_uids_in_order(obj, out_list: list[str], seen: set[str]) -> None:
    """Collect UID theo thứ tự xuất hiện trong payload (giữ vòng đánh)."""
    if isinstance(obj, dict):
        for _, v in obj.items():
            if isinstance(v, str) and _UID_RE.match(v):
                if v not in seen:
                    seen.add(v)
                    out_list.append(v)
            else:
                _collect_uids_in_order(v, out_list, seen)
    elif isinstance(obj, list):
        for x in obj:
            _collect_uids_in_order(x, out_list, seen)
