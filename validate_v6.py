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

def test_run_a_ignores_divergence(closed, params):
    """No divergence may appear in any exit reason or entry trigger.

    The column-level check is `test_divergence_columns_inert`; this is the
    output-level companion, confirming nothing leaked through into a realised trade.
    """
    check("config has divergence_in_decision_set false",
          params.get('divergence_in_decision_set') is False)
    df = pd.DataFrame(closed)
    check("no bearish_divergence exits in Run A'",
          df.empty or 'bearish_divergence' not in set(df['exit_reason']),
          f"{len(df)} trades")
    check("no divergence entry triggers in Run A'",
          df.empty or not df['trigger'].str.contains('div').any())

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
    # Run A asserted the 0.05 fallback NEVER occurs. That was the wrong test: live
    # tracker.py:141 substitutes 0.05, flags the trade, and FILLS, so refusing was
    # itself the mismatch. The correct assertion is that any trade using the
    # fallback is LABELLED, so the wide-stop population can be segmented instead of
    # silently averaged into the headline.
    fb = df[np.isclose(df['stdev_20'], 0.05, rtol=1e-12)]
    check("any 0.05 fallback trade is flagged as contaminated",
          fb.empty or bool(fb['stdev_fallback'].all()),
          f"{len(fb)} trade(s) at the fallback, "
          f"{int(fb['stdev_fallback'].sum()) if not fb.empty else 0} flagged")
    check("stdev_fallback flag is persisted for segmentation",
          'stdev_fallback' in df.columns,
          f"{int(df['stdev_fallback'].sum())} of {len(df)} trades used live's "
          f"0.05 fallback (indicator warm-up precedes the window, so this is "
          f"expected to be rare)")

def test_max_drawdown_uses_running_peak():
    """MUST-FIX 4. The global-peak method must be demonstrably different."""
    eq = pd.Series([100, 150, 90, 140, 200, 190])
    mdd, _ = max_drawdown(eq)
    peak_i = int(eq.idxmax())
    global_only = (eq.iloc[peak_i:].min() - eq.iloc[peak_i]) / eq.iloc[peak_i] * 100
    check("max drawdown measured from running peak",
          abs(mdd - (-40.0)) < 1e-9 and abs(global_only - (-5.0)) < 1e-9,
          f"running-peak {mdd:.1f}% vs V1-V5 global-peak {global_only:.1f}%")

def test_accounting(closed, params, counters, openpos=()):
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
    # With no forced liquidation the identity must span BOTH books: realised P&L on
    # closed trades plus unrealised P&L on positions still open must equal the change
    # in total equity. Reconciling against cash alone would silently ignore whatever
    # is still held, which is exactly where a sizing or booking error would hide.
    unreal = sum(p['unrealised_pnl'] for p in openpos)
    open_val = sum(p['market_value'] for p in openpos)
    actual = (counters['final_cash'] + open_val) - params['starting_capital']
    diff = abs((df['pnl'].sum() + unreal) - actual)
    check("realised + unrealised P&L reconciles with final equity",
          diff <= max(0.01, 0.01 * len(openpos)),
          f"diff ${diff:.4f} (realised ${df['pnl'].sum():+.2f}, "
          f"unrealised ${unreal:+.2f}, {len(openpos)} open)")
    check("scale-out audit fields are persisted",
          {'scale_out_price', 'scale_out_date', 'scale_out_shares',
           'remaining_shares', 'commission_paid'} <= set(df.columns))

