"""Prompt- and session-level feature extraction (RQ2).

Deterministic features: lengths, time buckets, language.
SLM-derived features (cached per distinct text and model, so reruns are free):
- English normalisation + intent class for each distinct prompt,
- English translation of each distinct response,
- topic clusters over embeddings of the normalised prompts, labelled by the SLM,
- response topic (nearest prompt-topic centroid) and whether it matches the prompt's topic.

Responses are matched to topics via embeddings rather than an SLM judge: in our tests
2-8B judges rated obviously matching cross-lingual pairs inconsistently.
"""

import hashlib
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from langdetect import DetectorFactory, LangDetectException, detect_langs
from sklearn.cluster import AgglomerativeClustering

from app import llm
from app.config import CACHE_DIR, models_config

log = logging.getLogger(__name__)
DetectorFactory.seed = 0

EXPECTED_LANGUAGES = ("en", "fi", "sv")
INTENTS = ("how_to", "explanation", "examples", "best_practices", "design_help", "troubleshooting", "other")
TOPIC_DISTANCE_THRESHOLD = 0.15
EMBED_PREFIX = "clustering: "
# Concurrent Ollama chat calls during sync. Raise with MAS_CHAT_WORKERS if the GPU keeps up.
CHAT_WORKERS = max(1, int(os.environ.get("MAS_CHAT_WORKERS", "8")))


def detect_language(text: str) -> str:
    """langdetect with a preference for the languages expected in this deployment.

    Short English sentences are often mis-detected (e.g. as French); if any expected
    language appears among the candidates we take the most probable of those.
    """
    if not text or len(text.strip()) < 3:
        return "unknown"
    try:
        candidates = detect_langs(text)
    except LangDetectException:
        return "unknown"
    for cand in candidates:
        if cand.lang in EXPECTED_LANGUAGES:
            return cand.lang
    return candidates[0].lang


class FeatureCache:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text("utf-8")) if path.exists() else {}
        self._lock = threading.Lock()

    def get(self, section: str, key: str):
        with self._lock:
            return self.data.get(section, {}).get(key)

    def put(self, section: str, key: str, value) -> None:
        with self._lock:
            self.data.setdefault(section, {})[key] = value

    def save(self) -> None:
        with self._lock:
            payload = json.dumps(self.data, ensure_ascii=False, indent=1)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(payload, "utf-8")


