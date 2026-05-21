from typing import Dict, List, Optional, Tuple
import threading

from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QTimer

from core.logger import log
from engine.card import Card
from engine.arranger import arrange_13_cards, arrange_cards, ArrangeStrategy
from engine.scorer import score_three_chi
# ĐÃ BỎ: score_matchup_detail (VS OPP) để tránh nặng/đơ

from engine.action import apply_arrangement

# ĐÃ BỎ: ThreeChi, score_money_vs_opp (VS OPP)

from .dashboard_constants import (
    classify_chis,
    hand_type_color,
    _format_suggestion_label,
)


# -------------------------------------------------
# Helper dùng chung cho phần money
# -------------------------------------------------
def _extract_money_value(raw: object) -> Optional[float]:
    """
    Chuẩn hóa giá trị trả về từ score_three_chi:

    - Nếu là tuple/list => lấy phần tử đầu.
    - Nếu là số => cast float.
    - Nếu kiểu khác => trả về None.
    """
    try:
        if isinstance(raw, (tuple, list)) and raw:
            raw = raw[0]
        if isinstance(raw, (int, float)):
            return float(raw)
        return float(raw)  # thử cast string -> float
    except Exception:
        return None


# -------------------------------------------------
# Lấy 13 lá bài đã quét cho 1 profile
# -------------------------------------------------
def get_scanned_cards_impl(self, pid: str) -> Optional[List[Card]]:
    codes = self.card_codes_flat.get(pid, [])
    usable = [c for c in codes if c and c not in ("--", "??")]
    if len(usable) != 13:
        return None
    return [Card.from_code(c) for c in usable]


# -------------------------------------------------
# Build list gợi ý cho 1 profile (Tiền / Max)
# -------------------------------------------------
def build_suggestions_for_profile_impl(self, profile_id: str) -> None:
    combo = self.suggestion_combos.get(profile_id)
    if combo is None:
        return

    cards = self._get_scanned_cards(profile_id)
    combo.clear()
    self.suggestions[profile_id] = []

    if not cards or len(cards) != 13:
        combo.addItem("Thiếu bài (chưa đủ 13 lá) – hãy Scan lại")
        combo.setEnabled(False)
        return

    combo.setEnabled(True)

    # Chỉ còn 2 chế độ: Tiền, Max – KHÔNG còn Vs OPP
    modes: List[Tuple[str, str, ArrangeStrategy]] = [
        ("money", "Tiền", ArrangeStrategy.MAX_MONEY),
        ("max", "Max", ArrangeStrategy.MAX_STRENGTH),
    ]

    suggestions: List[dict] = []

    for key, label, strat in modes:
        try:
            # KHÔNG còn nhánh MAX_MONEY_VS_OPP
            chi1, chi2, chi3 = arrange_cards(cards, strategy=strat)
        except Exception as e:
            log.error(
                "Dashboard _build_suggestions_for_profile(%s, %s) lỗi arrange_cards: %s",
                profile_id,
                key,
                e,
            )
            continue

        # Tính "Tiền" bằng score_three_chi như cũ (tự thân)
        money_raw = score_three_chi(chi1, chi2, chi3)
        money_val = _extract_money_value(money_raw)

        chi_types = classify_chis(chi1, chi2, chi3)

        # VS OPP đã loại bỏ hoàn toàn
        vs_opp_val = None

        suggestions.append(
            {
                "key": key,
                "label": label,
                "chi": (chi1, chi2, chi3),
                "chi_types": chi_types,
                "money": money_val,
                "vs_opp": vs_opp_val,
            }
        )

    if not suggestions:
        combo.addItem("Không tạo được gợi ý – xem log")
        combo.setEnabled(False)
        return

    # Sắp xếp: Tiền trước, Max sau
    order_weight = {"Tiền": 0, "Max": 1}

    def sort_key(s: dict) -> int:
        return order_weight.get(s["label"], 99)

    suggestions_sorted = sorted(suggestions, key=sort_key)

    self.suggestions[profile_id] = suggestions_sorted

    for s in suggestions_sorted:
        label_text = _format_suggestion_label(
            s["label"],
            s["money"],
            s["vs_opp"],   # luôn None
            s["chi_types"],
        )
        combo.addItem(label_text)

    self._on_suggestion_changed(profile_id)


