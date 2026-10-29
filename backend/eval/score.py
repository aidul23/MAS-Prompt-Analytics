"""Scoring of system outputs against gold SQL results.

Result correctness compares the system's result table with the gold result,
ignoring column names and tolerating rounding and fraction-vs-percent.
Answer correctness checks that the text states the key fact (scalar value or
top-1 label). Faithfulness is the share of numbers in the text that are backed
by the system's own result table or by the gold result (a hallucination check).
"""

import math
import re
from datetime import date, datetime

import pandas as pd

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$")
_NUM_RE = re.compile(r"(?<![\w.])-?(?:\d{1,3}(?:[,\u00a0\u202f ]\d{3})+|\d+)(?:[.,]\d+)?(?![\w])")


def norm(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        v = v.item()
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return _norm_time(pd.Timestamp(v))
    s = str(v).strip()
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if _DATE_RE.match(s):
        return _norm_time(pd.Timestamp(s))
    return s.lower()


def _norm_time(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%d") if ts == ts.normalize() else ts.strftime("%Y-%m-%dT%H:%M:%S")


def values_equal(g, s) -> bool:
    if isinstance(g, float) and isinstance(s, float):
        if math.isclose(g, s, rel_tol=0.005, abs_tol=0.006):
            return True
        return 0 <= g <= 1 and math.isclose(g * 100, s, rel_tol=0.005, abs_tol=0.06)
    if isinstance(g, bool) or isinstance(s, bool):
        return g == s
    return g == s


def row_contains(gold_row: list, sys_row: list) -> bool:
    """Every gold value appears in the system row (each system cell used once)."""
    free = list(sys_row)
    for g in gold_row:
        for i, s in enumerate(free):
            if values_equal(g, s):
                free.pop(i)
                break
        else:
            return False
    return True


def _rows(df_or_rows) -> list[list]:
    if isinstance(df_or_rows, pd.DataFrame):
        df_or_rows = df_or_rows.astype(object).values.tolist()
    return [[norm(v) for v in r] for r in df_or_rows]


def result_correct(match: str, gold: pd.DataFrame | None, sys_rows: list[list] | None, status: str) -> bool:
    if match == "out_of_scope":
        return status == "out_of_scope"
    if status != "ok" or sys_rows is None or gold is None:
        return False
    g, s = _rows(gold), _rows(sys_rows)
    if match == "scalar":
        return len(s) == 1 and any(values_equal(g[0][0], v) for v in s[0])
    if match == "top1":
        return bool(s) and any(values_equal(g[0][0], v) for v in s[0])
    if match in ("rows", "ordered"):
        if len(s) != len(g):
            return False
        if match == "ordered":
            return all(row_contains(gr, sr) for gr, sr in zip(g, s, strict=True))
        free = list(s)
        for gr in g:
            hit = next((i for i, sr in enumerate(free) if row_contains(gr, sr)), None)
            if hit is None:
                return False
            free.pop(hit)
        return True
    if match == "subset":
        if not s:
            return False
        has_time = any(isinstance(v, str) and _DATE_RE.match(v) for v in s[0])
        keys = g if has_time else [[r[1]] for r in g]
        return all(any(row_contains(k, sr) for k in keys) for sr in s)
    raise ValueError(f"unknown match mode {match}")


def numbers_in_text(text: str) -> list[tuple[float, int]]:
    """Numbers with their number of shown decimals. Handles 1,234 / 1 234 / 16,3 / 94.9%."""
    out = []
    for m in _NUM_RE.finditer(text or ""):
        tok = m.group(0)
        if re.search(r"\d[,\u00a0\u202f ]\d{3}(?!\d)", tok) and not re.search(r"[.,]\d{1,2}$", tok.split()[-1] if " " in tok else tok[-3:]):
            tok = re.sub(r"[,\u00a0\u202f ]", "", tok)
        elif "," in tok and "." not in tok:
            tok = tok.replace(",", ".")
        else:
            tok = re.sub(r"[,\u00a0\u202f ]", "", tok)
        try:
            val = float(tok)
        except ValueError:
            continue
        decimals = len(tok.split(".")[1]) if "." in tok else 0
        out.append((val, decimals))
    return out


def _text_matches_number(g: float, nums: list[tuple[float, int]]) -> bool:
    for val, dec in nums:
        tol = max(0.5 * 10**-dec + 1e-9, 0.005 * abs(g))
        if abs(val - g) <= tol or (0 <= g <= 1 and abs(val - g * 100) <= max(0.5 * 10**-dec + 1e-9, 0.005 * g * 100)):
            return True
    return False


def answer_correct(match: str, gold: pd.DataFrame | None, answer: str, status: str) -> bool | None:
    if match == "out_of_scope":
        return status == "out_of_scope"
    if gold is None or gold.empty or match not in ("scalar", "top1"):
        return None
    key = norm(gold.iloc[0, 0])
    if isinstance(key, float):
        return _text_matches_number(key, numbers_in_text(answer))
    return str(key).lower() in (answer or "").lower()


def faithfulness(answer: str, sys_rows: list[list] | None, gold: pd.DataFrame | None) -> float | None:
    """Share of numbers in the answer that appear in the system result or the gold result.

    Small integers (<= 10), years and day-of-month numbers next to month names are ignored.
    """
    nums = [(v, d) for v, d in numbers_in_text(answer) if not (d == 0 and (abs(v) <= 10 or 2000 <= v <= 2100))]
    if not nums:
        return None
    pool = [v for r in (_rows(sys_rows) if sys_rows else []) for v in r if isinstance(v, float)]
    if gold is not None:
        pool += [v for r in _rows(gold) for v in r if isinstance(v, float)]
    if not pool:
        return 0.0
    supported = sum(1 for v, d in nums if any(_text_matches_number(p, [(v, d)]) for p in pool))
    return supported / len(nums)
