"""Types shared by the MAS, the baseline and the chat API."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.llm import LLMCall

ChartType = Literal["kpi", "bar", "line", "pie", "table"]


class ChartSpec(BaseModel):
    type: ChartType
    x: str | None = None
    y: list[str] = []
    title: str = ""
    dashboard_section: str | None = None
    source: Literal["llm", "rule"] = "rule"


class DataTable(BaseModel):
    columns: list[str] = []
    rows: list[list[Any]] = []
    total_rows: int = 0


class AgentStep(BaseModel):
    agent: str
    model: str | None = None
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    model_load_s: float = 0.0
    output: Any = None
    error: str | None = None

    def add_call(self, call: LLMCall) -> None:
        self.llm_calls += 1
        self.prompt_tokens += call.prompt_tokens
        self.completion_tokens += call.completion_tokens
        self.model_load_s = round(self.model_load_s + call.load_s, 3)


class Turn(BaseModel):
    question: str
    query: Any = None
    answer: str = ""


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["mas", "baseline"] = "mas"
    profile: str | None = None
    conversation_id: str | None = None
    # Saved chat sessions: when chat_id is set the response is stored and memory comes from the chat.
    chat_id: str | None = Field(default=None, max_length=64)
    message_id: str | None = Field(default=None, max_length=64)
    ui_mode: Literal["mas", "baseline", "compare"] | None = None


class ChatResponse(BaseModel):
    id: str
    conversation_id: str
    mode: Literal["mas", "baseline"]
    profile: str
    question: str
    answer: str
    status: Literal["ok", "out_of_scope", "error"] = "ok"
    data: DataTable | None = None
    chart: ChartSpec | None = None
    sql: str | None = None
    query_spec: dict | None = None
    steps: list[AgentStep] = []
    total_latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    error: str | None = None

    def finalise(self, latency_s: float) -> "ChatResponse":
        self.total_latency_s = round(latency_s, 3)
        self.prompt_tokens = sum(s.prompt_tokens for s in self.steps)
        self.completion_tokens = sum(s.completion_tokens for s in self.steps)
        self.llm_calls = sum(s.llm_calls for s in self.steps)
        return self
