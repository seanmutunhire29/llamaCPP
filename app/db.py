import sqlite3
from app.config import DB_PATH


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Creates the api_keys table if it doesn't exist yet. Called on app startup."""
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            key_hash     TEXT NOT NULL UNIQUE,
            key_prefix   TEXT NOT NULL,
            scopes       TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            expires_at   TEXT NOT NULL,
            revoked      INTEGER NOT NULL DEFAULT 0,
            last_used_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()
