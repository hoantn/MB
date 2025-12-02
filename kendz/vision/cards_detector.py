# kendz/vision/cards_detector.py
"""Nhận diện lá bài từ frame.

Phase 3:
- Chỉ tạo skeleton và mô hình dữ liệu.
- Chưa hiện thực hoá thuật toán nhận diện thực sự (sẽ làm ở phase sau).

Ý tưởng:
- Hàm detect_cards() nhận vào:
  + frame gốc (numpy.ndarray)
  + danh sách CardRegion (vị trí các lá bài)
- Trả về:
  + danh sách CardDetectionResult, chứa:
    * index lá bài
    * hình crop
    * (tạm thời) rank/suit là None (chưa nhận diện)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from kendz.vision.layout_types import CardRegion


@dataclass
class CardDetectionResult:
    """Kết quả nhận diện một lá bài (skeleton).

    Giai đoạn này:
    - rank/suit tạm thời để None.
    - confidence mặc định là 0.0 (sẽ cập nhật sau).
    """

    index: int
    image: np.ndarray
    rank: Optional[str] = None
    suit: Optional[str] = None
    confidence: float = 0.0


def crop_card(frame: np.ndarray, region: CardRegion) -> np.ndarray:
    """Crop ảnh lá bài từ frame dựa trên CardRegion (toạ độ tương đối)."""
    h, w, _ = frame.shape
    x = int(region.x * w)
    y = int(region.y * h)
    cw = int(region.w * w)
    ch = int(region.h * h)

    # Bảo vệ để không vượt khỏi frame
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))
    cw = max(1, min(cw, w - x))
    ch = max(1, min(ch, h - y))

    return frame[y : y + ch, x : x + cw].copy()


def detect_cards(frame: np.ndarray, card_regions: List[CardRegion]) -> List[CardDetectionResult]:
    """Hàm skeleton nhận diện lá bài.

    Hiện tại:
    - Chỉ crop lá bài theo vùng region
    - Chưa đoán rank/suit (sẽ làm ở phase sau)
    - Đặt confidence = 0.0

    Mục đích:
    - Kiểm tra pipeline Vision:
      + capture -> crop -> (sau này nhận diện) -> emit event
    """
    results: List[CardDetectionResult] = []
    for region in card_regions:
        card_img = crop_card(frame, region)
        results.append(
            CardDetectionResult(
                index=region.index,
                image=card_img,
                rank=None,
                suit=None,
                confidence=0.0,
            )
        )
    return results
