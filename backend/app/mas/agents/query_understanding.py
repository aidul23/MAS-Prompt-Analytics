"""Query Understanding Agent: question (+ conversation history) -> validated QuerySpec."""

import json

from pydantic import ValidationError

from app.config import mas_options
from app.data.context import context_text
from app.mas import query_spec as qs
from app.mas.agents.base import Agent, AgentFailure, SharedContext
from app.mas.agents.data_processing import DataProcessingAgent
from app.schemas import AgentStep

MAX_ATTEMPTS = 3

SYSTEM = """You translate questions about chatbot usage analytics into a JSON query spec. Never write SQL.

{context}

Spec fields:
- in_scope: false if the question is not about this chatbot usage data (then other fields are ignored).
- kind: "aggregate" for numbers/statistics, "list" to show individual prompts.
- metrics (aggregate only): one or more of
{metrics}
- group_by: up to 2 of {dims}. day = per calendar day, hour_bucket = per hour over time, hour_of_day = 0-23.
- filters: list of {{"field", "op", "values"}}. fields: {fields}.
  ops: eq, neq, in, not_in, gt, gte, lt, lte, contains (contains = substring of prompt_text). Use known values exactly.
- start / end: ISO date or datetime (inclusive), "today", "yesterday", or null. Use these for dates, never weekday filters.
- Only add filters the question asks for.
- order: "desc" (largest first), "asc" (smallest first) or "time". limit: max rows (use 1 for "which ... most", N for "top N").

For follow-up questions, start from the previous spec and change only what the user asks for."""


EXAMPLES = [
    ('How many prompts were in Finnish?', {"in_scope": True, "kind": "aggregate", "metrics": ["prompt_count"], "group_by": [], "filters": [{"field": "prompt_language", "op": "eq", "values": ["fi"]}], "start": None, "end": None, "order": "desc", "limit": 50}),
    ('Which app has the highest average latency?', {"in_scope": True, "kind": "aggregate", "metrics": ["avg_latency"], "group_by": ["app"], "filters": [], "start": None, "end": None, "order": "desc", "limit": 1}),
    ('Show daily prompt volume for LianaMailer', {"in_scope": True, "kind": "aggregate", "metrics": ["prompt_count"], "group_by": ["day"], "filters": [{"field": "app", "op": "eq", "values": ["LianaMailer"]}], "start": None, "end": None, "order": "time", "limit": 50}),
    ('Top 3 topics among admins and their share', {"in_scope": True, "kind": "aggregate", "metrics": ["prompt_count", "share_of_prompts"], "group_by": ["topic"], "filters": [{"field": "user_role", "op": "eq", "values": ["Admin"]}], "start": None, "end": None, "order": "desc", "limit": 3}),
    ('What share of answers is off-topic for each topic?', {"in_scope": True, "kind": "aggregate", "metrics": ["off_topic_rate", "off_topic_count"], "group_by": ["topic"], "filters": [], "start": None, "end": None, "order": "desc", "limit": 50}),
    ('How many sessions were there yesterday?', {"in_scope": True, "kind": "aggregate", "metrics": ["session_count"], "group_by": [], "filters": [], "start": "yesterday", "end": "yesterday", "order": "desc", "limit": 50}),
    ('Show some Finnish prompts about newsletters', {"in_scope": True, "kind": "list", "metrics": [], "group_by": [], "filters": [{"field": "prompt_language", "op": "eq", "values": ["fi"]}, {"field": "topic", "op": "eq", "values": ["Newsletter Creation"]}], "start": None, "end": None, "order": "desc", "limit": 10}),
    ('What was the median latency on June 4?', {"in_scope": True, "kind": "aggregate", "metrics": ["median_latency"], "group_by": [], "filters": [], "start": "2026-06-04", "end": "2026-06-04", "order": "desc", "limit": 50}),
    ('List prompts longer than 50 words', {"in_scope": True, "kind": "list", "metrics": [], "group_by": [], "filters": [{"field": "prompt_words", "op": "gt", "values": [50]}], "start": None, "end": None, "order": "desc", "limit": 50}),
    ('Write me a poem about cats', {"in_scope": False, "kind": "aggregate", "metrics": [], "group_by": [], "filters": [], "start": None, "end": None, "order": "desc", "limit": 50}),
]


def _schema() -> dict:
    s = qs.json_schema()
    return {**s, "properties": {"in_scope": {"type": "boolean"}, **s["properties"]}, "required": ["in_scope", *s["required"]]}


class QueryUnderstandingAgent(Agent):
    name = "query_understanding"
    model_role = "query_understanding"

    def system_prompt(self) -> str:
        return SYSTEM.format(
            context=context_text(),
            metrics="\n".join(f"  {k}: {desc}" for k, (_, desc) in qs.METRICS.items()),
            dims=", ".join(qs.DIMENSIONS),
            fields=", ".join(qs.FILTER_FIELDS),
        )

    def act(self, ctx: SharedContext, step: AgentStep) -> dict:
        messages = [{"role": "system", "content": self.system_prompt()}]
        for q, spec in EXAMPLES:
            messages += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(spec)}]
        for turn in ctx.history:
            if turn.query is not None and not isinstance(turn.query, dict):
                continue
            messages.append({"role": "user", "content": turn.question})
            messages.append({"role": "assistant", "content": json.dumps({"in_scope": turn.query is not None, **(turn.query or {})})})
        messages.append({"role": "user", "content": ctx.question})
        if ctx.feedback:
            messages.append({"role": "user", "content": f"The previous spec failed: {ctx.feedback}. Return a corrected spec."})

        errors = []
        for _attempt in range(MAX_ATTEMPTS):
            res = self.chat(step, messages, schema=_schema(), max_tokens=400)
            raw = dict(res.parsed)
            if not raw.pop("in_scope", True):
                ctx.in_scope, ctx.spec = False, None
                return {"in_scope": False}
            try:
                spec = qs.QuerySpec.model_validate(raw)
                spec = qs.normalise(spec, ctx.data_context["values"], DataProcessingAgent.data_end(ctx))
                dropped = []
                if mas_options().get("ground_filters", True):
                    asked = " ".join([*(t.question for t in ctx.history), ctx.question])
                    spec, dropped = qs.ground_filters(spec, asked, ctx.data_context["grounding"])
                ctx.in_scope, ctx.spec = True, spec
                return {"in_scope": True, "spec": spec.model_dump(), "description": spec.describe(), "retries": len(errors), "dropped_filters": dropped}
            except (ValidationError, qs.SpecError) as exc:
                msg = _short_error(exc)
                errors.append(msg)
                messages += [
                    {"role": "assistant", "content": res.content},
                    {"role": "user", "content": f"Invalid spec: {msg}. Return a corrected spec."},
                ]
        raise AgentFailure(f"could not produce a valid query spec: {errors[-1]}")


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())[:400]
    return str(exc)[:400]
