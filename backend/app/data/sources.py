"""Data sources: uploaded trace exports and watched folders, synced into the analytics database.

Updates are incremental in effect: every imported file is kept, traces are deduplicated by id (a later
file replaces an earlier version of the same trace), and the feature database is rebuilt into a temporary
file and swapped in atomically. SLM outputs are cached per distinct text, so only new prompts and
responses cost model calls. A failed sync leaves the current data untouched.
"""

import hashlib
import logging
import re
import shutil
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app import llm
from app.config import DATA_DIR, DB_PATH, RAW_CSV, SOURCES_DB, SOURCES_DIR
from app.data import context, loader, pipeline, store

log = logging.getLogger(__name__)

UPLOADS = "uploads"
SCHEDULER_TICK_S = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT,
    sync_interval_min INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_checked_at TEXT
);
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    managed INTEGER NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    rows INTEGER NOT NULL,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS syncs (
    id TEXT PRIMARY KEY,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    files INTEGER,
    rows_before INTEGER,
    rows_after INTEGER,
    new_traces INTEGER,
    message TEXT
);
"""


class SyncBusy(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    SOURCES_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(SOURCES_DB)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _store_path(path: Path) -> str:
    """Paths inside the data folder are stored relative to it, so the folder can be moved or mounted elsewhere (e.g. Docker)."""
    try:
        return str(path.resolve().relative_to(DATA_DIR.resolve()))
    except ValueError:
        return str(path)


def _resolve(stored: str) -> Path:
    path = Path(stored)
    if not path.is_absolute():
        return DATA_DIR / path
    if path.exists():
        return path
    # Registries written before relative paths: re-anchor files that lived in the old data folder.
    parts = path.parts
    candidate = DATA_DIR.joinpath(*parts[len(parts) - 1 - parts[::-1].index("sources") :]) if "sources" in parts else DATA_DIR / path.name
    return candidate if candidate.exists() else path


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", Path(name).name)[:120] or "upload"


# --- registry -----------------------------------------------------------------------------------


def ensure_initialised() -> None:
    """Create the uploads source; on the very first run register the bundled dataset so existing setups keep working.

    Later runs never re-register it, so removing every file really leaves the dataset empty.
    """
    with _connect() as con:
        first_run = (
            con.execute("INSERT OR IGNORE INTO sources (id, name, kind, created_at) VALUES (?, 'Uploaded files', 'upload', ?)", (UPLOADS, _now())).rowcount
            == 1
        )
    if first_run and RAW_CSV.exists():
        rows = len(loader.read_records(RAW_CSV))
        with _connect() as con:
            con.execute(
                "INSERT INTO files VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)",
                (uuid.uuid4().hex, UPLOADS, RAW_CSV.name, _store_path(RAW_CSV), RAW_CSV.stat().st_size, _sha256(RAW_CSV), rows, _now()),
            )


def has_files() -> bool:
    with _connect() as con:
        return con.execute("SELECT count(*) FROM files").fetchone()[0] > 0


def list_sources() -> list[dict]:
    with _connect() as con:
        sources = [dict(r) for r in con.execute("SELECT * FROM sources ORDER BY kind DESC, created_at")]
        files = [dict(r) for r in con.execute("SELECT id, source_id, name, size, rows, added_at, stored_path FROM files ORDER BY added_at, rowid")]
    for s in sources:
        s["enabled"] = bool(s["enabled"])
        s["files"] = [
            {k: v for k, v in f.items() if k not in ("source_id", "stored_path")} | {"missing": not _resolve(f["stored_path"]).exists()}
            for f in files
            if f["source_id"] == s["id"]
        ]
    return sources


def _source(source_id: str) -> dict:
    with _connect() as con:
        row = con.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise KeyError(f"source {source_id} not found")
    return dict(row)


def add_folder_source(name: str, path: str, sync_interval_min: int | None) -> dict:
    folder = Path(path).expanduser()
    if not folder.is_dir():
        raise ValueError(f"Folder not found: {folder}")
    sid = uuid.uuid4().hex[:12]
    with _connect() as con:
        con.execute(
            "INSERT INTO sources (id, name, kind, path, sync_interval_min, created_at) VALUES (?, ?, 'folder', ?, ?, ?)",
            (sid, name.strip() or folder.name, str(folder.resolve()), sync_interval_min, _now()),
        )
    return _source(sid)


def update_source(source_id: str, *, name: str | None = None, sync_interval_min: int | None = -1, enabled: bool | None = None) -> dict:
    _source(source_id)
    with _connect() as con:
        if name is not None:
            con.execute("UPDATE sources SET name = ? WHERE id = ?", (name.strip(), source_id))
        if sync_interval_min != -1:
            con.execute("UPDATE sources SET sync_interval_min = ? WHERE id = ?", (sync_interval_min, source_id))
        if enabled is not None:
            con.execute("UPDATE sources SET enabled = ? WHERE id = ?", (int(enabled), source_id))
    return _source(source_id)


def delete_source(source_id: str) -> None:
    if source_id == UPLOADS:
        raise ValueError("The uploads source cannot be deleted; delete its files instead")
    with _connect() as con:
        managed = [r["stored_path"] for r in con.execute("SELECT stored_path FROM files WHERE source_id = ? AND managed = 1", (source_id,))]
        if con.execute("DELETE FROM sources WHERE id = ?", (source_id,)).rowcount == 0:
            raise KeyError(f"source {source_id} not found")
    for p in managed:
        _resolve(p).unlink(missing_ok=True)


def delete_file(file_id: str) -> None:
    with _connect() as con:
        row = con.execute("SELECT stored_path, managed FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            raise KeyError(f"file {file_id} not found")
        con.execute("DELETE FROM files WHERE id = ?", (file_id,))
    if row["managed"]:
        _resolve(row["stored_path"]).unlink(missing_ok=True)


def inspect(path: Path) -> dict:
    """Validate an export and count how many of its traces are not yet in the database."""
    try:
        df = loader.load_many([path])
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not read the file: {exc}") from exc
    if df.empty:
        raise ValueError("No usable traces (each needs an id, a timestamp and a user prompt)")
    known = _current_ids()
    return {
        "rows": int(len(df)),
        "new_traces": int((~df["id"].isin(known)).sum()),
        "start": str(df["timestamp"].min()),
        "end": str(df["timestamp"].max()),
    }


def _import(source_id: str, src: Path, name: str, *, move: bool) -> dict:
    """Copy (or move) a validated export into managed storage and register it."""
    sha = _sha256(src)
    with _connect() as con:
        dup = con.execute("SELECT name FROM files WHERE source_id = ? AND sha256 = ?", (source_id, sha)).fetchone()
    if dup:
        raise ValueError(f"This file was already imported as '{dup['name']}'")
    info = inspect(src)
    fid = uuid.uuid4().hex
    dest = SOURCES_DIR / source_id / f"{fid[:8]}_{_safe_name(name)}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    (shutil.move if move else shutil.copy2)(src, dest)
    with _connect() as con:
        con.execute(
            "INSERT INTO files VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (fid, source_id, Path(name).name, _store_path(dest), dest.stat().st_size, sha, info["rows"], _now()),
        )
    return {"id": fid, "name": Path(name).name, **info}


def add_upload(tmp_path: Path, filename: str) -> dict:
    if Path(filename).suffix.lower() not in loader.SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type. Use one of: {', '.join(loader.SUPPORTED_SUFFIXES)}")
    staged = tmp_path.with_suffix(Path(filename).suffix.lower())
    tmp_path.rename(staged)
    try:
        return _import(UPLOADS, staged, filename, move=True)
    finally:
        staged.unlink(missing_ok=True)


def scan_folder(source_id: str) -> tuple[list[dict], list[str]]:
    """Import new or changed exports from a watched folder. Returns (imported files, problems)."""
    source = _source(source_id)
    imported, problems = [], []
    folder = Path(source["path"] or "")
    if not folder.is_dir():
        problems.append(f"{source['name']}: folder not found ({folder})")
    else:
        for path in sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in loader.SUPPORTED_SUFFIXES):
            try:
                imported.append(_import(source_id, path, path.name, move=False))
            except ValueError as exc:
                if "already imported" not in str(exc):
                    problems.append(f"{path.name}: {exc}")
    with _connect() as con:
        con.execute("UPDATE sources SET last_checked_at = ? WHERE id = ?", (_now(), source_id))
    return imported, problems


# --- sync -----------------------------------------------------------------------------------------

_sync_lock = threading.Lock()
_pending = threading.Event()


def _current_ids() -> set[str]:
    try:
        return set(store.query("SELECT id FROM prompts")["id"])
    except Exception:
        return set()


def run_sync(trigger: str, *, scan: bool = True, use_slm: bool = True, sync_id: str | None = None) -> dict:
    """Import from watched folders, rebuild the feature database from all files and swap it in."""
    if not _sync_lock.acquire(blocking=False):
        raise SyncBusy("A sync is already running")
    sync_id = sync_id or uuid.uuid4().hex
    with _connect() as con:
        con.execute("INSERT OR IGNORE INTO syncs (id, trigger, status, started_at) VALUES (?, ?, 'running', ?)", (sync_id, trigger, _now()))
    tmp = DB_PATH.with_name(DB_PATH.stem + ".building.duckdb")
    notes: list[str] = []
    try:
        if scan:
            for s in list_sources():
                if s["kind"] == "folder" and s["enabled"]:
                    imported, problems = scan_folder(s["id"])
                    notes += [f"Imported {f['name']} ({f['new_traces']} new traces)" for f in imported] + problems
        with _connect() as con:
            paths = [_resolve(r["stored_path"]) for r in con.execute("SELECT stored_path FROM files ORDER BY added_at, rowid")]
        missing = [p.name for p in paths if not p.exists()]
        paths = [p for p in paths if p.exists()]
        if missing:
            notes.append(f"Skipped missing files: {', '.join(missing)}")
        if not paths and missing:
            raise ValueError("None of the data files can be found on disk. The current data was kept.")
        if paths and use_slm and not llm.is_available():
            raise RuntimeError("Ollama is not running, so new prompts cannot be analysed. The current data was kept.")

        before = _current_ids()
        if paths:
            tmp.unlink(missing_ok=True)
            report = pipeline.build(paths=paths, db_path=tmp, use_slm=use_slm, strict_slm=True)
            store.replace_database(tmp)
            notes.append(f"Built in {report['build_seconds']} s")
        else:
            store.remove_database()
            notes.append("All data files were removed, so the dataset is now empty")
        context.refresh()
        after = _current_ids()
        result = {
            "status": "ok",
            "files": len(paths),
            "rows_before": len(before),
            "rows_after": len(after),
            "new_traces": len(after - before),
            "message": "; ".join(notes),
        }
    except Exception as exc:
        log.exception("sync %s failed", sync_id)
        tmp.unlink(missing_ok=True)
        result = {"status": "error", "message": "; ".join(notes + [str(exc)])}
    finally:
        _sync_lock.release()
    with _connect() as con:
        con.execute(
            "UPDATE syncs SET status = ?, finished_at = ?, files = ?, rows_before = ?, rows_after = ?, new_traces = ?, message = ? WHERE id = ?",
            (result["status"], _now(), result.get("files"), result.get("rows_before"), result.get("rows_after"), result.get("new_traces"), result["message"], sync_id),
        )
    return {"id": sync_id, "trigger": trigger, **result}


def start_sync(trigger: str, *, scan: bool = True) -> str | None:
    """Run a sync in the background. If one is running, queue another run after it and return None."""
    if _sync_lock.locked():
        _pending.set()
        return None
    sync_id = uuid.uuid4().hex
    with _connect() as con:
        con.execute("INSERT INTO syncs (id, trigger, status, started_at) VALUES (?, ?, 'running', ?)", (sync_id, trigger, _now()))

    def work() -> None:
        try:
            run_sync(trigger, scan=scan, sync_id=sync_id)
            while _pending.is_set():
                _pending.clear()
                run_sync("queued", scan=False)
        except SyncBusy:
            _pending.set()

    threading.Thread(target=work, name="data-sync", daemon=True).start()
    return sync_id


def list_syncs(limit: int = 20) -> list[dict]:
    with _connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM syncs ORDER BY started_at DESC, rowid DESC LIMIT ?", (limit,))]


def status() -> dict:
    data = None
    if DB_PATH.exists():
        try:
            data = store.data_range()
        except Exception:
            data = None
    syncs = list_syncs(1)
    return {"data": data, "version": store.version(), "running": _sync_lock.locked(), "last_sync": syncs[0] if syncs else None}


def mark_interrupted() -> None:
    """Syncs still marked running after a restart were interrupted."""
    with _connect() as con:
        con.execute("UPDATE syncs SET status = 'error', finished_at = ?, message = 'Interrupted by a server restart' WHERE status = 'running'", (_now(),))


# --- scheduler ------------------------------------------------------------------------------------


def due_sources(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    due = []
    for s in list_sources():
        if s["kind"] != "folder" or not s["enabled"] or not s["sync_interval_min"]:
            continue
        last = datetime.fromisoformat(s["last_checked_at"]) if s["last_checked_at"] else None
        if last is None or (now - last).total_seconds() >= s["sync_interval_min"] * 60:
            due.append(s)
    return due


def scheduler(stop: threading.Event) -> None:
    """Check watched folders on their interval and sync when new exports appear."""
    while not stop.wait(SCHEDULER_TICK_S):
        try:
            new = 0
            for s in due_sources():
                imported, problems = scan_folder(s["id"])
                new += len(imported)
                for p in problems:
                    log.warning("folder source %s: %s", s["name"], p)
            if new:
                start_sync("auto", scan=False)
        except Exception:
            log.exception("data source scheduler failed")
