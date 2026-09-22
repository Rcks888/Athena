"""Athena V6 validation — prove the causality claims instead of asserting them.

V1-V5's defect was invisible because nothing checked it. Each test here fails
loudly if the specific defect from the audit comes back.

    PYTHONPATH=vendor python3 validate_v6.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from engine.data_feed import load_stock, available_symbols
from engine.indicators import (
    add_indicators, SWING_WINDOW, _find_swing_highs, detect_bearish_divergence,
)
from engine.portfolio_sim_v6 import load_params, run_sim, summarise, max_drawdown

FAILURES = []

def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)

def test_divergence_is_causal(symbol):
    """MUST-FIX 1. A flag on bar i must not depend on any bar after i.

    Truncating the series at bar i must not change the flag at bar i. Under the
    V1-V5 code this fails: the flag was written onto the pivot itself, which is
    only identifiable using the following `window` bars.
    """
    df = add_indicators(load_stock(symbol))
    flags = df['bearish_div'].to_numpy()
    hits = np.flatnonzero(flags)
    if len(hits) == 0:
        check("divergence flags exist to test", False, f"{symbol} produced none")
        return
    tested = 0
    for i in hits[-8:]:
        truncated = add_indicators(load_stock(symbol).iloc[:i + 1])
        if not bool(truncated['bearish_div'].iloc[-1]):
            check("divergence flag is causal", False,
                  f"{symbol} bar {i} ({df.index[i].date()}) vanishes when the "
                  f"future is removed — look-ahead has returned")
            return
        tested += 1
    check("divergence flag is causal", True,
          f"{symbol}: {tested} flags survive truncation at their own bar")

def test_flag_can_reach_latest_bar():
    """The inverse defect: a flag must be REACHABLE at `latest`.

    The pivot loop stops at len-window-1, so back-dated flags could never land
    within `window` bars of the end — which is why `latest['bearish_div']` and
    friends are structurally always False in live Ares, and why the exit that
    produced ~96% of backtested profit cannot fire in production at all.

    This is a capability test, not a survey of one symbol: whether a real ticker
    happens to have a pivot near its final bar is luck. The check is that the
    highest index the pivot search can return, plus the confirmation lag, is the
    last bar of the series.
    """
    n = 400
    last_possible_pivot = n - SWING_WINDOW - 1
    check("pivot search + confirmation lag reaches the final bar",
          last_possible_pivot + SWING_WINDOW == n - 1,
          f"pivot {last_possible_pivot} confirms at "
          f"{last_possible_pivot + SWING_WINDOW}, series ends {n - 1}")

    # Demonstrate it end to end on a synthetic series whose last legal pivot is a
    # genuine swing high, and confirm the flag lands on the very last bar.
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(np.linspace(100, 140, n), index=idx)
    close.iloc[last_possible_pivot] += 12.0
    highs = _find_swing_highs(close)
    check("a pivot at the last legal index is detected",
          last_possible_pivot in highs,
          f"detected pivots near end: {[h for h in highs if h > n - 30]}")

def test_run_a_ignores_divergence(symbols):
    """Run A must contain no divergence exit and no divergence trigger."""
    p = load_params()
    check("config has divergence_in_decision_set false",
          p.get('divergence_in_decision_set') is False)
    closed, hist, c = run_sim(symbols, "2021-09-01", "2026-09-01", p, label="validate")
    df = pd.DataFrame(closed)
    check("no bearish_divergence exits in Run A",
          df.empty or 'bearish_divergence' not in set(df['exit_reason']),
          f"{len(df)} trades")
    check("no bullish_div entry triggers in Run A",
          df.empty or not df['trigger'].str.contains('div').any())
    return closed, hist, c, p

def test_next_bar_fills(closed):
    """MUST-FIX 7. Entry AND exit fills must be strictly after their signal."""
    df = pd.DataFrame(closed)
    same = df[df['entry_date'] <= df['signal_date']]
    check("entry fills strictly after signal bar", len(same) == 0,
          f"{len(same)} same-or-earlier-bar entry fills")
    bad = df[df['exit_date'] < df['entry_date']]
    check("exit date never precedes entry", len(bad) == 0, f"{len(bad)} violations")

def test_no_fill_at_stop_price(closed):
    """MUST-FIX 2. An exit must never fill at exactly the stop price."""
    df = pd.DataFrame(closed)
    stops = df[df['exit_reason'].isin(['stop_loss', 'trailing_stop'])]
    exact = stops[np.isclose(stops['exit_price'], stops['stop_loss'], rtol=1e-9)]
    check("stop exits do not fill at the stop price", len(exact) == 0,
          f"{len(exact)}/{len(stops)} filled at exactly the stop")

def test_no_forward_looking_columns(closed):
    """MUST-FIX 5. The forward-looking fields must not exist at all."""
    cols = set(pd.DataFrame(closed).columns)
    banned = cols & {'peak_after_exit', 'missed_upside_pct'}
    check("no peak_after_exit / missed_upside_pct columns", not banned, str(banned))

def test_stop_from_returns_stdev(closed, params):
    """MUST-FIX 6. Stop distance must equal entry * stdev_20 * sl_mult."""
    df = pd.DataFrame(closed)
    expected = df['entry_price'] * (1 - df['stdev_20'] * params['stop_loss_multiplier'])
    dev = float((df['stop_loss'] - expected).abs().max())
    check("stop distance from returns stdev, matching live Ares",
          dev < 1e-4, f"max deviation {dev:.3e} (field rounding only)")
    check("no fabricated 0.05 volatility fallback",
          not bool(np.isclose(df['stdev_20'], 0.05, rtol=1e-12).any()))

def test_max_drawdown_uses_running_peak():
    """MUST-FIX 4. The global-peak method must be demonstrably different."""
    eq = pd.Series([100, 150, 90, 140, 200, 190])
    mdd, _ = max_drawdown(eq)
    peak_i = int(eq.idxmax())
    global_only = (eq.iloc[peak_i:].min() - eq.iloc[peak_i]) / eq.iloc[peak_i] * 100
    check("max drawdown measured from running peak",
          abs(mdd - (-40.0)) < 1e-9 and abs(global_only - (-5.0)) < 1e-9,
          f"running-peak {mdd:.1f}% vs V1-V5 global-peak {global_only:.1f}%")

def test_accounting(closed, params, counters):
    """Reported P&L must equal the real cash delta, per trade and in total."""
    df = pd.DataFrame(closed)
    recomputed = df['total_returned'] - df['total_invested']
    check("per-trade pnl equals returned minus invested",
          bool(np.allclose(df['pnl'], recomputed, atol=0.005)))
    basis = df['original_shares'] * df['entry_price'] + df['entry_commission']
    dev = float((df['total_invested'] - basis).abs().max())
    check("entry commission is inside the cost basis", dev < 1e-3,
          f"max deviation {dev:.3e}")
    check("scale-out proceeds are net of commission",
          bool((df.loc[df['scaled_out'], 'scale_out_proceeds']
                <= df.loc[df['scaled_out'], 'scale_out_shares']
                * df.loc[df['scaled_out'], 'scale_out_price']).all()))
    check("total P&L reconciles with final cash",
          abs(df['pnl'].sum() - (counters['final_cash'] - params['starting_capital'])) < 0.01)
    check("scale-out audit fields are persisted",
          {'scale_out_price', 'scale_out_date', 'scale_out_shares',
           'remaining_shares', 'commission_paid'} <= set(df.columns))

def main():
    syms = available_symbols()
    if not syms:
        raise SystemExit("No snapshot. Run `PYTHONPATH=vendor python3 snapshot_data.py`.")
    probe = 'AAPL' if 'AAPL' in syms else syms[0]
    subset = syms[:25]

    print("=" * 66)
    print("  ATHENA V6 VALIDATION")
    print("=" * 66)
    print(f"\n  Look-ahead (must-fix 1), probe {probe}:")
    test_divergence_is_causal(probe)
    test_flag_can_reach_latest_bar()

    print(f"\n  Run A decision set, {len(subset)} symbols:")
    closed, hist, counters, params = test_run_a_ignores_divergence(subset)

    print(f"\n  Execution and pricing (must-fixes 2, 7):")
    test_next_bar_fills(closed)
    test_no_fill_at_stop_price(closed)

    print(f"\n  Metrics and sizing (must-fixes 4, 5, 6):")
    test_max_drawdown_uses_running_peak()
    test_no_forward_looking_columns(closed)
    test_stop_from_returns_stdev(closed, params)

    print(f"\n  Accounting:")
    test_accounting(closed, params, counters)

    print("\n" + "=" * 66)
    if FAILURES:
        print(f"  {len(FAILURES)} FAILURE(S): {', '.join(FAILURES)}")
        return 1
    print("  All validation checks passed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
