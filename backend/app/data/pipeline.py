"""Build the analytics database: `uv run python -m app.data.pipeline [--csv PATH] [--no-slm]`."""

import argparse
import json
import logging
import time
from pathlib import Path

from app.config import DB_PATH, RAW_CSV
from app.data import features, loader, store

log = logging.getLogger(__name__)


def build(
    csv_path: Path = RAW_CSV, db_path: Path = DB_PATH, use_slm: bool = True, paths: list[Path] | None = None, strict_slm: bool = False
) -> dict:
    t0 = time.perf_counter()
    df = loader.load_many(paths or [csv_path])
    report = loader.profile(df)
    df = features.add_basic_features(df)
    if use_slm:
        df = features.add_slm_features(df, strict=strict_slm)
    else:
        df = features.add_placeholder_features(df)
    sessions = features.build_sessions(df)
    store.write_tables(df, sessions, db_path)
    report["build_seconds"] = round(time.perf_counter() - t0, 2)
    report["topics"] = df["topic"].value_counts().to_dict()
    report["intents"] = df["intent"].value_counts().to_dict()
    report["prompt_languages"] = df["prompt_language"].value_counts().to_dict()
    report["response_on_topic"] = df["response_on_topic"].value_counts(dropna=False).to_dict()
    report["language_match"] = df["language_match"].value_counts().to_dict()
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=RAW_CSV)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--no-slm", action="store_true", help="skip SLM-derived features")
    args = ap.parse_args()
    report = build(args.csv, args.db, use_slm=not args.no_slm)
    print(json.dumps(report, indent=1, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
