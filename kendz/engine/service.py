# kendz/engine/service.py
"""EngineService - service dùng để test Mậu Binh Engine offline.

Phase 4.1:
- So sánh nhanh giữa 2 chiến lược:
  + arrange_basic
  + arrange_advanced (heuristic)

Mục tiêu:
- Kiểm tra engine có hoạt động ổn định.
- Xem kết quả xếp của chiến lược nâng cao khác gì so với cơ bản.
"""

from __future__ import annotations

import random

from kendz.core.app_context import AppContext
from kendz.engine.cards import full_deck, format_cards
from kendz.engine.arranger import arrange_basic, arrange_advanced


def test_engine_random(ctx: AppContext) -> None:
    """Chạy thử engine với một bộ bài ngẫu nhiên và log kết quả.

    Bước:
    1. Sinh một bộ bài đầy đủ (52 lá) và xáo.
    2. Lấy 13 lá đầu tiên.
    3. Xếp bài bằng arrange_basic() và arrange_advanced().
    4. Ghi log chi tiết để so sánh.
    """
    logger = ctx.logger
    deck = full_deck()
    random.shuffle(deck)

    cards13 = deck[:13]

    arranged_basic = arrange_basic(cards13)
    arranged_adv = arrange_advanced(cards13)

    logger.info("ENGINE TEST - 13 lá: %s", format_cards(cards13))
    logger.info("ENGINE BASIC    - %s", arranged_basic.to_str())
    logger.info("ENGINE ADVANCED - %s", arranged_adv.to_str())
