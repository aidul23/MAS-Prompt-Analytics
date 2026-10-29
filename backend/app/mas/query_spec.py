"""The typed query language between the Query Understanding Agent and the Metrics Agent (RQ4).

SLMs fill in a small JSON spec instead of writing SQL. The spec is validated,
its values are snapped to values that exist in the data, and it is compiled to
parameterised DuckDB SQL by deterministic code.
"""

import difflib
import re
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator

METRICS: dict[str, tuple[str, str]] = {
    "prompt_count": ("count(*)", "number of prompts"),
    "session_count": ("count(DISTINCT session_id)", "number of sessions"),
    "user_count": ("count(DISTINCT user_id)", "number of distinct users"),
    "organization_count": ("count(DISTINCT organization_id)", "number of distinct organizations"),
    "distinct_prompt_count": ("count(DISTINCT prompt)", "number of distinct prompt texts"),
    "share_of_prompts": ("round(count(*) * 1.0 / sum(count(*)) OVER (), 4)", "share of prompts in each group (0-1)"),
    "avg_latency": ("round(avg(latency_s), 3)", "average response latency in seconds"),
    "median_latency": ("round(median(latency_s), 3)", "median latency in seconds"),
    "p95_latency": ("round(quantile_cont(latency_s, 0.95), 3)", "95th percentile latency in seconds"),
    "max_latency": ("max(latency_s)", "maximum latency in seconds"),
    "min_latency": ("min(latency_s)", "minimum latency in seconds"),
    "total_tokens": ("CAST(sum(total_tokens) AS BIGINT)", "sum of total tokens"),
    "avg_tokens": ("round(avg(total_tokens), 1)", "average total tokens per prompt"),
    "total_input_tokens": ("CAST(sum(input_tokens) AS BIGINT)", "sum of input (prompt) tokens"),
    "total_output_tokens": ("CAST(sum(output_tokens) AS BIGINT)", "sum of output (completion) tokens"),
    "avg_output_tokens": ("round(avg(output_tokens), 1)", "average output tokens per prompt"),
    "avg_prompt_words": ("round(avg(prompt_words), 2)", "average prompt length in words"),
    "avg_prompt_chars": ("round(avg(prompt_chars), 1)", "average prompt length in characters"),
    "avg_response_words": ("round(avg(output_words), 1)", "average response length in words"),
    "on_topic_rate": ("round(avg(CASE WHEN response_on_topic THEN 1.0 ELSE 0.0 END), 4)", "share of responses that match the prompt topic (0-1)"),
    "off_topic_count": ("count(*) FILTER (WHERE NOT response_on_topic)", "number of responses about a different topic than the prompt"),
    "off_topic_rate": ("round(avg(CASE WHEN response_on_topic THEN 0.0 ELSE 1.0 END), 4)", "share of responses about a different topic than the prompt (0-1)"),
    "language_match_rate": ("round(avg(CASE WHEN language_match THEN 1.0 ELSE 0.0 END), 4)", "share of responses in the same language as the prompt (0-1)"),
    "language_mismatch_count": ("count(*) FILTER (WHERE NOT language_match)", "number of responses in a different language than the prompt"),
}

DIMENSIONS: dict[str, str] = {
    "app": "app",
    "user_role": "user_role",
    "topic": "topic",
    "intent": "intent",
    "prompt_language": "prompt_language",
    "output_language": "output_language",
    "response_topic": "response_topic",
    "response_on_topic": "response_on_topic",
    "language_match": "language_match",
    "prompt": "prompt",
    "organization_id": "organization_id",
    "user_id": "user_id",
    "day": "CAST(date_trunc('day', timestamp) AS DATE)",
    "hour_bucket": "date_trunc('hour', timestamp)",
    "hour_of_day": "hour",
    "weekday": "weekday",
}

