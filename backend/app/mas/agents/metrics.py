"""Metrics Agent: compiles the QuerySpec to SQL and executes it. Deterministic (tool agent)."""

import duckdb

from app.data import store
from app.data.context import to_table
from app.mas import query_spec as qs
from app.mas.agents.base import Agent, AgentFailure, SharedContext
from app.schemas import AgentStep

MAX_ROWS = 200


class MetricsAgent(Agent):
    name = "metrics"

    def act(self, ctx: SharedContext, step: AgentStep) -> dict:
        sql, params = qs.compile_sql(ctx.spec)
        ctx.sql, ctx.sql_params = sql, params
        try:
            df = store.query(sql, params)
        except duckdb.Error as exc:
            raise AgentFailure(str(exc).splitlines()[0]) from exc
        ctx.table = to_table(df, MAX_ROWS)
        return {"sql": qs.render_sql(sql, params), "rows": ctx.table.total_rows, "columns": ctx.table.columns}
