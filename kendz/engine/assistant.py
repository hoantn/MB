from __future__ import annotations

"""Engine assistant helpers (phiên bản đồng bộ với engine hiện tại).

Tầng này đứng giữa Vision và Engine core:
- Nhận 13 lá dưới dạng mã string: ["2C", "JD", ..., "9H"].
- Dùng `kendz.engine.cards.parse_card` để chuyển sang `Card` chuẩn.
- Gọi `arrange_advanced` để xếp bài tối ưu.
- Chuẩn hoá output thành struct đơn giản để UI / tool (Assist, GUI) dùng.

Mục tiêu:
- Hoàn toàn KHÔNG động đến logic trong arranger/evaluator.
- Chỉ đóng vai trò adapter (chuyển đổi dữ liệu + format hiển thị).
"""

from dataclasses import dataclass
from typing import List

from kendz.engine.arranger import arrange_advanced
from kendz.engine.cards import Card, parse_card
from kendz.vision.card_recognizer import SUIT_SYMBOLS


def _codes_to_cards(codes: List[str]) -> List[Card]:
    """Chuyển list mã bài ("AS", "7D", ...) thành list `Card`.

    Hàm này đảm bảo:
    - Mọi mã đều hợp lệ theo chuẩn engine (RANK_ORDER + SUIT_ORDER).
    - Nếu có lỗi sẽ raise ValueError kèm thông tin cụ thể để dễ debug.
    """
    cards: List[Card] = []
    for code in codes:
        if not isinstance(code, str):
            raise ValueError(f"Mã lá bài phải là string, nhận: {code!r}")
        code = code.strip().upper()
        if len(code) != 2:
            raise ValueError(f"Mã lá bài không hợp lệ (không đủ 2 ký tự): {code!r}")
        card = parse_card(code)
        cards.append(card)
    return cards


def format_cards_with_symbols(codes: List[str]) -> str:
    """Đổi list mã bài thành chuỗi có kí hiệu ♣ ♦ ♥ ♠.

    Ví dụ:
    - ["2C", "JD"] -> "2♣ J♦".
    - Nếu mã kỳ lạ -> in thẳng string để dễ debug.
    """
    parts: List[str] = []
    for code in codes:
        if not isinstance(code, str) or len(code) != 2:
            parts.append(str(code))
            continue
        rank, suit = code[0], code[1]
        sym = SUIT_SYMBOLS.get(suit, "?")
        parts.append(f"{rank}{sym}")
    return " ".join(parts)


@dataclass
class ChiSuggestion:
    """Kết quả gợi ý xếp bài cho 13 lá.

    - chi1 / chi2 / chi3: list mã bài (string), không dùng trực tiếp Card
      để layer trên (UI) đơn giản hoá.
    - is_binh_lung: engine đánh dấu thế bài bị lủng.
    - note: mô tả ngắn từ engine (heuristic, bài đặc biệt...).
    """

    chi1: List[str]          # 3 lá (trên)
    chi2: List[str]          # 5 lá (giữa)
    chi3: List[str]          # 5 lá (dưới)
    is_binh_lung: bool
    note: str

    @property
    def chi1_symbols(self) -> str:
        return format_cards_with_symbols(self.chi1)

    @property
    def chi2_symbols(self) -> str:
        return format_cards_with_symbols(self.chi2)

    @property
    def chi3_symbols(self) -> str:
        return format_cards_with_symbols(self.chi3)


def suggest_for_13_cards(codes: List[str]) -> ChiSuggestion:
    """Nhận 13 mã bài (string) và trả về gợi ý xếp bài.

    - `codes`: list 13 mã, ví dụ ["2C", "JD", "AH", ...].

    Adapter này:
    1) Chuyển sang list `Card` chuẩn bằng `_codes_to_cards`.
    2) Gọi `arrange_advanced` (engine core).
    3) Convert ngược kết quả `ArrangedHand` về list mã string.
    """
    if len(codes) != 13:
        raise ValueError(f"Cần đúng 13 lá, hiện có {len(codes)}: {codes}")

    # 1) Convert sang Card chuẩn của engine
    cards = _codes_to_cards(codes)

    # 2) Gọi engine core
    arranged = arrange_advanced(cards)

    # 3) Convert kết quả về mã string
    chi1_codes = [c.to_code() for c in arranged.chi1.cards]
    chi2_codes = [c.to_code() for c in arranged.chi2.cards]
    chi3_codes = [c.to_code() for c in arranged.chi3.cards]

    return ChiSuggestion(
        chi1=chi1_codes,
        chi2=chi2_codes,
        chi3=chi3_codes,
        is_binh_lung=arranged.is_lung,
        note=arranged.notes,
    )
