"""Turn results.jsonl into thesis-ready tables and plots.

    uv run python -m eval.report eval/results/<run>

Produces summary.md, summary.csv, by_category.csv, agent_latency.csv,
code_metrics.csv, ratings_template.csv and PNG plots in the run directory.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "mas-analytics-mpl"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from eval import code_metrics  # noqa: E402


def load(run_dir: Path) -> pd.DataFrame:
    with open(run_dir / "results.jsonl", encoding="utf-8") as f:
        df = pd.DataFrame([json.loads(line) for line in f if line.strip()])
    df["config"] = df["profile"] + " / " + df["mode"]
    df["total_tokens"] = df["prompt_tokens"] + df["completion_tokens"]
    for col in ("result_correct", "answer_correct"):
        df[col] = df[col].astype("boolean")
    return df


def summary(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["profile", "mode"])
    out = pd.DataFrame(
        {
            "questions": g.size(),
            "result_accuracy": g["result_correct"].mean(),
            "answer_accuracy": g["answer_correct"].mean(),
            "faithfulness": g["faithfulness"].mean(),
            "error_rate": g["status"].apply(lambda s: (s == "error").mean()),
            "latency_mean_s": g["latency_s"].mean(),
            "latency_median_s": g["latency_s"].median(),
            "latency_p95_s": g["latency_s"].quantile(0.95),
            "model_load_mean_s": g["model_load_s"].mean() if "model_load_s" in df else float("nan"),
            "llm_calls_mean": g["llm_calls"].mean(),
            "tokens_mean": g["total_tokens"].mean(),
            "retry_rate": g["retries"].apply(lambda s: (s > 0).mean()),
            "peak_ollama_gb": g["ollama_bytes"].max() / 1e9,
        }
    )
    return out.round(3).reset_index()


def by_category(df: pd.DataFrame) -> pd.DataFrame:
    return df.pivot_table(index="category", columns="config", values="result_correct", aggfunc="mean").round(3)


def agent_latency(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        for s in r["steps"]:
            rows.append({"config": r["config"], "agent": s["agent"], "model": s["model"], "latency_s": s["latency_s"], "llm_calls": s["llm_calls"], "tokens": s["prompt_tokens"] + s["completion_tokens"]})
    steps = pd.DataFrame(rows)
    if steps.empty:
        return steps
    return steps.groupby(["config", "agent", "model"], dropna=False).agg(
        calls=("llm_calls", "sum"), mean_latency_s=("latency_s", "mean"), total_latency_s=("latency_s", "sum"), mean_tokens=("tokens", "mean")
    ).round(3).reset_index()


def failures(df: pd.DataFrame) -> pd.DataFrame:
    bad = df[df["result_correct"] == False]  # noqa: E712
    return bad[["config", "id", "category", "question", "status", "sql", "error", "answer"]]


def _plots(df: pd.DataFrame, summ: pd.DataFrame, cat: pd.DataFrame, run_dir: Path) -> list[str]:
    files = []
    configs = summ["profile"] + " / " + summ["mode"]

    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(summ))
    ax.bar([i - 0.2 for i in x], summ["result_accuracy"], width=0.4, label="result accuracy")
    ax.bar([i + 0.2 for i in x], summ["answer_accuracy"], width=0.4, label="answer accuracy")
    ax.set_xticks(list(x), configs, rotation=20, ha="right")
    ax.set_ylim(0, 1)
    ax.set_ylabel("share correct")
    ax.legend()
    ax.set_title("Correctness by configuration")
    fig.tight_layout()
    fig.savefig(run_dir / "accuracy.png", dpi=150)
    files.append("accuracy.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    order = list(configs)
    ax.boxplot([df.loc[df["config"] == c, "latency_s"] for c in order], showfliers=True)
    ax.set_xticks(range(1, len(order) + 1), order, rotation=20, ha="right")
    ax.set_ylabel("seconds")
    ax.set_title("End-to-end latency per question")
    fig.tight_layout()
    fig.savefig(run_dir / "latency.png", dpi=150)
    files.append("latency.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(1.6 + 1.3 * len(cat.columns), 0.5 + 0.45 * len(cat)))
    im = ax.imshow(cat.values.astype(float), vmin=0, vmax=1, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(cat.columns)), cat.columns, rotation=30, ha="right")
    ax.set_yticks(range(len(cat.index)), cat.index)
    for i in range(len(cat.index)):
        for j in range(len(cat.columns)):
            v = cat.values[i, j]
            if pd.notna(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.03)
    ax.set_title("Result accuracy by question category")
    fig.tight_layout()
    fig.savefig(run_dir / "accuracy_by_category.png", dpi=150)
    files.append("accuracy_by_category.png")
    plt.close(fig)
    return files


def _md(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines)


def build(run_dir: Path) -> None:
    run_dir = Path(run_dir)
    df = load(run_dir)
    summ, cat, agents, fails = summary(df), by_category(df), agent_latency(df), failures(df)
    code = pd.DataFrame(code_metrics.collect())
    summ.to_csv(run_dir / "summary.csv", index=False)
    cat.to_csv(run_dir / "by_category.csv")
    agents.to_csv(run_dir / "agent_latency.csv", index=False)
    fails.to_csv(run_dir / "failures.csv", index=False)
    code.to_csv(run_dir / "code_metrics.csv", index=False)
    ratings = df[["config", "id", "question", "answer"]].copy()
    ratings["usefulness_1to5"] = ""
    ratings["understandability_1to5"] = ""
    ratings["notes"] = ""
    ratings.to_csv(run_dir / "ratings_template.csv", index=False)
    plots = _plots(df, summ, cat, run_dir)

    code_totals = code.groupby("system")[["loc", "functions", "branches", "prompt_chars"]].sum().reset_index()
    md = [
        f"# Evaluation run `{run_dir.name}`",
        "",
        f"{df['id'].nunique()} questions, {len(df)} answers.",
        "",
        "## Summary",
        _md(summ),
        "",
        "## Result accuracy by category",
        _md(cat.reset_index()),
        "",
        "## Per-agent latency",
        _md(agents),
        "",
        "## Code size (maintainability)",
        _md(code_totals),
        "",
        _md(code),
        "",
        "## Failures",
        _md(fails.drop(columns=["answer"]).head(80)),
        "",
        *[f"![{p}]({p})" for p in plots],
    ]
    (run_dir / "summary.md").write_text("\n".join(md), "utf-8")


if __name__ == "__main__":
    build(Path(sys.argv[1]))
