"""PRE-REGISTERED TEST — momentum factor substitution.

Registered in `Ares/ROADMAP.md` on 2026-09-22, BEFORE any result was known. That is
the entire point of the document, so this script implements the spec and nothing else.

    Is this strategy an expensive, high-maintenance way to buy momentum factor
    exposure that MTUM provides for 0.15%?

METHOD, AS REGISTERED. Regress strategy monthly excess return on (a) MTUM excess
return and (b) QQQ - SPY, separately. Report R-squared, beta, alpha, standard errors.
~59 monthly observations over 2021-09-01 -> 2026-09-01. Annual would give 5 points
and is unusable.

DECISION RULE, FIXED IN ADVANCE:
  R2 > 0.5 and alpha not significantly positive -> momentum beta; question CLOSES
  R2 < 0.3 and alpha not significantly negative -> possible idiosyncratic component
  anything between                              -> INCONCLUSIVE, stop

WHAT THIS SCRIPT MAY NOT DO. If the result lands in the inconclusive band it is
reported as inconclusive. The proxy is not swapped, the frequency is not changed to
annual, the window is not re-cut, and the 0.3/0.5 thresholds are not moved. The
prohibition is the reason the pre-registration exists: a test whose thresholds move
after seeing the estimate measures the analyst, not the strategy.

One thing the spec left open is the significance level, so it is pinned here and
stated in the output: two-sided t-test at 5%, with "significantly positive" read as
p < 0.05 AND alpha > 0. Fixing it in code rather than in prose keeps it out of reach
of the result.

    PYTHONPATH=vendor python3 momentum_substitution_test.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from scipy import stats

from engine.data_feed import load_stock

RESULTS = ROOT / "results"
START = "2021-09-01"
END = "2026-09-01"
ALPHA_LEVEL = 0.05
R2_MOMENTUM_BETA = 0.5
R2_IDIOSYNCRATIC = 0.3

UNIVERSES = {'A_original_130': 'Universe A (130 mega-cap)',
             'B_midcap_98': 'Universe B (98 mid-cap control)'}

# A month is usable only if its last observation is within this many days of the
# calendar month end. The strategy equity curve stops on 2026-09-01 while the factor
# series run to 2026-09-21, so an unfiltered resample produces a September 2026
# "monthly return" comparing ONE day of strategy against TWENTY-ONE days of MTUM.
# That is a mismatched observation, not a short one, and it inflates N to 60 against
# the registered ~59. Dropping it is alignment hygiene rather than re-cutting: it is
# applied before any coefficient is read, both the 59- and 60-observation results are
# recorded in the JSON, and the verdicts are reported for both so it is auditable
# that the conclusion does not depend on this choice.
MONTH_END_TOLERANCE_DAYS = 5

def monthly_from_daily_levels(s, drop_partial=True):
    """Month-end level series -> monthly simple returns, partial months excluded."""
    m = s.resample('ME').last()
    if drop_partial:
        last_obs = s.groupby(s.index.to_period('M')).apply(lambda g: g.index[-1])
        month_end = m.index
        keep = []
        for i, per in enumerate(m.index.to_period('M')):
            obs = last_obs.get(per)
            keep.append(obs is not None
                        and (month_end[i] - obs).days <= MONTH_END_TOLERANCE_DAYS)
        m = m[pd.Series(keep, index=m.index).values]
    return m.pct_change().dropna()

def ols(y, x, xname):
    """OLS of y on [1, x] with classical standard errors.

    Written out rather than pulled from statsmodels because statsmodels is not in
    the pinned `vendor/` set, and adding a dependency to the environment that
    defines live-vs-backtest comparability is not worth a convenience import.
    """
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    beta_hat, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta_hat
    dof = n - 2
    sigma2 = float(resid @ resid) / dof
    XtX_inv = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(sigma2 * XtX_inv))
    tstat = beta_hat / se
    pval = 2 * (1 - stats.t.cdf(np.abs(tstat), dof))
    ss_tot = float(((y - y.mean()) ** 2).sum())
    ss_res = float(resid @ resid)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float('nan')

    # Newey-West(3) is computed as a DISCLOSURE only and does NOT enter the decision
    # rule, which uses the classical SEs as registered. Monthly returns from ~2.5
    # trades a month are lumpy and possibly autocorrelated, so suppressing this
    # entirely would hide a real caveat; letting it drive the verdict would be
    # exactly the re-cutting the pre-registration forbids.
    lag = 3
    S = np.zeros((2, 2))
    u = resid[:, None] * X
    for l in range(lag + 1):
        w = 1.0 if l == 0 else 1.0 - l / (lag + 1)
        G = u[l:].T @ u[:n - l] / n
        S += w * (G + G.T) if l > 0 else w * G
    V_hac = n * XtX_inv @ S @ XtX_inv
    se_hac = np.sqrt(np.abs(np.diag(V_hac)))
    p_hac = 2 * (1 - stats.t.cdf(np.abs(beta_hat / se_hac), dof))

    return {
        'regressor': xname, 'n': n,
        'alpha_monthly': float(beta_hat[0]),
        'alpha_annualised_pct': float(((1 + beta_hat[0]) ** 12 - 1) * 100),
        'alpha_se': float(se[0]), 'alpha_t': float(tstat[0]),
        'alpha_p': float(pval[0]),
        'beta': float(beta_hat[1]), 'beta_se': float(se[1]),
        'beta_t': float(tstat[1]), 'beta_p': float(pval[1]),
        'r_squared': float(r2),
        'resid_sd_monthly': float(np.sqrt(sigma2)),
        'alpha_se_hac3': float(se_hac[0]), 'alpha_p_hac3': float(p_hac[0]),
        'beta_se_hac3': float(se_hac[1]), 'beta_p_hac3': float(p_hac[1]),
    }

def bootstrap_r2(y, x, n_boot=10000, seed=20260922):
    """Bootstrap distribution of R-squared. DISCLOSURE ONLY.

    This does not enter the decision rule and cannot change a verdict. It exists
    because a point estimate of 0.2946 against a 0.30 threshold is a 0.005 margin,
    and reporting "R2 < 0.3" from that without stating its precision would be
    overclaiming from noise — the same error, in miniature, as the inflated figure
    this whole audit exists to correct. The threshold stays where it was registered;
    what is added is an honest statement of how well 59 lumpy observations pin the
    estimate down.

    Seeded so the interval is reproducible.
    """
    rng = np.random.default_rng(seed)
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    n = len(y)
    out = np.empty(n_boot)
    for b in range(n_boot):
        i = rng.integers(0, n, n)
        yb, xb = y[i], x[i]
        X = np.column_stack([np.ones(n), xb])
        coef, *_ = np.linalg.lstsq(X, yb, rcond=None)
        resid = yb - X @ coef
        ss_tot = float(((yb - yb.mean()) ** 2).sum())
        out[b] = 1 - float(resid @ resid) / ss_tot if ss_tot > 0 else np.nan
    out = out[~np.isnan(out)]
    return {
        'r2_ci95_low': float(np.percentile(out, 2.5)),
        'r2_ci95_high': float(np.percentile(out, 97.5)),
        'p_r2_above_0p3': float((out > R2_IDIOSYNCRATIC).mean()),
        'p_r2_above_0p5': float((out > R2_MOMENTUM_BETA).mean()),
        'n_boot': int(len(out)),
    }

def verdict(r2, alpha, alpha_p):
    """The registered decision rule. No branch depends on the observed values
    beyond what is written here."""
    sig_pos = alpha_p < ALPHA_LEVEL and alpha > 0
    sig_neg = alpha_p < ALPHA_LEVEL and alpha < 0
    if r2 > R2_MOMENTUM_BETA and not sig_pos:
        return ('MOMENTUM_BETA',
                f"R2 {r2:.3f} > {R2_MOMENTUM_BETA} and alpha is not significantly "
                f"positive (p={alpha_p:.3f}). QUESTION CLOSES: own the factor or the "
                f"index; do not operate a costly replica. No structural study follows.")
    if r2 < R2_IDIOSYNCRATIC and not sig_neg:
        return ('POSSIBLE_IDIOSYNCRATIC',
                f"R2 {r2:.3f} < {R2_IDIOSYNCRATIC} and alpha is not significantly "
                f"negative (p={alpha_p:.3f}). The single pre-registered slot study "
                f"becomes justified.")
    return ('INCONCLUSIVE',
            f"R2 {r2:.3f} falls in [{R2_IDIOSYNCRATIC}, {R2_MOMENTUM_BETA}] or the "
            f"alpha sign condition is not met (alpha={alpha:+.5f}, p={alpha_p:.3f}). "
            f"Report as inconclusive and STOP. Do not proceed to sweeps and do not "
            f"re-cut the test.")

def idle_cash_credit(hist, bil_daily):
    """What the omitted T-bill interest on idle cash would have been worth.

    The simulator pays 0% on cash while at most 5 x $149 = $745 of $1,000 is ever
    deployed, so every net figure is understated by the interest a real account would
    have earned over 2021-2026 — a period that includes a 5% policy rate.

    Reported as an explicit adjustment rather than credited inside `run_sim`. Paying
    interest during the run would relax the broker funding gate, changing which
    entries fill and therefore the trade population, which would supersede the Run A'
    figures a second time for a second-order reason. Quantifying it keeps the trade
    population fixed and still puts the number next to every net figure, which is
    what the audit asked for.

    Interest is accrued on each day's closing cash and NOT reinvested, which is the
    conservative direction.
    """
    h = hist.copy()
    h['date'] = pd.to_datetime(h['date'])
    h = h.set_index('date')
    r = bil_daily.reindex(h.index).fillna(0.0)
    daily_interest = h['cash'] * r
    return {
        'total_interest': float(daily_interest.sum()),
        'mean_idle_cash': float(h['cash'].mean()),
        'min_idle_cash': float(h['cash'].min()),
        'bil_total_return_pct': float((1 + bil_daily.reindex(h.index)
                                       .fillna(0.0)).prod() - 1) * 100,
        'days': int(len(h)),
    }

def exposure_profile(hist, start_capital):
    """Average fraction of the account actually at risk.

    Needed for two things the raw framing distorts: a ~50% invested strategy compared
    against 100% SPY is not like for like, and partial investment ATTENUATES the
    regression beta, so the beta on deployed capital is the reported beta divided by
    average exposure.
    """
    h = hist.copy()
    invested = (h['equity'] - h['cash']).clip(lower=0)
    exposure = (invested / h['equity']).replace([np.inf, -np.inf], np.nan).dropna()
    return {
        'mean_exposure': float(exposure.mean()),
        'median_exposure': float(exposure.median()),
        'max_exposure': float(exposure.max()),
        'pct_days_fully_idle': float((exposure < 0.01).mean() * 100),
    }

def main():
    # ---- frozen inputs ------------------------------------------------
    fm = json.loads((ROOT / "data" / "factor_manifest.json").read_text())
    levels = {}
    for sym in ('MTUM', 'SPY', 'QQQ', 'BIL'):
        levels[sym] = load_stock(sym)['Close'].loc[START:END]

    print("=" * 74)
    print("  PRE-REGISTERED TEST — momentum factor substitution")
    print("=" * 74)
    print(f"  Registered   Ares/ROADMAP.md, 2026-09-22, before any result was known")
    print(f"  Question     Is this an expensive way to buy momentum exposure that")
    print(f"               MTUM provides for 0.15%?")
    print(f"  Window       {START} -> {END}  (data begins 2021-09-22)")
    print(f"  Frequency    monthly; annual would give 5 points and is unusable")
    print(f"  Proxies      (a) MTUM excess return   (b) QQQ - SPY")
    print(f"  Significance two-sided t-test at {ALPHA_LEVEL:.0%}; 'significantly "
          f"positive' = p<{ALPHA_LEVEL} AND alpha>0")
    print(f"  Data         yfinance {fm['yfinance_version']}, "
          f"snapshot {fm['created_utc']}, auto_adjust=True (total return)")

    # BIL is the risk-free proxy: what idle cash would actually have earned.
    bil_daily = levels['BIL'].pct_change().dropna()
    monthly = {s: monthly_from_daily_levels(levels[s]) for s in levels}
    m_bil, m_mtum = monthly['BIL'], monthly['MTUM']
    m_spy, m_qqq = monthly['SPY'], monthly['QQQ']
    # Unfiltered variants, kept purely so the partial-month exclusion is auditable.
    raw_monthly = {s: monthly_from_daily_levels(levels[s], drop_partial=False)
                   for s in levels}

    try:
        irx = load_stock('_IRX')['Close'].loc[START:END]
        irx_note = f"{irx.mean():.2f}% mean 13-week T-bill discount rate"
    except Exception:
        irx_note = "unavailable"
    print(f"  Risk-free    BIL total return "
          f"{((1 + bil_daily).prod() - 1) * 100:.2f}% over the window "
          f"({irx_note})")

    out = {'registered': 'Ares/ROADMAP.md 2026-09-22',
           'window': [START, END], 'alpha_level': ALPHA_LEVEL,
           'r2_thresholds': {'momentum_beta': R2_MOMENTUM_BETA,
                             'idiosyncratic': R2_IDIOSYNCRATIC},
           'factor_manifest': fm['created_utc'], 'universes': {}}

    for uni, label in UNIVERSES.items():
        hist = pd.read_csv(RESULTS / f"v6_runA2_{uni}_equity.csv")
        eq = hist.copy()
        eq['date'] = pd.to_datetime(eq['date'])
        m_strat = monthly_from_daily_levels(eq.set_index('date')['equity'])

        idx = m_strat.index.intersection(m_mtum.index).intersection(
            m_spy.index).intersection(m_qqq.index).intersection(m_bil.index)
        y = (m_strat.loc[idx] - m_bil.loc[idx])          # strategy EXCESS return
        x_mtum = (m_mtum.loc[idx] - m_bil.loc[idx])      # MTUM EXCESS return
        x_spread = (m_qqq.loc[idx] - m_spy.loc[idx])     # already a zero-cost spread

        print(f"\n{'=' * 74}")
        print(f"  {label}")
        print(f"{'=' * 74}")
        print(f"    {len(idx)} monthly observations, "
              f"{str(idx[0])[:7]} -> {str(idx[-1])[:7]}")

        expo = exposure_profile(hist, 1000.0)
        cash = idle_cash_credit(hist, bil_daily)
        print(f"    Mean exposure {expo['mean_exposure']:.1%} of equity at risk "
              f"(median {expo['median_exposure']:.1%}, "
              f"max {expo['max_exposure']:.1%})")

        regs = {}
        for key, xs, xname in (('mtum', x_mtum, 'MTUM excess return'),
                               ('qqq_spy', x_spread, 'QQQ - SPY')):
            r = ols(y.values, xs.values, xname)
            r.update(bootstrap_r2(y.values, xs.values))
            v, why = verdict(r['r_squared'], r['alpha_monthly'], r['alpha_p'])
            r['verdict'] = v
            r['threshold_margin'] = float(min(abs(r['r_squared'] - R2_IDIOSYNCRATIC),
                                              abs(r['r_squared'] - R2_MOMENTUM_BETA)))
            r['verdict_fragile'] = bool(r['threshold_margin'] < 0.05)
            r['verdict_detail'] = why
            r['beta_on_deployed_capital'] = (
                r['beta'] / expo['mean_exposure'] if expo['mean_exposure'] else None)
            regs[key] = r

            print(f"\n    --- strategy excess return ~ {xname} ---")
            print(f"    R-squared          {r['r_squared']:.4f}")
            print(f"    beta               {r['beta']:+.4f}  "
                  f"(SE {r['beta_se']:.4f}, t {r['beta_t']:+.2f}, "
                  f"p {r['beta_p']:.4f})")
            print(f"    alpha  (monthly)   {r['alpha_monthly']:+.5f}  "
                  f"(SE {r['alpha_se']:.5f}, t {r['alpha_t']:+.2f}, "
                  f"p {r['alpha_p']:.4f})")
            print(f"    alpha  (annualised){r['alpha_annualised_pct']:+.2f}%")
            print(f"    residual SD        {r['resid_sd_monthly']:.5f}/month")
            print(f"    beta on DEPLOYED capital ~{r['beta_on_deployed_capital']:+.3f} "
                  f"(beta / {expo['mean_exposure']:.2f} mean exposure)")
            print(f"    HAC(3) disclosure  alpha p {r['alpha_p_hac3']:.4f}, "
                  f"beta p {r['beta_p_hac3']:.4f}  "
                  f"(NOT used for the decision)")
            print(f"    R2 bootstrap 95% CI [{r['r2_ci95_low']:.3f}, "
                  f"{r['r2_ci95_high']:.3f}]  "
                  f"P(R2>0.3)={r['p_r2_above_0p3']:.2f}, "
                  f"P(R2>0.5)={r['p_r2_above_0p5']:.2f}  (disclosure only)")
            print(f"    VERDICT            {v}")
            print(f"      {why}")
            if r['verdict_fragile']:
                print(f"    *** BOUNDARY WARNING: R2 is {r['threshold_margin']:.4f} "
                      f"from a decision threshold. The registered rule returns the "
                      f"verdict above and is NOT overridden here, but the margin is "
                      f"smaller than the sampling error, so this verdict must not be "
                      f"treated as a firm finding. ***")

        # Sensitivity of the verdict to the partial-month exclusion. Recorded, not
        # chosen after the fact: if including the mismatched September 2026
        # observation changed a verdict, that would have to be disclosed, so it is
        # computed either way.
        m_strat_raw = monthly_from_daily_levels(
            eq.set_index('date')['equity'], drop_partial=False)
        ridx = m_strat_raw.index.intersection(raw_monthly['MTUM'].index) \
            .intersection(raw_monthly['SPY'].index) \
            .intersection(raw_monthly['QQQ'].index) \
            .intersection(raw_monthly['BIL'].index)
        y_raw = m_strat_raw.loc[ridx] - raw_monthly['BIL'].loc[ridx]
        unfiltered = {}
        for key, xs in (('mtum', raw_monthly['MTUM'].loc[ridx]
                         - raw_monthly['BIL'].loc[ridx]),
                        ('qqq_spy', raw_monthly['QQQ'].loc[ridx]
                         - raw_monthly['SPY'].loc[ridx])):
            rr = ols(y_raw.values, xs.values, key)
            vv, _ = verdict(rr['r_squared'], rr['alpha_monthly'], rr['alpha_p'])
            unfiltered[key] = {'n': rr['n'], 'r_squared': rr['r_squared'],
                               'beta': rr['beta'], 'alpha_monthly':
                               rr['alpha_monthly'], 'alpha_p': rr['alpha_p'],
                               'verdict': vv}

        out['universes'][uni] = {
            'label': label, 'n_months': int(len(idx)),
            'first_month': str(idx[0])[:7], 'last_month': str(idx[-1])[:7],
            'exposure': expo, 'idle_cash': cash, 'regressions': regs,
            'unfiltered_including_partial_month': unfiltered,
        }

    print(f"\n{'=' * 74}")
    print("  SIDE ITEM 1 — omitted T-bill interest on idle cash")
    print(f"{'=' * 74}")
    print("  The simulator pays 0% on cash. Every net figure is understated by this.")
    for uni, label in UNIVERSES.items():
        c = out['universes'][uni]['idle_cash']
        net = -57.79 if uni == 'A_original_130' else -595.85
        print(f"    {label}")
        print(f"      mean idle cash ${c['mean_idle_cash']:.2f} over {c['days']} days")
        print(f"      omitted interest at BIL   ${c['total_interest']:+,.2f}")
        print(f"      net P&L as reported       ${net:+,.2f}")
        print(f"      net P&L + T-bill credit   ${net + c['total_interest']:+,.2f}")

    print(f"\n{'=' * 74}")
    print("  SIDE ITEM 2 — exposure-adjusted comparison")
    print(f"{'=' * 74}")
    print("  A ~50%-invested strategy against 100% SPY is not like for like.")
    spy_total = float((levels['SPY'].iloc[-1] / levels['SPY'].iloc[0] - 1) * 100)
    for uni, label in UNIVERSES.items():
        u = out['universes'][uni]
        e = u['exposure']['mean_exposure']
        raw = -5.58 if uni == 'A_original_130' else -57.32
        gross_raw = 27.32 if uni == 'A_original_130' else -26.99
        print(f"    {label}  (mean exposure {e:.1%})")
        print(f"      raw total return        {raw:+.2f}%")
        print(f"      on deployed capital     {raw / e:+.2f}%   "
              f"(raw / {e:.3f})")
        print(f"      gross, on deployed      {gross_raw / e:+.2f}%   "
              f"(before commission)")
        print(f"      SPY over same window    {spy_total:+.2f}% at 100% exposure")
        out['universes'][uni]['exposure_adjusted'] = {
            'raw_total_return_pct': raw,
            'on_deployed_capital_pct': round(raw / e, 2),
            'gross_on_deployed_pct': round(gross_raw / e, 2),
            'spy_total_return_pct': round(spy_total, 2),
        }

    print(f"\n{'=' * 74}")
    print("  CAVEATS, as registered")
    print(f"{'=' * 74}")
    caveats = [
        "~2.5 trades/month makes monthly returns lumpy; 59 observations of a "
        "sparse, discontinuous return series is a low-power test.",
        "Partial investment ATTENUATES beta. A beta of 0.4 at ~50% average exposure "
        "implies ~0.8 on deployed capital, so the raw beta understates the factor "
        "loading of the positions themselves.",
        "Both universes are hindsight-selected, which FLATTERS any momentum loading: "
        "the symbol lists were drawn knowing which names did well.",
        "Idle cash earns 0% in the simulator, so strategy returns are biased DOWN "
        "relative to a real account, which biases alpha down.",
    ]
    for i, c in enumerate(caveats, 1):
        print(f"    {i}. {c}")
    out['caveats'] = caveats

    (RESULTS / "momentum_substitution_test.json").write_text(
        json.dumps(out, indent=2, default=str))
    print(f"\n  Saved results/momentum_substitution_test.json")

if __name__ == "__main__":
    main()
