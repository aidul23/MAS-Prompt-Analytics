import json

import pandas as pd
import pytest

from app.data import loader, sources, store


def _trace(i: int, text: str, answer: str = "answer", day: int = 1) -> dict:
    return {
        "id": f"id{i}",
        "timestamp": f"2026-06-0{day}T08:{i:02d}:00.000Z",
        "userId": f"user-{i}",
        "sessionId": f"s{i}",
        "input": [{"role": "user", "content": {"text": text}}],
        "output": {"text": answer},
        "metadata": {"app": "LianaMailer", "userRole": "Admin"},
        "latency": 1.5,
        "totalTokens": 15,
    }


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    db = tmp_path / "analytics.duckdb"
    monkeypatch.setattr(sources, "SOURCES_DB", tmp_path / "sources.sqlite")
    monkeypatch.setattr(sources, "SOURCES_DIR", tmp_path / "sources")
    monkeypatch.setattr(sources, "DB_PATH", db)
    monkeypatch.setattr(sources, "RAW_CSV", tmp_path / "missing.csv")
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setattr(store, "_conn", None)
    sources.ensure_initialised()
    yield tmp_path
    if store._conn is not None:
        store._conn.close()


def test_loader_reads_json_jsonl_and_excel(tmp_path):
    traces = [_trace(1, "How do I create a newsletter?"), _trace(2, "Miten?")]
    (tmp_path / "a.json").write_text(json.dumps({"data": traces}))
    (tmp_path / "a.jsonl").write_text("\n".join(json.dumps(t) for t in traces))
    flat = [{k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in t.items()} for t in traces]
    pd.DataFrame(flat).to_excel(tmp_path / "a.xlsx", index=False)
    for name in ("a.json", "a.jsonl", "a.xlsx"):
        df = loader.load_traces(tmp_path / name)
        assert list(df["prompt"]) == ["How do I create a newsletter?", "Miten?"], name
        assert df["app"].iloc[0] == "LianaMailer" and df["latency_s"].iloc[0] == 1.5


def test_loader_rejects_files_without_required_fields(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps([{"foo": 1}]))
    with pytest.raises(ValueError):
        loader.read_records(tmp_path / "bad.json")


def test_later_files_replace_traces_with_the_same_id(tmp_path):
    (tmp_path / "1.json").write_text(json.dumps([_trace(1, "old"), _trace(2, "keep")]))
    (tmp_path / "2.json").write_text(json.dumps([_trace(1, "new")]))
    df = loader.load_many([tmp_path / "1.json", tmp_path / "2.json"])
    assert sorted(df["prompt"]) == ["keep", "new"]


def _upload(tmp_path, name: str, traces: list[dict]) -> dict:
    path = tmp_path / f"incoming-{name}"
    path.write_text(json.dumps(traces))
    return sources.add_upload(path, name)


def test_upload_and_sync_add_new_traces(tmp_data):
    first = _upload(tmp_data, "june1.json", [_trace(1, "How do I create a newsletter?"), _trace(2, "Miten?")])
    assert first["rows"] == 2 and first["new_traces"] == 2
    result = sources.run_sync("test", use_slm=False)
    assert result["status"] == "ok" and result["rows_after"] == 2 and result["new_traces"] == 2
    assert store.data_range()["rows"] == 2

    second = _upload(tmp_data, "june2.json", [_trace(2, "Miten?"), _trace(3, "Can I export contacts?", day=2)])
    assert second["new_traces"] == 1
    result = sources.run_sync("test", use_slm=False)
    assert result["rows_before"] == 2 and result["rows_after"] == 3 and result["new_traces"] == 1
    assert store.data_range()["end"].startswith("2026-06-02")

    with pytest.raises(ValueError, match="already imported"):
        _upload(tmp_data, "again.json", [_trace(2, "Miten?"), _trace(3, "Can I export contacts?", day=2)])
    assert [s["status"] for s in sources.list_syncs()] == ["ok", "ok"]


def test_many_csv_uploads_merge_and_the_latest_version_wins(tmp_data):
    def csv_file(name: str, traces: list[dict]) -> str:
        flat = [{k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in t.items()} for t in traces]
        path = tmp_data / f"incoming-{name}"
        pd.DataFrame(flat).to_csv(path, index=False)
        return sources.add_upload(path, name)

    csv_file("a.csv", [_trace(1, "Hello"), _trace(2, "Hi")])
    csv_file("b.csv", [_trace(3, "Moi", day=2), _trace(4, "Hei", day=2)])
    csv_file("c.csv", [_trace(2, "Hi again"), _trace(5, "Terve", day=3)])
    result = sources.run_sync("test", use_slm=False)
    assert result["files"] == 3 and result["rows_after"] == 5
    assert store.query("SELECT prompt FROM prompts WHERE id = 'id2'")["prompt"][0] == "Hi again"


