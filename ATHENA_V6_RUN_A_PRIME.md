# Athena V6 Run A′ — the first backtest that runs Ares' own strategy code

**Date:** 2026-09-22
**Baseline:** Run A, commit `134c589`, preserved unmodified
**Verdict:** the strategy loses money on both universes. Correcting ~30 parity
defects moved the result **in both directions** and changed nothing about that.

---

## 1. What Run A′ is, and why Run A had to be replaced rather than patched

Run A was causal. Its numbers were honest about look-ahead. But it measured **a
hand-written reimplementation of the strategy, not the strategy.**
`portfolio_sim_v6.py` imported only `data_feed` and `indicators` and re-expressed
every entry rule in its own `_check_entry`, while `engine/signals.py` sat beside it
as a near-copy that **nothing imported**. An independent parity audit found ~30
divergences from live Ares, plus a look-ahead the reimplementation had introduced
on its own.

Patching those thirty items individually would have left the defect class intact,
because the next edit to Ares diverges again. So Run A′ **calls live's predicates**:

- `engine/signals.py` is now a **byte-identical copy** of `Ares/engine/signals.py`
  (md5 `da2ba2596cf43f6405dfd4521824c33d`).
- `engine/parity.py` asserts that checksum **at import**, so no code path can reach
  a simulation with a drifted copy.
- `engine/live_adapter.py` hands those predicates `df.iloc[:i+1]`. Causality stops
  being a claim about our code and becomes a property of the data they receive —
  a function cannot read bar `i+1` that is not in the frame it was given.

The drift was already real and measurable when this was built. Athena's dead copy
was **one functional line** behind live: Ares V3 added a `disable_trend_cont` gate
to the dispatcher and the copy still had the ungated `if not signal:`. One line, in
the code that decides which strategies may fire, silently wrong. That is the whole
argument for a checksum over a copy.

---

## 2. Headline numbers

`2021-09-01 → 2026-09-01`, 0.10% slippage, $1.00/fill, next-bar fills on both
sides, divergence removed from the decision set, **static $149 stake**.

| | Universe A (130) | Universe B (98) |
|---|---|---|
| Final equity | **$915.35** | **$561.07** |
| Total return | **−8.46%** | **−43.89%** |
| Non-compounding CAGR | −1.78% | −11.07% |
| Max drawdown (running peak) | −38.01% | −59.75% |
| Sharpe | −0.05 | −0.39 |
| Closed trades | 150 | 180 |
| Win rate | 30.0% | 26.7% |
| Profit factor (true dollar) | **0.922** | **0.702** |
| Expectancy / trade | −$0.52 | −$2.56 |
| Net realised P&L | −$77.47 | −$461.56 |
| Commissions | $345.00 | $405.00 |
| Still open at end | 5 pos, −$7.18 unrealised | 2 pos, +$22.62 unrealised |

Benchmarks over the same window: **SPY +85.66%**, **QQQ +97.72%**.

> Buy-and-hold deploys the full $1,000 and compounds. Run A′ risks at most
> 5 × $149 = $745 and never reinvests. The comparison is of strategies, not of
> equal capital at risk.

---

## 3. Run A → Run A′, and the comparison that is NOT valid

| | Run A (A) | Run A′ (A) | | Run A (B) | Run A′ (B) |
|---|---|---|---|---|---|
| Total return | −15.66% | **−8.46%** | | −27.55% | **−43.89%** |
| Max DD | −30.23% | −38.01% | | −37.76% | −59.75% |
| Trades | 156 | 150 | | 243 | 180 |
| Win rate | 26.9% | 30.0% | | 31.7% | 26.7% |
| Profit factor | 0.853 | 0.922 | | 0.844 | 0.702 |
| Signals | 3,135 | 935 | | 2,497 | 599 |
| Entries from queue | 0 | 31 | | 1 | 14 |

**Universe A improved, Universe B got substantially worse, and drawdown worsened on
both.** This was the outcome stated in advance: correcting a mismatch does not
improve a strategy, it **selects a different population**. The thirty defects did
not point one way and did not cancel.

**`cagr_pct` is not comparable between the two runs.** Live sizes positions at a
static $149 and does not compound; Run A used
`min(cash − equity×0.25, equity×0.20)`, which does. Run A's positions started ~33%
larger and grew with the equity curve. The two CAGRs describe **different money**.
`results/v6_runA2_summary.json` records `return_basis: fixed_stake_non_compounding`
and `comparable_to_run_a: false` so the figures cannot later be tabulated as like
for like.

---

## 4. The four corrections that moved the number

1. **Sizing is static and non-compounding** (`tracker.py:123`, $149 fixed). This is
   also what removed Run A's own look-ahead: `:300` sized from today's Close for an
   order filling at today's Open. There is now no equity read at fill time at all,
   so the defect cannot recur by construction.
2. **Queue promotion no longer re-requires the signal.** Live promotes on drift
   alone. Run A demanded a full fresh signal on the promotion bar, so **2,931
   queued signals produced 0 entries**. Run A′: 811 queued, **31 entered**.
3. **Scale-out is checked before exits and short-circuits them** (`tracker.py:814`).
   Run A checked exits first, letting an `emotional_extreme` (rsi > 90, common
   exactly at a profit target) liquidate a whole position where live banks half and
   rides the rest. This hit **winners specifically** — scale-outs rose 34 → 40 on A.
