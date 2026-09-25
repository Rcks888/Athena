# Block A stage 1 — status: RECONCILED

Runner `run_exit_replay.py`. Outputs `results/block_a_stage1_paired.csv`,
`results/block_a_stage1_summary.json`. Diagnostic `trace_mismatch.py`.
Run A' untouched throughout.

## DEFECT FOUND AND FIXED (category 3: simulation defect)

`exit_policy.decide_scale_out` gated take-profit preservation on the policy name:

    if pos.get("take_profit") and hit == 0 and params.get("exit_policy","A") == "A":

Policy A used the stored absolute `take_profit` (+10% tp_reversal for
mean_reversion, +18% tp_momentum for momentum). B and D fell through and recomputed
from `tiers[0] = 0.18`, so **B and D silently moved the mean-reversion scale-out
from +10% to +18%** — an unregistered second intervention confounding a trail-only
experiment. GILD 2021-11-01 needed 64.10 instead of 59.73 and never scaled; AMT
2021-11-16 needed 266.07 instead of 248.02.

Found by tracing the first divergent transition, not by reasoning from P&L. The
anomaly signature was `so_cond=True` for A and `False` for B on an identical close
and identical `tp`.

Fixed at source in `Ares/engine/exit_policy.py` by removing the policy gate;
Policy A's branch is unchanged. Re-vendored byte-identical to Athena,
`LIVE_EXIT_POLICY_MD5` re-pinned `1efad950… -> d00e621d…`. Regression guard
`assert_scale_out_policy_invariant` now runs before every replay and asserts A/B/D
agree on scale-out eligibility at, just below, and well above each tier.

`exit_policy.py` is still imported by nothing in live Ares (the tracker swap is
deliberately held), so this carried zero live risk.

### Independent confirmation that the fix restored the intended intervention
Post-fix affected-subset counts and hurdles reproduce the ROADMAP pre-registration
**exactly**. The confound had corrupted them.

| cell | registered | pre-fix (wrong) | post-fix |
|---|---|---|---|
| B / Universe A | 34, +2.13pp | 38, +1.91pp | **34, +2.13pp** |
| D / Universe A | 24, +3.02pp | 25, +2.90pp | **24, +3.02pp** |
| B / Universe B | 44, +1.68pp | 47, +1.57pp | **44, +1.68pp** |
| D / Universe B | 29, +2.55pp | 29, +2.55pp | **29, +2.55pp** |

## SETTLED

### Gate 1 — Policy A parity: PASS, 293/293, before and after the fix
Exact on symbol, entry_date, exit_date, exit_reason, scaled_out, scale_out_date,
holding_days; within 1e-4 on every dollar field. Tolerance is 1e-4 not 1e-6 because
three separate commission additions accumulate float error legitimately.

### 41 vs 37 tier-count reconciliation: CLOSED
| | scale-outs | mfe>=18% | momentum | reversal | reversal mfe<18 | mfe>=18 w/o scale-out |
|---|---|---|---|---|---|---|
| Universe A | 41 | 37 | 30 | 11 | **4** | **0** |
| Universe B | 30 | 27 | 24 | 6 | **3** | **0** |

Entirely `tp_reversal = 0.10`. 41 = 37+4, 30 = 27+3. Neither count was an error;
they measure different things. Always report both, never merged.

### Mechanism split (Policy A), reproduced via an independent code path
- +18% momentum tier: **0 net-loss of 54** executions (30 A + 24 B)
- +10% reversal tier: **2 net-loss of 17** executions (11 A + 6 B)
- `scaled_out => exit_reason != stop_loss`: PASS both universes

### Gate 3 — FINAL. All four cells fail; registered prior held
| Policy | Universe | mean | CI90 (date-block) | non-zero | pos / neg | verdict |
|---|---|---|---|---|---|---|
| B | A | +0.0734pp | [-0.4933, +0.6572] | 23/145 | 8 / 15 | FAILS |
| B | B | -0.0147pp | [-0.8530, +0.9479] | 35/148 | 10 / 25 | FAILS |
| D | A | +0.2113pp | [-0.0394, +0.4789] | 14/145 | 8 / 6 | FAILS |
| D | B | -0.0189pp | [-0.4813, +0.5483] | 20/148 | 6 / 14 | FAILS |

Median paired delta is exactly 0.0000pp in all four cells.

The confound had inflated every estimate. Correcting it removed the one cell that
looked interesting: **D / Universe A previously had CI90 [+0.0640, +0.6436],
excluding zero. It now includes zero.** That apparent signal was an artifact of the
unregistered +18% mean-reversion threshold, not evidence about trail activation.

### Gate 4 — affected subset only (sums reconcile to the affected counts)
| cell | hit_initial_stop | recovered_insufficiently | reached_tier | recovered_and_improved |
|---|---|---|---|---|
| B / A | 14 | 12 | 6 | 2 |
| D / A | 12 | 4 | 2 | 6 |
| B / B | 21 | 12 | 10 | 1 |
| D / B | 18 | 5 | 3 | 3 |

`hit_initial_stop` dominates every cell. This is the registered structural prior
confirmed empirically: `effective_stop = max(stop_loss, trailing_stop)`, so
suppressing the trail removes a known higher exit and exposes the trade to the lower
initial stop — a certain worse exit now for a speculative recovery later.

## HONEST CAVEAT on the concentration gate
`concentration_10` is 100% in all four cells, but this is **structurally forced and
carries no discriminating information here**: positive-delta counts are 8, 8, 10 and
6, all <= 10, so top-10 necessarily covers the entire positive set. The 50% gate was
designed for a larger positive population. Do not cite 100% concentration as
independent evidence against B and D. The verdict rests on the point estimates and
the cross-universe sign flip.

## Affected-trade definition, corrected
`trail_suppressed` (exit date or reason changed) is retained but is no longer the
affected criterion, because it undercounts. Added: `policy_path_diverged`,
`first_divergence_date`, `first_divergence_event`, `scale_out_path_differed`,
`share_path_differed`, `commission_path_differed`, `exit_path_differed`.
Affected is now `policy_path_diverged`. Gates 2 and 4 use it.

## VERDICT
Registered prior held: B and D fail in both universes. Policy A is retained.
Stage 1 cannot select a policy and stage 2 is not authorized to run for a candidate
that failed stage 1. Default registered outcome stands: **complete Block A and
stop.** Blocks B-D remain closed.

## UNCOMMITTED
`Ares/engine/exit_policy.py` (defect fix), `Athena/engine/exit_policy.py`
(re-vendor), `Athena/engine/parity.py` (md5), `Athena/run_exit_replay.py`,
`Athena/trace_mismatch.py`, this file, and the two results files.
