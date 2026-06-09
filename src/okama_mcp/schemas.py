"""Pydantic v2 input contracts for okama-mcp tools.

Every MCP tool that does non-trivial work accepts a typed spec object instead of
a sprawl of parameters. That gives the LLM a single, well-described shape to
fill in and gives us one place to validate (weights sum to 1, scenarios capped,
cashflow types discriminated, etc.) before we ever touch okama.

The discriminated union ``CashflowSpec`` mirrors the five strategy classes in
``okama.portfolios.cashflow_strategies``: IndexationStrategy, PercentageStrategy,
TimeSeriesStrategy, VanguardDynamicSpending, CutWithdrawalsIfDrawdown.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

# ---------------------------------------------------------------------------
# Common literals
# ---------------------------------------------------------------------------

RebalancingPeriod = Literal["month", "quarter", "half-year", "year", "none"]
CashflowFrequency = Literal["month", "quarter", "half-year", "year"]
Distribution = Literal["norm", "lognorm", "t"]


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


class RebalanceSpec(BaseModel):
    """Rebalancing strategy, mirrors ``okama.Rebalance``.

    Rebalancing happens at predetermined ``period`` intervals; optionally only
    when an asset weight drifts beyond ``abs_deviation`` / ``rel_deviation``
    thresholds (okama ignores a threshold set to None).
    """

    model_config = ConfigDict(extra="forbid")

    period: RebalancingPeriod = Field(
        default="year",
        description="Rebalancing frequency; 'none' means weights are never rebalanced",
    )
    abs_deviation: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="Max allowed |actual_weight - target_weight| before rebalancing; None to ignore",
    )
    rel_deviation: float | None = Field(
        default=None,
        gt=0,
        description="Max allowed |actual_weight / target_weight - 1| before rebalancing; None to ignore",
    )


class PortfolioSpec(BaseModel):
    """Specification of an investment portfolio passed to okama.Portfolio."""

    model_config = ConfigDict(extra="forbid")

    assets: list[Union[str, "PortfolioSpec"]] = Field(  # noqa: UP007, UP037 — self-reference
        min_length=1,
        description=(
            "Assets: each entry is a ticker string (e.g. 'GLD.US') OR a nested "
            "portfolio object (same shape as this spec) used as a single component."
        ),
    )
    weights: list[float] | None = Field(
        default=None,
        description="Asset weights, must sum to 1.0. If omitted, okama uses equal weights.",
    )
    ccy: str = Field(default="USD", description="Base currency for portfolio metrics")
    first_date: str | None = Field(default=None, description="ISO YYYY-MM start date (inclusive)")
    last_date: str | None = Field(default=None, description="ISO YYYY-MM end date (inclusive)")
    rebalancing_strategy: RebalanceSpec = Field(
        default_factory=RebalanceSpec,
        description="Rebalancing strategy (period and optional deviation thresholds)",
    )
    inflation: bool = Field(default=True, description="Include inflation series (limits date range by ~1 month)")
    symbol: str | None = Field(default=None, description="Optional portfolio label, e.g. 'gold_re.PF'")

    @model_validator(mode="after")
    def _validate_weights(self) -> PortfolioSpec:
        if self.weights is None:
            return self
        if len(self.weights) != len(self.assets):
            raise ValueError("weights must have the same length as assets")
        if any(w < 0 for w in self.weights):
            raise ValueError("weights must be non-negative")
        total = sum(self.weights)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1.0 (got {total})")
        return self


PortfolioSpec.model_rebuild()


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------


class MCSpec(BaseModel):
    """Monte Carlo simulation parameters."""

    model_config = ConfigDict(extra="forbid")

    distribution: Distribution = "norm"
    period_years: int = Field(default=25, ge=1, le=200, description="Forecast horizon in years")
    scenarios: int = Field(default=500, ge=1, le=5000, description="Number of Monte Carlo paths")
    percentiles: list[int] = Field(
        default_factory=lambda: [5, 50, 95],
        description="Percentiles (0..100) reported for the wealth distribution",
    )
    random_seed: int | None = Field(default=None, description="Optional seed for reproducibility")

    @model_validator(mode="after")
    def _validate_percentiles(self) -> MCSpec:
        if not self.percentiles:
            raise ValueError("percentiles must be non-empty")
        for p in self.percentiles:
            if p < 0 or p > 100:
                raise ValueError(f"percentile {p} must be in [0, 100]")
        return self


# ---------------------------------------------------------------------------
# Cash-flow strategies (discriminated union)
# ---------------------------------------------------------------------------


class _CashflowBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_investment: float = Field(gt=0, description="Initial capital (must be positive)")


class IndexationCashflow(_CashflowBase):
    """okama.IndexationStrategy — fixed amount per period, indexed."""

    type: Literal["indexation"] = "indexation"
    frequency: CashflowFrequency
    amount: float = Field(description="Withdrawal (negative) or contribution (positive) per period")
    indexation: Literal["inflation"] | float = Field(
        default="inflation",
        description="'inflation' to track inflation series, or a fixed annual rate (e.g. 0.03)",
    )


class PercentageCashflow(_CashflowBase):
    """okama.PercentageStrategy — withdraw/contribute % of portfolio per period."""

    type: Literal["percentage"] = "percentage"
    frequency: CashflowFrequency
    percentage: float = Field(
        ge=-1.0,
        le=1.0,
        description="Fraction of portfolio per period: negative withdraws, positive contributes",
    )


class TimeSeriesCashflow(_CashflowBase):
    """okama.TimeSeriesStrategy — user-supplied dated cash flows."""

    type: Literal["time_series"] = "time_series"
    events: dict[str, float] = Field(
        description="Mapping of 'YYYY-MM' to signed cash flow amount",
    )


class VanguardDynamicCashflow(_CashflowBase):
    """okama.VanguardDynamicSpending — % withdrawal with year-on-year guard rails."""

    type: Literal["vanguard"] = "vanguard"
    percentage: float = Field(le=0.0, ge=-1.0, description="Annual withdrawal % (must be negative or zero)")
    min_max_annual_withdrawals: tuple[float, float] | None = None
    adjust_min_max: bool = True
    floor_ceiling: tuple[float, float] | list[float] | None = Field(
        default=None,
        description="(floor, ceiling) year-on-year change limits, e.g. (-0.025, 0.05)",
    )
    adjust_floor_ceiling: bool = False
    indexation: Literal["inflation"] | float | None = "inflation"


class CutIfDrawdownCashflow(_CashflowBase):
    """okama.CutWithdrawalsIfDrawdown — cut withdrawals on big drawdowns."""

    type: Literal["cut_if_drawdown"] = "cut_if_drawdown"
    frequency: CashflowFrequency = "year"
    amount: float = Field(description="Base withdrawal (negative) before reduction kicks in")
    indexation: Literal["inflation"] | float | None = "inflation"
    crash_threshold_reduction: list[list[float]] | list[tuple[float, float]] = Field(
        default_factory=lambda: [[0.20, 0.40], [0.50, 1.0]],
        description="[[drawdown_threshold, reduction_fraction], ...] — e.g. [[0.2, 0.4]] cuts 40% if drawdown > 20%",
    )


CashflowSpec = Annotated[
    Union[  # noqa: UP007 — discriminator needs explicit Union
        IndexationCashflow,
        PercentageCashflow,
        TimeSeriesCashflow,
        VanguardDynamicCashflow,
        CutIfDrawdownCashflow,
    ],
    Field(discriminator="type"),
]

CashflowAdapter: TypeAdapter[Any] = TypeAdapter(CashflowSpec)


# ---------------------------------------------------------------------------
# Efficient Frontier
# ---------------------------------------------------------------------------


class FrontierSpec(BaseModel):
    """Specification of a multi-period Efficient Frontier optimisation."""

    model_config = ConfigDict(extra="forbid")

    assets: list[str | PortfolioSpec] = Field(
        min_length=2,
        description=(
            "At least two entries; each is a ticker string OR a nested portfolio "
            "object used as a single component."
        ),
    )
    ccy: str = "USD"
    first_date: str | None = None
    last_date: str | None = None
    bounds: list[list[float]] | None = Field(
        default=None,
        description="Per-asset (min, max) weight bounds, e.g. [[0.0, 0.5], [0.1, 0.3]]",
    )
    n_points: int = Field(default=20, ge=2, le=200, description="Resolution of the EF curve")
    rebalancing_strategy: RebalanceSpec = Field(
        default_factory=RebalanceSpec,
        description="Rebalancing strategy (period and optional deviation thresholds)",
    )
    inflation: bool = False
    full_frontier: bool = True

    @model_validator(mode="after")
    def _validate_bounds(self) -> FrontierSpec:
        if self.bounds is None:
            return self
        if len(self.bounds) != len(self.assets):
            raise ValueError("bounds length must equal assets length")
        for pair in self.bounds:
            if len(pair) != 2:
                raise ValueError("each bound must be a [min, max] pair")
            lo, hi = pair
            if lo < 0 or hi > 1 or lo > hi:
                raise ValueError(f"bound {pair} must satisfy 0 <= min <= max <= 1")
        return self