FILTER_FIELDS = {
    **{k: v for k, v in DIMENSIONS.items() if k not in ("day", "hour_bucket")},
    "latency_s": "latency_s",
    "total_tokens": "total_tokens",
    "prompt_words": "prompt_words",
    "prompt_text": "prompt",
}
NUMERIC_FIELDS = {"latency_s", "total_tokens", "prompt_words", "hour_of_day"}
BOOLEAN_FIELDS = {"response_on_topic", "language_match"}
# Models like to filter on a date column; normalise() moves these into start/end.
DATE_FIELDS = {"date"}
LIST_COLUMNS = ["timestamp", "app", "user_role", "prompt", "prompt_language", "topic", "output_text", "response_on_topic", "latency_s", "total_tokens"]

LANGUAGE_NAMES = {"english": "en", "finnish": "fi", "suomi": "fi", "swedish": "sv", "svenska": "sv"}

Op = Literal["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "contains"]
_SQL_OPS = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


class SpecError(ValueError):
    pass


class Filter(BaseModel):
    field: str
    op: Op = "eq"
    values: list[str] = Field(default_factory=list)

    @field_validator("field")
    @classmethod
    def _field(cls, v: str) -> str:
        if v not in FILTER_FIELDS and v not in DATE_FIELDS:
            raise ValueError(f"unknown filter field '{v}', use one of {sorted(FILTER_FIELDS)}")
        return v

    @field_validator("values", mode="before")
    @classmethod
    def _values(cls, v):
        if not isinstance(v, list):
            v = [v]
        return [str(x).lower() if isinstance(x, bool) else str(x) for x in v]


class QuerySpec(BaseModel):
    kind: Literal["aggregate", "list"] = "aggregate"
    metrics: list[str] = Field(default_factory=lambda: ["prompt_count"])
    group_by: list[str] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    start: str | None = None
    end: str | None = None
    order: Literal["desc", "asc", "time"] = "desc"
    limit: int = Field(50, ge=1, le=500)

    @field_validator("metrics")
    @classmethod
    def _metrics(cls, v: list[str]) -> list[str]:
        bad = [m for m in v if m not in METRICS]
        if bad:
            raise ValueError(f"unknown metrics {bad}, use names from {sorted(METRICS)}")
        return list(dict.fromkeys(v))[:4] or ["prompt_count"]

    @field_validator("group_by")
    @classmethod
    def _group_by(cls, v: list[str]) -> list[str]:
        bad = [d for d in v if d not in DIMENSIONS]
        if bad:
            raise ValueError(f"unknown group_by {bad}, use names from {sorted(DIMENSIONS)}")
        return list(dict.fromkeys(v))[:2]

    def describe(self) -> str:
        """Human-readable description, shown to the answer agent and in the UI."""
        parts = [", ".join(METRICS[m][1] for m in self.metrics) if self.kind == "aggregate" else "list of prompts"]
        if self.group_by:
            parts.append("by " + " and ".join(self.group_by))
        for f in self.filters:
            parts.append(f"where {f.field} {f.op} {', '.join(f.values)}")
        if self.start or self.end:
            parts.append(f"between {self.start or 'start'} and {self.end or 'end'}")
        return " ".join(parts)


def json_schema() -> dict:
    """Flat JSON schema for Ollama's constrained decoding."""
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["aggregate", "list"]},
            "metrics": {"type": "array", "items": {"type": "string", "enum": list(METRICS)}},
            "group_by": {"type": "array", "items": {"type": "string", "enum": list(DIMENSIONS)}},
            "filters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": [*FILTER_FIELDS, *DATE_FIELDS]},
                        "op": {"type": "string", "enum": list(Op.__args__)},
                        "values": {"type": "array", "items": {"type": ["string", "number", "boolean"]}},
                    },
                    "required": ["field", "op", "values"],
                },
            },
            "start": {"type": ["string", "null"]},
            "end": {"type": ["string", "null"]},
            "order": {"type": "string", "enum": ["desc", "asc", "time"]},
            "limit": {"type": "integer"},
        },
        "required": ["kind", "metrics", "group_by", "filters", "start", "end", "order", "limit"],
    }


