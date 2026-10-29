"""Load raw chatbot trace exports into a clean, flat DataFrame.

The export format (Langfuse-style traces) has a few quirks handled here:
- Some exports wrap each whole CSV line in one quoted field, so rows are unwrapped.
- `input` is a JSON list of chat messages; `output`, `metadata` and `usage` are JSON objects.
- Cost columns may be empty and numeric columns arrive as strings.
"""

import csv
import io
import json
import sys
from pathlib import Path

import pandas as pd

csv.field_size_limit(sys.maxsize)

NUMERIC_COLUMNS = {
    "latency": float,
    "inputTokens": int,
    "outputTokens": int,
    "totalTokens": int,
    "errorCount": int,
    "warningCount": int,
    "observationCount": int,
    "inputCost": float,
    "outputCost": float,
    "totalCost": float,
}


def read_raw_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        if len(header) == 1 and "," in header[0]:
            header = next(csv.reader(io.StringIO(header[0])))
        rows = []
        for line in reader:
            if not line:
                continue
            if len(line) == 1 and len(header) > 1:
                line = next(csv.reader(io.StringIO(line[0])))
            if len(line) != len(header):
                raise ValueError(f"Row has {len(line)} fields, expected {len(header)}: {line[:2]}")
            rows.append(dict(zip(header, line, strict=False)))
    return rows


SUPPORTED_SUFFIXES = (".csv", ".json", ".jsonl", ".ndjson", ".xlsx")
REQUIRED_COLUMNS = ("id", "timestamp", "input")


def read_records(path: Path) -> list[dict]:
    """Raw trace records from a CSV, JSON (list or {"data": [...]}), JSONL or Excel export."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        records = read_raw_rows(path)
    elif suffix in (".jsonl", ".ndjson"):
        with open(path, encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
    elif suffix == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = next((data[k] for k in ("data", "traces", "items") if isinstance(data.get(k), list)), [data])
        records = data
    elif suffix == ".xlsx":
        frame = pd.read_excel(path, dtype=str).fillna("")
        records = frame.to_dict(orient="records")
    else:
        raise ValueError(f"Unsupported file type '{suffix}'. Use one of: {', '.join(SUPPORTED_SUFFIXES)}")
    if not records:
        raise ValueError("The file contains no rows")
    if not all(isinstance(r, dict) for r in records):
        raise ValueError("Every record must be an object with trace fields")
    missing = [c for c in REQUIRED_COLUMNS if c not in records[0]]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}. Found: {', '.join(list(records[0])[:15])}")
    return records


def _json(value, default):
    if isinstance(value, (dict, list)):
        return value
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("text"):
            return content["text"]
        parts = content.get("parts") or []
        return " ".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return ""


def _to_number(value, kind):
    if value in ("", None):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return int(number) if kind is int else number


def parse_row(raw: dict) -> dict:
    messages = _json(raw.get("input"), raw.get("input") or [])
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    if isinstance(messages, dict):
        messages = messages.get("messages") if isinstance(messages.get("messages"), list) else [messages]
    messages = [m for m in messages if isinstance(m, dict)]
    user_messages = [m for m in messages if m.get("role", "user") == "user"]
    output = _json(raw.get("output"), raw.get("output") or {})
    output_text = (output.get("text") or output.get("content") or "") if isinstance(output, dict) else str(output)
    meta = _json(raw.get("metadata"), {})
    if not isinstance(meta, dict):
        meta = {}
    usage = _json(raw.get("usage"), {})

    row = {
        "id": str(raw["id"]),
        "timestamp": raw.get("timestamp"),
        "user_id": raw.get("userId") or None,
        "session_id": raw.get("sessionId") or None,
        "trace_name": raw.get("name") or None,
        "version": raw.get("version") or None,
        "environment": raw.get("environment") or None,
        "level": raw.get("level") or None,
        "prompt": _message_text(user_messages[-1]).strip() if user_messages else "",
        "history_turns": len(user_messages),
        "history_messages": len(messages),
        "output_text": output_text.strip(),
        "app": meta.get("app"),
        "user_role": meta.get("userRole"),
        "organization_id": str(meta["organizationId"]) if meta.get("organizationId") is not None else None,
        "application_id": str(meta["applicationId"]) if meta.get("applicationId") is not None else None,
        "is_staff": bool(meta.get("isStaffUser", False)),
        "message_kind": meta.get("messageKind"),
        "conversation_id": meta.get("conversationId") or meta.get("threadId"),
    }
    for col, kind in NUMERIC_COLUMNS.items():
        row[_snake(col)] = _to_number(raw.get(col), kind)
    if not isinstance(usage, dict):
        usage = {}
    for src, dst in (("promptTokens", "input_tokens"), ("completionTokens", "output_tokens"), ("totalTokens", "total_tokens")):
        if row.get(dst) is None and usage.get(src) is not None:
            row[dst] = int(usage[src])
    return row


def _snake(name: str) -> str:
    return "".join("_" + c.lower() if c.isupper() else c for c in name)


def load_traces(path: Path) -> pd.DataFrame:
    return load_many([path])


def load_many(paths: list[Path]) -> pd.DataFrame:
    """Combine several exports; a trace id seen again in a later file replaces the earlier version."""
    rows = [parse_row(r) for p in paths for r in read_records(p)]
    df = pd.DataFrame(rows)
    df = df.rename(columns={"latency": "latency_s"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce", format="mixed").dt.tz_convert(None)

    before = len(df)
    df = df.dropna(subset=["timestamp"]).drop_duplicates(subset=["id"], keep="last")
    df = df[df["prompt"].str.len() > 0]
    df.attrs["dropped_rows"] = before - len(df)

    for col in ("input_cost", "output_cost", "total_cost"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    for col in ("app", "user_role"):
        df[col] = df[col].fillna("Unknown")
    df["session_id"] = df["session_id"].fillna(df["id"])
    return df.sort_values("timestamp").reset_index(drop=True)


def profile(df: pd.DataFrame) -> dict:
    """Data-quality summary used for the data-understanding phase (RQ2)."""
    return {
        "rows": int(len(df)),
        "dropped_rows": int(df.attrs.get("dropped_rows", 0)),
        "time_range": [str(df["timestamp"].min()), str(df["timestamp"].max())],
        "users": int(df["user_id"].nunique()),
        "sessions": int(df["session_id"].nunique()),
        "distinct_prompts": int(df["prompt"].nunique()),
        "distinct_outputs": int(df["output_text"].nunique()),
        "apps": df["app"].value_counts().to_dict(),
        "user_roles": df["user_role"].value_counts().to_dict(),
        "null_share": {c: round(float(v), 3) for c, v in df.isna().mean().items() if v > 0},
        "constant_columns": [c for c in df.columns if df[c].nunique(dropna=False) <= 1],
    }
