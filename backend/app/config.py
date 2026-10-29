import json
import os
from functools import lru_cache
from pathlib import Path

import yaml

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = Path(os.environ.get("MAS_DATA_DIR", PROJECT_DIR / "data"))
CACHE_DIR = DATA_DIR / "cache"
RAW_CSV = Path(os.environ.get("MAS_RAW_CSV", DATA_DIR / "dummy_chatbot_traces_500.csv"))
DB_PATH = Path(os.environ.get("MAS_DB_PATH", DATA_DIR / "analytics.duckdb"))
SOURCES_DIR = Path(os.environ.get("MAS_SOURCES_DIR", DATA_DIR / "sources"))
SOURCES_DB = Path(os.environ.get("MAS_SOURCES_DB", DATA_DIR / "sources.sqlite"))
CHATS_DB = Path(os.environ.get("MAS_CHATS_DB", DATA_DIR / "chats.sqlite"))
TRACE_LOG = Path(os.environ.get("MAS_TRACE_LOG", DATA_DIR / "logs" / "chat_traces.jsonl"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODELS_CONFIG = Path(os.environ.get("MAS_MODELS_CONFIG", BACKEND_DIR / "app" / "mas" / "config.yaml"))
MODEL_SETTINGS = Path(os.environ.get("MAS_MODEL_SETTINGS", DATA_DIR / "model_settings.json"))
MODEL_ROLES = ("query_understanding", "visualization_planning", "answer_generation", "baseline")


@lru_cache
def models_config() -> dict:
    with open(MODELS_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def mas_options() -> dict:
    opts = dict(models_config().get("mas_options", {}))
    env = os.environ.get("MAS_GROUND_FILTERS")
    if env is not None:
        opts["ground_filters"] = env.strip().lower() not in ("0", "false", "no")
    return opts


def user_model_settings() -> dict:
    """Profiles created in the UI and the chosen default; built-in profiles in config.yaml stay unchanged."""
    data = {}
    if MODEL_SETTINGS.exists():
        with open(MODEL_SETTINGS, encoding="utf-8") as f:
            data = json.load(f)
    return {"profiles": data.get("profiles", {}), "descriptions": data.get("descriptions", {}), "default_profile": data.get("default_profile")}


def save_user_model_settings(settings: dict) -> None:
    MODEL_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODEL_SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=1), encoding="utf-8")
    os.replace(tmp, MODEL_SETTINGS)


def all_profiles() -> dict[str, dict]:
    """Built-in profiles first, then user profiles; each maps role -> model."""
    return {**models_config()["profiles"], **user_model_settings()["profiles"]}


def default_profile_name() -> str:
    profiles = all_profiles()
    for name in (os.environ.get("MAS_PROFILE"), user_model_settings()["default_profile"]):
        if name and name in profiles:
            return name
    return models_config()["default_profile"]


def profile(name: str | None = None) -> dict:
    profiles = all_profiles()
    name = name or default_profile_name()
    if name not in profiles:
        raise KeyError(f"Unknown model profile '{name}'. Available: {list(profiles)}")
    return {"name": name, **profiles[name]}