def _snap(value: str, allowed: list[str], field: str) -> str:
    """Map a free-text value onto the closest value present in the data."""
    v = value.strip()
    if field in ("prompt_language", "output_language"):
        v = LANGUAGE_NAMES.get(v.lower(), v)
    lower = {a.lower(): a for a in allowed}
    if v.lower() in lower:
        return lower[v.lower()]
    contains = [a for a in allowed if v.lower() in a.lower() or a.lower() in v.lower()]
    if len(contains) == 1:
        return contains[0]
    close = difflib.get_close_matches(v.lower(), list(lower), n=1, cutoff=0.6)
    if close:
        return lower[close[0]]
    raise SpecError(f"'{value}' is not a known {field}; known values: {', '.join(allowed)}")


def _parse_time(value: str | None, data_end: datetime, is_end: bool) -> datetime | None:
    if not value or not str(value).strip():
        return None
    v = str(value).strip().lower()
    today = data_end.replace(hour=0, minute=0, second=0, microsecond=0)
    relative = {"today": today, "yesterday": today - timedelta(days=1)}
    if v in relative:
        base = relative[v]
        return base + timedelta(days=1) - timedelta(microseconds=1) if is_end else base
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise SpecError(f"cannot parse time '{value}', use ISO format YYYY-MM-DD") from exc
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    if is_end and ts == ts.normalize() and len(str(value).strip()) <= 10:
        ts = ts + timedelta(days=1) - timedelta(microseconds=1)
    return ts.to_pydatetime()


WILDCARDS = {"*", "all", "any", "%", "", "null", "none"}
TIME_DIMENSIONS = ("day", "hour_bucket", "hour_of_day")


def normalise(spec: QuerySpec, values: dict[str, list[str]], data_end: datetime) -> QuerySpec:
    spec = spec.model_copy(deep=True)
    for f in spec.filters:
        f.values = [v for v in f.values if str(v).strip().lower() not in WILDCARDS]
    spec.filters = [f for f in spec.filters if f.values]
    for f in [f for f in spec.filters if f.field in DATE_FIELDS]:
        spec.filters.remove(f)
        lo, hi = min(f.values), max(f.values)
        if f.op in ("eq", "in", "gt", "gte"):
            spec.start = spec.start or lo
        if f.op in ("eq", "in", "lt", "lte"):
            spec.end = spec.end or hi
    for f in spec.filters:
        if not f.values:
            raise SpecError(f"filter on {f.field} has no values")
        if f.field in BOOLEAN_FIELDS:
            f.values = ["true" if str(v).lower() in ("true", "1", "yes") else "false" for v in f.values]
            if f.op not in ("eq", "neq"):
                f.op = "eq"
        elif f.field in NUMERIC_FIELDS:
            try:
                [float(v) for v in f.values]
            except ValueError as exc:
                raise SpecError(f"filter on {f.field} needs numeric values") from exc
        elif f.field in values and f.op != "contains":
            f.values = [_snap(v, values[f.field], f.field) for v in f.values]
        if f.op in ("eq", "neq") and len(f.values) > 1:
            f.op = "in" if f.op == "eq" else "not_in"
    for attr, is_end in (("start", False), ("end", True)):
        ts = _parse_time(getattr(spec, attr), data_end, is_end)
        setattr(spec, attr, ts.isoformat() if ts else None)
    if spec.kind == "aggregate" and spec.group_by:
        if spec.group_by[0] in TIME_DIMENSIONS and spec.limit >= 24:
            spec.order = "time"
        elif spec.order == "time" and spec.group_by[0] not in TIME_DIMENSIONS:
            spec.order = "desc"
    return spec


LITERAL_FIELDS = {"organization_id", "user_id", "prompt"}


def _mentions(text: str, term: str) -> bool:
    """Word-prefix match on a crude stem, so inflected forms (uutiskirjeistä ~ uutiskirjeen) count."""
    stem = term if len(term) <= 5 else term[: max(5, len(term) - 3)]
    tail = r"(?![^\W\d_])" if len(term) <= 3 else ""
    return re.search(rf"(?<![^\W\d_]){re.escape(stem)}{tail}", text) is not None


