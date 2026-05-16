"""Tests for okama_mcp.serialization — pandas → JSON-safe dict conversion."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from okama_mcp import serialization as ser


class TestScalarSerialization:
    def test_int_passes_through(self) -> None:
        assert ser.value_to_json(42) == 42

    def test_float_is_rounded_to_six_decimals(self) -> None:
        assert ser.value_to_json(0.123456789) == 0.123457

    def test_nan_becomes_none(self) -> None:
        assert ser.value_to_json(float("nan")) is None

    def test_inf_becomes_none(self) -> None:
        assert ser.value_to_json(math.inf) is None
        assert ser.value_to_json(-math.inf) is None

    def test_numpy_float_handled(self) -> None:
        assert ser.value_to_json(np.float64(1.5)) == 1.5

    def test_pandas_timestamp_becomes_iso_string(self) -> None:
        ts = pd.Timestamp("2024-03-15")
        assert ser.value_to_json(ts) == "2024-03-15"

    def test_pandas_period_becomes_iso_string(self) -> None:
        p = pd.Period("2024-03", freq="M")
        assert ser.value_to_json(p) == "2024-03-31"


class TestSeriesSerialization:
    def test_empty_series(self) -> None:
        s = pd.Series([], dtype=float, name="empty")
        out = ser.series_to_json(s)
        assert out == {"name": "empty", "index": [], "values": []}

    def test_series_with_period_index(self) -> None:
        idx = pd.period_range("2024-01", periods=3, freq="M")
        s = pd.Series([1.0, 2.0, 3.0], index=idx, name="ror")
        out = ser.series_to_json(s)
        assert out["name"] == "ror"
        assert out["index"] == ["2024-01-31", "2024-02-29", "2024-03-31"]
        assert out["values"] == [1.0, 2.0, 3.0]

    def test_series_with_datetime_index(self) -> None:
        idx = pd.date_range("2024-01-31", periods=2, freq="D")
        s = pd.Series([1.0, 2.0], index=idx)
        out = ser.series_to_json(s)
        assert out["index"] == ["2024-01-31", "2024-02-01"]

    def test_series_nan_becomes_none(self) -> None:
        s = pd.Series([1.0, float("nan"), 3.0])
        out = ser.series_to_json(s)
        assert out["values"] == [1.0, None, 3.0]


class TestSeriesTruncation:
    def test_short_series_is_not_truncated(self) -> None:
        idx = pd.period_range("2020-01", periods=100, freq="M")
        s = pd.Series(range(100), index=idx, dtype=float, name="x")
        out = ser.series_to_json(s)
        assert "truncated" not in out or out.get("truncated") is False

    def test_long_series_is_truncated_by_default(self) -> None:
        idx = pd.period_range("1990-01", periods=600, freq="M")
        s = pd.Series(range(600), index=idx, dtype=float, name="long")
        out = ser.series_to_json(s)
        assert out["truncated"] is True
        assert out["total_rows"] == 600
        assert len(out["head"]["values"]) == 50
        assert len(out["tail"]["values"]) == 50
        assert "summary" in out
        assert out["summary"]["count"] == 600

    def test_long_series_full_disables_truncation(self) -> None:
        idx = pd.period_range("1990-01", periods=600, freq="M")
        s = pd.Series(range(600), index=idx, dtype=float)
        out = ser.series_to_json(s, full=True)
        assert "truncated" not in out or out.get("truncated") is False
        assert len(out["values"]) == 600


class TestDataFrameSerialization:
    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame(columns=["a", "b"])
        out = ser.dataframe_to_json(df)
        assert out == {"columns": ["a", "b"], "index": [], "data": []}

    def test_dataframe_with_period_index(self) -> None:
        idx = pd.period_range("2024-01", periods=2, freq="M")
        df = pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]}, index=idx)
        out = ser.dataframe_to_json(df)
        assert out["columns"] == ["x", "y"]
        assert out["index"] == ["2024-01-31", "2024-02-29"]
        assert out["data"] == [[1.0, 3.0], [2.0, 4.0]]

    def test_dataframe_nan_becomes_none(self) -> None:
        df = pd.DataFrame({"x": [1.0, float("nan")]})
        out = ser.dataframe_to_json(df)
        assert out["data"] == [[1.0], [None]]

    def test_long_dataframe_is_truncated(self) -> None:
        idx = pd.period_range("1990-01", periods=600, freq="M")
        df = pd.DataFrame({"x": range(600)}, index=idx)
        out = ser.dataframe_to_json(df)
        assert out["truncated"] is True
        assert out["total_rows"] == 600
        assert len(out["head"]["data"]) == 50
        assert len(out["tail"]["data"]) == 50


def test_to_json_dispatches_on_type() -> None:
    assert ser.to_json(1) == 1
    assert ser.to_json(pd.Series([1.0]))["values"] == [1.0]
    assert ser.to_json(pd.DataFrame({"x": [1.0]}))["columns"] == ["x"]


@pytest.mark.parametrize(
    "val,expected",
    [
        (None, None),
        ("hello", "hello"),
        (True, True),
        ([1, 2, 3], [1, 2, 3]),
    ],
)
def test_to_json_passthrough_primitives(val: object, expected: object) -> None:
    assert ser.to_json(val) == expected
