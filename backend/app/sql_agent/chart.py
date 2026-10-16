"""Pick a chart for a query result: rules in code, not an LLM call (Phase 6).

The shape of the result decides, the way an analyst would:

    1 row, 1 number                       -> number   (a big figure: "average score: 71.4")
    a date/time column + number columns   -> line     (a trend: x = time, sorted)
    a text column + number columns, 2-30  -> bar      (a comparison between categories)
    anything else                         -> no chart (the table is the answer)

Why not ask the model? This is free, instant, the same every time, and can't name a column that
doesn't exist. An LLM helps when the choice depends on intent ("share of" -> stacked bar); here the
result's shape is enough. No pie charts: bars compare values more accurately, and pies stop working
past a handful of slices.
"""

from datetime import date, datetime
from decimal import Decimal

MAX_BARS = 30
MAX_SERIES = 3


def _is_number(v) -> bool:
    return isinstance(v, int | float | Decimal) and not isinstance(v, bool)


def _kind(values: list) -> str | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    if all(_is_number(v) for v in present):
        return "number"
    if all(isinstance(v, datetime | date) for v in present):
        return "time"
    if all(isinstance(v, str) for v in present):
        return "text"
    return None


def _is_id(name: str) -> bool:
    name = name.lower()
    return name == "id" or name.endswith("_id")


def choose_chart(columns: list[str], rows: list[tuple]) -> dict | None:
    if not rows or not columns:
        return None
    kinds = {c: _kind([r[i] for r in rows]) for i, c in enumerate(columns)}
    numbers = [c for c in columns if kinds[c] == "number" and not _is_id(c)]

    if len(rows) == 1 and len(columns) == 1 and numbers:
        return {"type": "number", "x": None, "y": numbers}
    if not numbers:
        return None

    times = [c for c in columns if kinds[c] == "time"]
    if times and len(rows) >= 2:
        return {"type": "line", "x": times[0], "y": numbers[:MAX_SERIES]}

    labels = [c for c in columns if kinds[c] == "text"]
    if labels and 2 <= len(rows) <= MAX_BARS:
        return {"type": "bar", "x": labels[0], "y": numbers[:MAX_SERIES]}
    return None
