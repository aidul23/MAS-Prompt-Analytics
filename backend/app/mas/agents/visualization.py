"""Visualization Planning Agent: chooses a chart for the result and links it to a dashboard section."""

from app.data.context import table_preview
from app.mas.agents.base import Agent, SharedContext
from app.schemas import AgentStep, ChartSpec
from app.viz_rules import is_time_column, numeric_columns, plan_chart

SECTIONS = ["overview", "volume", "topics", "quality", "latency_tokens", "prompts", "sessions"]

SCHEMA = {
    "type": "object",
    "properties": {
        "chart_type": {"type": "string", "enum": ["kpi", "bar", "line", "pie", "table"]},
        "x": {"type": ["string", "null"]},
        "y": {"type": "array", "items": {"type": "string"}},
        "title": {"type": "string"},
        "dashboard_section": {"type": "string", "enum": SECTIONS},
    },
    "required": ["chart_type", "x", "y", "title", "dashboard_section"],
}

SYSTEM = """You plan visualisations for analytics answers. Given a question and the result table, pick a chart:
- kpi: a single number or a single row
- line: values over time (day, hour_bucket, hour_of_day)
- bar: comparing categories
- pie: shares of a whole with at most 6 categories
- table: lists of prompts or results with many columns
x must be a category or time column of the result; y must be numeric columns of the result.
Also pick the dashboard section that shows related information:
overview (KPIs), volume (prompts over time), topics (topics, intents, languages, apps), quality (on-topic and language match),
latency_tokens (latency and token usage), prompts (top prompts), sessions (session table).
Title: short, max 8 words. Answer in JSON."""


class VisualizationPlanningAgent(Agent):
    name = "visualization_planning"
    model_role = "visualization_planning"

    def act(self, ctx: SharedContext, step: AgentStep) -> dict:
        table = ctx.table
        rule = plan_chart(table, title="")
        trivial = table.total_rows <= 1 or getattr(ctx.spec, "kind", "aggregate") == "list"
        if trivial:
            rule.dashboard_section = _section_for(ctx)
            ctx.chart = rule
            return {"chart": rule.model_dump(), "skipped_llm": True}

        user = (
            f"Question: {ctx.question}\nQuery: {ctx.spec.describe()}\n"
            f"Numeric columns: {', '.join(numeric_columns(table)) or 'none'}\nResult ({table.total_rows} rows):\n{table_preview(table, 8)}"
        )
        res = self.chat(step, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], schema=SCHEMA, max_tokens=150)
        chart, problem = _validate(res.parsed, table)
        if chart is None:
            rule.title = res.parsed.get("title", "")
            rule.dashboard_section = res.parsed.get("dashboard_section") or _section_for(ctx)
            ctx.chart = rule
            return {"chart": rule.model_dump(), "fallback_reason": problem, "proposed": res.parsed}
        ctx.chart = chart
        return {"chart": chart.model_dump()}


def _validate(p: dict, table) -> tuple[ChartSpec | None, str | None]:
    nums = numeric_columns(table)
    ctype, x = p.get("chart_type"), p.get("x")
    y = [c for c in p.get("y", []) if c in nums]
    if ctype == "table":
        return ChartSpec(type="table", title=p.get("title", ""), dashboard_section=p.get("dashboard_section"), source="llm"), None
    if not y:
        return None, f"y {p.get('y')} has no numeric result column"
    if ctype in ("bar", "line", "pie"):
        if x not in table.columns or x in nums and not is_time_column(table, x):
            return None, f"x '{x}' is not a category/time column"
        if ctype == "pie" and (table.total_rows > 6 or len(y) != 1):
            return None, "pie needs at most 6 rows and one measure"
        if ctype == "line" and not is_time_column(table, x):
            return None, f"line chart needs a time x axis, got '{x}'"
    if ctype == "kpi" and table.total_rows > 3:
        return None, "kpi only suits 1-3 rows"
    return ChartSpec(type=ctype, x=x if ctype != "kpi" else None, y=y, title=p.get("title", ""), dashboard_section=p.get("dashboard_section"), source="llm"), None


def _section_for(ctx: SharedContext) -> str:
    spec = ctx.spec
    if spec is None or spec.kind == "list":
        return "prompts"
    metrics, dims = set(spec.metrics), set(spec.group_by)
    if dims & {"day", "hour_bucket", "hour_of_day", "weekday"}:
        return "volume"
    if metrics & {"on_topic_rate", "off_topic_count", "language_match_rate", "language_mismatch_count"}:
        return "quality"
    if any("latency" in m or "token" in m for m in metrics):
        return "latency_tokens"
    if dims & {"topic", "intent", "prompt_language", "app", "user_role"}:
        return "topics"
    return "overview"
