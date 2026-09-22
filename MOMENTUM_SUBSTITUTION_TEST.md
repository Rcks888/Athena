# Pre-registered test — momentum factor substitution

**Registered** `Ares/ROADMAP.md`, 2026-09-22, before any result was known.
**Run** 2026-09-22 on the frozen A′ equity curves and a frozen factor snapshot.
**Question** Is this strategy an expensive, high-maintenance way to buy momentum
factor exposure that MTUM provides for 0.15%?

---

## Answer

**No — and the question does not close.**

The strategy is **not** a momentum-beta replica. On the primary registered proxy the
bootstrap puts **P(R² > 0.5) = 0.02**, so the "momentum beta, own the factor instead"
branch is ruled out at roughly 98% confidence. Momentum explains about a fifth to a
third of monthly variance, not most of it.

But the branch that *did* trigger rests on a coin flip, and the residual it points at
is negative:

| Universe / proxy | R² | β | α (annualised) | α p-value | Registered verdict |
|---|---|---|---|---|---|
| **A / MTUM** | **0.2946** | +0.391 | **−7.27%** | 0.197 | `POSSIBLE_IDIOSYNCRATIC` ⚠ |
| A / QQQ−SPY | 0.0431 | +0.345 | −4.17% | 0.526 | `POSSIBLE_IDIOSYNCRATIC` |
| **B / MTUM** | **0.1909** | +0.471 | **−20.93%** | **0.0147** | **`INCONCLUSIVE`** |
| B / QQQ−SPY | 0.0205 | +0.356 | −17.57% | 0.063 | `POSSIBLE_IDIOSYNCRATIC` |

59 monthly observations, 2021-10 → 2026-08. Two-sided t-test at 5%.

⚠ **Universe A / MTUM sits 0.0054 from the 0.3 threshold.** The bootstrap 95% CI for
that R² is **[0.131, 0.488]** and **P(R² > 0.3) = 0.50**. Which side of the decision
boundary it lands on is, with 59 lumpy observations, indistinguishable from a coin
toss. **The registered rule is not overridden** — it returns
`POSSIBLE_IDIOSYNCRATIC` and that is what is reported — but the margin is far smaller
than the sampling error and it must not be treated as a firm finding.

**The two primary-proxy results disagree.** Universe A says the slot study is
justified; Universe B, the control, returns `INCONCLUSIVE` because its alpha **is**
significantly negative (−20.9%/yr, p=0.015). The rule's instruction for that branch
is explicit: report as inconclusive and stop.

So the useful summary is narrower than either branch:

- **Momentum loading is real and statistically strong.** β = 0.391 (t=4.88, p<0.0001)
  on A and 0.471 (t=3.67, p=0.0005) on B. On **deployed** capital that is **≈0.61 and
  ≈0.81**. The strategy does buy momentum.
- **Momentum is not most of what it does.** R² of 0.19–0.29 on MTUM, 0.02–0.04 on
  QQQ−SPY.
- **What it does beyond momentum has a negative sign everywhere it can be measured** —
  −7.3%/yr on A (not significant), −20.9%/yr on B (significant). The "idiosyncratic
  component" the rule points toward is, on the evidence available, a cost rather than
  an edge.

**Stated plainly:** this is not a costly momentum replica. It is something with
genuine momentum loading plus a residual that is negative on the control universe.
The pre-registered slot study is formally justified on Universe A alone, on a
coin-flip margin, while the control universe says stop. **Per the registered rule the
honest position is that the question is not resolved, and the case for spending the
single slot study on this is weak.** That is a judgement for you, not for this script
— what I will not do is re-cut the test to manufacture either verdict.

---

## Method, exactly as registered

- **Strategy returns** from `results/v6_runA2_*_equity.csv`, month-end equity.
- **Excess returns** over BIL (SPDR 1–3 Month T-Bill ETF, total return), which
  returned **19.33%** over the window; the 13-week T-bill discount rate averaged
  **3.69%**.
- **Proxy (a)** MTUM excess return. **Proxy (b)** QQQ − SPY, used as a zero-cost
  spread and so not excess-adjusted.
- **OLS with classical standard errors**, written out in `ols()` rather than imported,
  because statsmodels is not in the pinned `vendor/` set and the pin defines
  live-vs-backtest comparability.
- **Monthly.** Annual would give 5 points and is unusable.

Nothing was varied. No threshold was moved, no proxy swapped, no window re-cut.

### One alignment correction, made before any coefficient was read