# -------------------------------------------------
# Nút “Gợi ý” (nếu bạn có dùng)
# -------------------------------------------------
def suggest_for_impl(self, profile_id: str) -> None:
    """
    Giữ behavior đơn giản: luôn dùng gợi ý đầu tiên sau khi build.
    """
    self._build_suggestions_for_profile(profile_id)
    suggs = self.suggestions.get(profile_id) or []
    if not suggs:
        return

    chi1, chi2, chi3 = suggs[0]["chi"]
    self.update_engine_panel(
        focus_profile=profile_id,
        forced_chis={profile_id: (chi1, chi2, chi3)},
    )


# -------------------------------------------------
# Khi chọn item khác trong combobox gợi ý
# -------------------------------------------------
def on_suggestion_changed_impl(self, profile_id: str) -> None:
    combo = self.suggestion_combos.get(profile_id)
    suggs = self.suggestions.get(profile_id) or []
    if combo is None or not suggs:
        return

    idx = combo.currentIndex()
    if idx < 0 or idx >= len(suggs):
        idx = 0

    suggestion = suggs[idx]
    chi1, chi2, chi3 = suggestion["chi"]

    # Lưu chi preview cho đúng profile đó
    self.preview_chis[profile_id] = (chi1, chi2, chi3)

    self.refresh_all_views()
    self.update_engine_panel(focus_profile=profile_id)


# -------------------------------------------------
# Áp dụng gợi ý lên game (drag bài)
# -------------------------------------------------
def apply_suggestion_for_impl(self, profile_id: str) -> None:
    """
    Giữ nguyên logic apply của anh.
    """
    cards = self._get_scanned_cards(profile_id)
    if not cards or len(cards) != 13:
        QMessageBox.information(
            self,
            "Thiếu bài",
            f"Profile {profile_id} chưa đủ 13 lá để xếp.",
        )
        return

    mode_index = 0
    try:
        if self.engine_mode_max.isChecked():
            mode_index = 1
    except Exception:
        mode_index = 0

    suggs = self.suggestions.get(profile_id) or []
    if suggs:
        if mode_index >= len(suggs):
            mode_index = 0
        chi1, chi2, chi3 = suggs[mode_index]["chi"]
    else:
        chi1, chi2, chi3 = arrange_13_cards(cards)

    ws_codes: List[str] = [c.to_code() for c in cards]
    current_codes: List[str] = ws_codes

    try:
        if not hasattr(self, "_layout_codes"):
            self._layout_codes = {}  # type: ignore[attr-defined]
        cached = self._layout_codes.get(profile_id)  # type: ignore[attr-defined]
        if isinstance(cached, list) and len(cached) == 13 and sorted(cached) == sorted(ws_codes):
            current_codes = list(cached)
        else:
            self._layout_codes[profile_id] = list(ws_codes)  # type: ignore[attr-defined]
    except Exception:
        current_codes = ws_codes

    if not hasattr(self, "_apply_threads"):
        self._apply_threads = {}  # type: ignore[attr-defined]

    try:
        running = self._apply_threads.get(profile_id)  # type: ignore[index]
    except Exception:
        running = None

    if running is not None and running.is_alive():
        QMessageBox.information(
            self,
            "Đang áp dụng",
            f"{profile_id} đang áp dụng gợi ý lên game, vui lòng đợi hoàn tất trước khi chạy lại.",
        )
        return

    try:
        self._apply_btn_set_busy(profile_id)
    except Exception:
        pass

    def _worker_apply():
        try:
            try:
                delay_ms = int(getattr(self, "ui_apply_delay_ms").value())  # type: ignore[attr-defined]
            except Exception:
                delay_ms = 10
            delay_s = max(0.0, float(delay_ms) / 1000.0)
            res_codes = apply_arrangement(
                profile_id,
                self.browser_manager,
                current_codes,
                chi1,
                chi2,
                chi3,
                delay_s=delay_s,
            )
            try:
                if not hasattr(self, "_layout_codes"):
                    self._layout_codes = {}  # type: ignore[attr-defined]
                if isinstance(res_codes, list) and len(res_codes) == 13:
                    self._layout_codes[profile_id] = list(res_codes)  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception as e:
            log.error(
                "Dashboard apply_suggestion_for (thread) lỗi apply_arrangement cho %s: %s",
                profile_id,
                e,
            )
        finally:
            try:
                self._apply_threads.pop(profile_id, None)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                QTimer.singleShot(0, lambda p=profile_id: self._apply_btn_set_default(p))
            except Exception:
                pass

    t = threading.Thread(
        target=_worker_apply,
        name=f"MB-Apply-{profile_id}",
        daemon=True,
    )
    self._apply_threads[profile_id] = t  # type: ignore[attr-defined]
    t.start()

    self.preview_chis[profile_id] = (chi1, chi2, chi3)
    self.refresh_all_views()
    self.update_engine_panel(
        focus_profile=profile_id,
        forced_chis={profile_id: (chi1, chi2, chi3)},
    )
    self._set_profile_state(profile_id, "applied")