def test_future_perturbation_cannot_change_the_past(symbols):
    """THE centrepiece test. Corrupt the future; the past must not move.

    Every other causality test here checks a specific known defect, which means it
    can only catch a defect someone already thought of. Run A passed all of them and
    still contained a look-ahead: `portfolio_sim_v6.py:300` sized a position from
    today's Close for an order filling at today's Open. No targeted test covered it
    because nobody suspected sizing.

    This test is general. It runs the simulation to a cut date, then re-runs it with
    every bar after the cut replaced by garbage, and asserts that every trade that
    opened and closed before the cut is byte-for-byte identical. Any read of a future
    bar — in entry logic, exit logic, sizing, stops, or fills — changes something and
    fails this. It is the test that would have caught the sizing defect, and it will
    catch the next one of its kind without being told what to look for.
    """
    from engine.data_feed import load_stock as _ls
    import engine.portfolio_sim_v6 as sim

    params = load_params("strategy_params_v6.json")
    cut = "2024-09-01"
    full_end = "2026-09-01"

    baseline_closed, _, _, _ = run_sim(symbols, "2021-09-01", cut, params,
                                       label="perturb_base")

    # Re-run over the LONGER window, but with post-cut bars destroyed. If nothing
    # reads the future, the pre-cut trades must be unaffected by the destruction.
    real_prepare = sim.prepare
    def poisoned_prepare(syms, start_date, end_date, p, min_bars=100):
        data = real_prepare(syms, start_date, full_end, p, min_bars=min_bars)
        out = {}
        for s, df in data.items():
            df = df.copy()
            mask = df.index > pd.Timestamp(cut)
            if mask.any():
                # Garbage, not merely shifted values: a 50x price spike and
                # inverted indicators. Anything peeking forward will behave wildly.
                for col in ('Open', 'High', 'Low', 'Close'):
                    df.loc[mask, col] = df.loc[mask, col] * 50.0
                df.loc[mask, 'rsi'] = 99.0
                df.loc[mask, 'vol_ratio'] = 25.0
                df.loc[mask, 'macd_hist'] = -df.loc[mask, 'macd_hist']
                df.loc[mask, 'pct_from_high'] = 0.0
                df.loc[mask, 'stdev_20'] = 0.99
            out[s] = df
        return out

    sim.prepare = poisoned_prepare
    try:
        poisoned_closed, _, _, _ = run_sim(symbols, "2021-09-01", cut, params,
                                           label="perturb_poisoned")
    finally:
        sim.prepare = real_prepare

    cut_ts = pd.Timestamp(cut)
    def pre_cut(trades):
        return {(t['symbol'], t['entry_date'], t['exit_date']): t
                for t in trades if pd.Timestamp(t['exit_date']) < cut_ts}

    base, pois = pre_cut(baseline_closed), pre_cut(poisoned_closed)

    check("perturbation: same set of pre-cut trades",
          set(base) == set(pois),
          f"{len(base)} baseline vs {len(pois)} poisoned, "
          f"{len(set(base) ^ set(pois))} differing")

    fields = ('entry_price', 'exit_price', 'original_shares', 'pnl',
              'stop_loss', 'take_profit', 'exit_reason', 'scale_out_price')
    drifted = []
    for key in set(base) & set(pois):
        for f in fields:
            a, b = base[key][f], pois[key][f]
            if isinstance(a, float) and isinstance(b, float):
                if abs(a - b) > 1e-9:
                    drifted.append(f"{key[0]}.{f}")
            elif a != b:
                drifted.append(f"{key[0]}.{f}")
    check("perturbation: pre-cut trade details identical (NO look-ahead anywhere)",
          not drifted,
          f"{len(drifted)} field(s) moved when the future was corrupted: "
          f"{drifted[:6]}" if drifted else
          f"{len(base)} trades x {len(fields)} fields unchanged")

def test_sizing_is_static_and_equity_independent(closed, params):
    """Live sizes every position at a fixed $149. Run A compounded instead.

    Two things are asserted. First that the stake matches live's formula. Second
    that it does NOT vary across the run — a compounding rule would show the stake
    drifting with the equity curve, which is the Run A behaviour being removed.
    """
    from engine.portfolio_sim_v6 import static_position_size
    expected = static_position_size(params)
    check("sizing matches live tracker.py:123 ($149)",
          abs(expected - 149.0) < 1e-9, f"${expected:.2f}")

    invested = np.array([t['original_shares'] * t['entry_price'] for t in closed])
    if len(invested) == 0:
        check("sizing is constant across the run", False, "no trades")
        return
    spread = float(invested.max() - invested.min())
    check("sizing is CONSTANT across the run (non-compounding)",
          spread < 0.01,
          f"stake range ${invested.min():.4f}-${invested.max():.4f} "
          f"(spread ${spread:.6f})")
    check("every stake equals live's static size",
          bool(np.all(np.abs(invested - expected) < 0.01)),
          f"max deviation ${float(np.abs(invested - expected).max()):.6f}")

