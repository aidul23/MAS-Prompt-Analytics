from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app import chats, traces
from app.baseline import single_model
from app.data import store
from app.mas import orchestrator
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if store.version() is None:
        raise store.NoData("No data is loaded yet. Add a trace export on the Data sources page, then ask again.")
    handler = orchestrator.answer if req.mode == "mas" else single_model.answer
    conversation_id = req.conversation_id
    if req.chat_id:
        conversation_id = f"{req.chat_id}:{req.mode}"
        traces.seed(conversation_id, await run_in_threadpool(chats.turns, req.chat_id, req.mode, 10))
    try:
        resp = await run_in_threadpool(handler, req.question, req.profile, conversation_id)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    if req.chat_id:
        await run_in_threadpool(chats.save, req.chat_id, req.message_id or resp.id, req.ui_mode or req.mode, resp)
    return resp


@router.get("/traces/{response_id}", response_model=ChatResponse)
def get_trace(response_id: str) -> ChatResponse:
    resp = traces.get(response_id)
    if resp is None:
        raise HTTPException(404, "trace not found")
    return resp


@router.delete("/conversations/{conversation_id}")
def reset_conversation(conversation_id: str) -> dict:
    traces.forget(conversation_id)
    return {"ok": True}


class ChatRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.get("/chats")
def list_chats() -> list[dict]:
    return chats.list_chats()


@router.get("/chats/{chat_id}")
def get_chat(chat_id: str) -> dict:
    chat = chats.get_chat(chat_id)
    if chat is None:
        raise HTTPException(404, "chat not found")
    return chat


@router.patch("/chats/{chat_id}")
def rename_chat(chat_id: str, body: ChatRename) -> dict:
    if not chats.rename(chat_id, body.title):
        raise HTTPException(404, "chat not found")
    return {"ok": True}


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: str) -> dict:
    if not chats.delete(chat_id):
        raise HTTPException(404, "chat not found")
    for mode in ("mas", "baseline"):
        traces.forget(f"{chat_id}:{mode}")
    return {"ok": True}
