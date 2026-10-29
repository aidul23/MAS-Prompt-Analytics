"""Single-model baseline: one SLM writes DuckDB SQL, the same SLM then phrases the answer.

There are no agent roles. The model gets the same data context as the MAS and one
SQL repair attempt, so the comparison isolates the effect of task decomposition.
"""

import json
import re
import time
import uuid

import duckdb

from app import llm, traces
from app.config import profile as get_profile
from app.data import store
from app.data.context import context_text, table_preview, to_table
from app.mas.agents.answer import SYSTEM as ANSWER_AGENT_SYSTEM
from app.schemas import AgentStep, ChatResponse, Turn
from app.viz_rules import plan_chart

SQL_SCHEMA = {
    "type": "object",
    "properties": {
        "in_scope": {"type": "boolean"},
        "sql": {"type": "string"},
    },
    "required": ["in_scope", "sql"],
}

SQL_SYSTEM = """You are a data analyst for a chatbot analytics product. Write one DuckDB SQL SELECT query that answers the user's question about chatbot usage data.

{context}

Rules:
- Only query the tables prompts and sessions. Only SELECT statements.
- Use exact known values for filters (e.g. app = 'LianaMailer', prompt_language = 'fi').
- Booleans: response_on_topic, language_match. Rates: avg(CASE WHEN x THEN 1.0 ELSE 0.0 END).
- Give result columns short snake_case aliases.
- If the question is not about this data, set in_scope to false and sql to "".
Answer in JSON: {{"in_scope": true, "sql": "SELECT ..."}}"""

ANSWER_SYSTEM = ANSWER_AGENT_SYSTEM.replace("a description of the query that was run", "the SQL that was run")

OUT_OF_SCOPE = "I can only answer questions about the chatbot usage data (prompts, sessions, topics, apps, latency, tokens)."
MAX_RESULT_ROWS = 200
_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|copy|pragma|install|load|export|call|set)\b", re.I)


def validate_sql(sql: str) -> str:
    sql = sql.strip().rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Only a single statement is allowed")
    if not re.match(r"^(select|with)\b", sql, re.I):
        raise ValueError("Query must start with SELECT or WITH")
    if _FORBIDDEN.search(sql):
        raise ValueError("Query contains a forbidden keyword")
    return sql


def _history_messages(history: list[Turn]) -> list[dict]:
    msgs = []
    for t in history:
        msgs.append({"role": "user", "content": t.question})
        msgs.append({"role": "assistant", "content": json.dumps({"in_scope": True, "sql": t.query}) if t.query else OUT_OF_SCOPE})
    return msgs


def answer(question: str, profile_name: str | None = None, conversation_id: str | None = None, log: bool = True) -> ChatResponse:
    t0 = time.perf_counter()
    prof = get_profile(profile_name)
    model = prof["baseline"]
    conversation_id = conversation_id or uuid.uuid4().hex
    history = traces.history(conversation_id)
    resp = ChatResponse(id=uuid.uuid4().hex, conversation_id=conversation_id, mode="baseline", profile=prof["name"], question=question, answer="")

    sql_step = AgentStep(agent="single_model:sql", model=model)
    resp.steps.append(sql_step)
    messages = [{"role": "system", "content": SQL_SYSTEM.format(context=context_text())}, *_history_messages(history), {"role": "user", "content": question}]
    table, sql, last_error = None, None, None
    s0 = time.perf_counter()
    try:
        for _attempt in range(2):
            res = llm.chat(model, messages, schema=SQL_SCHEMA, max_tokens=600)
            sql_step.add_call(res.call)
            if not res.parsed.get("in_scope", True) or not res.parsed.get("sql", "").strip():
                break
            try:
                sql = validate_sql(res.parsed["sql"])
                df = store.query(f"SELECT * FROM ({sql}) AS q LIMIT {MAX_RESULT_ROWS + 1}")
                table = to_table(df, MAX_RESULT_ROWS)
                last_error = None
                break
            except (duckdb.Error, ValueError) as exc:
                last_error = str(exc).splitlines()[0][:300]
                messages += [
                    {"role": "assistant", "content": res.content},
                    {"role": "user", "content": f"That query failed: {last_error}\nReturn a corrected query."},
                ]
    except llm.LLMError as exc:
        last_error = str(exc)
    sql_step.latency_s = round(time.perf_counter() - s0, 3)
    sql_step.output = {"sql": sql}
    sql_step.error = last_error
    resp.sql = sql

    if table is None:
        resp.status = "error" if last_error else "out_of_scope"
        resp.answer = f"Sorry, I could not compute an answer ({last_error})." if last_error else OUT_OF_SCOPE
        resp.error = last_error
    else:
        resp.data = table
        resp.chart = plan_chart(table)
        ans_step = AgentStep(agent="single_model:answer", model=model)
        resp.steps.append(ans_step)
        s1 = time.perf_counter()
        try:
            res = llm.chat(
                model,
                [
                    {"role": "system", "content": ANSWER_SYSTEM},
                    {"role": "user", "content": f"Question: {question}\nSQL: {sql}\nResult:\n{table_preview(table)}"},
                ],
                temperature=0.2,
                max_tokens=300,
            )
            ans_step.add_call(res.call)
            resp.answer = res.content.strip()
        except llm.LLMError as exc:
            ans_step.error = str(exc)
            resp.answer = table_preview(table, 10)
        ans_step.latency_s = round(time.perf_counter() - s1, 3)

    resp.finalise(time.perf_counter() - t0)
    traces.remember(conversation_id, Turn(question=question, query=sql, answer=resp.answer))
    traces.record(resp, log=log)
    return resp
