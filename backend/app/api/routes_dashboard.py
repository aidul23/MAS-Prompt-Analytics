from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.metrics import dashboard as m
from app.metrics.filters import Filters

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def filters(
    start: datetime | None = None,
    end: datetime | None = None,
    app: list[str] = Query(default=[]),
    user_role: list[str] = Query(default=[]),
    prompt_language: list[str] = Query(default=[]),
    topic: list[str] = Query(default=[]),
) -> Filters:
    return Filters(start=start, end=end, app=app, user_role=user_role, prompt_language=prompt_language, topic=topic)


Granularity = Literal["hour", "day"]


@router.get("/filters")
def get_filters():
    return m.filter_options()


@router.get("/summary")
def get_summary(f: Filters = Depends(filters)):
    return m.summary(f)


@router.get("/volume")
def get_volume(granularity: Granularity = "hour", f: Filters = Depends(filters)):
    return m.volume(f, granularity)


@router.get("/breakdown/{dimension}")
def get_breakdown(dimension: str, f: Filters = Depends(filters)):
    try:
        return m.breakdown(f, dimension)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/histogram/{column}")
def get_histogram(column: str, bins: int = Query(12, ge=2, le=50), f: Filters = Depends(filters)):
    try:
        return m.histogram(f, column, bins)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/tokens")
def get_tokens(granularity: Granularity = "hour", f: Filters = Depends(filters)):
    return m.tokens_over_time(f, granularity)


@router.get("/top-prompts")
def get_top_prompts(limit: int = Query(20, ge=1, le=200), f: Filters = Depends(filters)):
    return m.top_prompts(f, limit)


@router.get("/topic-alignment")
def get_topic_alignment(f: Filters = Depends(filters)):
    return m.topic_alignment(f)


@router.get("/sessions")
def get_sessions(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), f: Filters = Depends(filters)):
    return m.sessions(f, limit, offset)
