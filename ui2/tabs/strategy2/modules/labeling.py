from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from engine.card import Card
from engine.rules import evaluate_5cards
from engine.money_scoring import evaluate_3cards


@dataclass
class LabelingContext:
    """
    Context read-only để build label NGU theo đúng logic hiện có trong StrategyTab.
    Tất cả field dưới đây đều map 1-1 từ StrategyTab (KHÔNG ĐỔI HÀNH VI).
    """
    profiles: List[str]
    active_profile: str
    suggestions: Dict[str, List[dict]]
    suggestions_render: Dict[str, List[dict]]
    selected_index: Dict[str, int]
    max_ui_ngu_items: int


class Labeling:
    """
    Extracted labeling + per-chi type + compare helpers from StrategyTab.

    Mục tiêu: di chuyển code sang module, KHÔNG đổi logic, KHÔNG đổi HTML,
    KHÔNG thay đổi cache behavior.
    """

    def __init__(self) -> None:
        self._chi_type_cache: Dict[Tuple[Tuple[str, ...], int], Tuple[str, str, str]] = {}
        self._chi_type_cache_limit: int = 5000

        # compare cache (giữ nguyên đúng như StrategyTab hiện tại)
        self._cmp_cache: Dict[Tuple[str, str], Tuple[int, int, int]] = {}
        self._cmp_cache_limit: int = 8000

    # ===== cache config (để StrategyTab set đúng giá trị đang dùng) =====
    def set_cache_limits(self, chi_type_cache_limit: int, cmp_cache_limit: int) -> None:
        self._chi_type_cache_limit = int(chi_type_cache_limit)
        self._cmp_cache_limit = int(cmp_cache_limit)

    # =================== per-chi name ===================
    def hand_name_icon_color_5(self, t: int) -> Tuple[str, str, str]:
        mp = {
            8: ("💎", "Thùng phá sảnh", "#c084fc"),
            7: ("🔥", "Tứ quý", "#ef4444"),
            6: ("-", "Cù", "#9ca3af"),
            5: ("-", "Thùng", "#9ca3af"),
            4: ("-", "Sảnh", "#9ca3af"),
            3: ("-", "Xám", "#9ca3af"),
            2: ("-", "Thú", "#9ca3af"),
            1: ("-", "Đôi", "#9ca3af"),
            0: ("-", "Mậu", "#9ca3af"),
        }
        return mp.get(int(t), ("·", f"#{t}", "#9ca3af"))
    def _sap_badge(self, kind: str) -> str:
        # kind: "ham_win","ham_lose","lang_win","lang_lose"
        if kind == "lang_win":
            return '<span style="color:#fbbf24; font-weight:900;">🏆 Làng</span>'
        if kind == "lang_lose":
            return '<span style="color:#ef4444; font-weight:900;"> Làng</span>'
        if kind == "ham_win":
            return '<span style="color:#f59e0b; font-weight:900;">🏆 Sập</span>'
        if kind == "ham_lose":
            return '<span style="color:#ef4444; font-weight:900;"> Sập</span>'
        return ""

    def hand_name_icon_color_3(self, t: int) -> Tuple[str, str, str]:
        mp = {2: ("⭐", "Xám", "#f472b6"), 1: ("-", "Đôi", "#9ca3af"), 0: ("-", "Mậu", "#9ca3af")}
        return mp.get(int(t), ("·", f"#{t}", "#9ca3af"))

    def chi_type(self, chi_codes: List[str], chi_index: int) -> Tuple[str, str, str]:
        try:
            key = (tuple(chi_codes or []), int(chi_index))
            cached = self._chi_type_cache.get(key)
            if cached is not None:
                return cached

            cards = [Card.from_code(c) for c in chi_codes]
            if chi_index in (1, 2):
                t, _ = evaluate_5cards(cards)
                res = self.hand_name_icon_color_5(int(t))
                if len(self._chi_type_cache) > self._chi_type_cache_limit:
                    self._chi_type_cache.clear()
                self._chi_type_cache[key] = res
                return res

            t, _ = evaluate_3cards(cards)
            res = self.hand_name_icon_color_3(int(t))
            if len(self._chi_type_cache) > self._chi_type_cache_limit:
                self._chi_type_cache.clear()
            self._chi_type_cache[key] = res
            return res
        except Exception:
            return ("·", "?", "#9ca3af")

    def build_label_html_base(self, s: dict) -> str:
        """Chỉ hiển thị loại bài 3 chi (không so thắng/thua)."""
        chi1 = list(s.get("chi1_codes") or [])
        chi2 = list(s.get("chi2_codes") or [])
        chi3 = list(s.get("chi3_codes") or [])
        ic1, n1, c1 = self.chi_type(chi1, 1)
        ic2, n2, c2 = self.chi_type(chi2, 2)
        ic3, n3, c3 = self.chi_type(chi3, 3)
        return (
            f'<span style="color:{c1}; font-weight:900;">{ic1}{n1}</span> '
            f'<span style="color:{c2}; font-weight:900;">{ic2}{n2}</span> '
            f'<span style="color:{c3}; font-weight:900;">{ic3}{n3}</span>'
        )

    def auto_prefix_html(self, s: dict) -> str:
        if s.get("_auto_profile_money") or s.get("_auto_opp_money"):
            return '<span style="color:#fbbf24; font-weight:900;">[Auto]</span> '
        return ""

    # =================== Label helpers (standardized) ===================
    def fmt_delta(self, d: int) -> str:
        """Generic delta: supports any int, but P uses -1/0/+1."""
        if d > 0:
            return f'<span style="color:#22c55e; font-weight:900;">+{d}</span>'
        if d < 0:
            return f'<span style="color:#ef4444; font-weight:900;">{d}</span>'
        return '<span style="color:#9ca3af; font-weight:900;">0</span>'

    def fmt_delta_n(self, d: int) -> str:
        """Delta for NGU aggregate (range -3..+3)."""
        if d > 0:
            return f'<span style="color:#22c55e; font-weight:900;">+{d}</span>'
        if d < 0:
            return f'<span style="color:#ef4444; font-weight:900;">{d}</span>'
        return '<span style="color:#9ca3af; font-weight:900;">0</span>'

    def fmt_total(self, total: int) -> str:
        if total > 0:
            return f'<span style="color:#22c55e; font-weight:900;">(+{total})</span>'
        if total < 0:
            return f'<span style="color:#ef4444; font-weight:900;">({total})</span>'
        return '<span style="color:#9ca3af; font-weight:900;">(0)</span>'

    # =================== compare helpers ===================
    def cmp_tuple(self, a: Tuple[int, object], b: Tuple[int, object]) -> int:
        try:
            if a > b:
                return 1
            if a < b:
                return -1
            return 0
        except Exception:
            return 0

    def compare_chi(self, my_codes: List[str], opp_codes: List[str], chi_index: int) -> int:
        """
        Trả về delta chi theo luật chi thưởng:
          - hòa: 0
          - thắng: +N
          - thua:  -N
        N phụ thuộc loại bài của BÊN THẮNG và vị trí chi.
        """
        try:
            my_cards = [Card.from_code(c) for c in (my_codes or [])]
            opp_cards = [Card.from_code(c) for c in (opp_codes or [])]

            def _hand_type(v) -> int:
                # v có thể là tuple kiểu (t, ...) từ evaluate_5cards/3cards
                if isinstance(v, (tuple, list)) and len(v) > 0:
                    return int(v[0])
                return int(v)

            def _bonus_for(winner_eval, chi_idx: int) -> int:
                t = _hand_type(winner_eval)

                # 3-card (chi 3): t=2 là Xám
                if chi_idx == 3:
                    if t == 2:   # Xám chi cuối
                        return 6
                    return 1

                # 5-card (chi 1/2)
                if chi_idx == 1:
                    if t == 7:   # Tứ quý chi đầu
                        return 8
                    if t == 8:   # Thùng phá sảnh chi đầu
                        return 10
                    return 1

                if chi_idx == 2:
                    if t == 6:   # Cù lũ chi giữa
                        return 4
                    if t == 7:   # Tứ quý chi giữa
                        return 16
                    if t == 8:   # Thùng phá sảnh chi giữa
                        return 20
                    return 1

                return 1

            if chi_index in (1, 2):
                if len(my_cards) != 5 or len(opp_cards) != 5:
                    return 0
                a = evaluate_5cards(my_cards)
                b = evaluate_5cards(opp_cards)
                cmpv = self.cmp_tuple(a, b)
                if cmpv == 0:
                    return 0
                winner_eval = a if cmpv > 0 else b
                bonus = _bonus_for(winner_eval, chi_index)
                return int(cmpv) * int(bonus)

            # chi 3
            if len(my_cards) != 3 or len(opp_cards) != 3:
                return 0
            a = evaluate_3cards(my_cards)
            b = evaluate_3cards(opp_cards)
            cmpv = self.cmp_tuple(a, b)
            if cmpv == 0:
                return 0
            winner_eval = a if cmpv > 0 else b
            bonus = _bonus_for(winner_eval, chi_index)
            return int(cmpv) * int(bonus)

        except Exception:
            return 0

    # =================== HTML build vs ===================
    def build_label_html_vs(self, s: dict, opp: Optional[dict]) -> str:
        """
        P label format (GIỮ NGUYÊN):
          (tổng) Chi1Type Δ1  Chi2Type Δ2  Chi3Type Δ3
        """
        chi1 = list(s.get("chi1_codes") or [])
        chi2 = list(s.get("chi2_codes") or [])
        chi3 = list(s.get("chi3_codes") or [])

        ic1, n1, c1 = self.chi_type(chi1, 1)
        ic2, n2, c2 = self.chi_type(chi2, 2)
        ic3, n3, c3 = self.chi_type(chi3, 3)

        seg1 = f'<span style="color:{c1}; font-weight:900;">{ic1}{n1}</span>'
        seg2 = f'<span style="color:{c2}; font-weight:900;">{ic2}{n2}</span>'
        seg3 = f'<span style="color:{c3}; font-weight:900;">{ic3}{n3}</span>'
        auto_prefix = self.auto_prefix_html(s)
        if not opp:
            return f"{auto_prefix}{seg1} {seg2} {seg3}"

        d1 = self.compare_chi(chi1, list(opp.get("chi1_codes") or []), 1)
        d2 = self.compare_chi(chi2, list(opp.get("chi2_codes") or []), 2)
        d3 = self.compare_chi(chi3, list(opp.get("chi3_codes") or []), 3)
        base_total = int(d1) + int(d2) + int(d3)

        wins = (1 if d1 > 0 else 0) + (1 if d2 > 0 else 0) + (1 if d3 > 0 else 0)
        losses = (1 if d1 < 0 else 0) + (1 if d2 < 0 else 0) + (1 if d3 < 0 else 0)
        ties = (1 if d1 == 0 else 0) + (1 if d2 == 0 else 0) + (1 if d3 == 0 else 0)

        sap_kind = None
        eff_total = base_total

        # Rule: nếu có hoà -> không sập
        if ties == 0 and (wins == 3 or losses == 3):
            # sập hầm: thêm 1 lần tổng chi đã thua  => x2
            if wins == 3:
                sap_kind = "ham_win"
                eff_total = base_total * 2
            else:
                sap_kind = "ham_lose"
                eff_total = base_total * 2  # base_total âm => tự thành -2x

            # sập làng: thêm 2 lần tổng chi đã thua => x3
            if s.get("_sap_lang_win") and wins == 3:
                sap_kind = "lang_win"
                eff_total = base_total * 3
            if s.get("_sap_lang_lose") and losses == 3:
                sap_kind = "lang_lose"
                eff_total = base_total * 3

        badge = self._sap_badge(sap_kind) if sap_kind else ""

        # Đưa tổng + badge sang bên phải
        if badge:
            suffix = f" {self.fmt_total(eff_total)}{badge}"
        else:
            suffix = f" {self.fmt_total(eff_total)}"

        return f"{auto_prefix}{seg1} {seg2} {seg3}{suffix}"

    def _has_playable_split(self, s: Optional[dict]) -> bool:
        if not s:
            return False
        return (
            len(list(s.get("chi1_codes") or [])) == 5
            and len(list(s.get("chi2_codes") or [])) == 5
            and len(list(s.get("chi3_codes") or [])) == 3
        )

    def _pick_selected_playable_suggestion(self, pid: str, ctx: LabelingContext) -> Optional[dict]:
        render_list = list(ctx.suggestions_render.get(pid) or [])
        base_list = list(ctx.suggestions.get(pid) or [])
        candidates = render_list or base_list

        if candidates:
            try:
                idx = int(ctx.selected_index.get(pid, 0) or 0)
            except Exception:
                idx = 0
            if 0 <= idx < len(candidates):
                selected = candidates[idx]
                if self._has_playable_split(selected):
                    return selected

        for item in render_list:
            if self._has_playable_split(item):
                return item
        for item in base_list:
            if self._has_playable_split(item):
                return item
        return None

    def build_label_html_ngu_vs_3p(self, ngu_s: dict, ctx: LabelingContext, is_special_row_fn) -> str:
        """
        NGU label format (GIỮ NGUYÊN):
          (TỔNG) Chi1Type Δ1  Chi2Type Δ2  Chi3Type Δ3
        Δ theo góc nhìn 3P.
        """
        chi1 = list(ngu_s.get("chi1_codes") or [])
        chi2 = list(ngu_s.get("chi2_codes") or [])
        chi3 = list(ngu_s.get("chi3_codes") or [])

        ic1, n1, c1 = self.chi_type(chi1, 1)
        ic2, n2, c2 = self.chi_type(chi2, 2)
        ic3, n3, c3 = self.chi_type(chi3, 3)

        seg1 = f'<span style="color:{c1}; font-weight:900;">{ic1}{n1}</span>'
        seg2 = f'<span style="color:{c2}; font-weight:900;">{ic2}{n2}</span>'
        seg3 = f'<span style="color:{c3}; font-weight:900;">{ic3}{n3}</span>'
        auto_prefix = self.auto_prefix_html(ngu_s)

        d1 = d2 = d3 = 0
        any_seen = False
        pair_sweeps: List[Tuple[int, int, int, int]] = []  # (wins, losses, ties, base_total)

        for pid in ctx.profiles:
            # ---- chọn đúng suggestion của P đang được chọn trên UI ----
            my_s = self._pick_selected_playable_suggestion(pid, ctx)

            # 1) ưu tiên list đang render cho mọi pid
            my_list = ctx.suggestions_render.get(pid) or []
            if not my_list:
                my_list = ctx.suggestions.get(pid) or []

            if my_s is None and my_list:
                idx = int(ctx.selected_index.get(pid, 0))
                if idx < 0 or idx >= len(my_list):
                    idx = 0
                my_s = my_list[idx]

                # skip special row
                if my_s is not None and is_special_row_fn(my_s):
                    my_s = my_list[1] if len(my_list) > 1 else None

            # 2) fallback: nếu vẫn None thì lấy gợi ý đầu tiên
            if my_s is None:
                base_list = ctx.suggestions.get(pid) or []
                if base_list:
                    my_s = base_list[0]

            if not my_s or is_special_row_fn(my_s):
                continue

            any_seen = True

            # ---- tính theo góc nhìn 3P: compare(Pi, NGU) ----
            pd1 = self.compare_chi(list(my_s.get("chi1_codes") or []), chi1, 1)
            pd2 = self.compare_chi(list(my_s.get("chi2_codes") or []), chi2, 2)
            pd3 = self.compare_chi(list(my_s.get("chi3_codes") or []), chi3, 3)

            d1 += pd1
            d2 += pd2
            d3 += pd3

            wins = (1 if pd1 > 0 else 0) + (1 if pd2 > 0 else 0) + (1 if pd3 > 0 else 0)
            losses = (1 if pd1 < 0 else 0) + (1 if pd2 < 0 else 0) + (1 if pd3 < 0 else 0)
            ties = (1 if pd1 == 0 else 0) + (1 if pd2 == 0 else 0) + (1 if pd3 == 0 else 0)
            base_total = int(pd1) + int(pd2) + int(pd3)

            pair_sweeps.append((wins, losses, ties, base_total))

        if not any_seen:
            return f"{auto_prefix}{seg1} {seg2} {seg3}"

        # ---- Global sập làng (4 nhà): chỉ khi đủ sweep ở TẤT CẢ cặp và KHÔNG hoà ----
        # 3P sập làng NGU: mọi cặp đều wins==3 & ties==0
        # NGU sập làng 3P: mọi cặp đều losses==3 & ties==0
        sap_lang_3p = True
        sap_lang_ngu = True

        # NGU chỉ tồn tại khi đủ 3P -> yêu cầu đủ đúng 3 cặp
        if len(pair_sweeps) != 3:
            sap_lang_3p = False
            sap_lang_ngu = False

        else:
            for (w, l, t, _bt) in pair_sweeps:
                if not (t == 0 and w == 3):
                    sap_lang_3p = False
                if not (t == 0 and l == 3):
                    sap_lang_ngu = False

        # ---- total_eff: áp sập hầm x2, sập làng x3 (theo base_total thực tế) ----
        total_eff = 0
        for (w, l, t, bt) in pair_sweeps:
            eff = bt
            if t == 0 and (w == 3 or l == 3):
                if sap_lang_3p or sap_lang_ngu:
                    eff = bt * 3
                else:
                    eff = bt * 2
            total_eff += eff

        return f"{auto_prefix}{seg1} {seg2} {seg3} {self.fmt_total(int(total_eff))}"
