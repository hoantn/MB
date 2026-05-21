# engine/phom/constants.py
from __future__ import annotations

TOTAL_CARDS = 52

# Phỏm WS cmds (theo log bạn cung cấp)
CMD_DEAL = 850
CMD_DISCARD = 851
CMD_HAND_SNAPSHOT = 852
CMD_ACTION_853 = 853
CMD_ACTION_854 = 854

# Default: số lá đối thủ đang cầm (có thể chỉnh trên UI)
DEFAULT_OPP_HAND_SIZE_GUESS = 10

# Supported image extensions for card assets
CARD_IMAGE_EXTS = (".png", ".webp", ".jpg", ".jpeg")
