# PHASE 8 – Mậu Binh Automation (Dry-Run)

## Mục tiêu

- Tận dụng toàn bộ pipeline hiện có (Vision + Recognizer + Engine).
- Xây dựng **kế hoạch đánh (strategy)** từ kết quả Engine cho từng ván.
- Chạy realtime cho từng profile, tương tự assist loop.
- Giai đoạn hiện tại: **dry-run**, chỉ log các bước dự kiến, *chưa* click chuột thật.

## Thành phần chính

### 1. `kendz.automation.mau_binh_plan`

- Hàm `build_strategy_from_suggestion(suggestion)`:

  - Input: `ChiSuggestion` từ `engine.assistant`.
  - Output: `List[StrategyStep]` – mỗi bước có `description` tiếng Việt.
  - Ví dụ step:

    - `Chi 1 (3 lá): ...`
    - `Chi 2 (5 lá): ...`
    - `Chi 3 (5 lá): ...`
    - `Bài rơi vào trạng thái BINH LŨNG ...`
    - `Nhấn nút XÁC NHẬN / XẾP BÀI trên giao diện game.`

### 2. `kendz.tools.auto_mau_binh_dryrun`

- Vòng lặp Phase 8:

  1. `capture_and_crop_self_cards(ctx, profile_id)` – crop 13 lá.
  2. `recognize_13_cards(base_dir, game_id, profile_id, logger)` – nhận diện 13 lá.
  3. `suggest_for_13_cards(cards)` – Engine xếp bài.
  4. `build_strategy_from_suggestion(suggestion)` – tạo strategy.
  5. Log chi tiết từng bước strategy.

- Không có bất kỳ lệnh click chuột thật.

## Cách chạy

```bash
# Profile 1
python -m kendz.tools.auto_mau_binh_dryrun --profile-id 1

# Profile 2
python -m kendz.tools.auto_mau_binh_dryrun --profile-id 2

# Profile 3
python -m kendz.tools.auto_mau_binh_dryrun --profile-id 3
```

Mỗi profile nên chạy ở một cửa sổ CMD riêng.

## Hướng phát triển tiếp

- Bổ sung cấu trúc `ClickAction` (toạ độ, delay, mô tả).
- Thay `StrategyStep` bằng `ClickAction` + mapping chi tiết.
- Tích hợp với thư viện điều khiển chuột (pyautogui, win32, v.v.)
  với flag `dry_run=True/False` để bật/tắt auto-click.
