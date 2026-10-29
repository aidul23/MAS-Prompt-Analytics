"""Persistent chat sessions (SQLite), so conversations survive reloads and server restarts.

A chat holds messages (one user question each); a message holds one response per mode, two in compare mode.
"""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.config import CHATS_DB
from app.schemas import ChatResponse, Turn

TITLE_CHARS = 60
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS responses (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    mode TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_chat ON messages(chat_id, created_at);
CREATE INDEX IF NOT EXISTS responses_chat ON responses(chat_id, mode, created_at);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path: Path = CHATS_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def title_for(question: str) -> str:
    q = " ".join(question.split())
    return q if len(q) <= TITLE_CHARS else q[: TITLE_CHARS - 1].rstrip() + "…"


def save(chat_id: str, message_id: str, ui_mode: str, resp: ChatResponse) -> None:
    """Store a response, creating the chat and the message on first use."""
    now = _now()
    with _lock, _connect() as con:
        con.execute("INSERT OR IGNORE INTO chats VALUES (?, ?, ?, ?)", (chat_id, title_for(resp.question), now, now))
        con.execute("INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?)", (message_id, chat_id, resp.question, ui_mode, now))
        con.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?)", (resp.id, message_id, chat_id, resp.mode, resp.model_dump_json(), now))
        con.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))


def list_chats() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            """SELECT c.id, c.title, c.created_at, c.updated_at, count(m.id) AS messages
               FROM chats c LEFT JOIN messages m ON m.chat_id = c.id
               GROUP BY c.id ORDER BY c.updated_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_chat(chat_id: str) -> dict | None:
    with _connect() as con:
        chat = con.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if chat is None:
            return None
        messages = con.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at, rowid", (chat_id,)).fetchall()
        responses = con.execute("SELECT message_id, body FROM responses WHERE chat_id = ? ORDER BY created_at, rowid", (chat_id,)).fetchall()
    by_message: dict[str, list[ChatResponse]] = {}
    for r in responses:
        by_message.setdefault(r["message_id"], []).append(ChatResponse.model_validate_json(r["body"]))
    return {**dict(chat), "messages": [{**dict(m), "responses": by_message.get(m["id"], [])} for m in messages]}


def rename(chat_id: str, title: str) -> bool:
    with _lock, _connect() as con:
        return con.execute("UPDATE chats SET title = ? WHERE id = ?", (title.strip()[:200], chat_id)).rowcount > 0


def delete(chat_id: str) -> bool:
    with _lock, _connect() as con:
        return con.execute("DELETE FROM chats WHERE id = ?", (chat_id,)).rowcount > 0


def turns(chat_id: str, mode: str, max_turns: int) -> list[Turn]:
    """Conversation memory for one mode of a chat, rebuilt from stored responses."""
    with _connect() as con:
        rows = con.execute(
            "SELECT body FROM responses WHERE chat_id = ? AND mode = ? ORDER BY created_at DESC, rowid DESC LIMIT ?", (chat_id, mode, max_turns)
        ).fetchall()
    out = []
    for r in reversed(rows):
        resp = ChatResponse.model_validate_json(r["body"])
        out.append(Turn(question=resp.question, query=resp.query_spec if mode == "mas" else resp.sql, answer=resp.answer))
    return out
