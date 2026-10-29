"""DuckDB storage for the feature tables and the schema description shared with the agents."""

import os
import threading
from pathlib import Path

import duckdb
import pandas as pd

from app.config import DB_PATH

PROMPTS_COLUMNS = {
    "id": "trace id",
    "timestamp": "time of the prompt (UTC)",
    "date": "calendar date of the prompt",
    "hour": "hour of day 0-23",
    "weekday": "day name, e.g. Monday",
    "user_id": "end user id",
    "session_id": "chat session id",
    "app": "application the user was in",
    "user_role": "role of the user",
    "organization_id": "customer organization id",
    "prompt": "user prompt text (original language)",
    "prompt_english": "prompt translated to English",
    "prompt_chars": "prompt length in characters",
    "prompt_words": "prompt length in words",
    "prompt_language": "ISO code of the prompt language",
    "output_text": "assistant response text",
    "output_chars": "response length in characters",
    "output_language": "ISO code of the response language",
    "language_match": "true if response language equals prompt language",
    "intent": "intent class of the prompt",
    "topic": "topic cluster label of the prompt",
    "response_topic": "topic the response is about",
    "response_on_topic": "true if the response topic equals the prompt topic",
    "response_similarity": "cosine similarity (0-1) of the response to the prompt's topic",
    "history_turns": "number of user turns in the conversation so far",
    "latency_s": "response latency in seconds",
    "input_tokens": "prompt tokens",
    "output_tokens": "completion tokens",
    "total_tokens": "total tokens",
    "error_count": "errors in the trace",
    "observation_count": "observations (spans) in the trace",
}

class NoData(FileNotFoundError):
    pass


_lock = threading.Condition()
_conn: duckdb.DuckDBPyConnection | None = None
_active_queries = 0
SWAP_WAIT_S = 30


def write_tables(prompts: pd.DataFrame, sessions: pd.DataFrame, path: Path | None = None) -> None:
    global _conn
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        if _conn is not None and path.resolve() == DB_PATH.resolve():
            _conn.close()
            _conn = None
        con = duckdb.connect(str(path))
        try:
            con.register("prompts_df", prompts)
            con.register("sessions_df", sessions)
            con.execute("CREATE OR REPLACE TABLE prompts AS SELECT * FROM prompts_df")
            con.execute("CREATE OR REPLACE TABLE sessions AS SELECT * FROM sessions_df")
        finally:
            con.close()


def replace_database(new_path: Path, path: Path | None = None) -> None:
    """Atomically swap in a freshly built database once running queries finish; new queries wait meanwhile.

    The old connection must be closed before reconnecting: DuckDB shares one database instance per path
    within a process, so a lingering connection would keep serving the old file.
    """
    global _conn
    path = path or DB_PATH
    with _lock:
        _lock.wait_for(lambda: _active_queries == 0, timeout=SWAP_WAIT_S)
        if _conn is not None:
            _conn.close()
            _conn = None
        os.replace(new_path, path)


def remove_database(path: Path | None = None) -> None:
    """Delete the database once running queries finish, leaving the system with no data."""
    global _conn
    path = path or DB_PATH
    with _lock:
        _lock.wait_for(lambda: _active_queries == 0, timeout=SWAP_WAIT_S)
        if _conn is not None:
            _conn.close()
            _conn = None
        path.unlink(missing_ok=True)


def version(path: Path | None = None) -> str | None:
    path = path or DB_PATH
    return str(path.stat().st_mtime_ns) if path.exists() else None


def connection(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """A cursor on a shared read-only connection; safe to use from request threads."""
    global _conn
    path = path or DB_PATH
    with _lock:
        if _conn is None:
            if not path.exists():
                raise NoData("No data is loaded. Add a trace export on the Data sources page.")
            _conn = duckdb.connect(str(path), read_only=True)
        return _conn.cursor()


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    global _active_queries
    with _lock:
        cur = connection()
        _active_queries += 1
    try:
        return cur.execute(sql, params or []).df()
    finally:
        cur.close()
        with _lock:
            _active_queries -= 1
            _lock.notify_all()


def schema_description() -> str:
    lines = ["Table prompts (one row per user prompt):"]
    lines += [f"  - {col}: {desc}" for col, desc in PROMPTS_COLUMNS.items()]
    lines += [
        "Table sessions (one row per chat session):",
        "  - session_id, user_id, app, user_role, organization_id, started_at, ended_at,",
        "    turns, total_tokens, avg_latency_s, duration_s, languages, topics",
    ]
    return "\n".join(lines)


def categorical_values(max_values: int = 30) -> dict[str, list[str]]:
    """Distinct values of low-cardinality columns, used to ground entity extraction."""
    out = {}
    for col in ("app", "user_role", "topic", "intent", "prompt_language", "output_language", "response_topic", "weekday"):
        df = query(f"SELECT DISTINCT {col} AS v FROM prompts WHERE {col} IS NOT NULL ORDER BY 1 LIMIT {max_values + 1}")
        if len(df) <= max_values:
            out[col] = [str(v) for v in df["v"]]
    return out


def data_range() -> dict:
    df = query("SELECT min(timestamp) AS lo, max(timestamp) AS hi, count(*) AS n FROM prompts")
    return {"start": str(df["lo"][0]), "end": str(df["hi"][0]), "rows": int(df["n"][0])}
