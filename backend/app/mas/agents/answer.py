"""Answer Generation Agent: turns the result table into a short grounded answer."""

from app.data.context import table_preview
from app.mas.agents.base import Agent, SharedContext
from app.schemas import AgentStep

SYSTEM = """You write answers for a chatbot-analytics assistant. You get the user's question, a description of the query that was run and the result table.
- Answer in 1-3 sentences, directly, using the exact numbers from the result. Never invent, estimate or add up numbers.
- Only talk about rows that are in the result. Do not count rows yourself; the row count is given.
- Rates are already given as percentages; copy them as they are. Latencies are in seconds.
- If there are many rows, mention the most important ones; the user also sees the full table and a chart. Do not describe the chart.
- For a list of prompts, summarise it in one or two sentences instead of listing the rows.
- If the result is empty, say no matching data was found.
- Reply in the same language as the question."""

LIST_PREVIEW_COLUMNS = ("timestamp", "app", "prompt", "topic", "response_on_topic")


class AnswerGenerationAgent(Agent):
    name = "answer_generation"
    model_role = "answer_generation"

    def act(self, ctx: SharedContext, step: AgentStep) -> dict:
        table = ctx.table
        if ctx.spec.kind == "list":
            keep = [i for i, c in enumerate(table.columns) if c in LIST_PREVIEW_COLUMNS]
            table = table.model_copy(update={"columns": [table.columns[i] for i in keep], "rows": [[r[i] for i in keep] for r in table.rows]})
        user = f"Question: {ctx.question}\nQuery: {ctx.spec.describe()}\nResult ({table.total_rows} rows):\n{table_preview(table, 25)}"
        res = self.chat(step, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], temperature=0.2, max_tokens=250)
        ctx.answer = res.content.strip()
        return {"chars": len(ctx.answer)}
