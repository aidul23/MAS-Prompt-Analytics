"""Data Processing Agent.

Offline: runs the feature pipeline (loading, cleaning, SLM normalisation, topic
clustering) and caches SLM outputs. Online: provides the other agents with the
data context (schema, known values, time range) without any model call.
"""

from datetime import datetime

from app.config import models_config
from app.data import context, pipeline
from app.mas.agents.base import Agent, SharedContext
from app.schemas import AgentStep


class DataProcessingAgent(Agent):
    name = "data_processing"

    def __init__(self, profile: dict):
        super().__init__(profile)
        self.model = models_config()["data_processing_model"]

    def act(self, ctx: SharedContext, step: AgentStep) -> dict:
        ctx.data_context = context.data_context()
        rng = ctx.data_context["range"]
        return {"rows": rng["rows"], "range": [rng["start"], rng["end"]], "known_fields": list(ctx.data_context["values"])}

    @staticmethod
    def data_end(ctx: SharedContext) -> datetime:
        return datetime.fromisoformat(ctx.data_context["range"]["end"])

    @staticmethod
    def rebuild(**kwargs) -> dict:
        report = pipeline.build(**kwargs)
        context.refresh()
        return report