def test_failed_sync_keeps_current_data(tmp_data, monkeypatch):
    _upload(tmp_data, "june1.json", [_trace(1, "Hello")])
    sources.run_sync("test", use_slm=False)
    monkeypatch.setattr(sources.llm, "is_available", lambda: False)
    _upload(tmp_data, "june2.json", [_trace(2, "Hi", day=2)])
    result = sources.run_sync("test")
    assert result["status"] == "error" and "Ollama" in result["message"]
    assert store.data_range()["rows"] == 1


def test_watched_folder_imports_new_files_once(tmp_data):
    folder = tmp_data / "exports"
    folder.mkdir()
    (folder / "day1.json").write_text(json.dumps([_trace(1, "Hello")]))
    (folder / "notes.txt").write_text("ignored")
    src = sources.add_folder_source("Exports", str(folder), 15)
    assert [s["id"] for s in sources.due_sources()] == [src["id"]]

    imported, problems = sources.scan_folder(src["id"])
    assert [f["name"] for f in imported] == ["day1.json"] and problems == []
    assert sources.due_sources() == []

    (folder / "day2.json").write_text(json.dumps([_trace(2, "Hi", day=2)]))
    (folder / "broken.json").write_text("[{}]")
    imported, problems = sources.scan_folder(src["id"])
    assert [f["name"] for f in imported] == ["day2.json"] and len(problems) == 1

    result = sources.run_sync("test", use_slm=False)
    assert result["rows_after"] == 2
    sources.delete_source(src["id"])
    assert [s["id"] for s in sources.list_sources()] == [sources.UPLOADS]


def test_removing_every_file_empties_the_dataset_for_good(tmp_data, monkeypatch):
    bundled = tmp_data / "bundled.json"
    bundled.write_text(json.dumps([_trace(1, "Hello"), _trace(2, "Hi")]))
    monkeypatch.setattr(sources, "SOURCES_DB", tmp_data / "fresh.sqlite")
    monkeypatch.setattr(sources, "RAW_CSV", bundled)
    sources.ensure_initialised()
    [initial] = sources.list_sources()[0]["files"]
    assert sources.run_sync("test", use_slm=False)["rows_after"] == 2

    sources.delete_file(initial["id"])
    assert bundled.exists()
    result = sources.run_sync("file removed", use_slm=False)
    assert result["status"] == "ok" and result["rows_before"] == 2 and result["rows_after"] == 0
    assert store.version() is None
    with pytest.raises(store.NoData):
        store.data_range()

    sources.ensure_initialised()
    assert not sources.has_files()


def test_sync_keeps_data_when_files_vanish_from_disk(tmp_data):
    _upload(tmp_data, "june1.json", [_trace(1, "Hello")])
    sources.run_sync("test", use_slm=False)
    for p in (tmp_data / "sources" / sources.UPLOADS).iterdir():
        p.unlink()
    result = sources.run_sync("test", use_slm=False)
    assert result["status"] == "error" and "can be found" in result["message"]
    assert store.data_range()["rows"] == 1


def test_paths_survive_moving_the_data_folder(tmp_path, monkeypatch):
    data = tmp_path / "mounted"
    (data / "sources" / "uploads").mkdir(parents=True)
    (data / "sources" / "uploads" / "f.csv").write_text("x")
    (data / "bundled.csv").write_text("x")
    monkeypatch.setattr(sources, "DATA_DIR", data)
    assert sources._store_path(data / "sources" / "uploads" / "f.csv") == "sources/uploads/f.csv"
    assert sources._resolve("sources/uploads/f.csv") == data / "sources" / "uploads" / "f.csv"
    assert sources._resolve("/Users/someone/project/data/sources/uploads/f.csv") == data / "sources" / "uploads" / "f.csv"
    assert sources._resolve("/Users/someone/project/data/bundled.csv") == data / "bundled.csv"
    assert sources._resolve("/elsewhere/missing.csv") == sources.Path("/elsewhere/missing.csv")
