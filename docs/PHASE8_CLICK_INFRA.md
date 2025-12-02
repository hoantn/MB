
# PHASE 8 – ClickAction Infrastructure

## Mục tiêu

- Chuẩn hoá cách mô tả **một hành động click chuột** trong hệ thống Kendz.
- Cho phép:
  - Giai đoạn debug: chỉ log kế hoạch click (`dry_run=True`).
  - Giai đoạn live: thực thi click thật (`dry_run=False`), nhưng thông qua một lớp
    duy nhất, dễ kiểm soát và tắt/bật.

## Thành phần

### 1. `ClickAction`

```python
@dataclass
class ClickAction:
    x: int
    y: int
    delay_before: float = 0.02
    delay_after: float = 0.03
    description: str = ""
    button: Literal["left", "right"] = "left"
```

- `(x, y)`: toạ độ màn hình (pixel).
- `delay_before`, `delay_after`: delay trước/sau mỗi click.
- `description`: mô tả cho log (ví dụ: "Chọn lá bài thứ 5 chi 2").
- `button`: 'left' hoặc 'right'.

### 2. `perform_click_actions(actions, dry_run=True, logger=None)`

- Lặp qua từng `ClickAction` theo thứ tự:
  - Log step + toạ độ + mô tả.
  - Sleep `delay_before`.
  - Nếu `dry_run=False` → thực sự gửi lệnh click (Win32 SendInput).
  - Sleep `delay_after`.

## Lưu ý

- Implementation hiện tại chỉ hỗ trợ Windows (`os.name == "nt"`).
- Mặc định `dry_run=True` để tránh click nhầm khi mới chạy thử.
- Các module Mậu Binh / game khác **chỉ nên trả về list[ClickAction]**;
  phần thực thi gọi `perform_click_actions` ở một nơi duy nhất.
