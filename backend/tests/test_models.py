import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, llm, model_pulls
from app.api.main import app

INSTALLED = [
    {"name": n, "embedding": n.startswith("nomic"), "size": 1, "parameter_size": None, "quantization": None, "family": None, "modified_at": None}
    for n in ("gemma2:2b", "llama3.2:3b", "qwen2.5-coder:7b", "nomic-embed-text:latest")
]
CUSTOM = {"query_understanding": "qwen2.5-coder:7b", "visualization_planning": "llama3.2:3b", "answer_generation": "gemma2:2b", "baseline": "llama3.2:3b"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_SETTINGS", tmp_path / "model_settings.json")
    monkeypatch.setattr(llm, "installed_models", lambda: INSTALLED)
    monkeypatch.setattr(llm, "loaded_models", lambda: [])
    monkeypatch.setattr(llm, "ollama_status", lambda: {"running": True, "installed": True, "version": "test", "url": ""})
    monkeypatch.delenv("MAS_PROFILE", raising=False)
    return TestClient(app)


def test_overview_lists_builtin_profiles(client):
    body = client.get("/api/models").json()
    assert {p["name"] for p in body["profiles"]} >= {"small", "tiny", "mixed"}
    assert all(p["builtin"] for p in body["profiles"])
    assert body["default_profile"] == "mixed" and body["roles"] == list(config.MODEL_ROLES)


def test_custom_profile_is_used_by_the_agents(client):
    assert client.put("/api/models/profiles/my-setup", json={"models": CUSTOM, "description": "test"}).status_code == 200
    assert client.put("/api/models/default", json={"profile": "my-setup"}).status_code == 200
    prof = config.profile()
    assert prof["name"] == "my-setup" and prof["answer_generation"] == "gemma2:2b"
    assert config.profile("mixed")["query_understanding"] == "qwen2.5-coder:7b"

    body = client.delete("/api/models/profiles/my-setup").json()
    assert body["default_profile"] == "mixed" and "my-setup" not in {p["name"] for p in body["profiles"]}


@pytest.mark.parametrize(
    ("name", "models", "status"),
    [
        ("mixed", CUSTOM, 400),
        ("Bad Name", CUSTOM, 422),
        ("x", CUSTOM | {"baseline": "missing:1b"}, 422),
        ("x", CUSTOM | {"baseline": "nomic-embed-text:latest"}, 422),
        ("x", {"baseline": "gemma2:2b"}, 422),
    ],
)
def test_invalid_profiles_are_rejected(client, name, models, status):
    assert client.put(f"/api/models/profiles/{name}", json={"models": models}).status_code == status
    assert client.delete("/api/models/profiles/mixed").status_code == 400


def _fake_ollama(monkeypatch, lines: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["model"] == "qwen2.5:3b"
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())

    real = httpx.Client
    monkeypatch.setattr(model_pulls.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), base_url="http://ollama"))


def _wait(name: str) -> dict:
    for _ in range(100):
        job = next(j for j in model_pulls.list_pulls() if j["name"] == name)
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("pull did not finish")


def test_pull_reports_progress_and_finishes(client, monkeypatch):
    _fake_ollama(monkeypatch, [{"status": "pulling manifest"}, {"status": "pulling abc", "total": 100, "completed": 40}, {"status": "success"}])
    assert client.post("/api/models/pull", json={"name": "qwen2.5:3b"}).json()["state"] == "running"
    job = _wait("qwen2.5:3b")
    assert job["state"] == "done" and job["total"] == 100 and job["completed"] == 40


def test_pull_errors_are_reported(client, monkeypatch):
    _fake_ollama(monkeypatch, [{"status": "pulling manifest"}, {"error": "pull model manifest: file does not exist"}])
    client.post("/api/models/pull", json={"name": "qwen2.5:3b"})
    job = _wait("qwen2.5:3b")
    assert job["state"] == "error" and "not found in the Ollama library" in job["error"]


def test_pull_validation_and_delete_guard(client, monkeypatch):
    assert client.post("/api/models/pull", json={"name": "rm -rf /"}).status_code == 422
    assert client.delete("/api/models/installed/gemma2:2b").status_code == 400
    monkeypatch.setattr(llm, "ollama_status", lambda: {"running": False, "installed": True, "version": None, "url": ""})
    assert client.post("/api/models/pull", json={"name": "qwen2.5:3b"}).status_code == 503
