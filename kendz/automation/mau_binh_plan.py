from __future__ import annotations

"""Phase 8 – Planner cho Mậu Binh (dry-run).

Mục tiêu:
- Từ kết quả Engine (ChiSuggestion), tạo ra một danh sách các bước (steps)
  mô tả cách xếp bài 3 chi một cách dễ hiểu cho log / debug.
- Chỉ làm "plan" ở mức logic, KHÔNG thực hiện click chuột hay thao tác UI.

Giai đoạn này:
- Không phụ thuộc vào toạ độ màn hình hay layout drag&drop.
- Không ràng buộc vào implementation cụ thể của pyautogui / win32, v.v.
- Đầu ra chỉ là list[str] để log ra console hoặc file.

Khi plan đã ổn, có thể mở rộng:
- Thay vì trả về list[str], trả về list[ClickAction] với thông tin đầy đủ hơn
  để Phase 8 (live) thực hiện click thật.
"""

from dataclasses import dataclass
from typing import List

from kendz.engine.assistant import ChiSuggestion


@dataclass
class StrategyStep:
    """Một bước logic trong kế hoạch đánh Mậu Binh.

    Thuộc tính:
        description: Mô tả tiếng Việt ngắn gọn, dùng để log.
    """

    description: str


def build_strategy_from_suggestion(suggestion: ChiSuggestion) -> List[StrategyStep]:
    """Tạo kế hoạch (strategy) ở mức logic từ kết quả Engine.

    Đầu ra:
        - List các bước StrategyStep, dùng cho log / kiểm tra.
        - Không gắn với toạ độ, index hay thao tác chuột cụ thể.

    Ghi chú:
        - Ở giai đoạn dry-run, thông tin này đủ để chúng ta kiểm tra xem
          Engine đang xếp bài có hợp lý không trước khi code phần auto-click.
    """
    steps: List[StrategyStep] = []

    # Bước 1: mô tả chi tiết 3 chi theo gợi ý
    steps.append(
        StrategyStep(
            description=f"Chi 1 (3 lá): {suggestion.chi1_symbols}",
        )
    )
    steps.append(
        StrategyStep(
            description=f"Chi 2 (5 lá): {suggestion.chi2_symbols}",
        )
    )
    steps.append(
        StrategyStep(
            description=f"Chi 3 (5 lá): {suggestion.chi3_symbols}",
        )
    )

    # Bước 2: trạng thái đặc biệt (nếu có)
    if suggestion.is_binh_lung:
        steps.append(
            StrategyStep(
                description="Bài rơi vào trạng thái BINH LŨNG theo luật Engine.",
            )
        )

    if suggestion.note:
        steps.append(
            StrategyStep(
                description=f"Ghi chú Engine: {suggestion.note}",
            )
        )

    # Bước 3: bước "chung" để chuẩn bị cho việc auto-click sau này
    steps.append(
        StrategyStep(
            description="Thực hiện thao tác kéo/thả lá bài để xếp đúng 3 chi theo gợi ý.",
        )
    )
    steps.append(
        StrategyStep(
            description="Nhấn nút XÁC NHẬN / XẾP BÀI trên giao diện game.",
        )
    )

    return steps
