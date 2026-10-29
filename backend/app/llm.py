"""Thin Ollama client that records latency and token usage for every call."""

import json
import shutil
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import OLLAMA_URL


class LLMError(RuntimeError):
    pass


@dataclass
class LLMCall:
    model: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    load_s: float = 0.0
    raw: str = ""


@dataclass
class LLMResult:
    content: str
    call: LLMCall
    parsed: Any = field(default=None)


_client = httpx.Client(base_url=OLLAMA_URL, timeout=httpx.Timeout(300.0, connect=5.0))


def chat(
    model: str,
    messages: list[dict],
    *,
    schema: dict | None = None,
    temperature: float = 0.0,
    num_ctx: int = 4096,
    max_tokens: int | None = None,
) -> LLMResult:
    options: dict[str, Any] = {"temperature": temperature, "num_ctx": num_ctx, "seed": 7}
    if max_tokens:
        options["num_predict"] = max_tokens
    body: dict[str, Any] = {"model": model, "messages": messages, "stream": False, "options": options}
    if schema is not None:
        body["format"] = schema
    t0 = time.perf_counter()
    try:
        resp = _client.post("/api/chat", json=body)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"Ollama call to {model} failed: {exc}") from exc
    data = resp.json()
    content = data.get("message", {}).get("content", "")
    call = LLMCall(
        model=model,
        latency_s=time.perf_counter() - t0,
        prompt_tokens=data.get("prompt_eval_count", 0),
        completion_tokens=data.get("eval_count", 0),
        load_s=data.get("load_duration", 0) / 1e9,
        raw=content,
    )
    result = LLMResult(content=content, call=call)
    if schema is not None:
        try:
            result.parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{model} returned invalid JSON: {content[:200]}") from exc
    return result


def embed(model: str, texts: list[str]) -> list[list[float]]:
    try:
        resp = _client.post("/api/embed", json={"model": model, "input": texts})
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"Ollama embed with {model} failed: {exc}") from exc
    return resp.json()["embeddings"]


def loaded_models() -> list[dict]:
    """Models currently resident in Ollama, with their memory footprint in bytes."""
    try:
        resp = _client.get("/api/ps")
        resp.raise_for_status()
    except httpx.HTTPError:
        return []
    return [
        {"name": m["name"], "size": m.get("size", 0), "size_vram": m.get("size_vram", 0)}
        for m in resp.json().get("models", [])
    ]


def installed_models() -> list[dict]:
    """Models pulled into the local Ollama, with size and details."""
    try:
        resp = _client.get("/api/tags", timeout=5.0)
        resp.raise_for_status()
    except httpx.HTTPError:
        return []
    out = []
    for m in resp.json().get("models", []):
        details = m.get("details") or {}
        families = details.get("families") or [details.get("family", "")]
        out.append(
            {
                "name": m["name"],
                "size": m.get("size", 0),
                "parameter_size": details.get("parameter_size"),
                "quantization": details.get("quantization_level"),
                "family": details.get("family"),
                "embedding": "embed" in m["name"] or any("bert" in (f or "") for f in families),
                "modified_at": m.get("modified_at"),
            }
        )
    return sorted(out, key=lambda m: m["name"])


def unload_all() -> None:
    """Evict every resident model, so resource measurements start from a clean state."""
    for m in loaded_models():
        try:
            _client.post("/api/generate", json={"model": m["name"], "keep_alive": 0}).raise_for_status()
        except httpx.HTTPError:
            pass


def ollama_status() -> dict:
    """Whether the Ollama server answers, and whether the CLI is installed on this machine."""
    version = None
    try:
        resp = _client.get("/api/version", timeout=2.0)
        if resp.status_code == 200:
            version = resp.json().get("version")
    except httpx.HTTPError:
        pass
    return {"running": version is not None, "installed": version is not None or shutil.which("ollama") is not None, "version": version, "url": OLLAMA_URL}


def delete_model(name: str) -> None:
    try:
        _client.request("DELETE", "/api/delete", json={"model": name}).raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not delete {name}: {exc}") from exc


def is_available() -> bool:
    try:
        return _client.get("/api/version", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False
