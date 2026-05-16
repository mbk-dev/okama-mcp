"""Serialization helpers: convert pandas objects to JSON-safe Python primitives.

The MCP protocol moves JSON over the wire, so every value a tool returns has to be
JSON-serialisable. okama returns lots of pandas objects (Series, DataFrame, Period,
Timestamp), and many of them are too large to ship in full — Monte Carlo results,
month-by-month wealth indices over 30 years, etc.

This module provides one entry point — `to_json(value)` — that dispatches on the
runtime type and applies the project's normalisation rules:

- ``float`` rounded to 6 decimals, ``NaN`` / ``inf`` mapped to ``None``
- ``pandas.Timestamp`` / ``Period`` rendered as period-end ISO date strings
- ``Series`` / ``DataFrame`` over ``TRUNCATION_THRESHOLD`` rows are returned as
  ``{head, tail, summary, truncated, total_rows}``; callers wanting the full
  payload pass ``full=True`` to ``series_to_json`` / ``dataframe_to_json``.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

TRUNCATION_THRESHOLD = 500
HEAD_TAIL_ROWS = 50
FLOAT_DECIMALS = 6


def _index_to_iso(idx: pd.Index) -> list[str]:
    """Render Period/Datetime indices as period-end ISO date strings."""
    if isinstance(idx, pd.PeriodIndex):
        return [ts.strftime("%Y-%m-%d") for ts in idx.to_timestamp(how="end").normalize()]
    if isinstance(idx, pd.DatetimeIndex):
        return [ts.strftime("%Y-%m-%d") for ts in idx]
    return [str(v) for v in idx]


def _round_float(x: float) -> float | None:
    if math.isnan(x) or math.isinf(x):
        return None
    return round(float(x), FLOAT_DECIMALS)


def value_to_json(v: Any) -> Any:
    """Convert a single scalar to a JSON-safe form."""
    if v is None:
        return None
    if isinstance(v, bool):  # bool must come before int
        return v
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return _round_float(float(v))
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, pd.Period):
        return v.to_timestamp(how="end").strftime("%Y-%m-%d")
    if isinstance(v, np.ndarray):
        return [value_to_json(x) for x in v.tolist()]
    # pd.isna over a scalar returns a scalar; over a Series/DataFrame it returns
    # an array-like whose truth value is ambiguous. Guard against that here so
    # callers that accidentally hand a non-scalar don't crash.
    try:
        is_missing = pd.isna(v)
    except (TypeError, ValueError):
        return v
    if isinstance(is_missing, bool) and is_missing:
        return None
    return v


def _series_summary(s: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(s, errors="coerce").dropna()
    if numeric.empty:
        return {"count": int(s.size), "min": None, "max": None, "mean": None, "std": None}
    return {
        "count": int(s.size),
        "min": _round_float(float(numeric.min())),
        "max": _round_float(float(numeric.max())),
        "mean": _round_float(float(numeric.mean())),
        "std": _round_float(float(numeric.std())) if numeric.size > 1 else None,
    }


def _series_payload(s: pd.Series) -> dict[str, Any]:
    return {
        "name": str(s.name) if s.name is not None else None,
        "index": _index_to_iso(s.index),
        "values": [value_to_json(v) for v in s.tolist()],
    }


def series_to_json(s: pd.Series, *, full: bool = False) -> dict[str, Any]:
    """Convert a Series to a JSON-safe dict, truncating long series unless ``full``."""
    if not full and len(s) > TRUNCATION_THRESHOLD:
        return {
            "truncated": True,
            "total_rows": int(len(s)),
            "name": str(s.name) if s.name is not None else None,
            "summary": _series_summary(s),
            "head": _series_payload(s.head(HEAD_TAIL_ROWS)),
            "tail": _series_payload(s.tail(HEAD_TAIL_ROWS)),
        }
    return _series_payload(s)


def _dataframe_payload(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "columns": [str(c) for c in df.columns],
        "index": _index_to_iso(df.index),
        "data": [[value_to_json(v) for v in row] for row in df.itertuples(index=False, name=None)],
    }


def _dataframe_summary(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for col in df.columns:
        out[str(col)] = _series_summary(df[col])
    return out


def dataframe_to_json(df: pd.DataFrame, *, full: bool = False) -> dict[str, Any]:
    """Convert a DataFrame to a JSON-safe dict, truncating long frames unless ``full``."""
    if not full and len(df) > TRUNCATION_THRESHOLD:
        return {
            "truncated": True,
            "total_rows": int(len(df)),
            "columns": [str(c) for c in df.columns],
            "summary": _dataframe_summary(df),
            "head": _dataframe_payload(df.head(HEAD_TAIL_ROWS)),
            "tail": _dataframe_payload(df.tail(HEAD_TAIL_ROWS)),
        }
    return _dataframe_payload(df)


def to_json(value: Any, *, full: bool = False) -> Any:
    """Top-level dispatcher: convert anything (pandas or primitive) to JSON-safe form."""
    if isinstance(value, pd.DataFrame):
        return dataframe_to_json(value, full=full)
    if isinstance(value, pd.Series):
        return series_to_json(value, full=full)
    if isinstance(value, dict):
        return {str(k): to_json(v, full=full) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v, full=full) for v in value]
    return value_to_json(value)
