"""Re-score a finished run against the current questions.yaml without calling any model.

    uv run python -m eval.rescore eval/results/<run>
"""

import json
import sys
from pathlib import Path

from eval import report
from eval.run_eval import gold_results, load_questions, score_answer


def rescore(run_dir: Path) -> None:
    questions = {q["id"]: q for q in load_questions()}
    gold = gold_results(list(questions.values()))
    path = run_dir / "results.jsonl"
    records = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
    changed = 0
    for r in records:
        q = questions.get(r["id"])
        if q is None:
            continue
        new = score_answer(q, gold[r["id"]], r["rows"], r["status"], r["answer"])
        changed += new["result_correct"] != r["result_correct"]
        r.update(new)
    path.write_text("".join(json.dumps(r, default=str, ensure_ascii=False) + "\n" for r in records), "utf-8")
    report.build(run_dir)
    print(f"Re-scored {len(records)} answers in {run_dir} ({changed} result verdicts changed)")


if __name__ == "__main__":
    rescore(Path(sys.argv[1]))
