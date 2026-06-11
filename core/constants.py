import os
import sys

APP_NAME = "MauBinhTool"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
DATA_DIR = os.path.join(BASE_DIR, "data")
TEMPLATES_DIR = os.path.join(BASE_DIR, "vision", "templates")
DB_DIR = os.path.join(BASE_DIR, "db")
LOG_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

DEFAULT_DB_PATH = os.path.join(DB_DIR, "mb_tool.sqlite3")

# Suit mapping:
# Rô = R, Cơ = C, Bích = B, Tép = T
SUIT_TO_SYMBOL = {
    "R": "♦",
    "C": "♥",
    "B": "♠",
    "T": "♣",
}

SUIT_COLOR = {
    "R": "red",
    "C": "red",
    "B": "black",
    "T": "black",
}

RANK_ORDER = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
