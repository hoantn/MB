from __future__ import annotations
import logging
from typing import List, Optional
from collections import Counter

from .templates import extract_template_key_from_suggestion, template_strength_from_key
from engine.card import Card
from engine.arranger_parts.arrange import _normalize_kicker_distribution

class RenderController:
    """
    Render-only controller extracted from StrategyTab.

    Nguyên tắc:
    - Không đổi logic.
    - Không đổi contract UI.
    - Chỉ move code, StrategyTab giữ wrapper methods để call y hệt.
    """
    FLEX_DEBUG = False
    _log = logging.getLogger("MauBinhTool")
    def __init__(self, max_ui_p_items: int, max_ui_ngu_items: int):
        self.max_ui_p_items = int(max_ui_p_items)
        self.max_ui_ngu_items = int(max_ui_ngu_items)
        
    def _apply_trash_law(self, tab, suggestion: dict) -> None:
        """
        Áp dụng luật dồn rác (normalize kicker 13 lá) cho 1 gợi ý.

        - Bỏ qua special row (bài 13 lá thực tế / bài đặc biệt).
        - Chỉ xử lý khi chi1/chi2/chi3 đủ 5-5-3 lá.
        - Dùng lại _normalize_kicker_distribution ở tầng arrange nên:
          + Không binh lủng (đã check trong hàm đó).
          + Không phá loại hand (cù, thú, tứ, sảnh, thùng...).
        """
        # Không đụng vào special row (bài thực tế)
        try:
            if tab._is_special_row(suggestion):
                return
        except Exception:
            # Nếu tab không có _is_special_row vì lý do gì đó thì coi như suggestion thường
            pass

        chi1_codes = list(suggestion.get("chi1_codes") or [])
        chi2_codes = list(suggestion.get("chi2_codes") or [])
        chi3_codes = list(suggestion.get("chi3_codes") or [])

        # Không đúng định dạng 5-5-3 thì bỏ qua
        if not (len(chi1_codes) == 5 and len(chi2_codes) == 5 and len(chi3_codes) == 3):
            return

        try:
            chi1_cards = [Card.from_code(c) for c in chi1_codes]
            chi2_cards = [Card.from_code(c) for c in chi2_codes]
            chi3_cards = [Card.from_code(c) for c in chi3_codes]
        except Exception:
            # Lỗi parse code -> bỏ qua, không được để UI chết
            return

        try:
            new1, new2, new3 = _normalize_kicker_distribution(
                chi1_cards, chi2_cards, chi3_cards
            )
        except Exception:
            # Tuyệt đối không để lỗi normalize chặn render
            return

        # Ghi lại codes sau khi dồn rác
        suggestion["chi1_codes"] = [c.to_code() for c in new1]
        suggestion["chi2_codes"] = [c.to_code() for c in new2]
        suggestion["chi3_codes"] = [c.to_code() for c in new3]

    # ===== FLEX nội bộ theo OPP: chỉ áp dụng khi CẢI THIỆN wins/losses =====
    def _vs_key(self, tab, s: dict, opp: dict):
        """
        Trả về key so chi vs OPP:
          (wins, losses, draws, total)
        Dùng compare_chi sẵn có của tab._labeling.
        """
        try:
            c1 = list(s.get("chi1_codes") or [])
            c2 = list(s.get("chi2_codes") or [])
            c3 = list(s.get("chi3_codes") or [])
            o1 = list(opp.get("chi1_codes") or [])
            o2 = list(opp.get("chi2_codes") or [])
            o3 = list(opp.get("chi3_codes") or [])
            d1 = tab._labeling.compare_chi(c1, o1, 1)
            d2 = tab._labeling.compare_chi(c2, o2, 2)
            d3 = tab._labeling.compare_chi(c3, o3, 3)
        except Exception:
            return (0, 0, 3, 0)

        wins = (1 if d1 > 0 else 0) + (1 if d2 > 0 else 0) + (1 if d3 > 0 else 0)
        losses = (1 if d1 < 0 else 0) + (1 if d2 < 0 else 0) + (1 if d3 < 0 else 0)
        draws = 3 - wins - losses
        total = d1 + d2 + d3
        return (wins, losses, draws, total)

    def _flex_internal_vs_ngu(self, tab, s: dict, opp: dict) -> dict:
        """
        Linh hoạt nội bộ suggestion theo OPP (NGU), NHẸ NHẤT:
        - Chỉ thử 1 biến thể: chạy _normalize_kicker_distribution (đã đảm bảo không phá loại hand và không binh lủng).
        - CHỈ áp dụng nếu:
            wins_new > wins_old  OR  losses_new < losses_old
        - Nếu không cải thiện số chi thắng/thua => trả lại suggestion gốc.
        """
        if self.FLEX_DEBUG:
            self._log.warning("[FLEX] try suggestion: %s",
                              s.get("template_key") or extract_template_key_from_suggestion(s))

        # Guard: không đụng special row
        try:
            if tab._is_special_row(s):
                return s
        except Exception:
            pass

        c1 = list(s.get("chi1_codes") or [])
        c2 = list(s.get("chi2_codes") or [])
        c3 = list(s.get("chi3_codes") or [])
        if not (len(c1) == 5 and len(c2) == 5 and len(c3) == 3):
            return s

        # Key gốc
        base_key = self._vs_key(tab, s, opp)
        if self.FLEX_DEBUG:
            bw, bl, bd, bt = base_key
            self._log.warning("[FLEX] base vs OPP -> wins=%s, losses=%s, draws=%s, total=%s", bw, bl, bd, bt)

        bw, bl, _bd, _bt = base_key  # wins, losses, draws, total

        # Tạo bản copy suggestion (không mutate bản gốc)
        s2 = dict(s)
        s2["chi1_codes"] = list(c1)
        s2["chi2_codes"] = list(c2)
        s2["chi3_codes"] = list(c3)

        # Thử normalize kicker distribution (an toàn)
        try:
            chi1_cards = [Card.from_code(x) for x in c1]
            chi2_cards = [Card.from_code(x) for x in c2]
            chi3_cards = [Card.from_code(x) for x in c3]
            n1, n2, n3 = _normalize_kicker_distribution(chi1_cards, chi2_cards, chi3_cards)
            s2["chi1_codes"] = [x.to_code() for x in n1]
            s2["chi2_codes"] = [x.to_code() for x in n2]
            s2["chi3_codes"] = [x.to_code() for x in n3]
        except Exception:
            return s

        # (OPTIONAL but safe) Không cho phép đổi TEMPLATE tổng thể (giữ "cùng 1 gợi ý")
        try:
            tpl0 = extract_template_key_from_suggestion(s)
            tpl1 = extract_template_key_from_suggestion(s2)
            if tpl0 is not None and tpl1 is not None and tpl0 != tpl1:
                return s
        except Exception:
            pass

        # Key mới
        new_key = self._vs_key(tab, s2, opp)
        if self.FLEX_DEBUG:
            nw, nl, nd, nt = new_key
            self._log.warning("[FLEX] new  vs OPP -> wins=%s, losses=%s, draws=%s, total=%s", nw, nl, nd, nt)

        nw, nl, _nd, _nt = new_key

        # CHỈ giữ nếu cải thiện đúng mục tiêu (wins↑ hoặc losses↓)
        improved = (nw > bw) or (nl < bl)

        if self.FLEX_DEBUG:
            if improved:
                self._log.warning("[FLEX] APPLY (improved wins/losses)")
            else:
                self._log.warning("[FLEX] SKIP (no win/loss improvement)")

        if improved:
            s2["_flex_vs_ngu"] = True
            return s2

        return s
        
    # ===== moved from StrategyTab._build_preview_codes =====
    def build_preview_codes(self, suggestion: dict) -> Optional[List[str]]:
        chi1 = list(suggestion.get("chi1_codes") or [])
        chi2 = list(suggestion.get("chi2_codes") or [])
        chi3 = list(suggestion.get("chi3_codes") or [])
        if len(chi1) == 5 and len(chi2) == 5 and len(chi3) == 3:
            return chi1 + chi2 + chi3
        return None

    # ===== moved from StrategyTab._find_money_base =====
    def find_money_base(self, suggs: List[dict]) -> Optional[dict]:
        if not suggs:
            return None
        for s in suggs:
            if str(s.get("mode", "")).lower() == "money":
                return s
        return suggs[0]

    # ===== moved from StrategyTab._build_render_suggestions =====
    def build_render_suggestions(self, tab, base_suggs: List[dict], opp: Optional[dict]) -> List[dict]:
        out = list(base_suggs or [])
        if opp is None or not out:
            return out
        if not getattr(tab, "_anti_sap_enabled", False):
            return out

        my_base = self.find_money_base(out)
        if my_base is None:
            return out

        try:
            anti = tab.build_anti_sap_suggestions(
                my_base=my_base, opp_base=opp, label_prefix="Chống sập", max_out=3
            )
        except Exception as e:
            tab.log.error("[Strategy2] anti_sap build error: %s", e)
            anti = []

        for i, s in enumerate(anti):
            s["mode"] = "anti_sap"
            s["label"] = f"[Chống sập {i+1}]"
        out.extend(anti)
        return out

    # ===== UI-only filter: gom theo TEMPLATE (loại bài 3 chi) =====
    def _filter_dominated_suggestions(self, tab, suggs: List[dict]) -> List[dict]:
        """
        Lọc gợi ý theo TEMPLATE, NHƯNG GIỮ NGUYÊN THỨ TỰ ENGINE:

          - Không tự chấm lại bằng money hay beauty.
          - Với mỗi TEMPLATE, lấy đúng gợi ý đầu tiên engine trả về.
          - Vẫn giữ nguyên special row (bài thực tế / bài đặc biệt) ở đầu danh sách.
        """
        try:
            if not suggs:
                return suggs

            # 1) Tách special rows và gợi ý thường
            special_rows: List[dict] = []
            normals: List[dict] = []
            for s in suggs:
                if tab._is_special_row(s):
                    special_rows.append(s)
                else:
                    normals.append(s)

            if not normals:
                # Chỉ có special rows -> trả nguyên
                return special_rows

            # 1.b) ÁP DỤNG LUẬT DỒN RÁC CHO TOÀN BỘ GỢI Ý THƯỜNG
            # for s in normals:
                # self._apply_trash_law(tab, s)

            def _preview_key(s: dict) -> str:
                codes = self.build_preview_codes(s) or []
                return "|".join(codes)

            result_normals: List[dict] = []
            seen_templates = set()
            seen_previews = set()

            # 2) Giữ base = gợi ý đầu tiên của engine
            base = normals[0]
            base_tpl = extract_template_key_from_suggestion(base)
            base_prev_key = _preview_key(base)

            if base_tpl is not None:
                seen_templates.add(base_tpl)
            if base_prev_key:
                seen_previews.add(base_prev_key)
            result_normals.append(base)

            # 3) Với các gợi ý còn lại:
            #    - Nếu TEMPLATE mới -> giữ gợi ý ĐẦU TIÊN gặp template đó (theo thứ tự engine).
            #    - Nếu không xác định được TEMPLATE -> giữ nguyên nhưng tránh trùng 13 lá.
            for s in normals[1:]:
                pk = _preview_key(s)
                tpl = extract_template_key_from_suggestion(s)

                # Tránh trùng 13 lá
                if pk and pk in seen_previews:
                    continue

                # Không xác định được template -> cho qua (nhưng không trùng 13 lá)
                if tpl is None:
                    if pk:
                        seen_previews.add(pk)
                    result_normals.append(s)
                    continue

                # Template trùng base hoặc đã có đại diện -> bỏ qua
                if tpl == base_tpl or tpl in seen_templates:
                    continue

                # Lần đầu gặp template này -> giữ lại gợi ý này
                seen_templates.add(tpl)
                if pk:
                    seen_previews.add(pk)
                result_normals.append(s)

            # 4) Sắp xếp các gợi ý thường (trừ base) theo "độ mạnh template"
            if result_normals:
                base_s = result_normals[0]
                others = result_normals[1:]

                others_with_tpl = []
                for s in others:
                    tpl = extract_template_key_from_suggestion(s)
                    others_with_tpl.append((s, tpl))

                others_sorted = sorted(
                    others_with_tpl,
                    key=lambda pair: template_strength_from_key(pair[1]),
                    reverse=True,
                )
                result_normals = [base_s] + [s for (s, _tpl) in others_sorted]

            # 5) Trả về: special_rows + toàn bộ gợi ý đại diện theo template
            return special_rows + result_normals

        except Exception:
            # Tuyệt đối không để lỗi filter làm chết render
            return suggs

    def _apply_pareto_frontier(self, tab, suggs: List[dict]) -> List[dict]:
        """
        Lọc PARETO (dominance) giữa các gợi ý thường:
          - Giữ nguyên special rows.
          - Với phần thường, chỉ giữ các gợi ý không bị gợi ý khác đè cả 3 chi.
        """
        try:
            if not suggs:
                return suggs

            specials: List[dict] = []
            normals: List[dict] = []
            for s in suggs:
                if tab._is_special_row(s):
                    specials.append(s)
                else:
                    normals.append(s)

            # Không có gợi ý thường -> trả nguyên
            if not normals:
                return suggs

            def _delta_between(a: dict, b: dict):
                """
                So sánh a vs b theo cùng logic hạng bài như ΔB hiện tại:
                  - so rank template từng chi
                  - nếu cùng hạng:
                      + MẬU THẦU -> dùng compare_chi để so rác
                      + hạng khác -> hòa
                Trả về (d1,d2,d3): d>0 nghĩa là a mạnh hơn b ở chi đó.
                """
                tpl_a = extract_template_key_from_suggestion(a)
                tpl_b = extract_template_key_from_suggestion(b)
                if tpl_a is None or tpl_b is None:
                    return None
                try:
                    t1_a, t2_a, t3_a = tpl_a
                    t1_b, t2_b, t3_b = tpl_b
                except Exception:
                    return None

                MAU_THAU_RANK = 0

                def _cmp_one(ra, rb, chi_idx: int) -> int:
                    # rank không phải số -> coi như hòa
                    if not isinstance(ra, int) or not isinstance(rb, int):
                        return 0

                    # khác hạng -> so rank
                    if ra != rb:
                        return 1 if ra > rb else -1

                    # cùng hạng
                    if ra == MAU_THAU_RANK:
                        # CÙNG là Mậu thầu: dùng lá rác để phá hòa (so trực tiếp 3/5 lá)
                        cards_a = list(a.get(f"chi{chi_idx}_codes") or [])
                        cards_b = list(b.get(f"chi{chi_idx}_codes") or [])
                        try:
                            return tab._labeling.compare_chi(cards_a, cards_b, chi_idx)
                        except Exception:
                            return 0

                    # cùng hạng nhưng KHÔNG phải mậu thầu -> coi như hòa
                    return 0

                d1 = _cmp_one(t1_a, t1_b, 1)
                d2 = _cmp_one(t2_a, t2_b, 2)
                d3 = _cmp_one(t3_a, t3_b, 3)
                return (d1, d2, d3)

            frontier: List[dict] = []
            for i, s in enumerate(normals):
                dominated = False
                for j, t in enumerate(normals):
                    if i == j:
                        continue
                    deltas = _delta_between(t, s)
                    if deltas is None:
                        continue
                    d1, d2, d3 = deltas
                    # t đè s nếu: t không kém s ở chi nào và hơn s ở ít nhất 1 chi
                    if d1 >= 0 and d2 >= 0 and d3 >= 0 and (d1 > 0 or d2 > 0 or d3 > 0):
                        dominated = True
                        break
                if not dominated:
                    frontier.append(s)

            return specials + frontier
        except Exception:
            # Không để lỗi lọc frontier chặn render
            return suggs

    def _pick_best_suggestion_vs_ngu(
        self,
        tab,
        base_suggs: List[dict],
        opp: Optional[dict],
    ) -> Optional[dict]:
        """
        Chọn 1 gợi ý "G5" bẻ bài OPP, quét trên TOÀN BỘ gợi ý (base + anti_sap đã dọn rác).

        Tiêu chí:
          - Wins  = số chi ăn (d > 0)
          - Losses = số chi thua (d < 0)
          - Draws = số chi hòa

          Ưu tiên:
            1) Wins càng nhiều càng tốt (ăn nhiều chi nhất).
            2) Nếu cùng Wins: Draws càng ít càng tốt (chống hòa).
            3) Nếu vẫn bằng: Losses càng ít càng tốt (thua ít chi nhất).
            4) Nếu vẫn bằng: tổng d1 + d2 + d3 càng cao càng tốt.

        Hàm này KHÔNG lọc số lượng, chỉ trả về 1 suggestion tốt nhất vs OPP
        hoặc None nếu không tính được.
        """
        if not base_suggs or not opp:
            return None

        opp_c1 = list(opp.get("chi1_codes") or [])
        opp_c2 = list(opp.get("chi2_codes") or [])
        opp_c3 = list(opp.get("chi3_codes") or [])

        best = None
        best_key = None  # (wins, draws, losses, total)

        for s in base_suggs:
            # Bỏ special row: G5 chỉ áp dụng cho bài thường
            if tab._is_special_row(s):
                continue

            c1 = list(s.get("chi1_codes") or [])
            c2 = list(s.get("chi2_codes") or [])
            c3 = list(s.get("chi3_codes") or [])
            if not (c1 and c2 and c3):
                continue

            try:
                d1 = tab._labeling.compare_chi(c1, opp_c1, 1)
                d2 = tab._labeling.compare_chi(c2, opp_c2, 2)
                d3 = tab._labeling.compare_chi(c3, opp_c3, 3)
            except Exception:
                continue

            wins = (1 if d1 > 0 else 0) + (1 if d2 > 0 else 0) + (1 if d3 > 0 else 0)
            losses = (1 if d1 < 0 else 0) + (1 if d2 < 0 else 0) + (1 if d3 < 0 else 0)
            draws = 3 - wins - losses
            total = d1 + d2 + d3

            key = (wins, draws, losses, total)

            if best_key is None:
                best, best_key = s, key
                continue

            bw, bd, bl, bt = best_key
            cw, cd, cl, ct = key

            better = False
            if cw > bw:
                # Ăn nhiều chi hơn
                better = True
            elif cw == bw:
                # Chống hòa: ít hòa hơn
                if cd < bd:
                    better = True
                elif cd == bd:
                    # Thua ít chi hơn
                    if cl < bl:
                        better = True
                    elif cl == bl and ct > bt:
                        # Cùng wins/draw/loss -> chọn tổng tốt hơn
                        better = True

            if better:
                best, best_key = s, key

        return best

    # ===== Sort gợi ý P theo số chi thắng/thua với OPP (NGU) =====
    def sort_suggestions_by_vs_ngu(self, tab, pid: str, suggs: List[dict], opp: Optional[dict]) -> List[dict]:
        """
        Sắp xếp lại thứ tự gợi ý (chỉ phần thường, giữ nguyên special row)
        theo số chi thắng/thua so với 1 bài OPP (NGU) đã chọn.

        - Ưu tiên: ăn nhiều chi nhất
        - Nếu cùng số chi ăn: thua ít chi hơn
        - Nếu vẫn bằng: tổng điểm (d1+d2+d3) cao hơn
        Chỉ kích hoạt khi user đã click chọn 1 gợi ý OPP (_ngu_clicked_once=True).
        """
        try:
            if not suggs or not opp:
                return suggs
            # Nếu chưa click OPP -> giữ nguyên thứ tự hiện tại
            if not getattr(tab, "_ngu_clicked_once", False):
                return suggs

            # Tách special rows để giữ nguyên ở đầu
            specials: List[dict] = []
            normals: List[dict] = []
            for s in suggs:
                if tab._is_special_row(s):
                    specials.append(s)
                else:
                    normals.append(s)

            if not normals:
                return suggs

            opp_c1 = list(opp.get("chi1_codes") or [])
            opp_c2 = list(opp.get("chi2_codes") or [])
            opp_c3 = list(opp.get("chi3_codes") or [])

            def _key(s: dict):
                try:
                    c1 = list(s.get("chi1_codes") or [])
                    c2 = list(s.get("chi2_codes") or [])
                    c3 = list(s.get("chi3_codes") or [])
                    d1 = tab._labeling.compare_chi(c1, opp_c1, 1)
                    d2 = tab._labeling.compare_chi(c2, opp_c2, 2)
                    d3 = tab._labeling.compare_chi(c3, opp_c3, 3)
                except Exception:
                    d1 = d2 = d3 = 0

                wins = (1 if d1 > 0 else 0) + (1 if d2 > 0 else 0) + (1 if d3 > 0 else 0)
                losses = (1 if d1 < 0 else 0) + (1 if d2 < 0 else 0) + (1 if d3 < 0 else 0)
                total = d1 + d2 + d3

                # sort: nhiều win -> ít loss -> total cao
                return (-wins, losses, -total)

            normals_sorted = sorted(normals, key=_key)
            return specials + normals_sorted
        except Exception:
            # Tuyệt đối không để lỗi sort làm chết render
            return suggs

    def render_ngu(self, tab) -> None:
        # 1) Lấy gợi ý OPP và áp dụng bộ lọc áp chế chung (dồn rác + lọc template)
        suggs = tab._ngu_suggestions or []
        suggs = self._filter_dominated_suggestions(tab, suggs)

        # 1.5) Áp dụng Pareto frontier giống 3P:
        #      - Tách special row (bài thực tế / đặc biệt) ra riêng.
        #      - Trên các gợi ý thường (normals), loại bỏ những gợi ý bị gợi ý khác
        #        đè cả 3 chi (>= ở mọi chi và > ở ít nhất 1 chi).
        if suggs:
            specials: List[dict] = []
            normals: List[dict] = []
            for s in suggs:
                try:
                    if tab._is_special_row(s):
                        specials.append(s)
                    else:
                        normals.append(s)
                except Exception:
                    # Nếu có lỗi khi check special row, coi là gợi ý thường
                    normals.append(s)

            try:
                def _delta_between(a: dict, b: dict):
                    """
                    So sánh a vs b theo cùng logic hạng bài như ΔB hiện tại:
                      - so rank template từng chi
                      - nếu cùng hạng:
                          + MẬU THẦU -> dùng compare_chi để so rác
                          + hạng khác -> hòa
                    Trả về (d1,d2,d3): d>0 nghĩa là a mạnh hơn b ở chi đó.
                    """
                    tpl_a = extract_template_key_from_suggestion(a)
                    tpl_b = extract_template_key_from_suggestion(b)
                    if tpl_a is None or tpl_b is None:
                        return None
                    try:
                        t1_a, t2_a, t3_a = tpl_a
                        t1_b, t2_b, t3_b = tpl_b
                    except Exception:
                        return None

                    MAU_THAU_RANK = 0

                    def _cmp_one(ra, rb, chi_idx: int) -> int:
                        # rank không phải số -> coi như hòa
                        if not isinstance(ra, int) or not isinstance(rb, int):
                            return 0

                        # khác hạng -> so rank
                        if ra != rb:
                            return 1 if ra > rb else -1

                        # cùng hạng
                        if ra == MAU_THAU_RANK:
                            # CÙNG là Mậu thầu: dùng lá rác để phá hòa (so trực tiếp 3/5 lá)
                            cards_a = list(a.get(f"chi{chi_idx}_codes") or [])
                            cards_b = list(b.get(f"chi{chi_idx}_codes") or [])
                            try:
                                return tab._labeling.compare_chi(cards_a, cards_b, chi_idx)
                            except Exception:
                                return 0

                        # cùng hạng nhưng KHÔNG phải mậu thầu -> coi như hòa
                        return 0

                    d1 = _cmp_one(t1_a, t1_b, 1)
                    d2 = _cmp_one(t2_a, t2_b, 2)
                    d3 = _cmp_one(t3_a, t3_b, 3)
                    return (d1, d2, d3)

                frontier: List[dict] = []
                for i, s in enumerate(normals):
                    dominated = False
                    for j, t in enumerate(normals):
                        if i == j:
                            continue
                        deltas = _delta_between(t, s)
                        if deltas is None:
                            continue
                        d1, d2, d3 = deltas
                        # t đè s nếu: t không kém s ở chi nào và hơn s ở ít nhất 1 chi
                        if d1 >= 0 and d2 >= 0 and d3 >= 0 and (d1 > 0 or d2 > 0 or d3 > 0):
                            dominated = True
                            break
                    if not dominated:
                        frontier.append(s)

                suggs = specials + frontier
            except Exception:
                # Không để lỗi frontier chặn render OPP
                pass

        # Cập nhật lại cache gợi ý NGU sau khi lọc
        tab._ngu_suggestions = suggs

        # 2) Nếu không còn gợi ý sau lọc -> clear bài OPP
        if not suggs:
            tab.view.set_cards_ngu_normalized([])
            return

        # 3) Đảm bảo index chọn hợp lệ
        idx = tab._ngu_selected_index
        if idx < 0 or idx >= len(suggs):
            idx = 0
            tab._ngu_selected_index = 0

        # 4) Nếu dòng đầu là special row thì không cho chọn index 0
        if (
            suggs
            and idx == 0
            and tab._is_special_row(suggs[0])
            and len(suggs) > 1
        ):
            idx = 1
            tab._ngu_selected_index = 1

        # 5) Render bài OPP
        s = suggs[idx]
        codes = self.build_preview_codes(s)
        if codes:
            tab.view.set_cards_ngu_normalized(codes)

    # ===== moved from StrategyTab._render_p_active (giữ logic cũ + ΔB theo hạng bài) =====
    def render_p_active(self, tab) -> None:
        pid = tab.active_profile
        tab.view.set_active_profile(pid)

        # mặc định ẩn nút retry, nếu không có gợi ý sẽ bật lại (kể cả chưa đủ 13 lá)
        if hasattr(tab.view, "set_p_retry_visible"):
            tab.view.set_p_retry_visible(False)

        base_suggs = tab._suggestions.get(pid) or []
        # lấy 13 lá hiện có để kiểm tra đủ bài
        codes = list(tab._codes_slot_order.get(pid, []) or [])
        has_full_hand = len(codes) == 13

        if not base_suggs:
            tab.view.set_cards_p_normalized(codes)
            tab.view.btn_hup.setEnabled(False)
            tab.view.set_p_labels([], 0)
            tab._suggestions_render[pid] = []

            # Không có gợi ý thì luôn cho phép user bấm reset
            if hasattr(tab.view, "set_p_retry_visible"):
                tab.view.set_p_retry_visible(True)
            return

        # Chọn bài NGU (đối thủ) giống như trước
        opp = None
        if tab._ngu_suggestions:
            j = tab._ngu_selected_index
            if j < 0 or j >= len(tab._ngu_suggestions):
                j = 0
            if (
                tab._ngu_suggestions
                and j == 0
                and tab._is_special_row(tab._ngu_suggestions[0])
                and len(tab._ngu_suggestions) > 1
            ):
                j = 1
            opp = tab._ngu_suggestions[j]

        # Gộp base + anti sập
        render_suggs = self.build_render_suggestions(tab, base_suggs, opp)

        # Lưu lại toàn bộ (base + anti_sap, đã dọn rác) để dùng cho G5 bẻ bài
        all_suggs = list(render_suggs)

        # Inject dòng "bài đặc biệt" (UI-only) CHỈ khi worker CHƯA trả special row.
        ws13 = tab._codes_slot_order.get(pid) or []
        if len(ws13) == 13:
            try:
                has_worker_special = any(
                    bool(s.get("_is_special_row")) and str(s.get("mode", "")).lower() == "special"
                    for s in (render_suggs or [])
                )
            except Exception:
                has_worker_special = False

            if not has_worker_special:
                render_suggs = tab._inject_special_row_for_profile(pid, ws13, render_suggs)

        # Lọc gợi ý theo TEMPLATE (UI filter)
        render_suggs = self._filter_dominated_suggestions(tab, render_suggs)

        # Gợi ý 5: nếu đã có bài OPP và user đã click chọn OPP,
        # sinh thêm 1 gợi ý "bẻ bài" ăn nhiều chi nhất (chống hòa)
        if opp is not None and getattr(tab, "_ngu_clicked_once", False):
            flex = self._pick_best_suggestion_vs_ngu(tab, all_suggs, opp)
            if flex is not None and (not tab._is_special_row(flex)):

                def _preview_key(s: dict) -> str:
                    codes = self.build_preview_codes(s) or []
                    return "|".join(codes)

                flex_key = _preview_key(flex)
                if flex_key:
                    existing_keys = {_preview_key(s) for s in render_suggs}
                    if flex_key not in existing_keys:
                        # Áp dụng LUẬT DỒN RÁC cho gợi ý G5 trước khi append
                        flex2 = dict(flex)
                        self._apply_trash_law(tab, flex2)
                        # Thêm gợi ý 5 vào danh sách thường (sẽ được sort lại ở bước dưới)
                        render_suggs.append(flex2)

        # ===== FLEX CUỐI: chỉ khi đã click OPP và chỉ khi cải thiện wins/losses =====
        if opp is not None and getattr(tab, "_ngu_clicked_once", False):
            if self.FLEX_DEBUG:
                self._log.warning("[FLEX] activated (OPP clicked)")
            try:
                new_list: List[dict] = []
                for s in render_suggs:
                    if tab._is_special_row(s):
                        new_list.append(s)
                        continue
                    new_list.append(self._flex_internal_vs_ngu(tab, s, opp))
                render_suggs = new_list
            except Exception:
                # Không để lỗi flex làm chết render
                pass
        render_suggs = self.sort_suggestions_by_vs_ngu(tab, pid, render_suggs, opp)

        # ===== LỌC PARETO (dominance) GIỮA CÁC GỢI Ý THƯỜNG – ĐỐI XỬ BÌNH ĐẲNG =====
        try:
            specials: List[dict] = []
            normals: List[dict] = []
            for s in render_suggs:
                if tab._is_special_row(s):
                    specials.append(s)
                else:
                    normals.append(s)

            def _delta_between(a: dict, b: dict):
                """
                So sánh a vs b theo cùng logic hạng bài như ΔB hiện tại:
                  - so rank template từng chi
                  - nếu cùng hạng:
                      + MẬU THẦU -> dùng compare_chi để so rác
                      + hạng khác -> hòa
                Trả về (d1,d2,d3): d>0 nghĩa là a mạnh hơn b ở chi đó.
                """
                tpl_a = extract_template_key_from_suggestion(a)
                tpl_b = extract_template_key_from_suggestion(b)
                if tpl_a is None or tpl_b is None:
                    return None
                try:
                    t1_a, t2_a, t3_a = tpl_a
                    t1_b, t2_b, t3_b = tpl_b
                except Exception:
                    return None

                MAU_THAU_RANK = 0

                def _cmp_one(ra, rb, chi_idx: int) -> int:
                    # rank không phải số -> coi như hòa
                    if not isinstance(ra, int) or not isinstance(rb, int):
                        return 0

                    # khác hạng -> so rank
                    if ra != rb:
                        return 1 if ra > rb else -1

                    # cùng hạng
                    if ra == MAU_THAU_RANK:
                        # CÙNG là Mậu thầu: dùng lá rác để phá hòa (so trực tiếp 3/5 lá)
                        cards_a = list(a.get(f"chi{chi_idx}_codes") or [])
                        cards_b = list(b.get(f"chi{chi_idx}_codes") or [])
                        try:
                            return tab._labeling.compare_chi(cards_a, cards_b, chi_idx)
                        except Exception:
                            return 0

                    # cùng hạng nhưng KHÔNG phải mậu thầu -> coi như hòa
                    return 0

                d1 = _cmp_one(t1_a, t1_b, 1)
                d2 = _cmp_one(t2_a, t2_b, 2)
                d3 = _cmp_one(t3_a, t3_b, 3)
                return (d1, d2, d3)

            frontier: List[dict] = []
            for i, s in enumerate(normals):
                dominated = False
                for j, t in enumerate(normals):
                    if i == j:
                        continue
                    deltas = _delta_between(t, s)
                    if deltas is None:
                        continue
                    d1, d2, d3 = deltas
                    # t đè s nếu: t không kém s ở chi nào và hơn s ở ít nhất 1 chi
                    if d1 >= 0 and d2 >= 0 and d3 >= 0 and (d1 > 0 or d2 > 0 or d3 > 0):
                        dominated = True
                        break
                if not dominated:
                    frontier.append(s)

            render_suggs = specials + frontier
        except Exception:
            # Không để lỗi lọc frontier chặn render
            pass

        # ===== Chọn base_for_delta CHỈ ĐỂ HIỂN THỊ ΔB (KHÔNG DÙNG ĐỂ LỌC NỮA) =====
        base_for_delta = self.find_money_base(render_suggs)
        base_tpl = None
        if base_for_delta and (not tab._is_special_row(base_for_delta)):
            base_tpl = extract_template_key_from_suggestion(base_for_delta)

        def _delta_vs_base_by_rank(s: dict):
            """
            Trả về (d1, d2, d3) so với base_for_delta để hiển thị ΔB:

              - Bước 1: so hạng bài từng chi (template rank).
              - Bước 2: nếu cùng hạng:
                  + Nếu là MẬU THẦU: cho phép dùng compare_chi để so lá.
                  + Nếu là hạng khác: coi như hòa (0), KHÔNG phá hòa bằng lá.

              d > 0: chi mạnh hơn base
              d < 0: chi yếu hơn base
              d = 0: ngang.
            """
            if not base_tpl or not base_for_delta:
                return None

            tpl_s = extract_template_key_from_suggestion(s)
            if tpl_s is None:
                return None
            try:
                t1_s, t2_s, t3_s = tpl_s
                t1_b, t2_b, t3_b = base_tpl
            except Exception:
                return None

            MAU_THAU_RANK = 0

            def _cmp_one(r_s, r_b, chi_idx: int) -> int:
                # rank không phải số -> coi như hòa
                if not isinstance(r_s, int) or not isinstance(r_b, int):
                    return 0

                # khác hạng -> so rank
                if r_s != r_b:
                    return 1 if r_s > r_b else -1

                # cùng hạng
                if r_s == MAU_THAU_RANK:
                    # CÙNG là Mậu thầu: dùng lá rác để phá hòa (so trực tiếp 3/5 lá)
                    cards_s = list(s.get(f"chi{chi_idx}_codes") or [])
                    cards_b = list(base_for_delta.get(f"chi{chi_idx}_codes") or [])
                    try:
                        return tab._labeling.compare_chi(cards_s, cards_b, chi_idx)
                    except Exception:
                        return 0

                # cùng hạng nhưng KHÔNG phải mậu thầu -> coi như hòa
                return 0

            d1 = _cmp_one(t1_s, t1_b, 1)
            d2 = _cmp_one(t2_s, t2_b, 2)
            d3 = _cmp_one(t3_s, t3_b, 3)
            return (d1, d2, d3)

        # --- LỌC TRÙNG (13 lá + pattern) ---
        # render_suggs = tab._dedup_suggestions_by_split_key(render_suggs)
        # --- HẾT PHẦN LỌC TRÙNG ---

        # Không giữ selection cũ sau khi sort: dùng logic chọn mặc định
        idx = tab._selected_index.get(pid, 0)

        if idx < 0 or idx >= len(render_suggs):
            base = 1 if (render_suggs and tab._is_special_row(render_suggs[0])) else 0
            idx = base + 1
            if idx >= len(render_suggs):
                idx = base if base < len(render_suggs) else 0

        # Nếu user đã click chọn special row (idx=0) thì GIỮ NGUYÊN để APPLY bài đặc biệt.
        # Rule "skip special khi chọn mặc định" đã xử lý ở nhánh idx invalid (idx <0 / >=len).
        # => Không ép idx=1 ở đây nữa.

        tab._selected_index[pid] = idx

        # Tính sap-làng + label cho các item hiển thị
        for s in render_suggs[:tab.MAX_UI_P_ITEMS]:
            if tab._is_special_row(s):
                continue
            if not s.get("_split_key"):
                s["_split_key"] = tab._make_split_key(s)

            # Global: sập làng (vs NGU + 2P còn lại). Flag phải gắn vào suggestion của P.
            lang_win, lang_lose = tab._compute_sap_lang_flags_for_active_suggestion(pid, s)
            s["_sap_lang_win"] = bool(lang_win)
            s["_sap_lang_lose"] = bool(lang_lose)

            # Label gốc (giữ logic cũ)
            s["label_html"] = tab._labeling.build_label_html_vs(s, opp)

            # Thêm phần hiển thị chênh lệch so với base MONEY (ΔB: chi1,chi2,chi3) theo hạng bài
            # if base_for_delta and base_tpl is not None and base_for_delta is not s:
                # deltas = _delta_vs_base_by_rank(s)
                # if deltas is not None:
                    # d1b, d2b, d3b = deltas

                    # def _sign(v: int) -> str:
                        # if v > 0:
                            # return "+"
                        # if v < 0:
                            # return "-"
                        # return "0"

                    # s1 = _sign(d1b)
                    # s2 = _sign(d2b)
                    # s3 = _sign(d3b)

                    # extra = f' <span style="color:#999;">(ΔB: {s1},{s2},{s3})</span>'
                    # if s.get("label_html"):
                        # s["label_html"] += extra
                    # else:
                        # s["label_html"] = extra

        render_suggs = list(render_suggs[:tab.MAX_UI_P_ITEMS])
        tab._suggestions_render[pid] = render_suggs
        tab.view.set_p_labels(render_suggs, idx)

        s = render_suggs[idx] if render_suggs else None
        if s:
            codes = self.build_preview_codes(s)
            if codes:
                tab.view.set_cards_p_normalized(codes)

        if s and tab._is_special_row(s):
            has_split = bool(s.get("chi1_codes")) and bool(s.get("chi2_codes")) and bool(s.get("chi3_codes"))
            tab.view.btn_hup.setEnabled(bool(has_split))
        else:
            tab.view.btn_hup.setEnabled(True)

