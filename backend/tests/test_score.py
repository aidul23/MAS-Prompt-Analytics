import pandas as pd

from eval import score


def test_numbers_in_text():
    nums = [v for v, _ in score.numbers_in_text("Admins used 1,722,111 tokens; 94.9% on topic, avg 16,3 s and 1 234 users")]
    assert nums == [1722111, 94.9, 16.3, 1234]


def test_scalar_and_percent_tolerance():
    gold = pd.DataFrame({"v": [0.1702]})
    assert score.result_correct("scalar", gold, [[0.17]], "ok")
    assert score.result_correct("scalar", gold, [[17.02]], "ok")
    assert not score.result_correct("scalar", gold, [[0.17], [0.2]], "ok")
    assert score.answer_correct("scalar", gold, "About 17.0% of answers", "ok")


def test_rows_ignore_order_and_extra_columns():
    gold = pd.DataFrame({"app": ["A", "B"], "n": [3, 5]})
    assert score.result_correct("rows", gold, [["b", 5, 0.1], ["a", 3, 0.2]], "ok")
    assert not score.result_correct("ordered", gold, [["b", 5], ["a", 3]], "ok")
    assert not score.result_correct("rows", gold, [["a", 3]], "ok")


def test_dates_normalised():
    gold = pd.DataFrame({"date": [pd.Timestamp("2026-06-01").date()], "n": [185]})
    assert score.result_correct("ordered", gold, [["2026-06-01T00:00:00", 185]], "ok")


def test_top1_and_out_of_scope():
    gold = pd.DataFrame({"app": ["LianaCMS"], "v": [16.33]})
    assert score.result_correct("top1", gold, [["LianaCMS"]], "ok")
    assert score.answer_correct("top1", gold, "LianaCMS is the slowest", "ok")
    assert score.result_correct("out_of_scope", None, None, "out_of_scope")


def test_faithfulness_flags_invented_numbers():
    rows = [["Email Segmentation", 0.9492]]
    assert score.faithfulness("Email Segmentation: 94.9%", rows, None) == 1.0
    assert score.faithfulness("Email Segmentation: 1.02% (56 out of 55,256)", rows, None) == 0.0
