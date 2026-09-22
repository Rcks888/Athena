# Athena V6 Run A′ — live predicates, causal, funded

**Date:** 2026-09-22
**Baseline:** Run A, commit `134c589`, preserved unmodified
**Supersedes:** the first A′ pass, kept at `results/superseded_runA2_no_cash_gate/`,
which financed a quarter of Universe B on an overdraft that cannot exist.

---

## The finding

**On the mega-cap universe the strategy has a positive gross edge that the fixed
commission then consumes. It is not a losing strategy so much as a strategy whose
edge is smaller than its friction at this position size.**

| Universe A (130) | |
|---|---|
| Gross P&L before commission | **+$273.21** ← gross-profitable |
| Commission (145 closed trades) | **−$331.00** |
| **Net P&L** | **−$57.79** |
| Commission as % of gross profit | **121.2%** |
| Gross edge per trade | **+$1.88** |
| Commission per trade | **−$2.28** |

At $149 per position, $1.00 each way is **1.34% round-trip** against a gross edge of
about **1.26%**. The edge is real and it is smaller than the toll. Win rate is 32.4%
before commission and 30.3% after — commission alone flips 2.1% of trades from
winners to losers.

**This must be tempered, and the control universe does temper it.** Universe A is
the survivorship-flattered mega-cap list. Universe B — the nominal control — is
**gross-negative at −$269.85 before commission**, so it has no edge for commission
to consume. **No edge is established.** What is established is a sharper diagnosis
than "the strategy loses money": on the flattered universe the gross edge exists and
is eaten by fixed costs, and on the control it does not exist at all.

---

## Headline numbers

`2021-09-01 → 2026-09-01`, 0.10% slippage, $1.00/fill, next-bar fills both sides,
divergence removed from the decision set, static $149 stake, **broker funding
enforced**.

| | Universe A (130) | Universe B (98) |
|---|---|---|
| Final equity | **$944.25** (−5.58%) | **$426.77** (−57.32%) |
| Gross P&L / commission / net | +$273.21 / −$331.00 / **−$57.79** | −$269.85 / −$326.00 / **−$595.85** |
| Max drawdown (running peak) | −34.65% (2023-05-23) | −67.55% (2026-02-26) |
| Sharpe | −0.02 | −0.74 |
| Closed trades | 145 | 148 |
| Win rate (before → after commission) | 32.4% → 30.3% | 30.4% → 25.7% |
| Profit factor | 0.941 | 0.537 |
| Expectancy / trade | −$0.40 | −$4.03 |
| Entries refused, insufficient cash | 16 | **305** |
| Still open at end | 5 pos, +$2.05 | 2 pos, +$22.62 |

Benchmarks: **SPY +85.66%**, **QQQ +97.72%**. Buy-and-hold deploys the full $1,000
and compounds; Run A′ risks at most 5 × $149 = $745 and never reinvests, so this
compares strategies, not equal capital at risk.

**No CAGR is reported.** Under a fixed non-compounding stake an annualised compound
rate describes money this run never had. The field is *absent* from the summary
rather than captioned, because a labelled number survives its caveat and gets quoted
later — that is precisely how "PF 2.41 over 1060 trades" reached Ares' README.
Run A's `cagr_pct` is left untouched: it genuinely compounded, so the figure was
valid there and `ROADMAP.md` quotes it.

---

## The funding constraint, and why adding it is not "fixing live"

The previous A′ pass reproduced live Ares faithfully — including that **live tracks
no cash balance and checks funding nowhere.** That reproduced live's *missing check*,
and the result was not faithful but impossible:

| | overdrawn days | worst overdraft |
|---|---|---|
| Universe A | 39 of 1241 (3.1%) | −$105.15 |
| **Universe B** | **309 of 1241 (24.9%)** | **−$356.00** |

Live Ares trades through IBKR, and **IBKR enforces what live's code omits** — those
orders would have been rejected. The broker is part of the live system, so modelling
its funding rule **completes** the model rather than editing the strategy. This is
categorically different from the inert `RSI`/`EMA_20` queue gates, which no external
party enforces and which remain reproduced as-is.

The gate is the broker's rule — cash must cover the debit — and explicitly **not**
the 25% reserve. Live never enforces a running reserve; `cash_reserve_pct` appears
only in the formula deriving the static stake. The debit includes commission, because
commission is part of what the broker debits; gating on the stake alone would leave
cash at −$1.00 per fill and quietly reintroduce the overdraft.

After gating, minimum cash is **$10.20** (A) and **$0.14** (B), with zero overdrawn
days. Solvency is now asserted on **every** simulated day. The old assertion tested
terminal cash only, which is why a 309-day overdraft that had recovered by the final
bar never tripped it — and its comment, "at 5 slots × $149 it cannot overdraw", was
false: the stake is constant while equity falls.

Universe B refused **305 entries** for want of funding, against 16 in A. That is the
constraint biting exactly where the account had collapsed to ~$340, and it is why B
got *worse*: the strategy was denied the entries it needed while its losers still
ran.

---

## Movement in both directions, twice

| | Run A | A′ ungated | **A′ funded** |
|---|---|---|---|
| Universe A | −15.66% | −8.46% | **−5.58%** |
| Universe B | −27.55% | −43.89% | **−57.32%** |
| A max DD | −30.23% | −38.01% | −34.65% |
| B max DD | −37.76% | −59.75% | −67.55% |

