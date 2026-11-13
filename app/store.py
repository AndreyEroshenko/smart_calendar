"""SQLite store for extractions awaiting the user's Add / Edit / Skip decision."""
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .models import Extraction

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending (
    id          INTEGER PRIMARY KEY,
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    source_text TEXT,
    extraction  TEXT NOT NULL,          -- Extraction JSON
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | added | skipped
    gcal_links  TEXT,                   -- JSON list of created event links
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass
class Pending:
    id: int
    chat_id: int
    user_id: int
    source_text: str | None
    extraction: Extraction
    status: str


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def add(self, chat_id: int, user_id: int, source_text: str | None, extraction: Extraction) -> int:
        with self._db:
            cur = self._db.execute(
                "INSERT INTO pending (chat_id, user_id, source_text, extraction) VALUES (?, ?, ?, ?)",
                (chat_id, user_id, source_text, extraction.model_dump_json()),
            )
        return cur.lastrowid

    def get(self, pending_id: int) -> Pending | None:
        row = self._db.execute("SELECT * FROM pending WHERE id = ?", (pending_id,)).fetchone()
        if row is None:
            return None
        return Pending(
            id=row["id"], chat_id=row["chat_id"], user_id=row["user_id"], source_text=row["source_text"],
            extraction=Extraction.model_validate_json(row["extraction"]), status=row["status"],
        )

    def update_extraction(self, pending_id: int, extraction: Extraction) -> None:
        with self._db:
            self._db.execute(
                "UPDATE pending SET extraction = ? WHERE id = ?", (extraction.model_dump_json(), pending_id)
            )

    def set_status(self, pending_id: int, status: str, links: list[str] | None = None) -> None:
        with self._db:
            self._db.execute(
                "UPDATE pending SET status = ?, gcal_links = ? WHERE id = ?",
                (status, json.dumps(links) if links else None, pending_id),
            )