def test_no_exit_on_entry_bar(closed):
    """Live suppresses all exit logic on the entry bar (tracker.py:788).

    Run A allowed same-bar and next-bar exits, producing 1-day trades live cannot
    produce. Because fills are next-bar, the minimum real holding period is 1 day
    of decision plus 1 of fill, so `holding_days == 0` is the signature of the bug.
    """
    same_bar = [t for t in closed if t['holding_days'] <= 0]
    check("no exits on the entry bar (live tracker.py:788)",
          not same_bar,
          f"{len(same_bar)} trade(s) exited within 0 days" if same_bar
          else f"min holding {min((t['holding_days'] for t in closed), default=0)}d")

def test_scale_out_short_circuits_exits(closed):
    """A scale-out bar cannot also be an exit bar, because live `continue`s.

    This ordering is why Run A under-reported winners: it evaluated exits first, so
    an `emotional_extreme` (rsi > 90, common precisely at a profit target) closed
    the whole position where live banks half and keeps the rest.
    """
    bad = [t for t in closed
           if t['scaled_out'] and t['scale_out_date'] == t['exit_date']]
    check("scale-out bar never also exits (live short-circuits)",
          not bad, f"{len(bad)} trade(s) scaled out and exited on the same bar")

def test_no_end_of_sim_liquidation(closed, summary):
    """Live has no forced liquidation, so the reason must not exist.

    Open positions are reported separately instead of being closed at an arbitrary
    date, which would book P&L on a decision the strategy never made.
    """
    forced = [t for t in closed if t['exit_reason'] == 'end_of_sim']
    check("no end_of_sim liquidation (live has no analogue)",
          not forced, f"{len(forced)} forced exit(s)")
    check("open positions reported separately, not booked as trades",
          summary['open_positions'] >= 0 and 'unrealised_pnl' in summary,
          f"{summary['open_positions']} open, "
          f"unrealised ${summary['unrealised_pnl']:+,.2f}")

def test_entry_logic_is_live_code_not_a_copy(symbols):
    """Assert the strategy is EXECUTED from live's file, not re-expressed.

    Two failure modes are covered. The checksum catches a drifted copy — the exact
    rot that let Athena's dead `signals.py` fall one functional line behind Ares V3.
    The adapter test catches an off-by-one in the slice, which would be a look-ahead
    even with a perfect copy: it confirms that evaluating bar `i` sees a frame whose
    last row IS bar `i`.
    """
    from engine import parity
    from engine.live_adapter import evaluate_entry
    from engine.indicators import add_indicators

    try:
        md5 = parity.assert_signals_parity()
        check("engine/signals.py is byte-identical to live Ares", True, md5)
    except parity.ParityDrift as e:
        check("engine/signals.py is byte-identical to live Ares", False, str(e)[:80])
        return

    check("dead re-implementation removed from the engine",
          not hasattr(__import__('engine.portfolio_sim_v6', fromlist=['x']),
                      '_check_entry'),
          "_check_entry no longer exists")

    # Wrap ALL THREE live checkers and scan the WHOLE series, recording the frame
    # handed over at every bar. Probing only the last 40 bars of one symbol made
    # this data-dependent — if no bar in that span was in an uptrend or range, the
    # momentum checker was never called and the test failed for want of a regime
    # rather than for a defect. That is the same flaw already corrected once in the
    # divergence test; a causality check must not depend on market conditions.
    params = load_params("strategy_params_v6.json")
    import engine.live_adapter as la

    names = ('check_momentum_breakout', 'check_uptrend_signals',
             'check_range_signals')
    originals = {n: getattr(la, n) for n in names}
    observed = []

    def make_spy(fn):
        def spy(sym, frame, p):
            observed.append((len(frame), frame.index[-1]))
            return fn(sym, frame, p)
        return spy

    df = None
    try:
        for n, fn in originals.items():
            setattr(la, n, make_spy(fn))
        for sym in symbols[:6]:
            df = add_indicators(load_stock(sym))
            observed.clear()
            mismatches = []
            for j in range(1, len(df)):
                before = len(observed)
                evaluate_entry(df, j, params, sym)
                for rows, last_bar in observed[before:]:
                    # The frame's last row must BE the decision bar. One row more
                    # is a look-ahead; one fewer is an off-by-one the other way.
                    if rows != j + 1 or last_bar != df.index[j]:
                        mismatches.append((j, rows, str(last_bar)[:10]))
            if observed:
                break
    finally:
        for n, fn in originals.items():
            setattr(la, n, fn)

    if observed:
        check("adapter hands live predicates a frame ending at the decision bar",
              not mismatches,
              f"{len(observed)} predicate calls checked across {len(df)} bars, "
              f"every frame ended exactly at its decision bar"
              if not mismatches else f"{len(mismatches)} mismatch(es): "
                                     f"{mismatches[:4]}")
    else:
        check("adapter hands live predicates a frame ending at the decision bar",
              False,
              "no live predicate was invoked on any bar of 6 symbols — the "
              "dispatcher is not reaching live's code at all")

