"""Model settings: installed Ollama models and the per-agent model profiles."""

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import llm, model_pulls
from app.config import (
    MODEL_ROLES,
    all_profiles,
    default_profile_name,
    models_config,
    save_user_model_settings,
    user_model_settings,
)

router = APIRouter(prefix="/api/models")

BUILTIN_DESCRIPTIONS = {
    "small": "Every agent and the single model on a ~3B model.",
    "tiny": "The smallest model everywhere.",
    "mixed": "A code-tuned 7B model for query understanding, 2-3B models elsewhere.",
}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

SUGGESTED = [
    {"name": "qwen2.5:3b", "size_gb": 1.9, "note": "Strong 3B general model, good at JSON"},
    {"name": "qwen2.5-coder:3b", "size_gb": 1.9, "note": "Code-tuned 3B, for query understanding or SQL"},
    {"name": "llama3.2:1b", "size_gb": 1.3, "note": "Very small and fast"},
    {"name": "phi3.5:3.8b", "size_gb": 2.2, "note": "Microsoft 3.8B reasoning model"},
    {"name": "gemma3:4b", "size_gb": 3.3, "note": "Newer Gemma, multilingual"},
    {"name": "qwen2.5:7b", "size_gb": 4.7, "note": "7B general model"},
    {"name": "mistral:7b", "size_gb": 4.1, "note": "7B general model"},
]


class PullBody(BaseModel):
    name: str


class ProfileBody(BaseModel):
    models: dict[str, str]
    description: str = ""


class DefaultBody(BaseModel):
    profile: str


def _overview() -> dict:
    cfg = models_config()
    user = user_model_settings()
    builtin = cfg["profiles"]
    descriptions = user["descriptions"]
    return {
        "roles": list(MODEL_ROLES),
        "installed": llm.installed_models(),
        "loaded": llm.loaded_models(),
        "profiles": [
            {
                "name": name,
                "builtin": name in builtin,
                "description": BUILTIN_DESCRIPTIONS.get(name, "") if name in builtin else descriptions.get(name, ""),
                "models": {role: models.get(role) for role in MODEL_ROLES},
            }
            for name, models in all_profiles().items()
        ],
        "default_profile": default_profile_name(),
        "data_processing_model": cfg["data_processing_model"],
        "embedding_model": cfg["embedding_model"],
        "ollama": llm.ollama_status(),
        "pulls": model_pulls.list_pulls(),
        "suggested": SUGGESTED,
    }


def _in_use(name: str) -> list[str]:
    cfg = models_config()
    users = [p for p, models in all_profiles().items() if name in models.values()]
    base = name.removesuffix(":latest")
    if base in (cfg["data_processing_model"], cfg["embedding_model"]) or name in (cfg["data_processing_model"], cfg["embedding_model"]):
        users.append("data processing")
    return users


@router.get("")
def overview():
    return _overview()


@router.put("/profiles/{name}")
def save_profile(name: str, body: ProfileBody):
    if name in models_config()["profiles"]:
        raise HTTPException(400, f"'{name}' is a built-in profile used by the evaluation; save your changes under a new name")
    if not NAME_RE.match(name):
        raise HTTPException(422, "Use 1-40 lowercase letters, digits, '-' or '_' for the profile name")
    missing = [r for r in MODEL_ROLES if not body.models.get(r)]
    if missing:
        raise HTTPException(422, f"Choose a model for: {', '.join(missing)}")
    installed = {m["name"]: m for m in llm.installed_models()}
    if installed:
        unknown = sorted({body.models[r] for r in MODEL_ROLES} - set(installed))
        if unknown:
            raise HTTPException(422, f"Not installed in Ollama: {', '.join(unknown)}. Download it on this page first.")
        embedding = sorted({body.models[r] for r in MODEL_ROLES if installed[body.models[r]]["embedding"]})
        if embedding:
            raise HTTPException(422, f"Embedding models cannot chat: {', '.join(embedding)}")
    settings = user_model_settings()
    settings["profiles"][name] = {r: body.models[r] for r in MODEL_ROLES}
    settings["descriptions"][name] = body.description.strip()
    save_user_model_settings(settings)
    return _overview()


@router.delete("/profiles/{name}")
def delete_profile(name: str):
    settings = user_model_settings()
    if name not in settings["profiles"]:
        raise HTTPException(404 if name not in models_config()["profiles"] else 400, f"'{name}' is not a custom profile")
    del settings["profiles"][name]
    settings["descriptions"].pop(name, None)
    if settings["default_profile"] == name:
        settings["default_profile"] = None
    save_user_model_settings(settings)
    return _overview()


@router.put("/default")
def set_default(body: DefaultBody):
    if body.profile not in all_profiles():
        raise HTTPException(404, f"Unknown profile '{body.profile}'")
    settings = user_model_settings()
    settings["default_profile"] = body.profile
    save_user_model_settings(settings)
    return _overview()


@router.post("/pull")
def pull(body: PullBody):
    if not llm.ollama_status()["running"]:
        raise HTTPException(503, "Ollama is not running. Start the Ollama app (or `ollama serve`) and try again.")
    try:
        return model_pulls.start_pull(body.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/pulls")
def pulls():
    return model_pulls.list_pulls()


@router.delete("/pulls/{name:path}")
def cancel_pull(name: str):
    if not model_pulls.cancel_pull(name):
        raise HTTPException(404, f"No download of '{name}' is running")
    return {"ok": True}


@router.delete("/installed/{name:path}")
def delete_installed(name: str):
    users = _in_use(name)
    if users:
        raise HTTPException(400, f"'{name}' is used by: {', '.join(users)}. Change those first.")
    try:
        llm.delete_model(name)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return _overview()
