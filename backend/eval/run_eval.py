"""Run the evaluation set against the MAS and the baseline.

    uv run python -m eval.run_eval                       # all profiles, both modes
    uv run python -m eval.run_eval --profiles small --modes mas --ids c01 r01
    uv run python -m eval.run_eval --repeat 3            # repeated runs for latency variance

Writes eval/results/<timestamp>/results.jsonl and then calls eval.report.
"""

import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import psutil
import yaml

from app import llm, traces
from app.baseline import single_model
from app.config import models_config
from app.data import store
from app.mas import orchestrator
from eval import report, score

EVAL_DIR = Path(__file__).resolve().parent
WARMUP_QUESTION = "How many prompts are there?"
HANDLERS = {"mas": orchestrator.answer, "baseline": single_model.answer}

log = logging.getLogger("eval")


def load_questions(path: Path = EVAL_DIR / "questions.yaml") -> list[dict]:
    return yaml.safe_load(path.read_text("utf-8"))["questions"]


def gold_results(questions: list[dict]) -> dict[str, list]:
    """Per question: the gold result followed by any equally correct alternatives."""
    out = {}
    for q in questions:
        sqls = [q["gold_sql"], *q.get("accept_sql", [])] if q.get("gold_sql") else []
        out[q["id"]] = [store.query(s) for s in sqls]
    return out


def score_answer(q: dict, golds: list, rows: list | None, status: str, answer: str) -> dict:
    primary = golds[0] if golds else None
    alternatives = golds or [None]
    return {
        "result_correct": any(score.result_correct(q["match"], g, rows, status) for g in alternatives),
        "answer_correct": score.answer_correct(q["match"], primary, answer, status),
        "faithfulness": score.faithfulness(answer, rows, primary),
    }


def _memory() -> dict:
    models = llm.loaded_models()
    return {
        "ollama_bytes": sum(m["size"] for m in models),
        "ollama_models": [m["name"] for m in models],
        "backend_rss_bytes": psutil.Process().memory_info().rss,
    }


def run_config(profile: str, mode: str, questions: list[dict], gold: dict, repeat: int, warmup: bool, out) -> None:
    handler = HANDLERS[mode]
    llm.unload_all()
    if warmup:
        t0 = time.perf_counter()
        handler(WARMUP_QUESTION, profile, None, False)
        log.info("[%s/%s] warm-up %.1fs", profile, mode, time.perf_counter() - t0)
    peak = 0
    for rep in range(repeat):
        conversations: dict[str, str] = {}
        for q in questions:
            conv = q.get("conversation")
            conv_id = None
            if conv:
                conv_id = conversations.setdefault(conv, f"eval-{profile}-{mode}-{rep}-{conv}")
            resp = handler(q["question"], profile, conv_id, False)
            rows = resp.data.rows if resp.data else None
            mem = _memory()
            peak = max(peak, mem["ollama_bytes"])
            query_calls = sum(s.llm_calls for s in resp.steps if s.agent in ("query_understanding", "single_model:sql"))
            record = {
                "id": q["id"],
                "category": q["category"],
                "match": q["match"],
                "profile": profile,
                "mode": mode,
                "repeat": rep,
                "question": q["question"],
                "status": resp.status,
                "answer": resp.answer,
                "sql": resp.sql,
                "query_spec": resp.query_spec,
                "columns": resp.data.columns if resp.data else None,
                "rows": rows[:50] if rows else rows,
                **score_answer(q, gold[q["id"]], rows, resp.status, resp.answer),
                "latency_s": resp.total_latency_s,
                "model_load_s": round(sum(s.model_load_s for s in resp.steps), 3),
                "llm_calls": resp.llm_calls,
                "prompt_tokens": resp.prompt_tokens,
                "completion_tokens": resp.completion_tokens,
                "retries": max(0, query_calls - 1),
                "error": resp.error,
                "chart_type": resp.chart.type if resp.chart else None,
                "chart_source": resp.chart.source if resp.chart else None,
                "dropped_filters": [d for s in resp.steps if s.agent == "query_understanding" and isinstance(s.output, dict) for d in s.output.get("dropped_filters", [])],
                "steps": [s.model_dump(exclude={"output"}) for s in resp.steps],
                **mem,
            }
            out.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
            out.flush()
            mark = "ok " if record["result_correct"] else "XX "
            log.info("[%s/%s r%d] %s %-5s %5.1fs %s", profile, mode, rep, mark, q["id"], resp.total_latency_s, q["question"][:60])
        for conv_id in conversations.values():
            traces.forget(conv_id)
    log.info("[%s/%s] peak Ollama memory %.2f GB", profile, mode, peak / 1e9)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = models_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", nargs="+", default=list(cfg["profiles"]))
    ap.add_argument("--modes", nargs="+", choices=list(HANDLERS), default=list(HANDLERS))
    ap.add_argument("--ids", nargs="+", help="only these question ids")
    ap.add_argument("--categories", nargs="+")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    if not llm.is_available():
        raise SystemExit("Ollama is not reachable; start it with `ollama serve`.")
    questions = load_questions()
    if args.ids:
        questions = [q for q in questions if q["id"] in args.ids]
    if args.categories:
        questions = [q for q in questions if q["category"] in args.categories]
    gold = gold_results(questions)

    out_dir = args.out or EVAL_DIR / "results" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(
        json.dumps({"args": vars(args), "models": cfg, "questions": len(questions)}, default=str, indent=1), "utf-8"
    )
    with open(out_dir / "results.jsonl", "a", encoding="utf-8") as out:
        for profile in args.profiles:
            for mode in args.modes:
                run_config(profile, mode, questions, gold, args.repeat, not args.no_warmup, out)
    report.build(out_dir)
    print(f"Results in {out_dir}")


if __name__ == "__main__":
    main()
