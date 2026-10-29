"""Download Ollama models in the background and track their progress for the UI."""

import json
import logging
import re
import threading
import time

import httpx

from app.config import OLLAMA_URL

log = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[a-zA-Z0-9][\w.\-]*(/[\w.\-]+)*(:[\w.\-]+)?$")
FINISHED_KEEP_S = 600

_jobs: dict[str, dict] = {}
_cancel: dict[str, threading.Event] = {}
_lock = threading.Lock()


def list_pulls() -> list[dict]:
    now = time.time()
    with _lock:
        for name in [n for n, j in _jobs.items() if j["finished_at"] and now - j["finished_at"] > FINISHED_KEEP_S]:
            del _jobs[name]
        return [dict(j) for j in sorted(_jobs.values(), key=lambda j: j["started_at"], reverse=True)]


def start_pull(name: str) -> dict:
    name = name.strip()
    if not NAME_RE.match(name) or len(name) > 120:
        raise ValueError(f"'{name}' is not a valid model name, e.g. qwen2.5:3b or llama3.2:1b")
    with _lock:
        job = _jobs.get(name)
        if job and job["state"] == "running":
            return dict(job)
        job = {"name": name, "state": "running", "status": "starting", "completed": 0, "total": 0, "error": None, "started_at": time.time(), "finished_at": None}
        _jobs[name] = job
        _cancel[name] = threading.Event()
        started = dict(job)
    threading.Thread(target=_run, args=(name,), name=f"pull-{name}", daemon=True).start()
    return started


def cancel_pull(name: str) -> bool:
    with _lock:
        event = _cancel.get(name)
        running = name in _jobs and _jobs[name]["state"] == "running"
    if event and running:
        event.set()
    return running


def _update(name: str, **fields) -> None:
    with _lock:
        _jobs[name].update(fields)


def _run(name: str) -> None:
    cancel = _cancel[name]
    layers: dict[str, tuple[int, int]] = {}
    try:
        with httpx.Client(base_url=OLLAMA_URL, timeout=httpx.Timeout(None, connect=5.0)) as client:
            with client.stream("POST", "/api/pull", json={"model": name, "stream": True}) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if cancel.is_set():
                        _update(name, state="cancelled", status="cancelled", finished_at=time.time())
                        return
                    if not line:
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise RuntimeError(data["error"])
                    fields = {"status": data.get("status", "")}
                    if data.get("total"):
                        layers[data.get("digest", "")] = (data.get("completed", 0), data["total"])
                        fields |= {"completed": sum(c for c, _ in layers.values()), "total": sum(t for _, t in layers.values())}
                    _update(name, **fields)
        _update(name, state="done", status="success", finished_at=time.time())
    except Exception as exc:
        log.warning("pull of %s failed: %s", name, exc)
        message = str(exc)
        if "file does not exist" in message or "manifest" in message:
            message = f"Model '{name}' was not found in the Ollama library. Check the name at ollama.com/library."
        _update(name, state="error", status="error", error=message, finished_at=time.time())