4. **Signal volume fell 3,135 → 935** (−70%), because live's real entry gate
   includes a 52-week-high proximity test the reimplementation lacked, and lacks a
   phantom `rsi > 50` the reimplementation had added.

**One correction turned out inert.** Live substitutes `stdev_20 = 0.05` and fills
where Run A refused, so this was expected to add a wide-stop population. It added
**zero trades**: indicators are computed on full history *before* the window is
sliced, so `stdev_20` is always warm. The trade record carries a `stdev_fallback`
flag anyway, so if the mechanism ever does fire those trades can be segmented
rather than silently averaged into the headline.

---

## 5. Live defects reproduced deliberately, not fixed

Run A′ measures the system Ares **is**, not the one its source appears to describe.

- **The queue's RSI and EMA20 gates are inert.** `tracker.py:400,403` read
  `latest.get('RSI', 50)` and `latest.get('EMA_20', 0)`, but `add_indicators`
  produces lowercase `rsi` and **never produces `EMA_20` at all**. The RSI check
  always sees 50 and can never reject; the EMA20 check always compares against 0
  and can never reject. **Live promotion is `|drift| ≤ 5%` and nothing else.**
  *This was found while building Run A′ and is not in the parity audit's list* —
  same inert-gate class as the six dead config keys.
- **All four divergence reads are structurally False in production.** Live's pivot
  loop stops at `len − window − 1` while live reads `len − 1`. `indicators.py` is
  now causal and *can* flag the latest bar, so faithfulness required masking those
  columns — otherwise the backtest would fire an exit live is incapable of firing.

Neither is repaired here. Fixing live behaviour inside the backtest is precisely how
the backtest and the live system drifted apart in the first place. Both belong in
Ares, as live changes, measured afterward.

---

## 6. Validation — 24 checks, all passing

The important addition is a **general** look-ahead test, because Run A passed every
targeted causality check and still contained a look-ahead in sizing that no
targeted test covered, since nobody suspected sizing.

`test_future_perturbation_cannot_change_the_past` runs the simulation to a cut date,
re-runs it with **every post-cut bar corrupted** (prices ×50, RSI forced to 99,
MACD histogram inverted), and asserts that all 56 pre-cut trades are identical
across 8 fields. Any read of a future bar — in entry logic, exit logic, sizing,
stops or fills — changes something and fails. It would have caught the sizing
defect **without being told to look for it**, and passes now.

Also added: static-sizing invariance (stake spread $0.000013 across the run),
no-exit-on-entry-bar, scale-out short-circuit, no `end_of_sim` liquidation, the
adapter slice check (776 predicate calls verified to receive a frame ending exactly
at the decision bar), and a reconciliation that now spans **both books** — realised
plus unrealised P&L must equal the change in total equity, reconciling to $0.0005.

Two of Run A's tests were themselves wrong and were corrected:
- The adapter slice check probed only the last 40 bars of one symbol, so it failed
  for want of an uptrend rather than for a defect. Now scans whole series across
  three predicates. *(Second time a data-dependent test has had to be fixed here.)*
- "No fabricated 0.05 fallback" asserted the opposite of live behaviour. Now
  asserts any fallback trade is **flagged**, rather than that it never happens.

---

## 7. What this does and does not establish

**Establishes.** Under its frozen parameters, on this window, with real friction and
live's actual entry rules, the strategy loses money on both universes and
underperforms SPY by ~94 points on Universe A. Profit factor below 1.0 on both.
Universe B's −59.75% drawdown is not survivable in practice.

**Does not establish.** That any *other* parameter set fails. Nothing was varied —
`tp_momentum 0.18` and `trailing_stop_pct 0.10` were measured, not chosen. Re-tuning
on this window is how the original inflated figure was manufactured; a real re-fit
needs fit 2021–2024 / test 2024–2026 and reports only the test result.

**Still open.** Run B (divergence repaired, confirmed at `i+5`) remains out of
scope. The divergence exit produced ~96% of V5's dollar P&L and **cannot fire live
at all**, so repairing it is a live change to Ares and a new measurement, not a
rerun.

**The 2024 anomaly.** Both universes were solidly profitable in 2024 (A +23.70%,
B +37.66%) and lost money in every other year. One good year in six is what a
momentum strategy looks like when it is fitted to a trend and the trend stops. It is
not a reason to re-fit on 2024.

---

## 8. Reproducing

```bash
cd ~/Olympus/Athena
PYTHONPATH=vendor python3 validate_v6.py            # 24 checks
PYTHONPATH=vendor python3 run_backtest_v6_runA2.py  # ~2 min
```

Data is the committed snapshot in `data/ohlcv/` (217 CSVs) — no network access, so
the run is bit-reproducible. `run_backtest_v6.py` (Run A) is **retired with a hard
refusal**: the engine beneath it was restructured, so any result it could now
produce would be a hybrid of two rule sets. Run A is reproduced by checking out
`134c589`.

`vendor/` pins (numpy 2.2.6, pandas 3.0.5, pandas_ta 0.4.71b0, yfinance 1.6.0) are
**load-bearing for comparability** with live. See `PROVENANCE.md`, which also records
the Yahoo HTTP 429 trap that silently produced zero rows for all 227 symbols on the
first attempt.
