"""Athena V6 Run A — "as-live". The first honest backtest.

Divergence is removed from the decision set entirely: it contributes to no entry,
no exit and no rejection. That matches what live Ares structurally does today,
because the pivot loop can never flag the latest bar, so all four divergence
reads are permanently False in production. The exit that produced ~96% of V5's
dollar P&L cannot occur live at all, and therefore does not occur here.

NO RE-OPTIMISATION. This run reports what `tp_momentum 0.18` and
`trailing_stop_pct 0.10` actually do. No parameter is varied, and no alternative
is tried. Re-tuning on this window is how the original figure was manufactured.
A future re-fit needs a real holdout — fit 2021-2024, test 2024-2026, report only
the test result — and would open its own sample phase.

Run B (divergence repaired, confirmed at i+5) is out of scope.

    PYTHONPATH=vendor python3 run_backtest_v6.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

import pandas as pd

from engine.data_feed import MANIFEST_PATH
from engine.portfolio_sim_v6 import (
    load_params, run_sim, summarise, yearly_table, exit_reason_table,
    buy_and_hold,
)
from engine.universe import UNIVERSE_A, UNIVERSE_B, KNOWN_UNAVAILABLE

START = "2021-09-01"
END = "2026-09-01"
RESULTS = ROOT / "results"

def _fmt(v):
    return f"{v:,.2f}" if isinstance(v, float) else f"{v}"

def report(name, summary, ytable, etable):
    print(f"\n{'=' * 66}")
    print(f"  {name}")
    print(f"{'=' * 66}")
    print(f"    ${summary['start_capital']:,} -> ${summary['final_equity']:,.2f}"
          f"  ({summary['total_return_pct']:+.2f}%)")
    print(f"    CAGR {summary['cagr_pct']:+.2f}%   "
          f"Max DD {summary['max_drawdown_pct']:.2f}% (running peak)   "
          f"Sharpe {summary['sharpe']:.2f}")
    print(f"    Trades {summary['trades']}   "
          f"Win rate {summary['win_rate_pct']:.1f}%   "
          f"Profit factor {summary['profit_factor']}")
    print(f"    Expectancy ${summary['expectancy_dollars']:+.3f} / trade "
          f"({summary['expectancy_pct']:+.3f}%)")
    print(f"    Gross profit ${summary['gross_profit']:,.2f}   "
          f"Gross loss ${summary['gross_loss']:,.2f}   "
          f"Commissions ${summary['commissions_paid']:,.2f}")
    print(f"    Net P&L ${summary['pnl_total']:+,.2f}   "
          f"P&L excl. commissions ${summary['pnl_excl_commissions']:+,.2f} "
          f"(diagnostic, not a parameter)")
    print(f"    Avg win {summary.get('avg_win_pct', 0):+.2f}%   "
          f"Avg loss {summary.get('avg_loss_pct', 0):+.2f}%   "
          f"Avg hold {summary.get('avg_holding_days', 0):.0f}d")
    print(f"    Symbols {summary['symbols_contributing']}/"
          f"{summary['symbols_requested']} contributing   "
          f"Signals {summary['signals_total']}   "
          f"Filled {summary['entries_filled']}   "
          f"Queued {summary['signals_queued']}")
    print(f"    Refused: no stdev {summary['refused_no_stdev']}, "
          f"size<$20 {summary['refused_too_small']}, "
          f"no next bar {summary['refused_no_next_bar']}")

    print(f"\n    Yearly (drawdown per year, from running peak):")
    print(ytable.to_string(index=False).replace("\n", "\n      ").rjust(6))
    print(f"\n    By exit reason:")
    print(etable.to_string(index=False).replace("\n", "\n      ").rjust(6))

def main():
    params = load_params("strategy_params_v6.json")
    if params.get('divergence_in_decision_set', False):
        raise SystemExit("Run A requires divergence_in_decision_set: false.")

    print("=" * 66)
    print("  ATHENA V6 — RUN A ('as-live', causal)")
    print("=" * 66)
    print(f"  Period            {START} -> {END}")
    print(f"  Universe A        {len(UNIVERSE_A)} symbols")
    print(f"  Universe B        {len(UNIVERSE_B)} symbols (sensitivity)")
    print(f"  Frozen params     tp_momentum {params['tp_momentum']}, "
          f"trailing_stop_pct {params['trailing_stop_pct']}, "
          f"sl_mult {params['stop_loss_multiplier']}")
    print(f"  Friction          {params['slippage_pct'] * 100:.2f}% slippage, "
          f"${params['commission_per_trade']:.2f}/fill, next-bar BOTH sides")
    print(f"  Divergence        REMOVED from decision set (Run A)")
    if KNOWN_UNAVAILABLE:
        print(f"  Excluded          {len(KNOWN_UNAVAILABLE)} symbols "
              f"(no data; see engine/universe.py)")
    if MANIFEST_PATH.exists():
        m = json.loads(MANIFEST_PATH.read_text())
        print(f"  Data snapshot     {m['created_utc']}, "
              f"yfinance {m['yfinance_version']}, "
              f"{m['symbols_snapshotted']}/{m['symbols_attempted']} symbols")

    runs = {}
    for name, universe in (("A_original_130", UNIVERSE_A),
                           ("B_midcap_98", UNIVERSE_B)):
        syms = [s for s in universe if s not in KNOWN_UNAVAILABLE]
        closed, history, counters = run_sim(syms, START, END, params, label=name)
        summary, df, hist = summarise(closed, history, counters, params)
        ytable = yearly_table(df, hist)
        etable = exit_reason_table(df)
        report(f"RUN A / UNIVERSE {name}", summary, ytable, etable)

        df.to_csv(RESULTS / f"v6_runA_{name}_trades.csv", index=False)
        hist.to_csv(RESULTS / f"v6_runA_{name}_equity.csv", index=False)
        ytable.to_csv(RESULTS / f"v6_runA_{name}_yearly.csv", index=False)
        etable.to_csv(RESULTS / f"v6_runA_{name}_exits.csv", index=False)
        runs[name] = summary

    print(f"\n{'=' * 66}")
    print("  BENCHMARKS (same period, same friction)")
    print(f"{'=' * 66}")
    benches = []
    for sym in ("SPY", "QQQ"):
        b = buy_and_hold(sym, START, END, params['starting_capital'],
                         params['slippage_pct'], params['commission_per_trade'])
        if b:
            benches.append(b)
            print(f"    {b['label']:<22} ${b['final_equity']:>10,.2f}  "
                  f"{b['total_return_pct']:+8.2f}%  CAGR {b['cagr_pct']:+7.2f}%  "
                  f"Max DD {b['max_drawdown_pct']:7.2f}%")

    print(f"\n{'=' * 66}")
    print("  RUN A vs BENCHMARK")
    print(f"{'=' * 66}")
    print(f"    {'run':<22} {'final':>12} {'CAGR':>9} {'maxDD':>9} "
          f"{'trades':>7} {'PF':>7}")
    for name, s in runs.items():
        print(f"    {name:<22} {s['final_equity']:>12,.2f} "
              f"{s['cagr_pct']:>8.2f}% {s['max_drawdown_pct']:>8.2f}% "
              f"{s['trades']:>7} {s['profit_factor']:>7}")
    for b in benches:
        print(f"    {b['label']:<22} {b['final_equity']:>12,.2f} "
              f"{b['cagr_pct']:>8.2f}% {b['max_drawdown_pct']:>8.2f}% "
              f"{'-':>7} {'-':>7}")

    out = {'run': 'A_as_live', 'period': [START, END], 'params': params,
           'universes': runs, 'benchmarks': benches,
           'known_unavailable': KNOWN_UNAVAILABLE}
    (RESULTS / "v6_runA_summary.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved results/v6_runA_*.{{csv,json}} (V1-V5 files untouched)")

if __name__ == "__main__":
    main()