def ground_filters(spec: QuerySpec, text: str, terms: dict[str, dict[str, list[str]]]) -> tuple[QuerySpec, list[dict]]:
    """Drop filter values that the user never mentioned (hallucinated or copied from examples).

    Categorical values are grounded via vocabulary from the data (see data.context);
    numbers and ids must appear literally. Free-text, boolean and intent filters are kept.
    """
    text = text.lower()
    spec = spec.model_copy(deep=True)
    kept, dropped = [], []
    for f in spec.filters:
        if f.field in terms:
            ok = [v for v in f.values if any(_mentions(text, t) for t in terms[f.field].get(v, [v.lower()]))]
        elif f.field in NUMERIC_FIELDS:
            ok = [v for v in f.values if re.search(rf"(?<!\d){re.escape(_num_text(v))}(?!\d)", text)]
        elif f.field in LITERAL_FIELDS:
            ok = [v for v in f.values if v.lower() in text]
        else:
            ok = list(f.values)
        if len(ok) < len(f.values):
            dropped.append({"field": f.field, "values": [v for v in f.values if v not in ok]})
        if ok:
            f.values = ok
            if f.op == "in" and len(ok) == 1:
                f.op = "eq"
            kept.append(f)
    spec.filters = kept
    return spec, dropped


def _num_text(v: str) -> str:
    n = float(v)
    return str(int(n)) if n.is_integer() else str(n)


def compile_sql(spec: QuerySpec) -> tuple[str, list]:
    where, params = [], []
    for f in spec.filters:
        col = FILTER_FIELDS[f.field]
        if f.field in BOOLEAN_FIELDS:
            want = f.values[0] == "true"
            where.append(f"{col} = ?" if f.op == "eq" else f"{col} <> ?")
            params.append(want)
        elif f.op == "contains":
            where.append("(" + " OR ".join(f"{col} ILIKE ?" for _ in f.values) + ")")
            params += [f"%{v}%" for v in f.values]
        elif f.op in ("in", "not_in"):
            where.append(f"{col} {'NOT IN' if f.op == 'not_in' else 'IN'} ({', '.join('?' for _ in f.values)})")
            params += [float(v) if f.field in NUMERIC_FIELDS else v for v in f.values]
        else:
            where.append(f"{col} {_SQL_OPS[f.op]} ?")
            params.append(float(f.values[0]) if f.field in NUMERIC_FIELDS else f.values[0])
    if spec.start:
        where.append("timestamp >= ?")
        params.append(datetime.fromisoformat(spec.start))
    if spec.end:
        where.append("timestamp <= ?")
        params.append(datetime.fromisoformat(spec.end))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    if spec.kind == "list":
        order = "timestamp ASC" if spec.order == "asc" else "timestamp DESC"
        sql = f"SELECT {', '.join(LIST_COLUMNS)} FROM prompts {where_sql} ORDER BY {order} LIMIT {spec.limit}"
        return sql, params

    dims = [f"{DIMENSIONS[d]} AS {d}" for d in spec.group_by]
    mets = [f"{METRICS[m][0]} AS {m}" for m in spec.metrics]
    sql = f"SELECT {', '.join(dims + mets)} FROM prompts {where_sql}"
    if spec.group_by:
        sql += f" GROUP BY {', '.join(str(i + 1) for i in range(len(dims)))}"
        if spec.order == "time":
            sql += f" ORDER BY {', '.join(spec.group_by)}"
        else:
            sql += f" ORDER BY {spec.metrics[0]} {'ASC' if spec.order == 'asc' else 'DESC'}, {spec.group_by[0]}"
        sql += f" LIMIT {spec.limit}"
    return sql, params


def render_sql(sql: str, params: list) -> str:
    """Inline parameters for display only (never executed)."""
    out = sql
    for p in params:
        lit = f"'{p}'" if isinstance(p, (str, datetime)) else str(p).upper() if isinstance(p, bool) else str(p)
        out = out.replace("?", lit, 1)
    return out
