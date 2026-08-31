"""Mechanical gates for portfolio stress testing.

Run these before any episode replay or forward scenario. Each gate exists because
its absence produced a wrong published number once; see SKILL.md for the incidents.

Usage:
    python stress_test.py check SBCB.MOEX OBLG.MOEX ... [--first 2010-02]
    python stress_test.py thresholds --symbols A,B --weights 10,90 --abs 10 --rel 50
    python stress_test.py validate --real A,B --proxy X,Y --weights 10,90 [--last 2026-05] [--ccy RUB]
    python stress_test.py attribute --real A,B --proxy X,Y --weights 10,90 --first 2023-01 --last 2023-12
"""

from __future__ import annotations

import argparse
import os

os.environ.setdefault("MPLBACKEND", "Agg")

import okama as ok  # noqa: E402  # okama imports matplotlib eagerly, so the backend must be set first
import pandas as pd  # noqa: E402


def _months_between(early: pd.Timestamp, late: pd.Timestamp) -> int:
    return (late.year - early.year) * 12 + (late.month - early.month)


def _parse_month(raw: str) -> pd.Period:
    """Parse a month string once, so every entry point agrees on what "2023-01" means."""
    try:
        return pd.Period(raw, freq="M")
    except Exception as exc:  # noqa: BLE001  # pandas raises several unrelated types here
        raise ValueError(f"expected a month like 2023-01, got {raw!r}") from exc


def _parse_weights(raw: str) -> list[float]:
    """Accept either percents (10,25,...) or fractions (0.1,0.25,...)."""
    values = [float(x) for x in raw.split(",")]
    total = sum(values)
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    return [v / total for v in values]


def history_floor(symbols: list[str], requested_first: str | None = None) -> pd.Timestamp:
    """Report each asset's inception and the date that binds the whole basket.

    okama truncates AssetList/Portfolio to the intersection of all series without
    raising or warning: `first_date` is a request, never a guarantee.
    """
    starts = {sym: ok.Asset(sym).first_date for sym in symbols}
    floor = max(starts.values())
    print("history floor:")
    for sym, start in sorted(starts.items(), key=lambda kv: kv[1]):
        mark = "   <-- binds the basket" if start == floor else ""
        print(f"  {sym:<18} from {start.date()}{mark}")
    if requested_first is not None:
        requested = _parse_month(requested_first).to_timestamp()
        if requested < floor:
            lost = _months_between(requested, floor)
            print(
                f"  WARNING: first_date={requested_first} is unreachable. okama will silently "
                f"return {floor.date()} instead — {lost} months shorter than requested."
            )
    return floor


def frozen_runs(symbols: list[str], min_months: int = 3) -> list[tuple[str, str, str, int, float]]:
    """Find runs of an unchanged monthly close: a suspended or blocked instrument.

    A frozen price reads as a flat 0% return and silently biases every window that
    overlaps it. SBCB.MOEX sat at 1055.0 for 22 months after February 2022.
    """
    findings: list[tuple[str, str, str, int, float]] = []
    for sym in symbols:
        series = ok.Asset(sym).close_monthly.dropna()
        run_start = 0
        for i in range(1, len(series) + 1):
            if i < len(series) and series.iloc[i] == series.iloc[i - 1]:
                continue
            run_len = i - run_start
            if run_len >= min_months:
                findings.append(
                    (sym, str(series.index[run_start]), str(series.index[i - 1]), run_len, float(series.iloc[run_start]))
                )
            run_start = i
    print(f"\nfrozen price runs (>= {min_months} months):")
    if not findings:
        print("  none")
    for sym, start, end, length, value in findings:
        print(f"  {sym:<18} {start}..{end}  {length} months at {value}")
    return findings


def binding_thresholds(symbols: list[str], weights: list[float], abs_dev: float, rel_dev: float) -> None:
    """Show which rebalancing threshold binds for each sleeve.

    okama `_check_if_rebalancing_required` combines the two deviations with OR,
    compares strictly (>), and rebalances the WHOLE portfolio when ANY single
    asset breaches. A small volatile sleeve therefore drives the schedule.
    """
    print(f"rebalancing thresholds (abs_deviation={abs_dev:.1%}, rel_deviation={rel_dev:.1%}, combined with OR):")
    for sym, w in zip(symbols, weights, strict=True):
        upper_abs, upper_rel = w + abs_dev, w * (1 + rel_dev)
        lower_abs, lower_rel = w - abs_dev, w * (1 - rel_dev)
        which = "abs" if upper_abs < upper_rel else "rel"
        print(
            f"  {sym:<18} target {w:6.1%}  upper: abs {upper_abs:6.1%} / rel {upper_rel:6.1%}"
            f"  -> binds {which} at {min(upper_abs, upper_rel):.1%}"
            f"   (lower {max(lower_abs, lower_rel):.1%})"
        )
    print("  NB: any one sleeve breaching rebalances the entire portfolio.")


