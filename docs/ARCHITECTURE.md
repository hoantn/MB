# Kendz – Kiến trúc hiện tại (Phase 1–3)

Tài liệu này dùng để:
- Ghi nhớ cấu trúc hệ thống Kendz
- Đảm bảo các Phase sau triển khai nhất quán, đồng bộ, không phá vỡ kiến trúc

## 1. Tổng quan

Kendz gồm 3 tầng đã triển khai:

- Core:
  - AppContext: gom config, logger, event_bus, db_session_factory
  - Config loader: đọc YAML -> Pydantic model -> KendzConfig
  - Logging: logger chung, ghi ra console + file logs/kendz.log
  - EventBus: giao tiếp nội bộ giữa các module
- Database local (SQLite):
  - File: data/kendz.db
  - ORM models: SessionModel, RoundModel, HandModel, LogEventModel
- Vision skeleton:
  - Capture màn hình bằng mss + OpenCV
  - Lưu file debug data/vision_test.png
  - Định nghĩa Region, CardRegion, CardDetectionResult

## 2. Cấu trúc thư mục chính

- kendz/
  - __init__.py     # __app_name__ = "Kendz", __version__ = "0.1.0"
  - main.py         # entry point, khởi tạo AppContext, test DB & Vision
  - core/
    - app_context.py
    - config_loader.py
    - logging_setup.py
    - events.py
    - errors.py
    - utils/
      - path.py
      - time.py
      - env.py
  - database/
    - db_session.py
    - models.py
  - vision/
    - __init__.py
    - layout_types.py
    - capture.py
    - cards_detector.py
    - service.py
- config/
  - core.yaml
  - profiles.yaml
  - strategy.yaml
  - vision.yaml
- data/
  - kendz.db
  - vision_test.png (tạo khi chạy test_capture)
- logs/
  - kendz.log

## 3. AppContext

AppContext chứa:

- app_name, app_version
- config: KendzConfig
  - core: CoreConfig
  - profiles: List[ProfileConfig]
  - strategy: StrategyConfig
  - vision: VisionConfig
- logger: logger chuẩn
- event_bus: EventBus
- db_session_factory: SessionLocal (SQLAlchemy sessionmaker)

Quy tắc:
- Mọi module lớn (vision, engine, automation, ui...) sẽ nhận AppContext hoặc một số thành phần trong đó.
- Không được tự ý tạo logger/ngắt kết nối DB ngoài AppContext trừ khi có lý do rõ ràng.

## 4. Database local (SQLite)

- SessionModel (bảng `sessions`):
  - Một lần chạy Kendz = một session
- RoundModel (bảng `rounds`):
  - Một ván game trong một session
- HandModel (bảng `hands`):
  - Bài của từng profile hoặc đối thủ trong một round
- LogEventModel (bảng `log_events`):
  - Log sự kiện có cấu trúc: module, level, event_type, message, context_json

Sau này:
- Mọi hành động quan trọng (vision, engine, automation) sẽ log vào đây.

## 5. Vision skeleton

- layout_types.Region / CardRegion: toạ độ tương đối 0–1.
- capture.capture_screen(): chụp toàn màn hình bằng mss.
- capture.save_frame_debug(): lưu frame ra file PNG/JPG.
- cards_detector.CardDetectionResult: chứa index, image, rank, suit, confidence.
- cards_detector.detect_cards(): hiện mới crop ảnh theo CardRegion, chưa nhận diện rank/suit.
- service.test_capture(): chụp 1 frame và lưu `data/vision_test.png`.

Quy tắc:
- Vision không chứa logic Mậu Binh.
- Vision chỉ trả về thông tin "thấy gì trên màn hình" (lá bài, nút, text...).

## 6. Nguyên tắc nhất quán cho các Phase tiếp theo

- Không thay đổi cấu trúc thư mục hiện tại trừ khi bắt buộc.
- Không đổi tên public API (class/hàm quan trọng) mà không cập nhật tài liệu.
- Mọi module mới đều phải:
  - Có comment tiếng Việt rõ ràng
  - Có README hoặc mô tả ngắn trong docs/
- Mọi thay đổi liên quan đến DB hoặc config:
  - Phải được cập nhật vào tài liệu này hoặc file docs khác (vd: docs/db.md, docs/config.md).

Tài liệu này sẽ được cập nhật dần khi ta hoàn thành các Phase tiếp theo (Engine, Automation, UI, License...).


## 7. Engine (Phase 4 - skeleton)

- Thư mục: `kendz/engine/`
  - `cards.py`: định nghĩa Card, full_deck, parse/format chuỗi bài.
  - `hand_types.py`: Chi3, Chi5, ArrangedHand, PokerHandType.
  - `evaluator.py`: đánh giá 5 lá theo poker cơ bản, chi3 theo rank.
  - `arranger.py`: hàm arrange_basic() xếp bài đơn giản.
  - `service.py`: EngineService với test_engine_random().

Ghi chú:
- Engine hiện tại mới là bản cơ bản để test pipeline.
- Luật Mậu Binh đầy đủ và tối ưu hoá sẽ được nâng cấp dần:
  + Xử lý bài đặc biệt.
  + Nhiều chiến lược xếp bài.
  + So sánh hand giữa nhiều người chơi.


## 8. Vision -> Engine pipeline (skeleton)

- Layout:
  - File `config/layouts_mau_binh.yaml` mô tả toạ độ tương đối 13 lá.
  - Sử dụng `LayoutManager` để đọc layout.
- Pipeline:
  - `capture_and_crop_self_cards()` chụp màn hình, crop 13 lá và lưu ảnh debug.
- Chưa nhận diện rank/suit; sẽ được bổ sung bằng module recognizer ở các Phase sau.
