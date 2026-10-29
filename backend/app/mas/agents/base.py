import time
from dataclasses import dataclass, field
from typing import Any

from app import llm
from app.schemas import AgentStep, ChartSpec, DataTable, Turn


@dataclass
class SharedContext:
    """Blackboard that the orchestrator passes from agent to agent."""

    question: str
    profile: dict
    history: list[Turn] = field(default_factory=list)
    data_context: dict | None = None
    spec: Any = None
    in_scope: bool = True
    sql: str | None = None
    sql_params: list = field(default_factory=list)
    table: DataTable | None = None
    chart: ChartSpec | None = None
    answer: str = ""
    feedback: str | None = None
    steps: list[AgentStep] = field(default_factory=list)


class AgentFailure(RuntimeError):
    pass


class Agent:
    name = "agent"
    model_role: str | None = None

    def __init__(self, profile: dict):
        self.model = profile.get(self.model_role) if self.model_role else None

    def run(self, ctx: SharedContext) -> AgentStep:
        step = AgentStep(agent=self.name, model=self.model)
        ctx.steps.append(step)
        t0 = time.perf_counter()
        try:
            step.output = self.act(ctx, step)
        except (AgentFailure, llm.LLMError) as exc:
            step.error = str(exc)
            raise AgentFailure(f"{self.name}: {exc}") from exc
        finally:
            step.latency_s = round(time.perf_counter() - t0, 3)
        return step

    def act(self, ctx: SharedContext, step: AgentStep) -> Any:
        raise NotImplementedError

    def chat(self, step: AgentStep, messages: list[dict], **kwargs) -> llm.LLMResult:
        res = llm.chat(self.model, messages, **kwargs)
        step.add_call(res.call)
        return res