def _wealth(symbols: list[str], ccy: str, first: str | None, last: str | None) -> pd.DataFrame:
    """Wealth indexes for the given symbols only.

    AssetList.wealth_indexes carries an extra inflation column when inflation=True;
    select the requested symbols explicitly instead of iterating over the frame.
    """
    al = ok.AssetList(symbols, ccy=ccy, first_date=first, last_date=last)
    return al.wealth_indexes[symbols]


def _total_return(series: pd.Series) -> float:
    return float(series.iloc[-1] / series.iloc[0] - 1)


def _portfolio(symbols: list[str], weights: list[float], ccy: str, first: str | None, last: str | None,
               reb_period: str, abs_dev: float, rel_dev: float) -> ok.Portfolio:
    return ok.Portfolio(
        symbols,
        weights=weights,
        ccy=ccy,
        first_date=first,
        last_date=last,
        rebalancing_strategy=ok.Rebalance(period=reb_period, abs_deviation=abs_dev, rel_deviation=rel_dev),
    )


def validate_proxy(real: list[str], proxy: list[str], weights: list[float], ccy: str, last: str | None,
                   reb_period: str, abs_dev: float, rel_dev: float) -> None:
    """Compare the proxy against the actual portfolio over their common window.

    A proxy replay without these numbers is not a result. Report the full-window
    figure AND each calendar year: an annual outlier is where the defects hide.
    """
    floor = max(max(ok.Asset(s).first_date for s in real), max(ok.Asset(s).first_date for s in proxy))
    first = str(floor.to_period("M"))
    last = str(_parse_month(last)) if last is not None else None
    pf_real = _portfolio(real, weights, ccy, first, last, reb_period, abs_dev, rel_dev)
    pf_proxy = _portfolio(proxy, weights, ccy, first, last, reb_period, abs_dev, rel_dev)
    wi_real, wi_proxy = pf_real.wealth_index.iloc[:, 0], pf_proxy.wealth_index.iloc[:, 0]
    common = wi_real.index.intersection(wi_proxy.index)
    wi_real, wi_proxy = wi_real[common], wi_proxy[common]

    print(f"requested window: {first}..{last or 'latest'}")
    print(
        f"window okama actually returned: fact {pf_real.first_date.date()}..{pf_real.last_date.date()}, "
        f"proxy {pf_proxy.first_date.date()}..{pf_proxy.last_date.date()}"
    )
    print(f"wealth-index overlap {common[0]}..{common[-1]} (the base point sits one month before the start)")
    print(f"  {'window':<12} {'fact':>10} {'proxy':>10} {'gap, p.p.':>11}")
    rows: list[tuple[str, pd.Series, pd.Series]] = [("full", wi_real, wi_proxy)]
    for year in sorted({p.year for p in common}):
        mask = [p.year == year for p in common]
        sub_real, sub_proxy = wi_real[mask], wi_proxy[mask]
        if len(sub_real) > 1:
            rows.append((str(year), sub_real, sub_proxy))
    for label, sub_real, sub_proxy in rows:
        r_fact, r_proxy = _total_return(sub_real), _total_return(sub_proxy)
        print(f"  {label:<12} {r_fact:9.1%} {r_proxy:9.1%} {(r_proxy - r_fact) * 100:10.2f}")


