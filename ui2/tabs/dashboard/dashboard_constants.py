# ui2/dashboard/dashboard_constants.py
from typing import Dict, List, Optional, Tuple
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from core.constants import RANK_ORDER
from core.logger import log
from engine.card import Card

# Suit order giống dashboard Tkinter cũ
SUITS = ["R", "C", "B", "T"]
FULL_DECK: List[str] = [r + s for s in SUITS for r in RANK_ORDER]

# Mapping scan/index → chi theo Option 1:
# 0-2   → chi3 (top, slot 1-3)
# 3-7   → chi2 (mid, slot 4-8)
# 8-12  → chi1 (bottom, slot 9-13)
INDEX_TO_CHI: List[Tuple[str, int]] = (
    [("chi3", i) for i in range(3)]
    + [("chi2", i) for i in range(5)]
    + [("chi1", i) for i in range(5)]
)

RANK_VALUE: Dict[str, int] = {r: i for i, r in enumerate(RANK_ORDER)}

# Cache ảnh lá bài từ vision/opp dùng cho WS mode
_OPP_PIXMAP_CACHE: Dict[Tuple[str, int, int], Optional[QPixmap]] = {}

# THƯ MỤC HIỆN TẠI CỦA MODULE
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _detect_project_root() -> str:
    """
    Trả về root project – nơi có thư mục vision/opp.

    Ưu tiên:
    1) Khi chạy exe (PyInstaller): dùng sys._MEIPASS.
    2) Khi dev: 3 cấp trên của file hiện tại.
    3) Fallback: thư mục chứa executable (cùng chỗ với .exe).
    """
    # 1) PyInstaller bundle
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS  # type: ignore[attr-defined]

    # 2) Dev: ui2/dashboard/ → project root ở 3 cấp trên
    root = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
    if os.path.isdir(os.path.join(root, "vision", "opp")):
        return root

    # 3) Fallback: cùng thư mục với file .exe
    exe_dir = os.path.dirname(getattr(sys, "executable", ""))
    if exe_dir and os.path.isdir(os.path.join(exe_dir, "vision", "opp")):
        return exe_dir

    # Nếu vẫn không thấy, cứ trả về root ước lượng – _load_opp_pixmap sẽ xử lý tiếp
    return root


_PROJECT_ROOT = _detect_project_root()
_OPP_IMG_ROOT = os.path.join(_PROJECT_ROOT, "vision", "opp")



def _load_opp_pixmap(card_code: str, w: int, h: int) -> Optional[QPixmap]:
    """
    Lấy thumbnail lá bài từ thư mục vision/opp theo mã bài (VD: '2B', 'TT', ...).
    File name: {code}.png (ví dụ: '2B.png', 'TT.png').
    Nếu không tồn tại file hoặc lỗi đọc, trả về None.
    """
    key = (card_code, w, h)
    if key in _OPP_PIXMAP_CACHE:
        return _OPP_PIXMAP_CACHE[key]

    try:
        filename = f"{card_code}.png"
        path = os.path.join(_OPP_IMG_ROOT, filename)
        if not os.path.exists(path):
            _OPP_PIXMAP_CACHE[key] = None
            return None
        pix = QPixmap(path)
        if pix.isNull():
            _OPP_PIXMAP_CACHE[key] = None
            return None
        pix = pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        _OPP_PIXMAP_CACHE[key] = pix
        return pix
    except Exception as e:
        log.warning("Không load được opp card image %s: %s", card_code, e)
        _OPP_PIXMAP_CACHE[key] = None
        return None


def _card_rank_code(card: Card) -> str:
    code = card.to_code()
    return code[:-1]


def _classify_five(cards: List[Card]) -> str:
    if len(cards) != 5:
        return "?"
    ranks = [_card_rank_code(c) for c in cards]
    suits = [c.to_code()[-1] for c in cards]

    count_rank: Dict[str, int] = {}
    for r in ranks:
        count_rank[r] = count_rank.get(r, 0) + 1
    counts = sorted(count_rank.values(), reverse=True)

    is_flush = len(set(suits)) == 1

    idxs = sorted(RANK_VALUE[r] for r in ranks)
    is_straight = False
    if max(idxs) - min(idxs) == 4 and len(set(idxs)) == 5:
        is_straight = True

    # Wheel straight: A2345 (A đóng vai trò thấp)
    # ranks: A,2,3,4,5 -> idxs: {12,0,1,2,3} (không thỏa max-min==4)
    if not is_straight:
        if set(idxs) == {0, 1, 2, 3, 12}:
            is_straight = True

    if is_flush and is_straight:
        return "Thùng phá sảnh"
    if counts == [4, 1]:
        return "Tứ quý"
    if counts == [3, 2]:
        return "Cù"
    if is_flush:
        return "Thùng"
    if is_straight:
        return "Sảnh"
    if counts == [3, 1, 1]:
        return "Xám"
    if counts == [2, 2, 1]:
        return "Thú"
    if counts == [2, 1, 1, 1]:
        return "Đôi"
    return "Mậu thầu"


def _classify_three(cards: List[Card]) -> str:
    if len(cards) != 3:
        return "?"
    ranks = [_card_rank_code(c) for c in cards]
    count_rank: Dict[str, int] = {}
    for r in ranks:
        count_rank[r] = count_rank.get(r, 0) + 1
    counts = sorted(count_rank.values(), reverse=True)
    if counts == [3]:
        return "Xám"
    if counts == [2, 1]:
        return "Đôi"
    return "Mậu thầu"


def classify_chis(chi1: List[Card], chi2: List[Card], chi3: List[Card]) -> Tuple[str, str, str]:
    type1 = _classify_five(chi1)
    type2 = _classify_five(chi2)
    type3 = _classify_three(chi3)
    return type1, type2, type3


def hand_type_color(hand_type: str) -> str:
    strong = {"Thùng phá sảnh", "Tứ quý", "Cù"}
    medium = {"Thùng", "Sảnh", "Xám"}
    weak = {"Thú", "Đôi"}
    if hand_type in strong:
        return "#ff8800"
    if hand_type in medium:
        return "#00c8ff"
    if hand_type in weak:
        return "#cccccc"
    return "#aaaaaa"


def _format_suggestion_label(
    label: str,
    money: Optional[float],
    vs_opp: Optional[float],
    chi_types: Tuple[str, str, str],
) -> str:
    """Render text cho ComboBox gợi ý (text thuần, không HTML).

    vs_opp vẫn nhận vào để khỏi phải sửa các chỗ gọi, nhưng sẽ BỎ QUA.
    """
    type1, type2, type3 = chi_types

    strong = {"Thùng phá sảnh", "Tứ quý", "Cù"}
    medium = {"Thùng", "Sảnh", "Xám"}
    types = {type1, type2, type3}

    icon = ""
    if types & strong:
        icon = "🔥"
    elif types & medium:
        icon = "★"

    chi_text = f"{type1} – {type2} – {type3}"

    metrics: List[str] = []
    if money is not None:
        metrics.append(f"T:{int(money)}")
    # KHÔNG còn Vs OPP
    metrics_text = f" ({' | '.join(metrics)})" if metrics else ""

    icon_text = f" {icon}" if icon else ""
    return f"[{label}]{icon_text} {chi_text}{metrics_text}"
