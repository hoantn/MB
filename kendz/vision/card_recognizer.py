from __future__ import annotations

"""Recognizer 52 lá (rank + suit) cho Mậu Binh GO88.

Phase 9 – Tối ưu hoá:

Mục tiêu:
- Ổn định, dễ bảo trì, mở rộng cho nhiều site (siteA, siteB, siteC).
- Tăng độ chính xác trong điều kiện chơi thật:
  + Lá bị tối / hiệu ứng.
  + Crop hơi lệch.
  + Dễ nhầm 2/3/5/6/8/9.

Chiến lược:
- Template-based như cũ, dùng 52 template trong `data/card_templates/<game_id>/`.
- Ưu tiên nhận diện CHẤT (suit) trước:
  1. Cắt ROI góc trên-trái (rank+suit).
  2. Ước lượng màu (RED / BLACK) bằng HSV.
  3. Chỉ xét group suit tương ứng:
     * RED  -> H, D
     * BLACK -> S, C
  4. Duyệt template trong group suit, lấy best_code, best_score, second_score.
- Chuẩn hoá độ sáng ROI bằng min-max normalize.
- Thêm khái niệm "độ tự tin":
  + is_confident = False nếu:
    * best_score < min_score, hoặc
    * best_score - second_score < min_margin.

Giao diện API giữ nguyên để không phá vỡ code cũ:
- RecognizedCard
- CardRecognizer(base_dir, game_id, target_size=(40, 40))
- recognize_card(img_bgr)
- recognize_card_path(path)
- recognize_folder(folder)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np

# Map suit -> ký hiệu
SUIT_SYMBOLS: Dict[str, str] = {
    "C": "♣",
    "D": "♦",
    "H": "♥",
    "S": "♠",
}

# Map suit -> màu (đỏ/đen)
SUIT_COLOR: Dict[str, str] = {
    "C": "BLACK",
    "S": "BLACK",
    "D": "RED",
    "H": "RED",
}


@dataclass
class RecognizedCard:
    code: str                 # VD: "2C", "AH"
    suit: str                 # "C","D","H","S"
    score: float              # score template tốt nhất
    second_score: float       # score template nhì tốt nhất
    best_match_path: str | None = None
    is_confident: bool = True  # Phase 9: cờ đánh dấu độ tin cậy
    confidence_margin: float = 0.0


class CardRecognizer:
    """Recognizer template-based cho 1 game_id.

    target_size: kích thước chuẩn cho ROI rank+suit (w, h).

    Lưu ý:
    - Không phụ thuộc trực tiếp vào AppContext để đảm bảo module Vision
      có thể dùng độc lập (test, tool nhỏ...).
    """

    def __init__(
        self,
        base_dir: Path,
        game_id: str,
        target_size: Tuple[int, int] = (40, 40),
        min_score: float = 0.75,
        min_margin: float = 0.03,
    ) -> None:
        self.base_dir = base_dir
        self.game_id = game_id
        self.target_size = target_size

        # Ngưỡng confidence (có thể chỉnh từ config hoặc code)
        self.min_score = min_score
        self.min_margin = min_margin

        # templates["QH"] = roi_gray
        self.templates: Dict[str, np.ndarray] = {}
        # templates_by_suit["H"] = [("QH", roi), ("2H", roi), ...]
        self.templates_by_suit: Dict[str, List[Tuple[str, np.ndarray]]] = {
            "C": [],
            "D": [],
            "H": [],
            "S": [],
        }

        self._load_templates()

    # ------------------------------------------------------------------
    # Template loading
    # ------------------------------------------------------------------
    def _load_templates(self) -> None:
        """Đọc toàn bộ template trong data/card_templates/<game_id>.

        Hỗ trợ cả:
        - File tên dạng: '2C.png', 'TD.png', 'AH.png' (1 template / lá).
        - Và dạng có biến thể: '2C_1.png', '2C_2.png', ... (nhiều template / lá).

        Quy ước:
        - 2 ký tự đầu tiên của tên file là mã lá bài (rank + suit), ví dụ: '2H', 'TD'.
        - Phần còn lại (sau dấu '_', nếu có) là chỉ số / tham số biến thể.
        """
        tpl_dir = self.base_dir / "data" / "card_templates" / self.game_id
        if not tpl_dir.exists():
            raise FileNotFoundError(f"Không tìm thấy thư mục template: {tpl_dir}")

        # Xoá dữ liệu cũ (nếu có) rồi load lại
        self.templates.clear()
        for k in self.templates_by_suit:
            self.templates_by_suit[k] = []

        for p in sorted(tpl_dir.glob("*.png")):
            stem = p.stem.upper()  # ví dụ: "2H" hoặc "2H_1"
            if len(stem) < 2:
                continue

            code = stem[:2]
            rank, suit = code[0], code[1]
            if suit not in {"C", "D", "H", "S"}:
                continue

            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue

            roi = self._preprocess_roi(img)

            # Lưu 1 template "chuẩn" cho mỗi lá (dùng cho fallback toàn bộ template)
            # Nếu có nhiều biến thể, chỉ lấy template đầu tiên làm chuẩn.
            if code not in self.templates:
                self.templates[code] = roi

            # Lưu tất cả biến thể vào templates_by_suit để _match_templates so sánh hết.
            self.templates_by_suit[suit].append((code, roi))

    # ------------------------------------------------------------------
    # ROI / tiền xử lý
    # ------------------------------------------------------------------
    def _extract_roi_gray(self, img_bgr: np.ndarray) -> np.ndarray:
        """Cắt ROI góc trên-trái nơi hiển thị rank+suit (grayscale).

        Tỉ lệ hiện tại:
        - 32% chiều cao
        - 35% chiều ngang phía trái

        Sau này nếu đổi layout, chỉ cần chỉnh tỉ lệ hoặc đưa ra config.
        """
        h, w = img_bgr.shape[:2]
        roi = img_bgr[0 : int(0.32 * h), 0 : int(0.35 * w)]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        return gray

    def _extract_roi_color(self, img_bgr: np.ndarray) -> np.ndarray:
        """Cắt ROI dùng để ước lượng màu (RED/BLACK)."""
        h, w = img_bgr.shape[:2]
        roi = img_bgr[0 : int(0.32 * h), 0 : int(0.35 * w)]
        return roi

    def _preprocess_roi(self, gray: np.ndarray) -> np.ndarray:
        """Chuẩn hoá ROI:

        - Resize về kích thước target.
        - Normalize histogram để giảm ảnh hưởng độ sáng.
        """
        resized = cv2.resize(gray, self.target_size, interpolation=cv2.INTER_AREA)
        min_val, max_val, _, _ = cv2.minMaxLoc(resized)
        if max_val > min_val:
            norm = (resized - min_val) * (255.0 / (max_val - min_val))
            norm = norm.astype("uint8")
        else:
            norm = resized
        return norm

    def _estimate_color_group(self, roi_bgr: np.ndarray) -> str:
        """Ước lượng màu chính của lá: 'RED' hoặc 'BLACK'.

        Dùng không gian HSV:
        - Nếu số pixel có Hue nằm vùng đỏ + Saturation cao chiếm tỷ lệ lớn -> RED.
        - Ngược lại -> BLACK.
        """
        hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)

        red_mask1 = (h < 10) & (s > 80)
        red_mask2 = (h > 160) & (s > 80)
        red_pixels = int(np.count_nonzero(red_mask1 | red_mask2))
        total = roi_bgr.shape[0] * roi_bgr.shape[1]

        if total == 0:
            return "UNKNOWN"

        ratio = red_pixels / float(total)
        if ratio > 0.15:
            return "RED"
        return "BLACK"

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------
    def _match_templates(
        self,
        roi_gray: np.ndarray,
        candidates: List[Tuple[str, np.ndarray]],
    ) -> Tuple[str, float, float]:
        """Tìm template phù hợp nhất trong danh sách candidates.

        Trả về:
        - best_code
        - best_score
        - second_best_score
        """
        best_code = ""
        best_score = -1.0
        second_score = -1.0

        for code, tpl in candidates:
            if tpl.shape != roi_gray.shape:
                tpl_resized = cv2.resize(tpl, (roi_gray.shape[1], roi_gray.shape[0]))
            else:
                tpl_resized = tpl

            res = cv2.matchTemplate(roi_gray, tpl_resized, cv2.TM_CCOEFF_NORMED)
            score = float(res.max())

            if score > best_score:
                second_score = best_score
                best_score = score
                best_code = code
            elif score > second_score:
                second_score = score

        return best_code, best_score, second_score

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def recognize_card(self, img_bgr: np.ndarray) -> RecognizedCard:
        """Nhận diện 1 lá bài từ ảnh BGR toàn lá bài."""
        if not self.templates:
            raise RuntimeError("Chưa load template nào.")

        # 1) Cắt ROI
        roi_gray_raw = self._extract_roi_gray(img_bgr)
        roi_gray = self._preprocess_roi(roi_gray_raw)
        roi_color = self._extract_roi_color(img_bgr)

        # 2) Ước lượng màu
        color_group = self._estimate_color_group(roi_color)

        # 3) Xác định danh sách candidate theo màu
        if color_group == "RED":
            candidate_suits = ["H", "D"]
        elif color_group == "BLACK":
            candidate_suits = ["S", "C"]
        else:
            candidate_suits = ["C", "D", "H", "S"]

        candidates: List[Tuple[str, np.ndarray]] = []
        for suit in candidate_suits:
            candidates.extend(self.templates_by_suit.get(suit, []))

        # Nếu vì lý do gì đó không có candidate, fallback dùng toàn bộ template
        if not candidates:
            candidates = list(self.templates.items())

        # 4) Matching
        best_code, best_score, second_score = self._match_templates(roi_gray, candidates)
        suit = best_code[1] if len(best_code) == 2 else "?"

        # 5) Đánh giá độ tự tin
        margin = 0.0
        if second_score >= 0:
            margin = best_score - second_score

        is_confident = True
        if best_score < self.min_score or margin < self.min_margin:
            is_confident = False

        return RecognizedCard(
            code=best_code,
            suit=suit,
            score=best_score,
            second_score=second_score,
            is_confident=is_confident,
            confidence_margin=margin,
        )

    def recognize_card_path(self, img_path: Path) -> RecognizedCard:
        img = cv2.imread(str(img_path))
        if img is None:
            raise FileNotFoundError(img_path)
        result = self.recognize_card(img)
        result.best_match_path = str(img_path)
        return result

    def recognize_folder(self, folder: Path) -> List[RecognizedCard]:
        cards: List[RecognizedCard] = []
        for p in sorted(folder.glob("card_*.png")):
            try:
                rc = self.recognize_card_path(p)
                cards.append(rc)
            except Exception:
                continue
        return cards