def _key(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


NORMALISE_SCHEMA = {
    "type": "object",
    "properties": {
        "english": {"type": "string"},
        "intent": {"type": "string", "enum": list(INTENTS)},
    },
    "required": ["english", "intent"],
}

NORMALISE_SYSTEM = (
    "You analyse questions that users asked a marketing-software chatbot. "
    "Translate the question to English (keep it unchanged if already English) and classify its intent:\n"
    "- how_to: asks how to perform a task\n- explanation: asks what something is or means\n"
    "- examples: asks for examples\n- best_practices: asks for tips or best practices\n"
    "- design_help: asks for help creating or designing content\n"
    "- troubleshooting: reports a problem or error\n- other: anything else\n"
    "Answer in JSON."
)

TRANSLATE_SCHEMA = {"type": "object", "properties": {"english": {"type": "string"}}, "required": ["english"]}
TRANSLATE_SYSTEM = "Translate the text to English. If it is already English, return it unchanged. Answer in JSON."

LABEL_SCHEMA = {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}
LABEL_SYSTEM = (
    "You name topics of chatbot questions. Given a list of similar questions, reply with a short "
    "English topic label of 1 to 4 words in Title Case, e.g. 'Newsletter Creation'. Answer in JSON."
)


def _cached_chat(cache: FeatureCache, section: str, model: str, system: str, text: str, schema: dict) -> dict:
    return _cached_chats(cache, section, model, system, [text], schema)[text]


def _cached_chats(
    cache: FeatureCache, section: str, model: str, system: str, texts: list[str], schema: dict, *, workers: int | None = None
) -> dict[str, dict]:
    """Run uncached chat calls in parallel; return {text: parsed} for every input text."""
    unique = list(dict.fromkeys(texts))
    missing = [t for t in unique if cache.get(section, _key(model, t)) is None]
    if missing:
        n = max(1, workers if workers is not None else CHAT_WORKERS)

        def one(text: str) -> tuple[str, dict]:
            hit = llm.chat(
                model, [{"role": "system", "content": system}, {"role": "user", "content": text}], schema=schema
            ).parsed
            return text, hit

        done = 0
        with ThreadPoolExecutor(max_workers=min(n, len(missing)), thread_name_prefix="slm-chat") as pool:
            futures = [pool.submit(one, t) for t in missing]
            for fut in as_completed(futures):
                text, hit = fut.result()
                cache.put(section, _key(model, text), hit)
                done += 1
                # Keep partial progress if the sync is interrupted mid-batch.
                if done == len(missing) or done % 32 == 0:
                    cache.save()
                    log.info("SLM %s: %d / %d", section, done, len(missing))
    return {t: cache.get(section, _key(model, t)) for t in unique}


def _embed(texts: list[str], cache: FeatureCache, model: str) -> np.ndarray:
    keys = [_key(model, t) for t in texts]
    missing = [(k, t) for k, t in zip(keys, texts, strict=False) if cache.get("embedding", k) is None]
    for i in range(0, len(missing), 64):
        batch = missing[i : i + 64]
        for (k, _), vec in zip(batch, llm.embed(model, [EMBED_PREFIX + t for _, t in batch]), strict=False):
            cache.put("embedding", k, vec)
    vecs = np.array([cache.get("embedding", k) for k in keys], dtype=float)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def _cluster_topics(english: list[str], cache: FeatureCache, embed_model: str, label_model: str):
    """Returns ({english_prompt: topic_label}, {topic_label: unit centroid})."""
    unique = sorted(set(english))
    vecs = _embed(unique, cache, embed_model)
    if len(unique) == 1:
        labels = np.zeros(1, dtype=int)
    else:
        labels = AgglomerativeClustering(
            n_clusters=None, metric="cosine", linkage="average", distance_threshold=TOPIC_DISTANCE_THRESHOLD
        ).fit_predict(vecs)
    groups: dict[int, list[int]] = {}
    for idx, lab in enumerate(labels):
        groups.setdefault(int(lab), []).append(idx)

    clusters = [(members, [unique[i] for i in members]) for members in sorted(groups.values(), key=lambda m: unique[m[0]])]
    samples = ["\n".join(f"- {t}" for t in texts[:15]) for _, texts in clusters]
    labels = _cached_chats(cache, "topic_label", label_model, LABEL_SYSTEM, samples, LABEL_SCHEMA)

    mapping, centroids, used = {}, {}, set()
    for (members, texts), sample in zip(clusters, samples, strict=False):
        label = (labels[sample].get("label") or "").strip().strip(".") or texts[0][:40]
        base, n = label, 2
        while label in used:
            label, n = f"{base} {n}", n + 1
        used.add(label)
        for t in texts:
            mapping[t] = label
        c = vecs[members].mean(axis=0)
        centroids[label] = c / np.linalg.norm(c)
    return mapping, centroids


def add_basic_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = df["timestamp"].dt.date
    df["hour"] = df["timestamp"].dt.hour
    df["weekday"] = df["timestamp"].dt.day_name()
    df["prompt_chars"] = df["prompt"].str.len()
    df["prompt_words"] = df["prompt"].str.split().str.len()
    df["output_chars"] = df["output_text"].str.len()
    df["output_words"] = df["output_text"].str.split().str.len()

    langs = {t: detect_language(t) for t in pd.unique(pd.concat([df["prompt"], df["output_text"]]))}
    df["prompt_language"] = df["prompt"].map(langs)
    df["output_language"] = df["output_text"].map(langs)
    df["language_match"] = df["prompt_language"] == df["output_language"]
    return df


def add_slm_features(df: pd.DataFrame, cache_path: Path | None = None, strict: bool = False) -> pd.DataFrame:
    df = df.copy()
    cfg = models_config()
    cache = FeatureCache(cache_path or CACHE_DIR / "slm_features.json")
    model, embed_model = cfg["data_processing_model"], cfg["embedding_model"]
    try:
        prompts = [p for p in df["prompt"].unique() if p is not None]
        norm = _cached_chats(cache, "normalise", model, NORMALISE_SYSTEM, prompts, NORMALISE_SCHEMA)
        cache.save()
        df["prompt_english"] = df["prompt"].map(lambda p: (norm[p]["english"] or "").strip() or p)
        df["intent"] = df["prompt"].map(lambda p: norm[p]["intent"])

        topics, centroids = _cluster_topics(list(df["prompt_english"]), cache, embed_model, model)
        cache.save()
        df["topic"] = df["prompt_english"].map(topics)

        outputs = [o for o in df["output_text"].unique() if o]
        translated = _cached_chats(
            cache, "translate", model, TRANSLATE_SYSTEM, [o[:2000] for o in outputs], TRANSLATE_SCHEMA
        )
        out_en = {o: (translated[o[:2000]].get("english") or o) for o in outputs}
        out_vecs = _embed([out_en[o] for o in outputs], cache, embed_model)
        names = list(centroids)
        sims = out_vecs @ np.stack([centroids[n] for n in names]).T
        out_topic = {o: names[int(sims[i].argmax())] for i, o in enumerate(outputs)}
        out_sim = {o: {n: float(sims[i, j]) for j, n in enumerate(names)} for i, o in enumerate(outputs)}

        df["output_english"] = df["output_text"].map(out_en)
        df["response_topic"] = df["output_text"].map(out_topic)
        df["response_on_topic"] = df["response_topic"] == df["topic"]
        df["response_similarity"] = [
            round(out_sim[o][t], 4) if o in out_sim else None for o, t in zip(df["output_text"], df["topic"], strict=False)
        ]
    except llm.LLMError as exc:
        if strict:
            raise
        log.warning("SLM features unavailable, using placeholders: %s", exc)
        df = add_placeholder_features(df)
    finally:
        cache.save()
    return df


def add_placeholder_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["prompt_english"] = df["prompt"]
    df["output_english"] = df["output_text"]
    df["intent"], df["topic"], df["response_topic"] = "other", "Unlabelled", None
    df["response_on_topic"], df["response_similarity"] = None, None
    return df


def build_sessions(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("session_id")
    sessions = g.agg(
        user_id=("user_id", "first"),
        app=("app", "first"),
        user_role=("user_role", "first"),
        organization_id=("organization_id", "first"),
        started_at=("timestamp", "min"),
        ended_at=("timestamp", "max"),
        turns=("id", "count"),
        max_history_turns=("history_turns", "max"),
        total_tokens=("total_tokens", "sum"),
        avg_latency_s=("latency_s", "mean"),
        languages=("prompt_language", lambda s: ",".join(sorted(set(s)))),
        topics=("topic", lambda s: ",".join(sorted(set(s)))),
    ).reset_index()
    sessions["duration_s"] = (sessions["ended_at"] - sessions["started_at"]).dt.total_seconds()
    return sessions