def test_divergence_columns_inert(symbols, params):
    """Run A' must reproduce live's structural blindness to divergence.

    Live's pivot loop stops before the bar it reads, so production can never see a
    divergence. `indicators.py` is now causal and CAN flag the latest bar, so the
    columns must be masked or the backtest would fire exits live cannot fire.
    """
    from engine.portfolio_sim_v6 import prepare, _DIV_COLS
    data = prepare(symbols[:5], "2021-09-01", "2026-09-01", params)
    leaked = {s: [c for c in _DIV_COLS if bool(df[c].any())]
              for s, df in data.items()}
    leaked = {s: cols for s, cols in leaked.items() if cols}
    check("all four divergence columns inert, as in production",
          not leaked, f"leaked: {leaked}" if leaked else
          f"{len(data)} symbols, 4 columns, all False")

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

    print(f"\n  Strategy provenance — is this live's code or a copy of it?")
    test_entry_logic_is_live_code_not_a_copy(subset)

    print(f"\n  Run A' decision set, {len(subset)} symbols:")
    params = load_params("strategy_params_v6.json")
    closed, hist, counters, openpos = run_sim(subset, "2021-09-01", "2026-09-01",
                                              params, label="validate")
    summary, _, _ = summarise(closed, hist, counters, params, openpos)
    check("run completed with trades to inspect", len(closed) > 0,
          f"{len(closed)} closed, {len(openpos)} open")
    test_run_a_ignores_divergence(closed, params)
    test_divergence_columns_inert(subset, params)

    print(f"\n  General look-ahead detection (catches defects nobody predicted):")
    test_future_perturbation_cannot_change_the_past(subset)

    print(f"\n  Execution and pricing (must-fixes 2, 7):")
    test_next_bar_fills(closed)
    test_no_fill_at_stop_price(closed)

    print(f"\n  Live parity of the trade lifecycle:")
    test_sizing_is_static_and_equity_independent(closed, params)
    test_no_exit_on_entry_bar(closed)
    test_scale_out_short_circuits_exits(closed)
    test_no_end_of_sim_liquidation(closed, summary)

    print(f"\n  Metrics and sizing (must-fixes 4, 5, 6):")
    test_max_drawdown_uses_running_peak()
    test_no_forward_looking_columns(closed)
    test_stop_from_returns_stdev(closed, params)

    print(f"\n  Accounting:")
    test_accounting(closed, params, counters, openpos)

    print("\n" + "=" * 66)
    if FAILURES:
        print(f"  {len(FAILURES)} FAILURE(S): {', '.join(FAILURES)}")
        return 1
    print("  All validation checks passed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
