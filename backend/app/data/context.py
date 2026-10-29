"""Data context given to every language model: schema, allowed categorical values and time range."""

import math
import re
from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd

from app.data import store
from app.schemas import DataTable

LANGUAGE_TERMS = {
    "en": ["english", "englanti", "englanniksi", "englanninkiel"],
    "fi": ["finnish", "finland", "suomi", "suomeksi", "suomen", "suomenkiel"],
    "sv": ["swedish", "svenska", "ruotsi", "ruotsiksi"],
}
ROLE_TERMS = {"admin": ["admin", "pääkäyttäj", "ylläpitäj"], "user": ["user", "käyttäj"]}


def _grounding_terms() -> dict[str, dict[str, list[str]]]:
    """Words that must occur in a question for a filter value to be considered asked for.

    Topic values are grounded by their label and by the words of the prompts in the topic,
    in both the original language and English, so Finnish questions can match English labels.
    """
    values = store.categorical_values()
    terms: dict[str, dict[str, list[str]]] = {}
    for field in ("app", "weekday"):
        terms[field] = {v: [v.lower()] for v in values.get(field, [])}
    terms["user_role"] = {v: ROLE_TERMS.get(v.lower(), [v.lower()]) for v in values.get("user_role", [])}
    for field in ("prompt_language", "output_language"):
        terms[field] = {v: [v.lower(), *LANGUAGE_TERMS.get(v, [])] for v in values.get(field, [])}
    topic_texts = store.query("SELECT DISTINCT topic, prompt, prompt_english FROM prompts WHERE topic IS NOT NULL")
    per_topic = {}
    for topic in values.get("topic", []):
        rows = topic_texts[topic_texts["topic"] == topic]
        per_topic[topic] = {w for w in _words(" ".join([topic, *rows["prompt"], *rows["prompt_english"]])) if len(w) >= 5}
    common = {w for w in set().union(*per_topic.values()) if sum(w in ws for ws in per_topic.values()) >= 3}
    common |= {a.lower() for a in values.get("app", [])}
    topic_terms = {t: sorted(ws - common) for t, ws in per_topic.items()}
    terms["topic"] = topic_terms
    terms["response_topic"] = topic_terms
    return terms


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", text.lower())


@lru_cache
def data_context() -> dict:
    return {
        "schema": store.schema_description(),
        "values": store.categorical_values(),
        "range": store.data_range(),
        "grounding": _grounding_terms(),
    }


def refresh() -> None:
    data_context.cache_clear()


def context_text(include_schema: bool = True) -> str:
    ctx = data_context()
    parts = []
    if include_schema:
        parts.append(ctx["schema"])
    parts.append("Known values:")
    parts += [f"  - {col}: {', '.join(vals)}" for col, vals in ctx["values"].items()]
    rng = ctx["range"]
    today = date.fromisoformat(rng["end"][:10])
    parts.append(
        f"Data covers {rng['start'][:19]} to {rng['end'][:19]} UTC ({rng['rows']} prompts). "
        f"Today is {today.isoformat()} ({today:%A}); yesterday is {today - timedelta(days=1)}. "
        "Language codes: en = English, fi = Finnish, sv = Swedish. "
        "topic is the subject of the user's prompt (use it by default); response_topic is the subject of the bot's answer."
    )
    return "\n".join(parts)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "item"):
        return _clean(v.item())
    if isinstance(v, float):
        return round(v, 4)
    return v


def to_table(df: pd.DataFrame, max_rows: int = 200) -> DataTable:
    head = df.head(max_rows)
    cols = [head[c].tolist() for c in head.columns]
    rows = [[_clean(v) for v in row] for row in zip(*cols, strict=False)] if len(head.columns) else []
    return DataTable(columns=[str(c) for c in df.columns], rows=rows, total_rows=len(df))


RATE_SUFFIXES = ("_rate", "share_of_prompts")


def _fmt(col: str, v) -> str:
    """Pre-format values so small models copy numbers instead of converting them."""
    if v is None:
        return ""
    if isinstance(v, float) and col.endswith(RATE_SUFFIXES) and 0 <= v <= 1:
        return f"{v * 100:.1f}%"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def table_preview(table: DataTable, max_rows: int = 30) -> str:
    """Compact pipe-separated rendering of a result table for LLM prompts."""
    if not table.columns:
        return "(no result)"
    lines = [" | ".join(table.columns)]
    lines += [" | ".join(_fmt(c, v) for c, v in zip(table.columns, row, strict=False)) for row in table.rows[:max_rows]]
    if table.total_rows > max_rows:
        lines.append(f"... ({table.total_rows - max_rows} more rows not shown)")
    if table.total_rows == 0:
        lines.append("(0 rows)")
    return "\n".join(lines)
