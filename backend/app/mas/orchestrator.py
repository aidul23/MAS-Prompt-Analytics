"""Orchestrator: runs the agents over a shared context and records every step.

data_processing -> query_understanding -> metrics -> visualization_planning -> answer_generation
If the Metrics Agent cannot execute the spec, its error is fed back to the Query
Understanding Agent once (repair loop).
"""

import time
import uuid

from app import traces
from app.config import profile as get_profile
from app.data.context import table_preview
from app.mas import query_spec as qs
from app.mas.agents.answer import AnswerGenerationAgent
from app.mas.agents.base import AgentFailure, SharedContext
from app.mas.agents.data_processing import DataProcessingAgent
from app.mas.agents.metrics import MetricsAgent
from app.mas.agents.query_understanding import QueryUnderstandingAgent
from app.mas.agents.visualization import VisualizationPlanningAgent
from app.schemas import ChatResponse, Turn
from app.viz_rules import plan_chart

OUT_OF_SCOPE = "I can only answer questions about the chatbot usage data (prompts, sessions, topics, apps, latency, tokens)."


class Orchestrator:
    def __init__(self, profile_name: str | None = None):
        self.profile = get_profile(profile_name)
        self.data_agent = DataProcessingAgent(self.profile)
        self.query_agent = QueryUnderstandingAgent(self.profile)
        self.metrics_agent = MetricsAgent(self.profile)
        self.viz_agent = VisualizationPlanningAgent(self.profile)
        self.answer_agent = AnswerGenerationAgent(self.profile)

    def run(self, ctx: SharedContext) -> str:
        """Returns the status: ok / out_of_scope. Raises AgentFailure on unrecoverable errors."""
        self.data_agent.run(ctx)
        self.query_agent.run(ctx)
        if not ctx.in_scope:
            ctx.answer = OUT_OF_SCOPE
            return "out_of_scope"
        try:
            self.metrics_agent.run(ctx)
        except AgentFailure as exc:
            ctx.feedback = str(exc)
            self.query_agent.run(ctx)
            if not ctx.in_scope:
                ctx.answer = OUT_OF_SCOPE
                return "out_of_scope"
            self.metrics_agent.run(ctx)
        try:
            self.viz_agent.run(ctx)
        except AgentFailure:
            ctx.chart = plan_chart(ctx.table)
        try:
            self.answer_agent.run(ctx)
        except AgentFailure:
            ctx.answer = table_preview(ctx.table, 10)
        return "ok"


def answer(question: str, profile_name: str | None = None, conversation_id: str | None = None, log: bool = True) -> ChatResponse:
    t0 = time.perf_counter()
    orch = Orchestrator(profile_name)
    conversation_id = conversation_id or uuid.uuid4().hex
    ctx = SharedContext(question=question, profile=orch.profile, history=traces.history(conversation_id))
    resp = ChatResponse(id=uuid.uuid4().hex, conversation_id=conversation_id, mode="mas", profile=orch.profile["name"], question=question, answer="")
    try:
        resp.status = orch.run(ctx)
    except AgentFailure as exc:
        resp.status, resp.error = "error", str(exc)
        ctx.answer = f"Sorry, I could not answer that question ({exc})."
    resp.answer = ctx.answer
    resp.data, resp.chart = ctx.table, ctx.chart
    resp.query_spec = ctx.spec.model_dump() if ctx.spec else None
    resp.sql = qs.render_sql(ctx.sql, ctx.sql_params) if ctx.sql else None
    resp.steps = ctx.steps
    resp.finalise(time.perf_counter() - t0)
    traces.remember(conversation_id, Turn(question=question, query=resp.query_spec, answer=resp.answer))
    traces.record(resp, log=log)
    return resp
