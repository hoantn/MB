# templates.py
from __future__ import annotations

from typing import List, Optional, Tuple

from engine.card import Card
from engine.rules import evaluate_5cards
from engine.money_scoring import evaluate_3cards


TemplateKey = Optional[Tuple[object, object, object]]


def extract_template_key_from_suggestion(s: dict) -> TemplateKey:
    """
    Trả về template key cho 3 chi, dựa trên loại bài của từng chi.

    - Chi 1, 2: dùng evaluate_5cards
    - Chi 3: dùng evaluate_3cards
    - Chỉ lấy thành phần đầu tiên của eval (loại bài) để gom nhóm.
    - Nếu lỗi hoặc không đủ lá -> trả về None.

    Logic được tách ra từ RenderController._filter_dominated_suggestions
    để dùng chung, không đổi hành vi.
    """
    try:
        c1_codes = list(s.get("chi1_codes") or [])
        c2_codes = list(s.get("chi2_codes") or [])
        c3_codes = list(s.get("chi3_codes") or [])

        # Phải đủ 5-5-3 lá
        if len(c1_codes) != 5 or len(c2_codes) != 5 or len(c3_codes) != 3:
            return None

        c1_cards = [Card.from_code(c) for c in c1_codes]
        c2_cards = [Card.from_code(c) for c in c2_codes]
        c3_cards = [Card.from_code(c) for c in c3_codes]

        ev1 = evaluate_5cards(c1_cards)
        ev2 = evaluate_5cards(c2_cards)
        ev3 = evaluate_3cards(c3_cards)

        def _norm(ev):
            # Thường evaluate_* trả tuple: (loại_bài, ...)
            # Ta chỉ cần phần đầu tiên để gom template.
            if isinstance(ev, (tuple, list)) and ev:
                return ev[0]
            return ev

        t1 = _norm(ev1)
        t2 = _norm(ev2)
        t3 = _norm(ev3)
        return (t1, t2, t3)
    except Exception:
        return None


def template_strength_from_key(tpl: TemplateKey) -> Tuple[int, int, int]:
    """
    Điểm mạnh của template:
      - Ưu tiên chi1 mạnh hơn, sau đó đến chi2, chi3.
      - Nếu ev[0] là số (thứ hạng trong engine) thì dùng trực tiếp.
      - Nếu không phải số -> coi như 0 để không lỗi.

    Logic được tách ra từ RenderController._filter_dominated_suggestions
    để có 1 chuẩn duy nhất cho việc sort template.
    """
    if tpl is None:
        return (0, 0, 0)

    try:
        t1, t2, t3 = tpl
    except Exception:
        return (0, 0, 0)

    def _part(v):
        return int(v) if isinstance(v, int) else 0

    return (_part(t1), _part(t2), _part(t3))
