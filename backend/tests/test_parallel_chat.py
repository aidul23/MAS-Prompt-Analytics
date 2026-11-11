"""Uncached SLM chat calls during feature extraction run in parallel."""

import threading
import time
from pathlib import Path

from app import llm
from app.data import features


def test_cached_chats_runs_uncached_calls_in_parallel(tmp_path: Path, monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_chat(model, messages, *, schema=None, **_):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        text = messages[-1]["content"]
        return llm.LLMResult(content="{}", call=llm.LLMCall(model=model, latency_s=0.05, prompt_tokens=1, completion_tokens=1), parsed={"english": text, "intent": "other"})

    monkeypatch.setattr(features.llm, "chat", fake_chat)
    cache = features.FeatureCache(tmp_path / "cache.json")
    texts = [f"prompt {i}" for i in range(12)]
    t0 = time.perf_counter()
    out = features._cached_chats(cache, "normalise", "fake", features.NORMALISE_SYSTEM, texts, features.NORMALISE_SCHEMA, workers=6)
    elapsed = time.perf_counter() - t0

    assert len(out) == 12
    assert all(out[t]["english"] == t for t in texts)
    assert peak >= 4, peak
    # Sequential would take ~0.6 s; parallel with 6 workers should finish much sooner.
    assert elapsed < 0.35, elapsed
    # Second call is cache-only and must not call the model again.
    calls = {"n": 0}

    def no_chat(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("cache miss")

    monkeypatch.setattr(features.llm, "chat", no_chat)
    again = features._cached_chats(cache, "normalise", "fake", features.NORMALISE_SYSTEM, texts, features.NORMALISE_SCHEMA, workers=6)
    assert again == out and calls["n"] == 0
