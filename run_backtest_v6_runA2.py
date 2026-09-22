"""Athena V6 Run A' — the first backtest that runs live Ares' own strategy code.

Run A was causal but measured a hand-written reimplementation of the strategy that
had drifted from live in ~30 ways. Run A' imports live's predicates through a
byte-identical, checksum-guarded copy of `Ares/engine/signals.py`, so entry logic
is executed rather than re-expressed. `engine/live_adapter.py` hands those
predicates `df.iloc[:i+1]`, making causality a property of the data they receive
instead of a promise about our code.

WHAT IS NOT COMPARABLE TO RUN A. Live sizes positions at a static $149 and does not
compound. Run A compounded. Run A's CAGR and Run A''s therefore describe different
money, and the summary records `return_basis: fixed_stake_non_compounding` so the
two can never be tabulated as like for like. The primary figures here are total
dollar P&L and return on the notional $1,000.

NO RE-OPTIMISATION. This reports what `tp_momentum 0.18` and
`trailing_stop_pct 0.10` actually do when live's real entry rules select the trades.
No parameter is varied. The expectation set out in advance was that Run A' would
differ substantially in BOTH directions, because correcting a mismatch does not
improve a strategy, it selects a different population. A better number here is not
evidence of success and a worse one is not evidence of failure.

Run B (divergence repaired, confirmed at i+5) remains out of scope.

    PYTHONPATH=vendor python3 run_backtest_v6_runA2.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

import pandas as pd

from engine import parity
from engine.data_feed import MANIFEST_PATH
from engine.portfolio_sim_v6 import (
    MODELLED_BROKER_CONSTRAINTS, REPRODUCED_LIVE_DEFECTS, buy_and_hold,
    exit_reason_table, load_params, run_sim, static_position_size, summarise,
    yearly_table,
)
from engine.universe import KNOWN_UNAVAILABLE, UNIVERSE_A, UNIVERSE_B

START = "2021-09-01"
END = "2026-09-01"
RESULTS = ROOT / "results"
TAG = "v6_runA2"

def report(name, summary, ytable, etable, openpos):
    print(f"\n{'=' * 70}")
    print(f"  {name}")
    print(f"{'=' * 70}")
    print(f"    ${summary['start_capital']:,} -> ${summary['final_equity']:,.2f}"
          f"  ({summary['total_return_pct']:+.2f}%)   "
          f"[fixed ${summary['static_stake']:.0f} stake, NON-compounding]")
    print(f"    CAGR suppressed: {summary['cagr_suppressed_reason']}")
    print(f"    Max DD {summary['max_drawdown_pct']:.2f}% (running peak)"
          f" on {summary['max_drawdown_date']}   Sharpe {summary['sharpe']:.2f}")

    # THE HEADLINE. Gross edge, friction, what survives — as three lines, because
    # "the strategy loses money" hides that Universe A has a positive gross edge
    # which the fixed commission then consumes.
    pct = summary['commission_pct_of_gross_profit']
    print(f"\n    --- GROSS vs COMMISSION vs NET ---")
    print(f"    Gross P&L before commission   ${summary['gross_pnl_before_commission']:+,.2f}"
          f"   ({'GROSS-PROFITABLE' if summary['gross_profitable'] else 'gross-negative'})")
    # Scoped to CLOSED trades so it reconciles against gross and net on the same
    # line. `commissions_paid` below is cash-scoped and larger, because it also
    # includes entry and scale-out commissions on positions still open. Two correct
    # figures that look like one figure disagreeing with itself, so both are named.
    print(f"    Commission (closed trades)    ${-summary['commission_total']:+,.2f}"
          f"   (${summary['commission_per_trade']:.2f}/trade)")
    print(f"    Net P&L after commission      ${summary['net_pnl_after_commission']:+,.2f}")
    if pct is not None:
        print(f"    Commission as % of gross profit  {pct:.1f}%"
              f"   <- gross edge ${summary['gross_edge_per_trade']:.2f}/trade vs "
              f"${summary['commission_per_trade']:.2f} cost")
    else:
        print(f"    Commission as % of gross profit  n/a (gross P&L is negative, so "
              f"the ratio would invert its meaning)")
    print(f"    Win rate before commission {summary['win_rate_before_commission_pct']:.1f}% "
          f"vs {summary['win_rate_pct']:.1f}% after")
    print(f"    ---------------------------------\n")
    print(f"    Trades {summary['trades']} closed   "
          f"Win rate {summary['win_rate_pct']:.1f}%   "
          f"Profit factor {summary['profit_factor']}")
    print(f"    Expectancy ${summary['expectancy_dollars']:+.3f} / trade "
          f"({summary['expectancy_pct']:+.3f}%)")
    print(f"    Gross profit ${summary['gross_profit']:,.2f}   "
          f"Gross loss ${summary['gross_loss']:,.2f}   "
          f"Cash commissions ${summary['commissions_paid']:,.2f} "
          f"(incl. ${summary['commissions_paid'] - summary['commission_total']:,.2f} "
          f"on still-open positions)")
    print(f"    Net realised P&L ${summary['pnl_total']:+,.2f}")
    print(f"    Avg win {summary.get('avg_win_pct', 0):+.2f}%   "
          f"Avg loss {summary.get('avg_loss_pct', 0):+.2f}%   "
          f"Avg hold {summary.get('avg_holding_days', 0):.0f}d   "
          f"Scaled out {summary['scaled_out_count']}")
    print(f"    Symbols {summary['symbols_contributing']}/"
          f"{summary['symbols_requested']}   "
          f"Signals {summary['signals_total']}   "
          f"Filled {summary['entries_filled']}   "
          f"Queued {summary['signals_queued']}   "
          f"From queue {summary['entries_from_queue']}")
    print(f"    Queue: promotions attempted {summary['queue_promotions_attempted']}, "
          f"rejected on drift {summary['queue_rejected_drift']}, "
          f"expired {summary['queue_expired_age']}, "
          f"evicted {summary['queue_evicted_size']}")
    print(f"    Pending: expired {summary['pending_expired']}, "
          f"attempts exhausted {summary['pending_fill_attempts_exhausted']}, "
          f"already held {summary['pending_dropped_already_held']}, "
          f"no slot {summary['pending_dropped_no_slot']}")
    print(f"    BROKER FUNDING: {summary['refused_insufficient_cash']} entries "
          f"refused for insufficient cash (live checks no balance; IBKR would "
          f"reject)")
    print(f"    Equity marks carried forward (no bar that day): "
          f"{summary['equity_marks_carried_forward']}")
    print(f"    stdev_20 fallback fills {summary['stdev_fallback_trades']} "
          f"(live substitutes 0.05; P&L ${summary['stdev_fallback_pnl']:+,.2f})")

    # No end-of-sim liquidation: live has no analogue, so these stay open and are
    # excluded from every trade statistic above.
    print(f"    Still open at {END}: {summary['open_positions']} positions, "
          f"market value ${summary['open_market_value']:,.2f}, "
          f"unrealised ${summary['unrealised_pnl']:+,.2f} "
          f"(excluded from trade stats, included in equity)")
    if openpos:
        for p in openpos:
            print(f"        {p['symbol']:<6} {p['strategy']:<20} "
                  f"entered {p['entry_date']}  "
                  f"unrealised ${p['unrealised_pnl']:+8.2f}")

    print(f"\n    Yearly (drawdown per year, from running peak):")
    print("      " + ytable.to_string(index=False).replace("\n", "\n      "))
    print(f"\n    By exit reason (share of GROSS flow, not of near-zero net):")
    print("      " + etable.to_string(index=False).replace("\n", "\n      "))

def main():
    params = load_params("strategy_params_v6.json")
    if params.get('divergence_in_decision_set', False):
        raise SystemExit(
            "Run A' requires divergence_in_decision_set: false. Live's pivot loop "
            "cannot flag the latest bar, so production never sees a divergence; "
            "enabling it here would fire exits live is incapable of firing. "
            "Repairing divergence is Run B, which is out of scope."
        )

    print("=" * 70)
    print("  ATHENA V6 — RUN A'  (live predicates, causal, fixed-stake)")
    print("=" * 70)
    print(f"  Period            {START} -> {END}")
    print(f"  Universe A        {len(UNIVERSE_A)} symbols")
    print(f"  Universe B        {len(UNIVERSE_B)} symbols (sensitivity)")
    print(f"  Entry logic       live Ares engine/signals.py, CALLED not re-expressed")
    print(f"  Parity guard      md5 {parity.assert_signals_parity()} verified")
    print(f"  Sizing            static ${static_position_size(params):.2f} per "
          f"position, non-compounding (live tracker.py:123)")
    print(f"  Frozen params     tp_momentum {params['tp_momentum']}, "
          f"trailing_stop_pct {params['trailing_stop_pct']}, "
          f"sl_mult {params['stop_loss_multiplier']}")
    print(f"  Friction          {params['slippage_pct'] * 100:.2f}% slippage, "
          f"${params['commission_per_trade']:.2f}/fill, next-bar BOTH sides")
    print(f"  Divergence        REMOVED from decision set (as production)")
    print(f"  End of period     positions left OPEN (live has no liquidation)")
    print(f"  Broker funding    entries REFUSED when cash < stake + commission")
    print(f"                    (live checks no balance and overdrew; IBKR enforces "
          f"what live omits)")
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
        closed, history, counters, openpos = run_sim(syms, START, END, params,
                                                    label=name)
        summary, df, hist = summarise(closed, history, counters, params, openpos)
        ytable = yearly_table(df, hist)
        etable = exit_reason_table(df)
        report(f"RUN A' / UNIVERSE {name}", summary, ytable, etable, openpos)

        df.to_csv(RESULTS / f"{TAG}_{name}_trades.csv", index=False)
        hist.to_csv(RESULTS / f"{TAG}_{name}_equity.csv", index=False)
        ytable.to_csv(RESULTS / f"{TAG}_{name}_yearly.csv", index=False)
        etable.to_csv(RESULTS / f"{TAG}_{name}_exits.csv", index=False)
        pd.DataFrame(openpos).to_csv(RESULTS / f"{TAG}_{name}_open.csv", index=False)
        runs[name] = summary

    print(f"\n{'=' * 70}")
    print("  BENCHMARKS (same period, same friction)")
    print(f"{'=' * 70}")
    benches = []
    for sym in ("SPY", "QQQ"):
        b = buy_and_hold(sym, START, END, params['starting_capital'],
                         params['slippage_pct'], params['commission_per_trade'])
        if b:
            benches.append(b)
            print(f"    {b['label']:<22} ${b['final_equity']:>10,.2f}  "
                  f"{b['total_return_pct']:+8.2f}%  CAGR {b['cagr_pct']:+7.2f}%  "
                  f"Max DD {b['max_drawdown_pct']:7.2f}%")
    print("    Note: buy-and-hold deploys the full $1,000 and compounds. Run A' "
          "risks at\n          most 5 x $149 = $745 and never reinvests, so the "
          "comparison is of\n          strategies, not of equal capital at risk.")

    print(f"\n{'=' * 70}")
    print("  RUN A' vs BENCHMARK")
    print(f"{'=' * 70}")
    print(f"    {'run':<22} {'final':>12} {'totalRet':>10} {'maxDD':>9} "
          f"{'trades':>7} {'PF':>7} {'gross':>10} {'comm':>9}")
    for name, s in runs.items():
        print(f"    {name:<22} {s['final_equity']:>12,.2f} "
              f"{s['total_return_pct']:>9.2f}% {s['max_drawdown_pct']:>8.2f}% "
              f"{s['trades']:>7} {s['profit_factor']:>7} "
              f"{s['gross_pnl_before_commission']:>+10.2f} "
              f"{-s['commission_total']:>+9.2f}")
    for b in benches:
        print(f"    {b['label']:<22} {b['final_equity']:>12,.2f} "
              f"{b['total_return_pct']:>9.2f}% {b['max_drawdown_pct']:>8.2f}% "
              f"{'-':>7} {'-':>7} {'-':>10} {'-':>9}")

    out = {
        'run': "A'_live_predicates",
        'period': [START, END],
        'return_basis': 'fixed_stake_non_compounding',
        'comparable_to_run_a': False,
        'comparability_note': (
            "Run A compounded position sizing; live and Run A' use a static $149 "
            "stake. Returns describe different money and must not be tabulated "
            "together."
        ),
        'live_signals_md5': parity.LIVE_SIGNALS_MD5,
        'reproduced_live_defects': REPRODUCED_LIVE_DEFECTS,
        'modelled_broker_constraints': MODELLED_BROKER_CONSTRAINTS,
        'params': params,
        'universes': runs,
        'benchmarks': benches,
        'known_unavailable': KNOWN_UNAVAILABLE,
    }
    (RESULTS / f"{TAG}_summary.json").write_text(
        json.dumps(out, indent=2, default=str))
    print(f"\n  Saved results/{TAG}_*.{{csv,json}} "
          f"(Run A and V1-V5 files untouched)")

if __name__ == "__main__":
    main()
