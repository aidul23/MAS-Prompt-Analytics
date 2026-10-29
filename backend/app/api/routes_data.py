"""Data source management: upload exports, watched folders, sync status and history."""

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import SOURCES_DIR
from app.data import sources

router = APIRouter(prefix="/api/data")

INTERVALS = (None, 5, 15, 60, 1440)


class FolderSource(BaseModel):
    name: str = ""
    path: str
    sync_interval_min: int | None = Field(default=15)


class SourceUpdate(BaseModel):
    name: str | None = None
    sync_interval_min: int | None = -1
    enabled: bool | None = None


def _check_interval(minutes: int | None) -> None:
    if minutes != -1 and minutes not in INTERVALS:
        raise HTTPException(422, f"sync_interval_min must be one of {INTERVALS}")


@router.get("/status")
def status():
    return sources.status()


@router.get("/sources")
def list_sources():
    return sources.list_sources()


@router.get("/syncs")
def list_syncs(limit: int = 20):
    return sources.list_syncs(limit)


@router.post("/sync")
def sync():
    sync_id = sources.start_sync("manual")
    return {"sync_id": sync_id, "queued": sync_id is None}


@router.post("/upload")
def upload(file: UploadFile = File(...)):
    incoming = SOURCES_DIR / ".incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=incoming, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
    tmp_path = Path(tmp.name)
    try:
        info = sources.add_upload(tmp_path, file.filename or "upload.csv")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"file": info, "sync_id": sources.start_sync("upload", scan=False)}


@router.post("/sources")
def add_folder(body: FolderSource):
    _check_interval(body.sync_interval_min)
    try:
        source = sources.add_folder_source(body.name, body.path, body.sync_interval_min)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    imported, problems = sources.scan_folder(source["id"])
    sync_id = sources.start_sync("folder added", scan=False) if imported else None
    return {"source": source, "imported": imported, "problems": problems, "sync_id": sync_id}


@router.patch("/sources/{source_id}")
def update_source(source_id: str, body: SourceUpdate):
    _check_interval(body.sync_interval_min)
    try:
        return sources.update_source(source_id, name=body.name, sync_interval_min=body.sync_interval_min, enabled=body.enabled)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/sources/{source_id}")
def delete_source(source_id: str):
    try:
        sources.delete_source(source_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "sync_id": sources.start_sync("source removed", scan=False)}


@router.delete("/files/{file_id}")
def delete_file(file_id: str):
    try:
        sources.delete_file(file_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True, "sync_id": sources.start_sync("file removed", scan=False)}
