import pytest

from app import chats
from app.schemas import ChatResponse


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(chats, "CHATS_DB", tmp_path / "chats.sqlite")


def _resp(rid: str, question: str, mode: str = "mas", **kw) -> ChatResponse:
    return ChatResponse(id=rid, conversation_id="c", mode=mode, profile="small", question=question, answer=f"answer to {question}", **kw)


def test_save_list_and_load_chat():
    chats.save("chat1", "m1", "mas", _resp("r1", "How many prompts per app?", query_spec={"metrics": ["prompt_count"]}))
    chats.save("chat1", "m2", "compare", _resp("r2", "And only Finnish?"))
    chats.save("chat1", "m2", "compare", _resp("r3", "And only Finnish?", mode="baseline", sql="SELECT 1"))

    [listed] = chats.list_chats()
    assert listed["id"] == "chat1" and listed["title"] == "How many prompts per app?" and listed["messages"] == 2

    chat = chats.get_chat("chat1")
    assert [m["mode"] for m in chat["messages"]] == ["mas", "compare"]
    assert [r.mode for r in chat["messages"][1]["responses"]] == ["mas", "baseline"]


def test_turns_rebuild_memory_per_mode():
    chats.save("chat1", "m1", "mas", _resp("r1", "Prompts per app", query_spec={"group_by": ["app"]}))
    chats.save("chat1", "m2", "baseline", _resp("r2", "Average latency", mode="baseline", sql="SELECT avg(latency_s) FROM prompts"))
    [mas] = chats.turns("chat1", "mas", 3)
    [base] = chats.turns("chat1", "baseline", 3)
    assert mas.query == {"group_by": ["app"]} and base.query.startswith("SELECT")


def test_rename_delete_and_long_titles():
    chats.save("chat1", "m1", "mas", _resp("r1", "x" * 100))
    assert len(chats.list_chats()[0]["title"]) == chats.TITLE_CHARS
    assert chats.rename("chat1", "Latency questions")
    assert chats.get_chat("chat1")["title"] == "Latency questions"
    assert chats.delete("chat1") and chats.get_chat("chat1") is None and chats.turns("chat1", "mas", 3) == []
    assert not chats.delete("missing")
