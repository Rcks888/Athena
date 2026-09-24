"""FriesTrader mechanical-layer ablation -- runner.

Executes the pre-registered test in FRIESTRADER_ABLATION.md. The decision rule was
committed (7db3b5e) before this script existed and is applied verbatim below.

    PYTHONPATH=vendor python3 run_friestrader_ablation.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

import pandas as pd

from engine import fries_adapter as fries
from engine.portfolio_sim_fries import run_sim, load, CONVICTION_PCT
from engine.universe import UNIVERSE_B
from momentum_substitution_test import ols, monthly_from_daily_levels, verdict_option_a

START, END = "2021-09-01", "2026-09-01"
RESULTS = ROOT / "results"
TAG = "fries_ablation"

# Pre-registered thresholds, committed 2026-09-24 in FRIESTRADER_ABLATION.md.
GATE_ALPHA_FOUNDATION = -2.0
GATE_ALPHA_ADVERSE = -3.0


def bh(symbol):
    px = load(symbol).loc[START:END]["Close"]
    return (px.iloc[-1] / px.iloc[0] - 1) * 100


def main():
    fries.assert_parity()
    rules = fries.load_rules()
    print("=" * 74)
    print("  FRIESTRADER MECHANICAL-LAYER ABLATION")
    print("=" * 74)
    print(f"  Subject      FriesTrader @ {fries.FRIES_COMMIT}, 7 scripts md5-pinned")
    print(f"  Window       {START} -> {END}  (includes 2022)")
    print(f"  Universe     Universe B midcap_98 proxy ({len(UNIVERSE_B)} symbols)")
    print( "  Judgment     REMOVED: direction=long, conviction=fixed, risk_flags=[]")
    print( "  Costs        zero commission (Robinhood), 5bp slippage")
    print(f"  Pre-reg      alpha >= {GATE_ALPHA_FOUNDATION}pct/yr AND excess >= 0 -> foundation")
    print(f"               alpha <= {GATE_ALPHA_ADVERSE}pct/yr OR excess < 0  -> ADVERSE")

    spy_ret, qqq_ret = bh("SPY"), bh("QQQ")
    print(f"\n  Benchmarks   SPY {spy_ret:+.2f}pct   QQQ {qqq_ret:+.2f}pct"
          f"   (auto_adjust = total return)")

    m_mtum = monthly_from_daily_levels(load("MTUM").loc[START:END]["Close"])
    m_bil = monthly_from_daily_levels(load("BIL").loc[START:END]["Close"])

    out = {}
    for conviction in ("high", "medium"):
        pct = int(100 * CONVICTION_PCT[conviction])
        slots = rules["position_sizing"]["max_concurrent_positions"]
        print("\n" + "=" * 74)
        print(f"  ARM M -- conviction fixed {conviction!r}"
              f"  ({pct}pct per position, max {slots} slots)")
        print("=" * 74)
        r = run_sim(UNIVERSE_B, START, END, conviction, rules,
                    start_capital=1000.0, label=f"armM_{conviction}")
        eq = r["equity"]
        closed = pd.DataFrame(r["closed"])
        final = float(eq["equity"].iloc[-1])
        total_ret = (final / 1000.0 - 1) * 100
        mean_exp = float(eq["exposure"].mean())
        peak = eq["equity"].cummax()
        mdd = float(((eq["equity"] - peak) / peak).min() * 100)
        ret_dep = total_ret / mean_exp if mean_exp > 0 else float("nan")

        print(f"    1,000 -> {final:,.2f}   ({total_ret:+.2f}pct)   compounding")
        print(f"    Mean exposure {mean_exp:.1%}   return on deployed {ret_dep:+.2f}pct")
        print(f"    Max drawdown  {mdd:.2f}pct   (2022 in window)")
        print(f"    Closed trades {len(closed)}   still open {len(r['open'])}")
        if len(closed):
            wins = int((closed["pnl"] > 0).sum())
            print(f"    Win rate      {wins}/{len(closed)} = {wins/len(closed):.1%}"
                  f"   mean hold {closed['held_days'].mean():.0f} cal days")
            print( "    Exit reasons  " + ", ".join(
                f"{k} {v}" for k, v in closed["reason"].value_counts().items()))
            print(f"    Scaled-out P&L booked before exit  {closed['scaled_pnl'].sum():+,.2f}")

        excess = ret_dep - spy_ret
        print( "\n    --- vs SPY ---")
        print(f"    SPY total return {spy_ret:+.2f}pct"
              f"   strategy on deployed {ret_dep:+.2f}pct")
        print(f"    NET EXCESS vs SPY (deployed)  {excess:+.2f}pct")

        eq_dated = eq.copy()
        eq_dated["date"] = pd.to_datetime(eq_dated["date"])
        m_strat = monthly_from_daily_levels(eq_dated.set_index("date")["equity"])
        idx = m_strat.index.intersection(m_mtum.index).intersection(m_bil.index)
        reg = None
        if len(idx) >= 12:
            y = (m_strat.loc[idx] - m_bil.loc[idx]).to_numpy()
            x = (m_mtum.loc[idx] - m_bil.loc[idx]).to_numpy()
            reg = ols(y, x, "MTUM-BIL")
            va, whya = verdict_option_a(reg["alpha_annualised_pct"],
                                        reg["alpha_ann_ci95_low_pct"],
                                        reg["alpha_ann_ci95_high_pct"])
            print(f"\n    --- vs MTUM ({len(idx)} monthly obs) ---")
            print(f"    beta {reg['beta']:+.3f}   R2 {reg['r_squared']:.4f}")
            print(f"    alpha annualised {reg['alpha_annualised_pct']:+.2f}pct"
                  f"   95pct CI [{reg['alpha_ann_ci95_low_pct']:+.2f}, "
                  f"{reg['alpha_ann_ci95_high_pct']:+.2f}]   p={reg['alpha_p']:.4f}")
            print(f"    Option A verdict: {va} -- {whya}")

        a = reg["alpha_annualised_pct"] if reg else float("nan")
        if a >= GATE_ALPHA_FOUNDATION and excess >= 0:
            gate = "FOUNDATION -- forward paper testing justified"
        elif a <= GATE_ALPHA_ADVERSE or excess < 0:
            gate = "ADVERSE -- do not fund"
        else:
            gate = "INCONCLUSIVE -- defaults to not funding"
        print(f"\n    >>> PRE-REGISTERED GATE: {gate}")

        eq.to_csv(RESULTS / f"{TAG}_{conviction}_equity.csv", index=False)
        if len(closed):
            closed.to_csv(RESULTS / f"{TAG}_{conviction}_trades.csv", index=False)
        out[conviction] = {
            "final_equity": round(final, 2), "total_return_pct": round(total_ret, 2),
            "mean_exposure": round(mean_exp, 4),
            "return_on_deployed_pct": round(ret_dep, 2),
            "max_drawdown_pct": round(mdd, 2),
            "closed_trades": int(len(closed)), "open_positions": len(r["open"]),
            "spy_total_return_pct": round(spy_ret, 2),
            "net_excess_vs_spy_deployed_pct": round(excess, 2),
            "mtum_regression": reg, "gate": gate,
            "skips": dict(sorted(r["skips"].items(), key=lambda kv: -kv[1])),
        }
        print( "\n    Blocked/skipped counters (top 12):")
        for k, v in list(sorted(r["skips"].items(), key=lambda kv: -kv[1]))[:12]:
            print(f"      {v:6d}  {k}")

    payload = {"pre_registration": "FRIESTRADER_ABLATION.md @ 7db3b5e",
               "fries_commit": fries.FRIES_COMMIT,
               "window": [START, END], "universe": "UNIVERSE_B_midcap_98",
               "commission": 0.0, "slippage": 0.0005,
               "spy_total_return_pct": round(spy_ret, 2),
               "qqq_total_return_pct": round(qqq_ret, 2),
               "arms": out}
    (RESULTS / f"{TAG}.json").write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n  Wrote results/{TAG}.json")


if __name__ == "__main__":
    main()
