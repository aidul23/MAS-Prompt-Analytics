from datetime import datetime

import pytest
from pydantic import ValidationError

from app.mas import query_spec as qs

VALUES = {
    "app": ["LianaCMS", "LianaMailer"],
    "user_role": ["Admin", "User"],
    "prompt_language": ["en", "fi"],
    "topic": ["Newsletter Creation", "Email Open Rates"],
}
DATA_END = datetime(2026, 6, 3, 2, 15)


def norm(**kw) -> qs.QuerySpec:
    return qs.normalise(qs.QuerySpec(**kw), VALUES, DATA_END)


def test_rejects_unknown_metric_and_dimension():
    with pytest.raises(ValidationError):
        qs.QuerySpec(metrics=["nonsense"])
    with pytest.raises(ValidationError):
        qs.QuerySpec(group_by=["colour"])
    with pytest.raises(ValidationError):
        qs.QuerySpec(filters=[{"field": "password", "values": ["x"]}])


def test_snaps_values_to_known_values():
    spec = norm(filters=[{"field": "app", "values": ["lianamailer"]}, {"field": "prompt_language", "values": ["Finnish"]}])
    assert spec.filters[0].values == ["LianaMailer"]
    assert spec.filters[1].values == ["fi"]
    spec = norm(filters=[{"field": "topic", "values": ["newsletter"]}])
    assert spec.filters[0].values == ["Newsletter Creation"]


def test_unknown_value_raises():
    with pytest.raises(qs.SpecError):
        norm(filters=[{"field": "app", "values": ["Photoshop"]}])


def test_wildcards_dropped_and_multi_values_become_in():
    spec = norm(filters=[{"field": "app", "values": ["*"]}, {"field": "user_role", "values": ["Admin", "User"]}])
    assert len(spec.filters) == 1 and spec.filters[0].op == "in"


def test_relative_dates():
    spec = norm(start="yesterday", end="yesterday")
    assert spec.start.startswith("2026-06-02T00:00:00")
    assert spec.end.startswith("2026-06-02T23:59:59")
    spec = norm(start="2026-06-01", end="2026-06-01")
    assert spec.end.startswith("2026-06-01T23:59:59")


def test_compile_aggregate_is_parameterised():
    spec = norm(metrics=["prompt_count", "avg_latency"], group_by=["app"], filters=[{"field": "app", "values": ["x' OR 1=1 --", "LianaCMS"], "op": "contains"}], limit=3)
    sql, params = qs.compile_sql(spec)
    assert "x' OR 1=1" not in sql
    assert "%x' OR 1=1 --%" in params
    assert sql.endswith("LIMIT 3")
    assert "GROUP BY 1" in sql


def test_time_grouping_orders_by_time():
    spec = norm(group_by=["day"], order="desc")
    sql, _ = qs.compile_sql(spec)
    assert "ORDER BY day" in sql


def test_category_group_with_time_order_falls_back_to_desc():
    spec = norm(group_by=["app"], order="time")
    assert spec.order == "desc"


def test_boolean_filter():
    spec = norm(metrics=["prompt_count"], filters=[{"field": "response_on_topic", "values": ["yes"]}])
    sql, params = qs.compile_sql(spec)
    assert "response_on_topic = ?" in sql and params == [True]


TERMS = {
    "user_role": {"Admin": ["admin", "pääkäyttäj"], "User": ["user", "käyttäj"]},
    "prompt_language": {"fi": ["fi", "finnish", "suomeksi"], "en": ["en", "english"]},
    "topic": {"Newsletter Creation": ["newsletter", "creation", "uutiskirjeen"]},
    "weekday": {"Wednesday": ["wednesday"]},
}


def test_grounding_drops_unmentioned_filters():
    spec = qs.QuerySpec(filters=[
        {"field": "user_role", "values": ["User"]},
        {"field": "weekday", "values": ["Wednesday"]},
        {"field": "hour_of_day", "op": "eq", "values": ["23"]},
        {"field": "user_id", "values": ["2026-06-01"]},
    ])
    grounded, dropped = qs.ground_filters(spec, "How many tokens were used yesterday?", TERMS)
    assert grounded.filters == [] and len(dropped) == 4
    lang = qs.QuerySpec(filters=[{"field": "prompt_language", "values": ["en"]}])
    assert qs.ground_filters(lang, "show prompts with latency above 24 seconds", TERMS)[0].filters == []


def test_grounding_keeps_mentioned_filters_across_languages():
    spec = qs.QuerySpec(filters=[
        {"field": "prompt_language", "values": ["fi"]},
        {"field": "topic", "values": ["Newsletter Creation"]},
        {"field": "latency_s", "op": "gt", "values": ["24"]},
        {"field": "user_role", "op": "in", "values": ["Admin", "User"]},
    ])
    grounded, dropped = qs.ground_filters(spec, "Suomeksi kysytyt uutiskirjeistä, latency above 24 s, by admins", TERMS)
    assert [f.field for f in grounded.filters] == ["prompt_language", "topic", "latency_s", "user_role"]
    assert grounded.filters[3].values == ["Admin"] and grounded.filters[3].op == "eq"
    assert dropped == [{"field": "user_role", "values": ["User"]}]


def test_date_filter_becomes_time_range():
    spec = qs.QuerySpec(filters=[{"field": "date", "op": "eq", "values": ["2026-06-02"]}])
    spec = qs.normalise(spec, VALUES, DATA_END)
    assert spec.filters == []
    assert spec.start.startswith("2026-06-02T00:00") and spec.end.startswith("2026-06-02T23:59")


def test_list_kind():
    sql, _ = qs.compile_sql(norm(kind="list", limit=5))
    assert sql.startswith("SELECT timestamp") and sql.endswith("LIMIT 5")
