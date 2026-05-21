# ui2/tabs/dashboard/dashboard_suggest_worker.py

from __future__ import annotations

from typing import List, Dict, Optional

from PySide6.QtCore import QObject, Signal

from engine.card import Card
from engine.arranger import arrange_cards, ArrangeStrategy
from engine.scorer import score_three_chi

from core.logger import log

from .dashboard_suggest import _extract_money_value
from .dashboard_constants import classify_chis


def build_suggestions_for_codes(
    profile_id: str,
    codes: List[Optional[str]],
    opp_chis: Optional[tuple[List[Card], List[Card], List[Card]]] = None,
) -> List[Dict]:
    """
    Build suggestions cho dashboard worker.

    LƯU Ý:
    - opp_chis giữ lại để tương thích call-site cũ, nhưng KHÔNG dùng.
    - Không còn MAX_MONEY_VS_OPP / score_money_vs_opp.
    """

    cards: List[Card] = []
    for code in codes:
        if not code or code in ("--", "??"):
            continue
        try:
            cards.append(Card.from_code(code))
        except Exception:
            continue

    if len(cards) != 13:
        return []

    modes = [
        ("Tien", "Tiền", ArrangeStrategy.MAX_MONEY),
        ("Max", "Max", ArrangeStrategy.MAX_STRENGTH),
    ]

    suggestions: List[Dict] = []

    for key, label, strat in modes:
        try:
            chi1, chi2, chi3 = arrange_cards(cards, strategy=strat)
        except Exception as e:
            log.debug("DashboardSuggestWorker: arrange_cards failed pid=%s mode=%s err=%s", profile_id, key, e)
            continue

        money_raw = score_three_chi(chi1, chi2, chi3)
        money_val = _extract_money_value(money_raw)
        chi_types = classify_chis(chi1, chi2, chi3)

        suggestions.append(
            {
                "key": key,
                "label": label,
                "chi": (chi1, chi2, chi3),
                "chi_types": chi_types,
                "money": money_val,
                "vs_opp": None,  # VS removed
            }
        )

    return suggestions


class SuggestionWorker(QObject):
    finished = Signal(str)
    suggestions_ready = Signal(str, list)

    def __init__(
        self,
        profile_id: str,
        codes: List[Optional[str]],
        opp_chis: Optional[tuple[List[Card], List[Card], List[Card]]] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.profile_id = profile_id
        self.codes = codes
        self.opp_chis = opp_chis  # kept for compatibility; unused

    def run(self):
        try:
            suggestions = build_suggestions_for_codes(self.profile_id, self.codes, self.opp_chis)
            self.suggestions_ready.emit(self.profile_id, suggestions)
        finally:
            self.finished.emit(self.profile_id)
