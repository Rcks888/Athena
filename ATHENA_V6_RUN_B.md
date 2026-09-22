# Athena V6 Run B — concept versus defect

**Registered** `Ares/ROADMAP.md`, 2026-09-22, before execution. Fail branch fixed first.
**Question** All four divergence columns are permanently `False` in production, so live
and every backtest so far measured a **crippled** version of the designed strategy.
Does repairing causal divergence move the residual from economically negative to
non-negative?

---

## Verdict: FAILURE

Both pre-registered conditions fail, by wide margins, on the primary universe declared
at registration.

| Primary metric (Universe A) | Run B | Threshold | |
|---|---|---|---|
| Annualised α vs MTUM | **−16.06%** | ≥ −2% | **FAIL** |
| Net excess vs SPY on deployed capital | **−146.17%** | ≥ 0% | **FAIL** |

α 95% CI **[−25.43%, −5.61%]**, p = **0.0040**, β +0.356, R² 0.256, 59 monthly
observations. Adverse under the corrected Option A gate as well.

**Per the registered rule, no strategy-continuation case arises from Run B.**

There is no ambiguity to adjudicate here. Repairing divergence did not move the
residual toward zero — it moved it **twice as far negative**, and made it
statistically significant in the process. This is not the −7% → −3% "less bad"
outcome the rule was written to catch; it is worse on every primary metric.

---

## The answer to concept versus defect

**The −7.3% residual belongs to the concept, not to the defect. The defect was
load-bearing in the strategy's favour.**

Divergence being permanently `False` in production was *protecting* the strategy.
Turning the designed behaviour on doubled the negative alpha.

| | Run A′ (divergence dead, as production) | Run B (divergence repaired, active) |
|---|---|---|
| α vs MTUM, Universe A | −7.27% | **−16.06%** |
| α p-value | 0.197 | **0.0040** |
| Net excess vs SPY on deployed | −94.27% | −146.17% |
| Gross P&L before commission | +$273.21 | **+$8.27** |
| Universe B α | −20.93% | −27.40% |

Both universes moved the same direction, which is the one thing that makes this
reading robust rather than a single-universe artifact.

### The one changed variable genuinely fired

A null result would be uninformative if the repaired detector barely activated. It did
not:

| | Universe A | Universe B |
|---|---|---|
| Entries with a divergence trigger | 28 (14.3%), P&L −$111.74 | 27 (14.4%), P&L −$223.12 |
| `bearish_divergence` exits | 41, P&L +$250.63 | 27, P&L +$219.91 |

Divergence entries **lost money in both universes**. The gross edge collapsed from
+$273.21 to +$8.27 on Universe A while trade count rose and commission went from $331
to $424.

Two cautions on reading that decomposition. The `bearish_divergence` exits carry
positive P&L in isolation, but that is **not** a causal attribution — the
counterfactual is what those same positions would have returned under the exits they
would otherwise have hit, which this run does not measure. And the totals do not
decompose additively, because enabling divergence changes which entries fill at all.
What can be said is the aggregate: the repaired concept is worse, consistently, on
both universes and on every primary metric.

---

## What changed, and what provably did not

**Exactly one variable:** `divergence_in_decision_set: false → true`. The driver
asserts this rather than trusting it — it diffs the Run B config against Run A′'s and
**exits if any key other than that one differs**. Run output confirms it.

The detector itself was already correct and was not touched for this run.
`_scan_divergence` writes its flag at `max(price_pivot, rsi_pivot) + window` and fires
on the **confirmation bar only**, never back-dated onto the pivot — that back-dating is
the original look-ahead defect. Run A′ masks the four columns to `False` to reproduce
production; Run B stops masking them. Lookback 21, pivot window 5, RSI pivot matching
tolerance 3 and every divergence parameter are unchanged.

Unchanged from Run A′: broker funding gate, fixed $149 non-compounding stake, both
universes, window, cost model, idle-cash adjustment reporting, exposure reporting.
**Nothing was re-optimised** — TP, trailing stop and confluence are frozen at
`tp_momentum 0.18` / `trailing_stop_pct 0.10` / `stop_loss_multiplier 2.0`.

### Parity: assertion active, divergence declared and scoped

The md5 parity assertion on `engine/signals.py` **stayed active and passed**
(`da2ba2596cf43f6405dfd4521824c33d`) — Run B does not touch live's strategy code.

`engine/indicators.py` is **not** byte-identical to live's, deliberately, and this is
now recorded in `engine/parity.py` rather than silenced:

- Athena `d4db2c84185279a4c442b22b7a83441b`, live `f2cf8af87476b03b5c27e220de5abcec`.
- **Scope:** four copy-pasted detectors collapsed into one `_scan_divergence`; flag
  written at the confirmation bar instead of back-dated; `SWING_WINDOW` named instead
  of a repeated literal; `load_params` resolving the active config.
- **Unchanged:** lookback, pivot window, RSI tolerance, every indicator formula,
  `detect_market_regime`.

Deliberately *not* a checksum assertion, because the divergence is intended. What is
guarded is that it stays **recorded** and that Athena's own copy does not drift further
unnoticed: both hashes are pinned and reported on every run.

---

## Not comparable to Run A′ line by line

Enabling divergence changes which entries fire and which exits trigger, so Run B is a
**different trade population and a new sample**. `results/v6_runB_summary.json` records
`run: B_causal_divergence`, `comparable_to_run_a_prime: false` and a comparability
note, the same way `return_basis` and `comparable_to_run_a` were recorded for A′.

Trade counts, win rates and exit mixes must not be tabulated against A′. Only the
pre-registered primary metrics are meant to be compared, and only against the fixed
thresholds — which is what `run_b_verdict.py` does.

---

## Secondary figures, for completeness only

Not part of the decision rule.

| | Universe A | Universe B |
|---|---|---|
| Final equity | $563.59 (−43.64%) | $262.72 (−73.73%) |
| Max drawdown | −50.80% | −75.86% |
| Gross / commission / net | +$8.27 / −$424.00 / −$415.73 | −$317.31 / −$407.00 / −$724.31 |
| Mean exposure | 72.0% | 58.1% |
| Omitted T-bill interest | +$26.85 → −$388.88 adjusted | +$37.57 → −$686.74 adjusted |

---

## Consequence

Per the registered rule: **no strategy-continuation case arises from Run B.** The
default stated at registration now stands — divergence stays dead and documented in
live, and is **not repaired mid-`clean_v3`**.

This also closes the Finviz objection's one legitimate branch. `ROADMAP.md` adjudicated
the divergence gap as *"real live-versus-design gap — the concept-versus-defect question
Run B addresses."* It is now addressed: repairing it makes things worse, so the gap
does not contain a rescue.

---

## Reproducing

```bash
cd ~/Olympus/Athena
PYTHONPATH=vendor python3 run_backtest_v6_runB.py   # ~2 min
PYTHONPATH=vendor python3 run_b_verdict.py
```

Artifacts: `results/v6_runB_*` and `results/v6_runB_verdict.json`. Run A, Run A′ and
V1–V5 outputs untouched.
