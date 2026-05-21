from __future__ import annotations

from typing import List, Optional
from engine.card import Card

from engine.money_scoring import (
    detect_special_13,
    Special13Type,
    get_special_13_bonus,
)

SPECIAL13_NAME_MAP = {
    Special13Type.SIX_PAIRS: "6 đôi",
    Special13Type.THREE_STRAIGHTS: "3 sảnh",
    Special13Type.THREE_FLUSHES: "3 thùng",
    Special13Type.FIVE_PAIRS_ONE_TRIPS: "5 đôi 1 xám",
    Special13Type.ALL_SAME_COLOR: "Đồng hoa",
    Special13Type.DRAGON: "Sảnh rồng",
    Special13Type.DRAGON_COLOR: "Sảnh rồng đồng hoa",
}

def special_html_7colors(text: str) -> str:
    colors = ["#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#32ade6", "#007aff", "#af52de"]
    parts: List[str] = []
    for i, ch in enumerate(text):
        c = colors[i % len(colors)]
        if ch == " ":
            parts.append("&nbsp;")
        else:
            parts.append(f'<span style="color:{c};">{ch}</span>')
    return "".join(parts)

def build_special_row(
    who: str,
    codes13: List[str],
    *,
    special_mode: str,
    detect_special_13_fn,
) -> Optional[dict]:
    # CÁCH A: dùng engine.money_scoring (chuẩn luật) để detect + build split
    if not codes13 or len(codes13) != 13:
        return None

    try:
        cards = [Card.from_code(c) for c in (codes13 or [])]
    except Exception:
        return None

    special_type = detect_special_13(cards)  # Optional[Special13Type]
    if not special_type:
        return None

    chi_pts = get_special_13_bonus(special_type)
    name = SPECIAL13_NAME_MAP.get(special_type, str(special_type))

    left_icon = "🏆"
    right_icon = "🏆"
    title = f"{left_icon} {name} ({chi_pts} chi) {right_icon}"
    html = (
        "<div style='font-weight:900; font-size:15px; line-height:1.2;'>"
        f"{special_html_7colors(title)}"
        "</div>"
    )

    row = {
        "pid": who,
        "mode": special_mode,
        "variant": -999,
        "label": "[SPECIAL]",
        "label_html": html,
        "_is_special_row": True,

        # Gán thẳng tên bài đặc biệt cho UI dùng
        "special_name": name,
        "is_special": True,
    }
    # Không build split nữa để tránh đơ UI.
    # Special row chỉ dùng để HIỂN THỊ trạng thái bài đặc biệt.
    row["special_has_split"] = False
    return row
    
def inject_special_row(
    who: str,
    codes13: List[str],
    suggs: List[dict],
    *,
    special_mode: str,
    detect_special_13_fn,
) -> List[dict]:
    # Nếu worker đã có special row rồi thì KHÔNG inject nữa (tránh 2 label)
    try:
        if any(bool(s.get("_is_special_row")) for s in (suggs or [])):
            return list(suggs or [])
    except Exception:
        pass

    # fallback cũ: chỉ loại theo mode (để tránh lặp khi UI tự inject nhiều lần)
    base = [s for s in (suggs or []) if str(s.get("mode")) != special_mode]

    row = build_special_row(
        who,
        codes13,
        special_mode=special_mode,
        detect_special_13_fn=detect_special_13_fn,
    )
    if row:
        return [row] + base
    return base

def is_special_row(s: Optional[dict], *, special_mode: str) -> bool:
    if not s:
        return False
    return str(s.get("mode")) == special_mode or bool(s.get("_is_special_row", False))
