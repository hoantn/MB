
from __future__ import annotations

"""Mậu Binh Click Planner (Phase 8.3 – drag & drop).

Logic:
- Game GO88 Mậu Binh sử dụng cơ chế KÉO-THẢ (drag & drop) để xếp bài.
- 13 lá bài của người chơi được hiển thị cố định trên 3 hàng:
  - Hàng 1: 3 lá (chi 1).
  - Hàng 2: 5 lá (chi 2).
  - Hàng 3: 5 lá (chi 3).
- Engine trả về `ChiSuggestion`:
  - `chi1`, `chi2`, `chi3`: list 3 + 5 + 5 mã bài theo thứ tự slot.

Nhiệm vụ:
- Từ danh sách 13 mã bài hiện tại (đọc từ Vision),
  và gợi ý 13 mã bài đích (chi1+chi2+chi3),
  sinh ra danh sách DragAction để hoán vị các lá bài.

Chiến lược:
- Đơn giản dùng thuật toán swap:
  - Xem mảng `curr[0..12]` là bài hiện tại.
  - Xem mảng `target[0..12]` là bài mong muốn theo chi1+chi2+chi3.
  - Duyệt i từ 0..12:
    - Nếu `curr[i]` đã là `target[i]` -> bỏ qua.
    - Ngược lại tìm j>i sao cho `curr[j] == target[i]`, drag card j -> slot i,
      rồi cập nhật mảng `curr` để phản ánh swap đó.

Như vậy:
- Số thao tác drag tối đa là 12, thường ít hơn.
- Không phụ thuộc vào luật chi tiết của engine (engine quyết định target).

Giai đoạn này:
- Chỉ xây dựng plan (list[DragAction]) và dùng trong chế độ dry-run
  để log ra console; chưa bật auto-click thực tế cho đến khi người dùng đồng ý.
"""  # noqa: D205, D400

from dataclasses import dataclass
from typing import List, Sequence

from kendz.automation.click_actions import DragAction, Action
from kendz.automation.window_binding import BoundWindow
from kendz.engine.assistant import ChiSuggestion
from kendz.vision.layout_manager import SelfLayout


@dataclass
class SlotPos:
    """Vị trí 1 slot bài (tương ứng 1 lá) tính theo pixel trên màn hình."""  # noqa: D205, D400

    index: int
    x: int
    y: int


def _flatten_target_order(suggestion: ChiSuggestion) -> List[str]:
    """Ghép chi1+chi2+chi3 thành list 13 mã bài theo đúng thứ tự slot."""  # noqa: D401
    return list(suggestion.chi1) + list(suggestion.chi2) + list(suggestion.chi3)


def compute_slot_positions(self_layout: SelfLayout, bound_win: BoundWindow) -> List[SlotPos]:
    """Tính toạ độ tâm từng slot bài từ layout + bound window.

    - `self_layout.card_regions` phải chứa đúng 13 vùng, index 1..13.
    - Kết quả trả về list SlotPos có độ dài 13, index 0..12 ứng với slot 1..13.
    """  # noqa: D401
    regions = sorted(self_layout.card_regions, key=lambda r: r.index)
    slots: List[SlotPos] = []
    for r in regions:
        x_rel = r.x + r.w / 2.0
        y_rel = r.y + r.h / 2.0
        x_px, y_px = bound_win.to_screen_from_rel(x_rel, y_rel)
        slots.append(SlotPos(index=r.index, x=x_px, y=y_px))
    return slots


def build_drag_plan_for_mau_binh(
    cards_current: Sequence[str],
    suggestion: ChiSuggestion,
    self_layout: SelfLayout,
    bound_win: BoundWindow,
) -> List[Action]:
    """Sinh plan drag để biến `cards_current` thành hand theo `suggestion`.

    Args:
        cards_current: List 13 mã bài hiện tại, theo thứ tự slot 1..13.
        suggestion: Gợi ý chi1/chi2/chi3 từ engine.
        self_layout: Layout 13 lá (self_cards) cho profile hiện tại.
        bound_win: Cửa sổ trình duyệt đã bind (dùng để đổi rel->pixel).

    Returns:
        List[Action] (hiện tại chỉ gồm DragAction) mô tả các bước kéo-thả.
    """  # noqa: D401
    if len(cards_current) != 13:
        raise ValueError(f"Cần đúng 13 lá, hiện có {len(cards_current)}: {cards_current}")

    target = _flatten_target_order(suggestion)
    if len(target) != 13:
        raise ValueError(f"Gợi ý engine không đủ 13 lá: {target}")

    # Sao chép mảng hiện tại để thao tác
    curr = list(cards_current)
    actions: List[Action] = []

    # Tính toạ độ slot
    slots = compute_slot_positions(self_layout, bound_win)

    # Duyệt từng slot, hoán vị cho khớp target
    for i in range(13):
        if curr[i] == target[i]:
            continue

        # Tìm slot j>i chứa lá target[i]
        try:
            j = curr.index(target[i], i + 1)
        except ValueError as exc:  # noqa: BLE001
            raise ValueError(
                f"Không tìm thấy lá {target[i]!r} cần cho slot {i}, curr={curr}",
            ) from exc

        # Tạo DragAction: kéo từ slot j -> slot i
        src = slots[j]
        dst = slots[i]
        actions.append(
            DragAction(
                x_from=src.x,
                y_from=src.y,
                x_to=dst.x,
                y_to=dst.y,
                delay_before=0.03,
                delay_after=0.04,
                description=f"Hoán vị lá {curr[j]} từ slot {j+1} về slot {i+1}",
            ),
        )

        # Cập nhật mảng curr để phản ánh swap
        curr[i], curr[j] = curr[j], curr[i]

    return actions
