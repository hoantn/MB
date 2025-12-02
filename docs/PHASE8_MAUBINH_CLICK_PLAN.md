
# PHASE 8.3–8.4 – Mậu Binh Drag Click Planner (Dry-Run)

## Mục tiêu

- Tự động sinh ra **kế hoạch kéo-thả** (drag & drop) để xếp bài đúng theo gợi ý Engine.
- Mỗi profile trình duyệt hoạt động độc lập:
  - Vision + Recognizer đọc 13 lá.
  - Engine gợi ý chi1/chi2/chi3.
  - Window binding gắn với đúng cửa sổ.
  - Click planner sinh `DragAction` theo thuật toán swap.
- Giai đoạn này: **DRY-RUN** – chỉ log kế hoạch, chưa kéo thật.

## Thành phần

### 1. `kendz.automation.click_actions`

- Thêm `DragAction`:

  ```python
  @dataclass
  class DragAction:
      x_from: int
      y_from: int
      x_to: int
      y_to: int
      delay_before: float = 0.02
      delay_after: float = 0.03
      description: str = ""
  ```

- Hàm `perform_actions(actions, dry_run=True, logger=None)`:
  - Cho phép thực thi hỗn hợp `ClickAction` + `DragAction`.
  - Nếu `dry_run=True` → chỉ log, không gửi chuột thật.

### 2. `kendz.automation.mau_binh_click_plan`

- Hàm `build_drag_plan_for_mau_binh(cards_current, suggestion, self_layout, bound_win) -> list[Action]`:

  - `cards_current`: list 13 mã hiện tại (theo slot 1..13).
  - `suggestion`: `ChiSuggestion` từ Engine.
  - `self_layout`: layout 13 lá cho profile.
  - `bound_win`: cửa sổ trình duyệt (window binding).

- Thuật toán swap:
  - Ghép `target = chi1 + chi2 + chi3`.
  - Duyệt i=0..12:
    - Nếu `curr[i] == target[i]` → bỏ qua.
    - Ngược lại tìm j>i sao cho `curr[j] == target[i]`.
    - Tạo `DragAction` từ slot j -> slot i.
    - Cập nhật `curr` để phản ánh swap.

### 3. `kendz.tools.auto_mau_binh_click_plan_dryrun`

- Vòng lặp:

  1. `capture_and_crop_self_cards(ctx, profile_id)`
  2. `recognize_13_cards(...)` → `cards`.
  3. `suggest_for_13_cards(cards)` → `ChiSuggestion`.
  4. `bind_window_for_profile(...)` → `BoundWindow`.
  5. `LayoutManager.get_self_layout(...)` → `SelfLayout`.
  6. `build_drag_plan_for_mau_binh(...)` → `actions`.
  7. `perform_actions(actions, dry_run=True, logger=logger)`.

- Log chi tiết từng bước drag, ví dụ:

  ```text
  ClickExec: Step 01 [DRAG] from=(800, 720) to=(950, 650) ... desc=Hoán vị lá AH từ slot 5 về slot 2
  ```

## Cách chạy

```bash
# Profile 1
python -m kendz.tools.auto_mau_binh_click_plan_dryrun --profile-id 1

# Profile 2
python -m kendz.tools.auto_mau_binh_click_plan_dryrun --profile-id 2

# Profile 3
python -m kendz.tools.auto_mau_binh_click_plan_dryrun --profile-id 3
```

Mỗi profile nên chạy ở một cửa sổ CMD riêng.

## Hướng sau DRY-RUN

- Khi log kế hoạch drag đã đúng với kỳ vọng của bạn:
  - Bật `dry_run=False` trong `perform_actions` (hoặc thêm config).
  - Khi đó hệ thống sẽ thực sự kéo-thả theo kế hoạch.
- Có thể fine-tune:
  - `delay_before`/`delay_after` trong `DragAction`.
  - Thêm random nhỏ vào delay để tự nhiên hơn.
