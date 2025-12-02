# kendz/main.py
"""Điểm vào chính của ứng dụng Kendz.

Hiện tại:
- Khởi tạo AppContext (config, logger, event bus, database)
- Ghi một bản ghi session mẫu vào SQLite
- Gọi Vision test (chụp 1 frame, lưu data/vision_test.png)
- Gọi Engine test (sinh 13 lá ngẫu nhiên và xếp bằng arrange_basic/advanced)
- Gọi Vision pipeline (crop 13 lá theo layout, lưu data/vision_cards/...)
"""

from datetime import datetime

from kendz.core.app_context import AppContext
from kendz.database.models import SessionModel
from kendz.vision.service import test_capture
from kendz.vision.pipeline import capture_and_crop_self_cards
from kendz.engine.service import test_engine_random


def main() -> None:
    ctx = AppContext.bootstrap()
    logger = ctx.logger
    logger.info("Kendz khởi động thành công.")
    logger.info("App version: %s", ctx.app_version)
    logger.info("Config core: %s", ctx.config.core)
    logger.info("Config vision: %s", ctx.config.vision)

    # Ghi một session mẫu vào DB
    db = ctx.db_session_factory()
    try:
        new_session = SessionModel(
            started_at=datetime.utcnow(),
            client_version=ctx.app_version,
            license_key=None,
        )
        db.add(new_session)
        db.commit()
        logger.info("Đã ghi một bản ghi session mẫu vào SQLite (id tạm thời chưa cần dùng).")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("Lỗi khi ghi session mẫu vào DB: %s", exc)
    finally:
        db.close()

    # Vision test (chụp toàn màn hình)
    test_capture(ctx)

    # Engine test (random 13 lá offline)
    test_engine_random(ctx)

    # Vision pipeline: crop 13 lá theo layout
    capture_and_crop_self_cards(ctx, profile_id=1)

    print(
        "Kendz đã khởi động. Kiểm tra logs/, data/vision_test.png "
        "và data/vision_cards/ để xác nhận Vision & Engine & Pipeline hoạt động."
    )


if __name__ == "__main__":
    main()
