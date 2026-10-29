import csv
import io
import json

import pytest

from app.baseline.single_model import validate_sql
from app.data.features import detect_language
from app.data.loader import load_traces
from app.schemas import DataTable
from app.viz_rules import plan_chart

HEADER = ["id", "timestamp", "userId", "sessionId", "input", "output", "metadata", "latency", "usage", "inputTokens", "outputTokens", "totalTokens", "totalCost"]


def _row(i: int, text: str) -> list[str]:
    msg = [{"role": "user", "content": {"text": text, "parts": [{"type": "text", "text": text}]}}]
    return [
        f"id{i}", f"2026-06-01T08:0{i}:00.000Z", f"user-{i}", f"s{i}", json.dumps(msg),
        json.dumps({"text": "answer"}), json.dumps({"app": "LianaMailer", "userRole": "Admin", "organizationId": 5}),
        "1.5", json.dumps({"promptTokens": 10}), "10", "5", "15", "",
    ]


def _csv(rows: list[list[str]], wrapped: bool) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    for r in rows:
        if wrapped:
            inner = io.StringIO()
            csv.writer(inner).writerow(r)
            w.writerow([inner.getvalue().rstrip("\r\n")])
        else:
            w.writerow(r)
    return buf.getvalue()


@pytest.mark.parametrize("wrapped", [False, True])
def test_loader_handles_plain_and_wrapped_rows(tmp_path, wrapped):
    path = tmp_path / "t.csv"
    path.write_text(_csv([_row(1, "How do I create a newsletter?"), _row(2, "Miten?")], wrapped), "utf-8")
    df = load_traces(path)
    assert list(df["prompt"]) == ["How do I create a newsletter?", "Miten?"]
    assert df["app"].iloc[0] == "LianaMailer" and df["organization_id"].iloc[0] == "5"
    assert df["total_tokens"].iloc[0] == 15 and df["latency_s"].iloc[0] == 1.5


def test_language_detection_prefers_expected_languages():
    assert detect_language("Can you help me design an email template?") == "en"
    assert detect_language("Miten parannan sähköpostin avaamisprosenttia?") == "fi"


def test_validate_sql():
    assert validate_sql("select 1;") == "select 1"
    for bad in ("DROP TABLE prompts", "select 1; select 2", "with x as (select 1) delete from prompts"):
        with pytest.raises(ValueError):
            validate_sql(bad)


def test_plan_chart_rules():
    assert plan_chart(DataTable(columns=["n"], rows=[[5]], total_rows=1)).type == "kpi"
    assert plan_chart(DataTable(columns=["day", "n"], rows=[["2026-06-01", 1], ["2026-06-02", 2]], total_rows=2)).type == "line"
    assert plan_chart(DataTable(columns=["app", "n"], rows=[["a", 1], ["b", 2]], total_rows=2)).type == "bar"
