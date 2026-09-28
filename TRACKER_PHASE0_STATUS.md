# Tracker migration Phase 0 — differential equivalence: COMPLETE

Harness `run_tracker_equivalence.py`. Output `results/tracker_equivalence_summary.json`.

**NOT a Block A experiment.** Block A stage 1 is closed — B and D failed, Policy A
retained. Nothing here reopens it, recalculates its gates, or depends on its result.

**PASSING DOES NOT AUTHORIZE THE SWAP.** It clears Phase 0 only.

## The question Phase 0 answers

Gate 1 proved the canonical module reproduces Athena's Run A' output — but Athena was
itself delegated to the module in `b70bed2`, so that proved the delegation was
behaviour-neutral *for Athena*. The link never tested was:

    Ares/engine/tracker.py inline chain  <->  engine/exit_policy.py

The module was hand-transcribed from tracker.py and nothing had verified the
transcription against its source. The future swap assumes that equivalence.

## Method

`check_open_trades()` reads `latest = df.iloc[-1]`, so a frame truncated to bar *i*
steps it exactly one bar. Its I/O boundary is injected (`load_trades`, `save_trades`,
`load_stock`, `get_live_price`, `add_indicators`, `expire_queue`) and restored after
each call. **`tracker.py` was never modified.** `get_live_price` is forced to `None`
so `current_price` is the daily Close, matching what the module is handed. State
objects are `deepcopy`d so neither implementation's mutation can reach the other.
Equivalence is asserted per transition, never on final P&L.

## Populations

| Population | Cases | Bars |
|---|---|---|
| Boundary fixtures | 20 | 40 |
| Historical Run A' paths | 250 | 4,690 |

Coverage gaps, reported not hidden: 0 symbols absent from the 220-symbol snapshot;
**43 entries classified `UNTESTED_INSUFFICIENT_WARMUP`** — not passed, not failed.
Cause analysis and live-reachability verdict in
`Ares/TRACKER_MIGRATION_PLAN.md`. Historical decision coverage is therefore
**250 of 293 paths**, with **43 of 43 excluded paths classified and explained**.

Boundary fixtures probe each threshold from below, at, and above, on **both**
strategies: TP at +10% reversal and +18% momentum; the stop; trailing-stop versus
initial stop; peak either side of +11.11%; already-scaled precondition; zero
volatility; a missing bar; and the `mean_reversion_complete` RSI branch that the
latent divergence `elif` can starve.

## RESULT

**0 mismatches requiring contract resolution. 0 decision-changing mismatches.**

No difference in `exit_reason`, `status`, termination, `scaled_out` or
`scale_out_date` on any bar of any case.

8,616 stored-value differences were found and **every one is reproduced exactly** by
applying tracker's own rounding discipline to the module's value — not accepted under
a widened tolerance, but re-derived to 1e-9:

- `tracker_2dp_rounding` — `round(module_value, 2)` equals tracker's stored value
- `tracker_rounding_compounded` — tracker derives `effective_stop` from
  already-rounded state, applies the fill model, then rounds again;
  `round(round(eff, 2) * (1 - slippage), 2)` reproduces tracker exactly

## The one real contract difference, documented not fixed

`tracker.py` stores `round(peak_price, 2)`, `round(trailing_stop, 2)`,
`round(shares, 2)` and `round(scale_out_price, 2)`. The module rounds only inside
`instrument_close` (reporting) and keeps full precision in `update_peak`.

**Rounded state feeds the next bar**, so this is a genuine contract question, not
cosmetic.

Correct wording, which is stronger and more accurate than claiming equivalence:

> **No decision-changing differences were detected within the tested population.
> Full-precision and tracker-rounded state are not universally equivalent by
> construction.**

A future price could land close enough to a threshold for the difference to change a
decision. 4,730 bars is evidence, not proof.

**Which side is correct is NOT decided here.** `tracker.py` is live, so equivalence
means *the module reproduces tracker's current behaviour*. If tracker's rounding is
itself undesirable, changing it is a separate production change and must not be
hidden inside canonicalization.

## Two harness defects found first, and what they cost

Worth recording, because both initially looked like implementation divergence:

1. **Double `add_indicators`.** The slice was pre-augmented, then tracker applied
   indicators again. On short pre-entry history it returns `None`, which tracker's
   bare `except Exception` swallows into a silent no-op **indistinguishable from
   "no action taken"**. This manufactured a false `status open vs closed` divergence
   on XOM and SLB, and a false exception on GILD.
2. **Comparing a decision price to a fill price.** `decide_exit` returns the decision
   price; `_close_trade` owns the fill and applies exit slippage. 27 false
   `exit_price` mismatches until the module's value was mapped through Ares' fill
   model.

Both were harness errors, not defects in either implementation. Neither side was
changed to make the harness pass.

## Phase 0 is clear. The swap is still held.

Remaining prerequisites, none of which this harness satisfies:

- ABM and SDGR clear, so the swap cannot land mid-position on a pre-clean trade
- The 2dp rounding contract is explicitly decided, either way
- A rollback point exists
- Shadow comparison completed
- The deployment commit contains **only** the import and call-site changes