Both corrections — the ~30 parity defects, then the funding constraint — moved
Universe A up and Universe B down. Refusing entries removes winners and losers
alike, and the direction was not predictable in advance. Neither pass changed the
conclusion that neither universe is profitable net of costs.

---

## Live defects recorded, not fixed

Three, now, in `REPRODUCED_LIVE_DEFECTS`. None are repaired in Athena; fixing live
behaviour inside the backtest is how the backtest and the live system drifted apart.

1. **Queue promotion gates are inert.** `tracker.py:400,403` read `latest.get('RSI',
   50)` and `latest.get('EMA_20', 0)`, but `add_indicators` emits lowercase `rsi` and
   **never emits `EMA_20` at all**. RSI always reads 50 and can never reject; EMA20
   always compares against 0 and can never reject. **Live promotion is
   `|drift| ≤ 5%` and nothing else.**
2. **All four divergence reads are structurally False in production.** The pivot loop
   stops at `len − window − 1` while live reads `len − 1`.
3. **Live sizes from `starting_capital` as a constant and never checks a balance**
   (`tracker.py:119-123`). As the account declines the static $149 becomes a growing
   fraction of equity and live will attempt orders IBKR rejects: **at $427 equity,
   5 × $149 = $745 is unfundable.** This has real consequences before June 2027.

None of the three are in the parity audit's list. All three are Ares' to fix, in
Ares.

---

## Validation — 33 checks, all passing

The centrepiece remains general rather than targeted, because Run A passed every
targeted causality check and still hid a look-ahead in sizing that no targeted test
covered. `test_future_perturbation_cannot_change_the_past` corrupts every bar after a
cut date (prices ×50, RSI→99, MACD inverted) and asserts all 56 pre-cut trades are
identical across 8 fields.

New this pass: cash non-negative on **every** day; every order-drop path and equity
skip counted (9 paths); `cagr_pct` **absent** from the summary; per-trade
`gross = net + commission` re-derivable from the CSV; `max_drawdown_date` a date even
when the trough sits at row 0; queue ordering matching live.

Corrected this pass:

- **`max_drawdown_date` returned `0`** instead of a date when the worst drawdown sat
  at row 0 — `index[0]` is falsy, so `and` short-circuited to the integer.
- **Equity silently dropped a held symbol with no bar that day**, understating equity
  and drawdown with no counter. Now carries the last known mark forward and counts
  occurrences (0 in both universes, so no figure changed).
- **`queue_max_size` was hardcoded** where live reads `params.get('queue_max_size',
  10)`. Identical today, divergent the moment the key is added.
- **Queue eviction and duplicate handling differed from live.** Live evicts on
  `(-confluence, date_added)` and keeps the **first** duplicate; the sim ranked with
  `|drift|` as a second key and kept the highest-confluence duplicate. Drift now
  appears only in the promotion test.
- **Pending orders dropped for being already held or having no slot had no counter**,
  unlike every other drop path.
- **Commission was summary-only**, so the gross/net split could not be audited from
  the CSV. `pnl_before_commission` and `win_before_commission` are now trade fields.
- **Two commission figures looked like one figure disagreeing with itself** ($331 vs
  $337). Both are correct and differently scoped: $331 on closed trades, plus $6 of
  entry and scale-out commission on the 5 still-open positions. Both are now named.

---

## What this does and does not establish

**Establishes.** Under frozen parameters, on this window, with real friction, live's
actual entry rules and an enforced funding constraint, neither universe is profitable
net of costs. Universe A is gross-profitable and commission-negative; Universe B is
gross-negative. Profit factor 0.941 and 0.537. B's −67.55% drawdown is not
survivable.

**Does not establish.** That any other parameter set fails. Nothing was varied.
The commission finding makes it tempting to argue for fewer, larger positions — **that
is a design question for Ares V4, not a parameter to tune here.** Re-fitting on this
window is how the original inflated figure was manufactured; a real re-fit needs
fit 2021–2024 / test 2024–2026 and reports only the test result.

**Still open.** Run B (divergence repaired, confirmed at `i+5`) remains out of scope.

**The 2024 anomaly persists.** Both universes were profitable in 2024 (A +24.61%,
B +9.87%) and lost in every other year. One good year in six is what a momentum
strategy looks like when fitted to a trend that then stopped. Not a reason to re-fit
on 2024.

---

## Reproducing

```bash
cd ~/Olympus/Athena
PYTHONPATH=vendor python3 validate_v6.py            # 33 checks
PYTHONPATH=vendor python3 run_backtest_v6_runA2.py  # ~2 min
```

Data is the committed snapshot in `data/ohlcv/` (217 CSVs, tracked in git alongside
`data/snapshot_manifest.json`) — no network access, so the run is bit-reproducible.
`run_backtest_v6.py` (Run A) is retired with a hard refusal; Run A is reproduced by
checking out `134c589`.

`vendor/` pins (numpy 2.2.6, pandas 3.0.5, pandas_ta 0.4.71b0, yfinance 1.6.0) are
**load-bearing for comparability** with live. See `PROVENANCE.md`, which also records
the Yahoo HTTP 429 trap that silently produced zero rows for all 227 symbols on the
first attempt.
