# kendz/vision/layout_types.py
"""Các kiểu dữ liệu mô tả layout cho Vision.

Ý tưởng:
- Dùng toạ độ tương đối (0.0 - 1.0) để dễ scale cho nhiều độ phân giải.
- Mỗi lá bài là một `CardRegion` trên frame gốc.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Region:
    """Vùng chữ nhật tương đối trên frame.

    Tất cả các giá trị đều nằm trong khoảng [0.0, 1.0]:

    - x: toạ độ trái (tính theo tỉ lệ chiều rộng)
    - y: toạ độ trên (tính theo tỉ lệ chiều cao)
    - w: chiều rộng vùng
    - h: chiều cao vùng
    """

    x: float
    y: float
    w: float
    h: float


@dataclass
class CardRegion(Region):
    """Vùng tương đối của một lá bài.

    Giai đoạn đầu:
    - Chỉ cần biết vị trí để crop ảnh lá bài từ frame gốc.
    - Thông tin nhận diện (rank/suit) sẽ được gắn sau.
    """

    index: int  # thứ tự lá bài trong 13 lá