An unfiltered resample produced **60** observations, not the registered ~59, because
the strategy equity curve ends 2026-09-01 while the factor series run to 2026-09-21.
That September 2026 "monthly return" compared **one day** of strategy against
**twenty-one days** of MTUM. Partial months are now excluded.

This is alignment hygiene, not re-cutting, and it is auditable: both variants are
recorded in the JSON, and **all four verdicts are identical either way.**

| | unfiltered (n=60) | filtered (n=59) | verdict |
|---|---|---|---|
| A / MTUM | R² 0.2954 | R² 0.2946 | unchanged |
| A / QQQ−SPY | R² 0.0436 | R² 0.0431 | unchanged |
| B / MTUM | R² 0.1896 | R² 0.1909 | unchanged |
| B / QQQ−SPY | R² 0.0203 | R² 0.0205 | unchanged |

### Two disclosures that do not enter the decision

- **Newey-West(3) standard errors**, since ~2.5 trades/month may autocorrelate. They
  do not change any verdict: A/MTUM alpha p 0.218 vs 0.197; B/MTUM alpha p 0.018 vs
  0.015.
- **Bootstrap R² intervals** (10,000 resamples, seeded). Reported because quoting
  "R² < 0.3" off a 0.005 margin without stating its precision would be overclaiming
  from noise — the same error, in miniature, that this audit exists to correct.

---

## Caveats, as registered

1. **~2.5 trades/month makes monthly returns lumpy.** 59 observations of a sparse,
   discontinuous return series is a low-power test. The A/MTUM coin flip is that
   low power made visible.
2. **Partial investment attenuates beta.** Mean exposure is **64.0%** (A) and
   **58.4%** (B) — higher than the ~50% assumed at registration — so betas on
   deployed capital are ≈0.61 and ≈0.81, not ≈0.8 and ≈0.9.
3. **Both universes are hindsight-selected**, which flatters any momentum loading:
   the symbol lists were drawn knowing which names did well. The true loading is
   plausibly lower than measured.
4. **Idle cash earns 0% in the simulator**, biasing strategy returns and therefore
   alpha **down**. Quantified below.

---

## Side item 1 — omitted T-bill interest on idle cash

The simulator pays 0% on cash while at most 5 × $149 = $745 of $1,000 is deployed.
Accrued daily on each day's closing cash at BIL, **not reinvested** (conservative):

| | mean idle cash | omitted interest | net as reported | **net + T-bill credit** |
|---|---|---|---|---|
| Universe A | $330.15 | **+$50.14** | −$57.79 | **−$7.65** |
| Universe B | $258.68 | +$35.66 | −$595.85 | −$560.19 |

**This changes how Universe A should be described.** At −$7.65 on $1,000 over five
years, A is **essentially flat, not losing** — which the raw figure does not say. The
audit's estimate was $60–80; the realised figure is $50.14.

Reported as an adjustment rather than credited inside `run_sim`, deliberately: paying
interest during the run would relax the broker funding gate, change which entries
fill, and supersede the A′ figures a second time for a second-order reason. This
keeps the trade population fixed and still places the number beside every net figure.

---

## Side item 2 — exposure-adjusted comparison

A ~60%-invested strategy against 100% SPY is not like for like.

| | mean exposure | raw return | on deployed capital | gross on deployed | SPY |
|---|---|---|---|---|---|
| Universe A | 64.0% | −5.58% | **−8.72%** | **+42.68%** | +85.55% |
| Universe B | 58.4% | −57.32% | −98.21% | −46.24% | +85.55% |

Universe A's gross edge on deployed capital is **+42.68% against SPY's +85.55%** —
still behind, by half rather than by the ~91 points the raw framing implies. The raw
comparison overstates the gap; the exposure-adjusted one still does not clear the
benchmark. Both statements are true and only the second is useful.

---

## Reproducing

```bash
cd ~/Olympus/Athena
PYTHONPATH=vendor python3 snapshot_factors.py            # freeze MTUM/SPY/QQQ/BIL/^IRX
PYTHONPATH=vendor python3 momentum_substitution_test.py
```

Factor series are committed in `data/ohlcv/` with provenance in
`data/factor_manifest.json` — deliberately separate from `snapshot_manifest.json`,
because `snapshot_universe` rebuilds that file from whatever symbol list it is given
and would have replaced the 217-symbol record with a five-symbol one. Same pinned
yfinance 1.6.0 and the same curl_cffi session as the equity snapshot; without the
latter Yahoo returns HTTP 429 and yfinance yields zero rows silently.

Results: `results/momentum_substitution_test.json`.
