"""Deterministic chart selection from the shape of a result table.

Used by the baseline, and by the Visualization Planning Agent as a fallback when
the SLM proposes an invalid chart.
"""

from datetime import date, datetime

from app.schemas import ChartSpec, DataTable

TIME_COLUMNS = {"day", "hour_bucket", "date", "bucket", "timestamp", "started_at"}
ORDINAL_COLUMNS = {"hour_of_day", "hour"}


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def numeric_columns(table: DataTable) -> list[str]:
    if not table.rows:
        return []
    return [c for i, c in enumerate(table.columns) if all(_is_number(r[i]) or r[i] is None for r in table.rows) and any(_is_number(r[i]) for r in table.rows)]


def is_time_column(table: DataTable, col: str) -> bool:
    if col in TIME_COLUMNS or col in ORDINAL_COLUMNS:
        return True
    i = table.columns.index(col)
    return bool(table.rows) and all(isinstance(r[i], (date, datetime)) for r in table.rows if r[i] is not None)


def plan_chart(table: DataTable, title: str = "") -> ChartSpec:
    if not table.rows:
        return ChartSpec(type="table", title=title)
    nums = numeric_columns(table)
    dims = [c for c in table.columns if c not in nums]
    if len(table.rows) == 1 and len(table.columns) <= 3 and nums:
        return ChartSpec(type="kpi", y=nums, title=title)
    if len(dims) == 1 and nums:
        x = dims[0]
        if is_time_column(table, x):
            return ChartSpec(type="line", x=x, y=nums[:3], title=title)
        if len(table.rows) <= 30:
            return ChartSpec(type="bar", x=x, y=nums[:2], title=title)
    if not dims and len(nums) >= 2 and nums[0] in ORDINAL_COLUMNS:
        return ChartSpec(type="line", x=nums[0], y=nums[1:3], title=title)
    return ChartSpec(type="table", title=title)
