"""Static size metrics for the maintainability comparison (RQ7): lines of code and prompt sizes."""

import ast
import json
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
PROMPT_NAMES = {"EXAMPLES"}

COMPONENTS = {
    "mas": {
        "orchestrator": ["mas/orchestrator.py", "mas/agents/base.py"],
        "query_understanding": ["mas/agents/query_understanding.py"],
        "query_spec": ["mas/query_spec.py"],
        "metrics": ["mas/agents/metrics.py"],
        "visualization_planning": ["mas/agents/visualization.py"],
        "answer_generation": ["mas/agents/answer.py"],
        "data_processing": ["mas/agents/data_processing.py"],
    },
    "baseline": {"single_model": ["baseline/single_model.py"]},
    "shared": {
        "data_pipeline": ["data/loader.py", "data/features.py", "data/store.py", "data/context.py", "data/pipeline.py"],
        "llm_client": ["llm.py"],
        "viz_rules": ["viz_rules.py"],
        "schemas_and_traces": ["schemas.py", "traces.py"],
    },
}


def _file_stats(path: Path) -> dict:
    src = path.read_text("utf-8")
    tree = ast.parse(src)
    code_lines = [ln for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    prompt_chars = 0
    for node in ast.walk(tree):
        names = [t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)] if isinstance(node, ast.Assign) else []
        if any(n.isupper() and "SYSTEM" in n for n in names) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            prompt_chars += len(node.value.value)
        elif any(n in PROMPT_NAMES for n in names):
            # few-shot example lists: count the literal as it is serialised for the model
            prompt_chars += len(json.dumps(ast.literal_eval(node.value), ensure_ascii=False))
    functions = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))
    branches = sum(isinstance(n, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.BoolOp, ast.IfExp)) for n in ast.walk(tree))
    return {"loc": len(code_lines), "functions": functions, "branches": branches, "prompt_chars": prompt_chars}


def collect() -> list[dict]:
    rows = []
    for system, comps in COMPONENTS.items():
        for comp, files in comps.items():
            stats = {"loc": 0, "functions": 0, "branches": 0, "prompt_chars": 0}
            for f in files:
                for k, v in _file_stats(APP / f).items():
                    stats[k] += v
            rows.append({"system": system, "component": comp, "files": len(files), **stats})
    return rows


if __name__ == "__main__":
    for r in collect():
        print(r)