# -------------------------------------------------
# Panel Engine bên dưới (tóm tắt OPP + P1/2/3)
# -------------------------------------------------
def update_engine_panel_impl(
    self,
    focus_profile: Optional[str] = None,
    forced_chis: Optional[
        Dict[str, Tuple[List[Card], List[Card], List[Card]]]
    ] = None,
) -> None:
    """
    Cập nhật bảng Engine – chỉ hiển thị hạng bài từng chi để so bằng mắt.
    ĐÃ BỎ: toàn bộ tính toán đối đầu P1/P2/P3 vs OPP (score_matchup_detail).
    """
    if not getattr(self, "engine_summary_labels", None):
        return

    mode_index = 0
    try:
        if getattr(self, "engine_mode_max", None) is not None and self.engine_mode_max.isChecked():
            mode_index = 1
    except Exception:
        mode_index = 0

    strategy = ArrangeStrategy.MAX_MONEY if mode_index == 0 else ArrangeStrategy.MAX_STRENGTH

    def build_html_for_chis(
        chi1: List[Card],
        chi2: List[Card],
        chi3: List[Card],
    ) -> str:
        type1, type2, type3 = classify_chis(chi1, chi2, chi3)

        strong = {"Thùng phá sảnh", "Tứ quý", "Cù"}
        medium = {"Thùng", "Sảnh", "Xám"}

        def piece(hand_type: str) -> str:
            color = hand_type_color(hand_type)
            icon = ""
            if hand_type in strong:
                icon = "🔥 "
            elif hand_type in medium:
                icon = "★ "
            return f"<span style='color:{color};font-weight:bold;'>{icon}{hand_type}</span>"

        return f"{piece(type1)} - {piece(type2)} - {piece(type3)}"

    # 1) Thu thập chi cho từng row (OPP + P1/P2/P3)
    rows: List[str] = ["OPP"] + list(self.profiles)

    chis_by_row: Dict[str, Tuple[List[Card], List[Card], List[Card]]] = {}
    labels_by_row: Dict[str, object] = {}

    for row in rows:
        if row == "OPP":
            label = getattr(self, "engine_opp_label", None)
        else:
            label = self.engine_summary_labels.get(row)

        if label is None:
            continue

        labels_by_row[row] = label
        tpl: Optional[Tuple[List[Card], List[Card], List[Card]]] = None

        if forced_chis and row in forced_chis:
            tpl = forced_chis[row]
        elif self.preview_chis.get(row):
            tpl = self.preview_chis[row]
        else:
            cards = self._get_scanned_cards(row)
            if not cards:
                valid_cnt = len([c for c in self.card_codes_flat.get(row, []) if c and c not in ("--", "??")])
                label.setText(f"Thiếu bài ({valid_cnt}/13)")
                continue

            if len(cards) != 13:
                label.setText(f"Thiếu bài ({len(cards)}/13)")
                continue

            try:
                # OPP cũng chỉ xếp tự thân theo strategy đang chọn (Tiền/Max)
                if row == "OPP":
                    chi1, chi2, chi3 = arrange_cards(cards, strategy=strategy)
                else:
                    chi1, chi2, chi3 = arrange_13_cards(cards)
                tpl = (chi1, chi2, chi3)
            except Exception as e:
                log.error("update_engine_panel: lỗi arrange cho %s: %s", row, e)
                label.setText("Lỗi xếp bài")
                continue

        if not tpl:
            label.setText("Thiếu bài (0/13)")
            continue

        chis_by_row[row] = tpl

    # 2) Render (không còn matchup)
    for row, label in labels_by_row.items():
        tpl = chis_by_row.get(row)
        if not tpl:
            continue
        chi1, chi2, chi3 = tpl
        label.setText(build_html_for_chis(chi1, chi2, chi3))
