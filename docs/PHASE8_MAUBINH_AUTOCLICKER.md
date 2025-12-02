
# PHASE 8.5 – Mậu Binh Auto-Click (Profile-based, Drag & Drop)

## Mục tiêu

- Bật chế độ **auto-click (kéo-thả thật)** cho Mậu Binh GO88, nhưng:
  - Độc lập theo từng profile trình duyệt.
  - Có thể chuyển qua lại giữa DRY-RUN và LIVE bằng flag CLI.
  - Mặc định an toàn (DRY-RUN).

## File mới

### `kendz.tools.auto_mau_binh_clicker`

- Tool loop hoàn chỉnh:

  1. `capture_and_crop_self_cards(ctx, profile_id)`
  2. `recognize_13_cards(...)`
  3. `suggest_for_13_cards(cards)`
  4. `bind_window_for_profile(...)`
  5. `LayoutManager.get_self_layout(...)`
  6. `build_drag_plan_for_mau_binh(...)`
  7. `perform_actions(actions, dry_run=not live, logger=logger)`

- Tham số:

  ```bash
  --profile-id   # 1, 2, 3, ...
  --live         # nếu có -> thực sự kéo-thả; nếu không -> DRY-RUN
  ```

## Cách dùng khuyến nghị

### 1. Test lần cuối ở DRY-RUN

```bash
python -m kendz.tools.auto_mau_binh_clicker --profile-id 1
```

- Quan sát log và UI:
  - Log phải giống hệt `auto_mau_binh_click_plan_dryrun`.
  - Trong game **không được có chuyển động chuột** (vì đang DRY-RUN).

### 2. Bật LIVE cho profile 1

Trước khi bật:
- Mở đúng phòng Mậu Binh.
- Đến bước "đang xếp bài" (13 lá hiển thị chưa xếp).

Sau đó chạy:

```bash
python -m kendz.tools.auto_mau_binh_clicker --profile-id 1 --live
```

- Bot sẽ:
  - Đợi lần đầu đọc được 13 lá.
  - Gọi engine gợi ý chi.
  - Sinh drag-plan và **kéo-thả thật** để xếp bài.
- Log vẫn hiển thị đầy đủ từng bước `[DRAG] from=(x1,y1) to=(x2,y2) ...`.

### 3. Dừng bot

- Nhấn `Ctrl + C` trong cửa sổ CMD của profile đó.

## Lưu ý an toàn

- Chỉ nên bật `--live` cho **1 profile** trong giai đoạn test đầu.
- Nếu thấy bot kéo sai, lập tức:
  - Nhấn `Ctrl + C`.
  - Thử lại với DRY-RUN để debug.
- Cấu trúc vẫn hoàn toàn tách biệt theo profile, không ảnh hưởng tới cửa sổ khác.