def attribute_gap(real: list[str], proxy: list[str], weights: list[float], ccy: str, first: str, last: str,
                  reb_period: str, abs_dev: float, rel_dev: float) -> float:
    """Attribute a fact/proxy divergence to named sleeves.

    The per-sleeve contributions must sum to the observed portfolio gap. An
    unexplained residual means the cause has not been found yet — do not accept a
    verbal explanation ("the proxy runs hot") in its place.

    Run this per episode window, not over the full history. Sleeve contributions are
    buy-and-hold while the portfolios rebalance, so on multi-year windows the
    rebalancing path itself lands in the residual and the identity stops being a
    defect signal.
    """
    first, last = str(_parse_month(first)), str(_parse_month(last))
    wi_real = _wealth(real, ccy, first, last)
    wi_proxy = _wealth(proxy, ccy, first, last)
    pf_real = _portfolio(real, weights, ccy, first, last, reb_period, abs_dev, rel_dev)
    pf_proxy = _portfolio(proxy, weights, ccy, first, last, reb_period, abs_dev, rel_dev)
    observed = (_total_return(pf_proxy.wealth_index.iloc[:, 0]) - _total_return(pf_real.wealth_index.iloc[:, 0])) * 100

    print(f"gap attribution, requested {first}..{last}, "
          f"okama returned {pf_real.first_date.date()}..{pf_real.last_date.date()} "
          f"(percentage points of portfolio return)")
    print(f"  {'fact sleeve':<18} {'proxy sleeve':<18} {'fact':>9} {'proxy':>9} {'weight':>8} {'contrib':>9}")
    explained = 0.0
    for r_sym, p_sym, w in zip(real, proxy, weights, strict=True):
        r_ret, p_ret = _total_return(wi_real[r_sym]), _total_return(wi_proxy[p_sym])
        contrib = w * (p_ret - r_ret) * 100
        explained += contrib
        print(f"  {r_sym:<18} {p_sym:<18} {r_ret:8.1%} {p_ret:8.1%} {w:7.1%} {contrib:8.2f}")
    residual = observed - explained
    print(f"  {'':<18} {'':<18} {'':>9} {'':>9} {'observed':>8} {observed:8.2f}")
    print(f"  {'':<18} {'':<18} {'':>9} {'':>9} {'explained':>8} {explained:8.2f}")
    print(f"  {'':<18} {'':<18} {'':>9} {'':>9} {'residual':>8} {residual:8.2f}")
    months = _months_between(_parse_month(first).to_timestamp(), _parse_month(last).to_timestamp())
    if abs(residual) > 0.5:
        if months > 24:
            print(
                f"  NOTE: window spans {months} months. Part of the residual is the rebalancing path, not a data "
                "defect — re-run per calendar year before treating the residual as a finding."
            )
        else:
            print("  WARNING: residual above 0.5 p.p. — the cause is not fully identified. Keep looking.")
    return residual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="history floor + frozen price runs")
    p_check.add_argument("symbols", nargs="+")
    p_check.add_argument("--first", default=None, help="the first_date you intended to use")
    p_check.add_argument("--min-months", type=int, default=3)

    p_thr = sub.add_parser("thresholds", help="which rebalancing threshold binds per sleeve")
    p_thr.add_argument("--symbols", required=True)
    p_thr.add_argument("--weights", required=True)
    p_thr.add_argument("--abs", dest="abs_dev", type=float, required=True, help="abs_deviation in percent")
    p_thr.add_argument("--rel", dest="rel_dev", type=float, required=True, help="rel_deviation in percent")

    for name, helptext in (("validate", "compare proxy vs fact on the overlap"),
                           ("attribute", "attribute a fact/proxy gap to sleeves")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--real", required=True)
        p.add_argument("--proxy", required=True)
        p.add_argument("--weights", required=True)
        p.add_argument("--ccy", default="RUB")
        p.add_argument("--reb-period", default="year")
        p.add_argument("--abs", dest="abs_dev", type=float, default=100.0)
        p.add_argument("--rel", dest="rel_dev", type=float, default=100.0)
        p.add_argument("--last", default=None, help="last month, e.g. 2026-05")
        if name == "attribute":
            p.add_argument("--first", required=True)

    args = parser.parse_args()

    if args.command == "check":
        history_floor(args.symbols, args.first)
        frozen_runs(args.symbols, args.min_months)
        return 0

    if args.command == "thresholds":
        symbols = args.symbols.split(",")
        binding_thresholds(symbols, _parse_weights(args.weights), args.abs_dev / 100, args.rel_dev / 100)
        return 0

    real, proxy = args.real.split(","), args.proxy.split(",")
    weights = _parse_weights(args.weights)
    if len(real) != len(proxy) or len(real) != len(weights):
        parser.error("--real, --proxy and --weights must have the same length (sleeves are matched pairwise)")
    if args.command == "validate":
        validate_proxy(real, proxy, weights, args.ccy, args.last, args.reb_period, args.abs_dev / 100, args.rel_dev / 100)
    else:
        if args.last is None:
            parser.error("attribute needs an explicit --last: attribution is per episode window")
        attribute_gap(real, proxy, weights, args.ccy, args.first, args.last,
                      args.reb_period, args.abs_dev / 100, args.rel_dev / 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
