"""Predefined dashboard metrics (RQ3). All functions are deterministic SQL over the feature tables."""

from app.data import store
from app.metrics.filters import Filters

BREAKDOWN_DIMENSIONS = (
    "topic", "app", "intent", "prompt_language", "output_language", "user_role", "response_topic", "weekday", "hour",
)
# date_trunc units; "week" starts on Monday (ISO).
GRANULARITIES = ("hour", "day", "week")


def _records(sql: str, params: list) -> list[dict]:
    df = store.query(sql, params)
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def summary(f: Filters) -> dict:
    where, p = f.where()
    rows = _records(
        f"""
        SELECT count(*) AS prompts,
               count(DISTINCT session_id) AS sessions,
               count(DISTINCT user_id) AS users,
               count(DISTINCT organization_id) AS organizations,
               round(avg(latency_s), 2) AS avg_latency_s,
               round(quantile_cont(latency_s, 0.95), 2) AS p95_latency_s,
               CAST(sum(total_tokens) AS BIGINT) AS total_tokens,
               round(avg(total_tokens)) AS avg_tokens_per_prompt,
               round(avg(prompt_words), 1) AS avg_prompt_words,
               round(avg(CASE WHEN response_on_topic THEN 1.0 ELSE 0.0 END), 3) AS on_topic_rate,
               round(avg(CASE WHEN language_match THEN 1.0 ELSE 0.0 END), 3) AS language_match_rate,
               round(count(*) * 1.0 / nullif(count(DISTINCT session_id), 0), 2) AS prompts_per_session
        FROM prompts {where}
        """,
        p,
    )
    return rows[0]


def volume(f: Filters, granularity: str = "hour") -> list[dict]:
    unit = granularity if granularity in GRANULARITIES else "hour"
    where, p = f.where()
    return _records(
        f"""
        SELECT date_trunc('{unit}', timestamp) AS bucket, count(*) AS prompts,
               count(DISTINCT session_id) AS sessions, CAST(sum(total_tokens) AS BIGINT) AS total_tokens
        FROM prompts {where} GROUP BY 1 ORDER BY 1
        """,
        p,
    )


def breakdown(f: Filters, dimension: str) -> list[dict]:
    if dimension not in BREAKDOWN_DIMENSIONS:
        raise ValueError(f"dimension must be one of {BREAKDOWN_DIMENSIONS}")
    where, p = f.where()
    return _records(
        f"""
        SELECT {dimension} AS key, count(*) AS prompts,
               round(avg(latency_s), 2) AS avg_latency_s,
               round(avg(total_tokens)) AS avg_tokens,
               round(avg(CASE WHEN response_on_topic THEN 1.0 ELSE 0.0 END), 3) AS on_topic_rate
        FROM prompts {where} GROUP BY 1 ORDER BY prompts DESC, key
        """,
        p,
    )


def histogram(f: Filters, column: str, bins: int = 12) -> list[dict]:
    if column not in ("prompt_chars", "prompt_words", "output_words", "latency_s", "total_tokens"):
        raise ValueError("unsupported histogram column")
    where, p = f.where()
    stats = store.query(f"SELECT min({column}) lo, max({column}) hi FROM prompts {where}", p)
    lo, hi = stats["lo"][0], stats["hi"][0]
    if lo is None or hi is None:
        return []
    width = max((float(hi) - float(lo)) / bins, 1e-9)
    rows = _records(
        f"""
        SELECT least(floor(({column} - ?) / ?), ?) AS b, count(*) AS n
        FROM prompts {where} GROUP BY 1 ORDER BY 1
        """,
        [float(lo), width, bins - 1, *p],
    )
    counts = {int(r["b"]): r["n"] for r in rows}
    return [
        {"from": round(float(lo) + i * width, 2), "to": round(float(lo) + (i + 1) * width, 2), "count": counts.get(i, 0)}
        for i in range(bins)
    ]


def tokens_over_time(f: Filters, granularity: str = "hour") -> list[dict]:
    unit = granularity if granularity in GRANULARITIES else "hour"
    where, p = f.where()
    return _records(
        f"""
        SELECT date_trunc('{unit}', timestamp) AS bucket, CAST(sum(input_tokens) AS BIGINT) AS input_tokens,
               CAST(sum(output_tokens) AS BIGINT) AS output_tokens, round(avg(latency_s), 2) AS avg_latency_s
        FROM prompts {where} GROUP BY 1 ORDER BY 1
        """,
        p,
    )


def top_prompts(f: Filters, limit: int = 20) -> list[dict]:
    where, p = f.where()
    return _records(
        f"""
        SELECT prompt, any_value(prompt_english) AS prompt_english, any_value(prompt_language) AS language,
               any_value(topic) AS topic, any_value(intent) AS intent, count(*) AS count,
               round(avg(CASE WHEN response_on_topic THEN 1.0 ELSE 0.0 END), 3) AS on_topic_rate
        FROM prompts {where} GROUP BY prompt ORDER BY count DESC, prompt LIMIT ?
        """,
        [*p, limit],
    )


def topic_alignment(f: Filters) -> list[dict]:
    """Prompt topic vs. response topic matrix: how often the bot answered a different subject."""
    where, p = f.where()
    return _records(
        f"""
        SELECT topic, response_topic, count(*) AS count
        FROM prompts {where} GROUP BY 1, 2 ORDER BY 1, 2
        """,
        p,
    )


def sessions(f: Filters, limit: int = 50, offset: int = 0) -> dict:
    where, p = f.where()
    session_filter = f"WHERE session_id IN (SELECT session_id FROM prompts {where})" if where else ""
    total = store.query(f"SELECT count(*) n FROM sessions {session_filter}", p)["n"][0]
    rows = _records(
        f"""
        SELECT session_id, user_id, app, user_role, started_at, turns, duration_s, total_tokens,
               round(avg_latency_s, 2) AS avg_latency_s, languages, topics
        FROM sessions {session_filter} ORDER BY started_at DESC LIMIT ? OFFSET ?
        """,
        [*p, limit, offset],
    )
    return {"total": int(total), "rows": rows}


def filter_options() -> dict:
    values = store.categorical_values()
    return {
        "range": store.data_range(),
        "app": values.get("app", []),
        "user_role": values.get("user_role", []),
        "prompt_language": values.get("prompt_language", []),
        "topic": values.get("topic", []),
    }
