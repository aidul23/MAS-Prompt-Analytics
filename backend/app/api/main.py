"""FastAPI entry point: `uv run uvicorn app.api.main:app --reload --port 8000`."""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import llm
from app.api import routes_chat, routes_dashboard, routes_data, routes_models
from app.config import DB_PATH, all_profiles, default_profile_name
from app.data import sources, store

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    sources.ensure_initialised()
    sources.mark_interrupted()
    if not DB_PATH.exists() and sources.has_files():
        sources.start_sync("startup")
    stop = threading.Event()
    threading.Thread(target=sources.scheduler, args=(stop,), name="data-scheduler", daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="SLM-MAS Prompt Analytics", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.exception_handler(store.NoData)
async def no_data(_: Request, exc: store.NoData) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


app.include_router(routes_dashboard.router)
app.include_router(routes_chat.router)
app.include_router(routes_data.router)
app.include_router(routes_models.router)


@app.get("/api/health")
def health():
    return {
        "database": DB_PATH.exists(),
        "data_version": store.version(),
        "ollama": llm.is_available(),
        "profiles": list(all_profiles()),
        "default_profile": default_profile_name(),
    }
