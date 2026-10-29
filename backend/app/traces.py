"""Stores chat responses (with per-agent steps) in memory and appends them to a JSONL log."""

import threading
from collections import OrderedDict

from app.config import TRACE_LOG
from app.schemas import ChatResponse, Turn

_MAX_IN_MEMORY = 500
_lock = threading.Lock()
_responses: "OrderedDict[str, ChatResponse]" = OrderedDict()
_conversations: dict[str, list[Turn]] = {}


def record(resp: ChatResponse, log: bool = True) -> None:
    with _lock:
        _responses[resp.id] = resp
        while len(_responses) > _MAX_IN_MEMORY:
            _responses.popitem(last=False)
        if log:
            TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(TRACE_LOG, "a", encoding="utf-8") as f:
                f.write(resp.model_dump_json() + "\n")


def get(response_id: str) -> ChatResponse | None:
    return _responses.get(response_id)


def history(conversation_id: str, max_turns: int = 3) -> list[Turn]:
    return list(_conversations.get(conversation_id, []))[-max_turns:]


def remember(conversation_id: str, turn: Turn) -> None:
    with _lock:
        _conversations.setdefault(conversation_id, []).append(turn)
        del _conversations[conversation_id][:-10]


def seed(conversation_id: str, turns: list[Turn]) -> None:
    """Restore memory for a conversation not held in memory (e.g. a saved chat after a restart)."""
    with _lock:
        if conversation_id not in _conversations:
            _conversations[conversation_id] = list(turns)[-10:]


def forget(conversation_id: str) -> None:
    with _lock:
        _conversations.pop(conversation_id, None)
