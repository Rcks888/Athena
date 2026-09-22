"""Run B verdict, computed from the pre-registered rule — not chosen after reading it.

Rule, registered in `Ares/ROADMAP.md` 2026-09-22 BEFORE execution:

    Primary universe : A, declared at registration
    Primary metric   : annualised alpha vs MTUM, plus net excess vs SPY on
                       deployed capital
    SUCCESS          : alpha >= -2%/yr AND net excess vs SPY >= 0
    FAILURE          : anything else. No strategy-continuation case arises.

The thresholds are constants below and the verdict is a direct function of them. The
reason for structuring it this way rather than writing a conclusion in prose: the
explicitly barred failure mode is running Run B, finding something less bad, and
continuing. If alpha moved from -7%/yr to -3%/yr that is LESS BAD, not worth
continuing, and this script returns FAILURE for it without discretion.

No re-cutting. The primary universe is not switched, no proxy is added, the window is
not re-cut, and nothing is re-optimised.

    PYTHONPATH=vendor python3 run_b_verdict.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

import pandas as pd

from engine.data_feed import load_stock
from momentum_substitution_test import (
    OPTION_A_ADVERSE_THRESHOLD_ANN_PCT, bootstrap_r2, exposure_profile,
    idle_cash_credit, monthly_from_daily_levels, ols, verdict_option_a,
)

RESULTS = ROOT / "results"
START, END = "2021-09-01", "2026-09-01"

# Pre-registered thresholds. Changing either of these invalidates the registration.
SUCCESS_ALPHA_ANN_PCT = -2.0
SUCCESS_NET_EXCESS_PCT = 0.0
PRIMARY_UNIVERSE = "A_original_130"
PRIMARY_PROXY = "MTUM"

def analyse(tag, uni):
    levels = {s: load_stock(s)['Close'].loc[START:END]
              for s in ('MTUM', 'SPY', 'BIL')}
    bil_daily = levels['BIL'].pct_change().dropna()
    m = {s: monthly_from_daily_levels(levels[s]) for s in levels}

    hist = pd.read_csv(RESULTS / f"{tag}_{uni}_equity.csv")
    eq = hist.copy()
    eq['date'] = pd.to_datetime(eq['date'])
    m_strat = monthly_from_daily_levels(eq.set_index('date')['equity'])

    idx = m_strat.index.intersection(m['MTUM'].index).intersection(
        m['SPY'].index).intersection(m['BIL'].index)
    y = m_strat.loc[idx] - m['BIL'].loc[idx]
    x = m['MTUM'].loc[idx] - m['BIL'].loc[idx]

    r = ols(y.values, x.values, 'MTUM excess return')
    r.update(bootstrap_r2(y.values, x.values))
    expo = exposure_profile(hist, 1000.0)
    cash = idle_cash_credit(hist, bil_daily)

    summary = json.loads((RESULTS / f"{tag}_summary.json").read_text())
    s = summary['universes'][uni]
    raw_ret = s['total_return_pct']
    spy_ret = float((levels['SPY'].iloc[-1] / levels['SPY'].iloc[0] - 1) * 100)
    deployed = raw_ret / expo['mean_exposure']

    return {
        'universe': uni, 'n_months': int(len(idx)),
        'alpha_ann_pct': r['alpha_annualised_pct'],
        'alpha_ann_ci95': [r['alpha_ann_ci95_low_pct'], r['alpha_ann_ci95_high_pct']],
        'alpha_p': r['alpha_p'], 'beta': r['beta'], 'r_squared': r['r_squared'],
        'beta_on_deployed': r['beta'] / expo['mean_exposure'],
        'raw_total_return_pct': raw_ret,
        'mean_exposure': expo['mean_exposure'],
        'net_return_on_deployed_pct': deployed,
        'spy_total_return_pct': spy_ret,
        'net_excess_vs_spy_on_deployed_pct': deployed - spy_ret,
        'gross_pnl_before_commission': s['gross_pnl_before_commission'],
        'commission_total': s['commission_total'],
        'net_pnl': s['net_pnl_after_commission'],
        'idle_cash': cash,
        'net_pnl_plus_tbill': s['net_pnl_after_commission'] + cash['total_interest'],
    }

def main():
    runB = {u: analyse('v6_runB', u)
            for u in ('A_original_130', 'B_midcap_98')}
    runA2 = {u: analyse('v6_runA2', u)
             for u in ('A_original_130', 'B_midcap_98')}

    print("=" * 74)
    print("  RUN B VERDICT — pre-registered rule, applied without discretion")
    print("=" * 74)
    print(f"  Registered    Ares/ROADMAP.md 2026-09-22, before execution")
    print(f"  Question      does repairing causal divergence move the residual from")
    print(f"                economically negative to non-negative?")
    print(f"  One variable  divergence_in_decision_set: false -> true")
    print(f"  SUCCESS       alpha >= {SUCCESS_ALPHA_ANN_PCT:+.0f}%/yr AND net excess "
          f"vs SPY >= {SUCCESS_NET_EXCESS_PCT:+.0f}% on Universe A")
    print(f"  Primary       Universe {PRIMARY_UNIVERSE} vs {PRIMARY_PROXY}, "
          f"declared at registration")

    p = runB[PRIMARY_UNIVERSE]
    a = runA2[PRIMARY_UNIVERSE]

    print(f"\n{'=' * 74}")
    print(f"  PRIMARY METRICS — Universe A, {p['n_months']} monthly observations")
    print(f"{'=' * 74}")
    print(f"    {'metric':<44} {'Run B':>13} {'threshold':>13}")
    print(f"    {'annualised alpha vs MTUM':<44} "
          f"{p['alpha_ann_pct']:>12.2f}% {SUCCESS_ALPHA_ANN_PCT:>12.0f}%")
    print(f"    {'net excess vs SPY on deployed capital':<44} "
          f"{p['net_excess_vs_spy_on_deployed_pct']:>12.2f}% "
          f"{SUCCESS_NET_EXCESS_PCT:>12.0f}%")
    print(f"    alpha 95% CI [{p['alpha_ann_ci95'][0]:+.2f}%, "
          f"{p['alpha_ann_ci95'][1]:+.2f}%]   p={p['alpha_p']:.4f}   "
          f"beta {p['beta']:+.3f} (R2 {p['r_squared']:.3f})")

    cond_alpha = p['alpha_ann_pct'] >= SUCCESS_ALPHA_ANN_PCT
    cond_excess = (p['net_excess_vs_spy_on_deployed_pct']
                   >= SUCCESS_NET_EXCESS_PCT)
    success = cond_alpha and cond_excess
    print(f"\n    condition 1  alpha >= {SUCCESS_ALPHA_ANN_PCT:+.0f}%/yr        "
          f"{'PASS' if cond_alpha else 'FAIL'}")
    print(f"    condition 2  net excess vs SPY >= 0    "
          f"{'PASS' if cond_excess else 'FAIL'}")
    print(f"\n    VERDICT: {'SUCCESS' if success else 'FAILURE'}")

    va, whya = verdict_option_a(p['alpha_ann_pct'], *p['alpha_ann_ci95'])
    print(f"    Option A corrected alpha gate: {va}")

    print(f"\n{'=' * 74}")
    print("  DIRECTION OF THE CHANGE (new sample, NOT a line-by-line comparison)")
    print(f"{'=' * 74}")
    print("  Only the pre-registered primary metrics are compared, and only against")
    print("  the fixed thresholds. Trade counts and exit mixes are not comparable.")
    print(f"    {'':<40} {'Run A(prime)':>14} {'Run B':>14}")
    for uni in ('A_original_130', 'B_midcap_98'):
        x, z = runA2[uni], runB[uni]
        print(f"    {uni}")
        print(f"      {'annualised alpha vs MTUM':<38} "
              f"{x['alpha_ann_pct']:>13.2f}% {z['alpha_ann_pct']:>13.2f}%")
        print(f"      {'net excess vs SPY on deployed':<38} "
              f"{x['net_excess_vs_spy_on_deployed_pct']:>13.2f}% "
              f"{z['net_excess_vs_spy_on_deployed_pct']:>13.2f}%")
        print(f"      {'gross P&L before commission':<38} "
              f"{x['gross_pnl_before_commission']:>13.2f} "
              f"{z['gross_pnl_before_commission']:>13.2f}")

    print(f"\n{'=' * 74}")
    print("  SAME ADJUSTMENTS AS RUN A' — idle cash and exposure")
    print(f"{'=' * 74}")
    for uni in ('A_original_130', 'B_midcap_98'):
        z = runB[uni]
        print(f"    {uni}  (mean exposure {z['mean_exposure']:.1%})")
        print(f"      net P&L ${z['net_pnl']:+,.2f}   "
              f"omitted T-bill interest ${z['idle_cash']['total_interest']:+,.2f}   "
              f"adjusted ${z['net_pnl_plus_tbill']:+,.2f}")
        print(f"      raw return {z['raw_total_return_pct']:+.2f}%   "
              f"on deployed {z['net_return_on_deployed_pct']:+.2f}%   "
              f"SPY {z['spy_total_return_pct']:+.2f}%")

    out = {
        'run': 'B_causal_divergence',
        'registered': 'Ares/ROADMAP.md 2026-09-22, before execution',
        'rule': {'success_alpha_ann_pct_min': SUCCESS_ALPHA_ANN_PCT,
                 'success_net_excess_pct_min': SUCCESS_NET_EXCESS_PCT,
                 'primary_universe': PRIMARY_UNIVERSE,
                 'primary_proxy': PRIMARY_PROXY},
        'primary': p,
        'condition_alpha_pass': bool(cond_alpha),
        'condition_net_excess_pass': bool(cond_excess),
        'verdict': 'SUCCESS' if success else 'FAILURE',
        'verdict_option_a': va,
        'comparable_to_run_a_prime': False,
        'comparability_note': (
            'Run B is a new sample. Only the pre-registered primary metrics are '
            'compared, and only against the fixed thresholds.'),
        'run_b': runB, 'run_a_prime': runA2,
        'no_continuation_case': not success,
    }
    (RESULTS / "v6_runB_verdict.json").write_text(json.dumps(out, indent=2,
                                                            default=str))
    print(f"\n  Saved results/v6_runB_verdict.json")

if __name__ == "__main__":
    main()
