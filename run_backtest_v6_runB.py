"""Athena V6 Run B — concept versus defect. PRE-REGISTERED, fail branch fixed first.

Registered in `Ares/ROADMAP.md`, "PRE-REGISTERED — Run B, concept versus defect",
2026-09-22, before execution.

QUESTION. All four divergence columns are permanently `False` in production, because
live's pivot loop back-dates its flag onto the pivot bar and stops at
`len - window - 1` while live reads `len - 1`. Live *and* every backtest so far have
therefore measured a CRIPPLED version of the designed strategy. Does repairing causal
divergence move the residual from economically negative to non-negative?

EXACTLY ONE VARIABLE CHANGES. `divergence_in_decision_set: false -> true`. Nothing
else. The detector in `engine/indicators.py` already confirms at
`max(price_pivot, rsi_pivot) + window` and fires on the CONFIRMATION bar only, never
back-dated; Run A' simply masks the four columns to False to reproduce production.
Run B stops masking them. Lookback 21, pivot window 5, RSI pivot matching tolerance 3
and every divergence parameter are untouched, as are the funding gate, the fixed $149
stake, both universes, the window, the cost model and the reporting.

DECISION RULE, FIXED IN ADVANCE:
  Primary universe : A (declared at registration, not after seeing results)
  Primary metric   : annualised alpha vs MTUM, plus net excess vs SPY on deployed
                     capital
  SUCCESS          : alpha >= -2%/yr AND net excess vs SPY >= 0, on Universe A
  FAILURE          : anything else. No strategy-continuation case arises from Run B.
  BANNED           : any re-optimisation of TP, trailing stop or confluence

Explicitly barred: running this until something looks less bad, then continuing. If
alpha moves from -7%/yr to -3%/yr that is LESS BAD, not worth continuing, and is
reported as FAILURE. The verdict is computed by `run_b_verdict.py` from the rule
above, not chosen after reading the output.

NOT COMPARABLE TO RUN A' LINE BY LINE. Enabling divergence changes which entries fire
and which exits trigger, so this is a DIFFERENT TRADE POPULATION and a new sample —
the same reason `return_basis` and `comparable_to_run_a` were recorded for A'. Run B's
artifacts carry `run: B_causal_divergence` and `comparable_to_run_a_prime: false`.

    PYTHONPATH=vendor python3 run_backtest_v6_runB.py
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
# Reuse A''s reporting verbatim rather than re-expressing it. Two hand-maintained
# report functions would drift, which is the defect class this whole project is about.
from run_backtest_v6_runA2 import report

START = "2021-09-01"
END = "2026-09-01"
RESULTS = ROOT / "results"
TAG = "v6_runB"
PRIMARY_UNIVERSE = "A_original_130"

def divergence_diagnostics(df, openpos):
    """How much the repaired detector actually did, so a null result is legible.

    If divergence barely fires, Run B answers a narrower question than it appears to
    and that must be visible rather than inferred from an unchanged bottom line.
    """
    if df.empty:
        return {'entries_with_div_trigger': 0, 'bearish_divergence_exits': 0,
                'pct_entries_with_div': 0.0, 'div_trigger_pnl': 0.0}
    has_div = df['trigger'].str.contains('div', case=False, na=False)
    return {
        'entries_with_div_trigger': int(has_div.sum()),
        'pct_entries_with_div': round(float(has_div.mean()) * 100, 1),
        'div_trigger_pnl': round(float(df.loc[has_div, 'pnl'].sum()), 2),
        'bearish_divergence_exits': int(
            (df['exit_reason'] == 'bearish_divergence').sum()),
        'bearish_divergence_exit_pnl': round(float(
            df.loc[df['exit_reason'] == 'bearish_divergence', 'pnl'].sum()), 2),
        'confluence_values': sorted(df['confluence'].unique().tolist()),
    }

def main():
    params = load_params("strategy_params_v6_runB.json")
    if not params.get('divergence_in_decision_set', False):
        raise SystemExit(
            "Run B REQUIRES divergence_in_decision_set: true. With it false this is "
            "Run A' and measures nothing new."
        )

    base = json.loads((ROOT / "config" / "strategy_params_v6.json").read_text())
    differing = {k for k in set(base) | set(params)
                 if base.get(k) != params.get(k)} - {'version'}
    if differing != {'divergence_in_decision_set'}:
        raise SystemExit(
            f"Run B must change EXACTLY ONE variable. Differing keys vs Run A': "
            f"{sorted(differing)}. Any other change makes this a different "
            f"experiment and the pre-registered rule would not apply to it."
        )

    print("=" * 70)
    print("  ATHENA V6 — RUN B  (causal divergence REPAIRED and ACTIVE)")
    print("=" * 70)
    print(f"  Registered        Ares/ROADMAP.md, 2026-09-22, before execution")
    print(f"  Question          does repairing causal divergence move the residual")
    print(f"                    from economically negative to non-negative?")
    print(f"  One variable      divergence_in_decision_set: false -> TRUE")
    print(f"                    (verified: only differing key vs Run A' config)")
    print(f"  Success           alpha >= -2%/yr AND net excess vs SPY >= 0 on A")
    print(f"  Primary universe  A  (declared at registration)")
    print(f"  Period            {START} -> {END}")
    print(f"  Sizing            static ${static_position_size(params):.2f}, "
          f"non-compounding")
    print(f"  Frozen params     tp_momentum {params['tp_momentum']}, "
          f"trailing_stop_pct {params['trailing_stop_pct']}, "
          f"sl_mult {params['stop_loss_multiplier']}  (NOT re-optimised)")
    print(f"  Broker funding    ENFORCED, as Run A'")

    # Parity md5 assertion stays ACTIVE. signals.py is untouched by Run B, so it must
    # still match live byte for byte.
    print(f"  Parity guard      signals.py md5 "
          f"{parity.assert_signals_parity()} verified (unchanged by Run B)")
    ind = parity.indicators_divergence_status()
    print(f"  DECLARED DIVERGENCE from live — engine/indicators.py")
    print(f"    athena md5 {ind['athena_md5']} "
          f"(matches record: {ind['athena_md5_matches_record']})")
    print(f"    live   md5 {ind['live_md5_at_record_time']}  — NOT byte-identical, "
          f"by design")
    print(f"    {ind['declared']}")
    print(f"    Scoped and recorded, not silenced: Run B is the ONLY configuration "
          f"in which\n    this divergence is active, which is the question itself.")

    if MANIFEST_PATH.exists():
        m = json.loads(MANIFEST_PATH.read_text())
        print(f"  Data snapshot     {m['created_utc']}, "
              f"yfinance {m['yfinance_version']}, "
              f"{m['symbols_snapshotted']}/{m['symbols_attempted']} symbols")
    print(f"\n  NOT COMPARABLE TO RUN A' LINE BY LINE — enabling divergence changes")
    print(f"  which entries fire and which exits trigger, so this is a different")
    print(f"  trade population and a NEW SAMPLE, not a variant of A' figures.")

    runs, diags = {}, {}
    for name, universe in (("A_original_130", UNIVERSE_A),
                           ("B_midcap_98", UNIVERSE_B)):
        syms = [s for s in universe if s not in KNOWN_UNAVAILABLE]
        closed, history, counters, openpos = run_sim(syms, START, END, params,
                                                    label=name)
        summary, df, hist = summarise(closed, history, counters, params, openpos)
        ytable = yearly_table(df, hist)
        etable = exit_reason_table(df)
        report(f"RUN B / UNIVERSE {name}"
               f"{'   <-- PRIMARY' if name == PRIMARY_UNIVERSE else ''}",
               summary, ytable, etable, openpos)

        d = divergence_diagnostics(df, openpos)
        diags[name] = d
        print(f"\n    --- DIVERGENCE ACTIVITY (the one changed variable) ---")
        print(f"    Entries with a divergence trigger  "
              f"{d['entries_with_div_trigger']} ({d['pct_entries_with_div']}%), "
              f"P&L ${d['div_trigger_pnl']:+,.2f}")
        print(f"    bearish_divergence exits           "
              f"{d['bearish_divergence_exits']}, "
              f"P&L ${d['bearish_divergence_exit_pnl']:+,.2f}")
        print(f"    Confluence values now observed     {d['confluence_values']}")

        df.to_csv(RESULTS / f"{TAG}_{name}_trades.csv", index=False)
        hist.to_csv(RESULTS / f"{TAG}_{name}_equity.csv", index=False)
        ytable.to_csv(RESULTS / f"{TAG}_{name}_yearly.csv", index=False)
        etable.to_csv(RESULTS / f"{TAG}_{name}_exits.csv", index=False)
        pd.DataFrame(openpos).to_csv(RESULTS / f"{TAG}_{name}_open.csv", index=False)
        runs[name] = summary

    benches = []
    for sym in ("SPY", "QQQ"):
        b = buy_and_hold(sym, START, END, params['starting_capital'],
                         params['slippage_pct'], params['commission_per_trade'])
        if b:
            benches.append(b)

    out = {
        'run': 'B_causal_divergence',
        'registered': 'Ares/ROADMAP.md 2026-09-22, before execution',
        'one_variable_changed': 'divergence_in_decision_set: false -> true',
        'period': [START, END],
        'primary_universe': PRIMARY_UNIVERSE,
        'success_rule': ('annualised alpha vs MTUM >= -2%/yr AND net excess vs SPY '
                         '>= 0 on deployed capital, Universe A'),
        'return_basis': 'fixed_stake_non_compounding',
        'comparable_to_run_a': False,
        'comparable_to_run_a_prime': False,
        'comparability_note': (
            'Run B is a NEW SAMPLE. Enabling divergence changes which entries fire '
            'and which exits trigger, so the trade population differs from Run A\'. '
            'Line-by-line comparison of trade counts, win rates or exit mixes '
            'against Run A\' is not valid; only the pre-registered primary metrics '
            'are meant to be compared, and only against the fixed thresholds.'),
        'live_signals_md5': parity.LIVE_SIGNALS_MD5,
        'indicators_divergence': parity.indicators_divergence_status(),
        'reproduced_live_defects': REPRODUCED_LIVE_DEFECTS,
        'modelled_broker_constraints': MODELLED_BROKER_CONSTRAINTS,
        'params': params,
        'universes': runs,
        'divergence_diagnostics': diags,
        'benchmarks': benches,
        'known_unavailable': KNOWN_UNAVAILABLE,
        'verdict_note': ('The pre-registered verdict is computed by '
                         'run_b_verdict.py from the fixed success rule. It is not '
                         'chosen after reading these figures.'),
    }
    (RESULTS / f"{TAG}_summary.json").write_text(
        json.dumps(out, indent=2, default=str))
    print(f"\n  Saved results/{TAG}_*.{{csv,json}} "
          f"(Run A, Run A' and V1-V5 untouched)")
    print(f"  Next: PYTHONPATH=vendor python3 run_b_verdict.py")

if __name__ == "__main__":
    main()
