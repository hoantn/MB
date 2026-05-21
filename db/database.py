import sqlite3
from typing import Optional
from core.constants import DEFAULT_DB_PATH
from core.logger import log

_connection: Optional[sqlite3.Connection] = None

def get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(DEFAULT_DB_PATH)
        _connection.row_factory = sqlite3.Row
    return _connection

def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            cards_raw TEXT NOT NULL,
            chi1 TEXT,
            chi2 TEXT,
            chi3 TEXT,
            total_score INTEGER,
            note TEXT
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            level TEXT NOT NULL,
            module TEXT NOT NULL,
            message TEXT NOT NULL
        );
        """
    )

    conn.commit()
    log.info("Database initialized")
    # ===== LƯU PHIÊN PHÒNG =====
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS room_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT NOT NULL,
            room_id INTEGER,
            bet INTEGER,
            my_uid TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS room_players_seen (
            session_id INTEGER NOT NULL,
            seen_uid TEXT NOT NULL,
            seen_name TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (session_id, seen_uid)
        );
        """
    )
    # --- MIGRATION: add seen_gold if missing ---
    cur.execute("PRAGMA table_info(room_players_seen)")
    cols = {row[1] for row in cur.fetchall()}  # row[1] = column name
    if "seen_gold" not in cols:
        cur.execute("ALTER TABLE room_players_seen ADD COLUMN seen_gold INTEGER")
        log.info("DB migration: added column room_players_seen.seen_gold")
    conn.commit()
