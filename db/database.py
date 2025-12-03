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
