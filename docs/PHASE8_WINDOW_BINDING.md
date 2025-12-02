
# PHASE 8 – Window Binding (Chuẩn bị Auto-Click)

## Mục tiêu

- Mỗi process Kendz gắn (bind) với **đúng một cửa sổ trình duyệt**.
- Ánh xạ được toạ độ **tương đối (layout)** sang toạ độ **pixel trên màn hình**.
- Kiểm tra việc cấu hình `automation.yaml` + title cửa sổ đã chính xác trước khi auto-click.

## File liên quan

### 1. `config/automation.yaml`

Ví dụ cấu trúc:

```yaml
mau_binh_siteA:
  profiles:
    1:
      window_title_keyword: "GO88 - P1"
    2:
      window_title_keyword: "GO88 - P2"
    3:
      window_title_keyword: "GO88 - P3"
```

- `window_title_keyword`: đoạn text có trong title cửa sổ trình duyệt của profile tương ứng.
- Tool sẽ tìm cửa sổ có `title` chứa substring này (case-insensitive).

### 2. `kendz.automation.window_binding`

- `find_window_by_title_keyword(keyword) -> BoundWindow | None`
- `bind_window_for_profile(game_id, profile_id, project_root, config_file="config/automation.yaml") -> BoundWindow`
- `BoundWindow.to_screen_from_rel(x_rel, y_rel)`:
  - Input: `x_rel, y_rel` trong `[0.0, 1.0]`.
  - Output: `(x, y)` pixel trên màn hình.

### 3. `kendz.tools.debug_window_binding`

Tool debug đơn giản:

```bash
python -m kendz.tools.debug_window_binding --profile-id 1
python -m kendz.tools.debug_window_binding --profile-id 2
python -m kendz.tools.debug_window_binding --profile-id 3
```

Luồng:

1. `AppContext.bootstrap()` để lấy `default_game_id`.
2. `bind_window_for_profile(...)` để tìm cửa sổ tương ứng với profile.
3. `LayoutManager.get_self_layout(game_id, profile_id)` để lấy 13 vùng self_cards.
4. Với mỗi `CardRegion`, tính tâm lá bài trong toạ độ tương đối → toạ độ pixel:
   - log: `card_01 -> rel=(0.123, 0.456) -> screen=(1000, 720)`.

Nếu log trông hợp lý (tâm lá bài nằm trong vùng cờ bạc của cửa sổ), window binding OK.

## Lưu ý

- Implementation hiện tại dùng Win32 API (ctypes), chỉ hỗ trợ Windows.
- Nếu chạy trên hệ điều hành khác, module sẽ raise `RuntimeError`.
- Sau khi window binding ổn, bước tiếp theo:
  - Thiết kế `ClickAction` và module thực thi click thật dựa trên `BoundWindow.to_screen_from_rel(...)`.
