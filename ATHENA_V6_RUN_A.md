# Athena V6 Run A — the first honest backtest

Run date 2026-09-22. Data snapshot 2026-09-22T06:03:34Z, yfinance 1.6.0,
217/227 symbols. Period 2021-09-01 → 2026-09-01 (4.92 years, 1241 trading days).

One-line summary for the logbook:

> Under causal rules with divergence removed, the frozen parameters lose money on
> both universes — −3.40% and −6.33% CAGR against SPY's +13.39% — with profit
> factor 0.85 and negative expectancy per trade. The V1-V5 edge does not survive
> removal of the look-ahead. Separately, Run A uncovered a new defect: only 12.2%
> of its entries satisfy live Ares' 52-week-high gate, so Run A is causal but is
> **not** yet "as-live" on entries.

## The numbers

| | Universe A (130) | Universe B (98 mid-cap) | SPY B&H | QQQ B&H |
|---|---|---|---|---|
| Final equity from $1,000 | **$843.37** | **$724.49** | $1,856.64 | $1,977.18 |
| Total return | **−15.66%** | **−27.55%** | +85.66% | +97.72% |
| CAGR | **−3.40%** | **−6.33%** | +13.39% | +14.85% |
| Max drawdown (running peak) | **−30.23%** | **−37.76%** | −24.50% | −35.12% |
| Sharpe | −0.20 | −0.22 | — | — |
| Trades | 156 | 243 | — | — |
| Win rate | 26.9% | 31.7% | — | — |
| Profit factor (dollar) | **0.853** | **0.844** | — | — |
| Expectancy / trade | **−$1.04 (−0.41%)** | **−$1.16 (−1.19%)** | — | — |
| Avg win / avg loss | +16.88% / −6.78% | +13.93% / −8.20% | — | — |
| Avg hold | 51 days | 30 days | — | — |
| Commissions paid | $346.00 | $543.00 | — | — |

Both universes lose money. Both lose to buy-and-hold by roughly 17-21 points of
CAGR. Universe B, the sensitivity check, is *worse* than Universe A, so the result
is not an artifact of one stock list.

### It is not just the commission

The obvious rescue is "use a zero-commission broker." That is tested, not assumed:

| | Universe A | Universe B |
|---|---|---|
| Net P&L | −$162.22 | −$281.05 |
| Commissions | $346.00 | $543.00 |
| P&L excluding commissions | **+$183.78** | **+$261.95** |

At zero commission and holding every decision fixed, Universe A returns +18.4%
over 4.92 years — about **+3.5% a year, against SPY's +13.39%**. Universe B gives
+4.8% a year. So commission converts a weak result into a losing one, but removing
it does not produce an edge; it produces significant underperformance of a
one-line index fund at far higher drawdown. $346 of commission on $1,000 of
capital across 156 trades is itself the finding: this trade frequency is not
viable at this account size.

### Where the old edge went

V5 attributed 96% of its dollar P&L to `bearish_divergence` exits. In Run A that
exit does not exist, and what remains is not an edge:

| Exit reason (Universe A) | Trades | Total P&L | Avg | Win rate |
|---|---|---|---|---|
| `stop_loss` | 89 | **−$873.21** | −$9.81 (−6.87%) | 0.0% |
| `trailing_stop` | 59 | +$520.22 | +$8.82 (+6.53%) | 59.3% |
| `emotional_extreme` | 2 | +$115.67 | +$57.84 | 100% |
| `end_of_sim` | 5 | +$47.01 | +$9.40 | 80% |
| `mean_reversion_complete` | 1 | +$28.10 | +$28.10 | 100% |

57% of all trades exit at the stop loss with a 0% win rate, and the trailing stop
cannot cover them. This is the same shape the audit predicted from V5's residual
exits ("trailing stop +3.82% and stop loss −6.38%, which is not obviously an
edge") — now measured on a causal engine rather than inferred from a contaminated
one.

### Yearly, including the 2022 bear market that V1-V3 excluded

Universe A:

| Year | Start | End | Return | Max DD | Trades | Win rate |
|---|---|---|---|---|---|---|
| 2021 (part) | $1,000.00 | $1,016.86 | +1.69% | −2.16% | 2 | 0.0% |
| **2022** | $1,009.61 | $779.60 | **−22.78%** | −27.41% | 45 | 20.0% |
| 2023 | $778.55 | $895.39 | +15.01% | −7.13% | 15 | 26.7% |
| 2024 | $889.16 | $975.51 | +9.71% | −9.52% | 28 | 25.0% |
| **2025** | $969.40 | $792.18 | **−18.28%** | −26.14% | 31 | 19.4% |
| 2026 (part) | $796.04 | $843.37 | +5.95% | −10.13% | 35 | 45.7% |

2022 is the worst year, as expected — but **2025 is nearly as bad at −18.28%**,
and 2025 was not a bear market. That is the more damaging observation: the strategy
does not merely suffer in a downtrend, it bleeds in ordinary conditions too.

## What Run A is, and what it is not

**It is:** causal end to end. Every check below passes in `validate_v6.py`,
including a truncation test that recomputes indicators on data ending at bar `i`
and confirms the divergence flag at bar `i` is unchanged — the direct test V1-V5
never had.

| # | Must-fix | Status |
|---|---|---|
| 1 | Swings confirmed at `i+window`, never back-dated | done — `indicators.py`, proven by truncation test |
| 2 | Stop exits never booked at the stop price | done — exits fill at the next bar's open |
| 3 | Correct `hidden_bull_div` / `hidden_bear_div` keys | done |
| 4 | Max drawdown from the running peak | done — test shows −40% vs V1-V5's −5% on the same curve |
| 5 | `peak_after_exit` / `missed_upside_pct` out of parameter selection | done — the fields do not exist |
| 6 | Stop distance from returns stdev, matching live Ares | done — `entry × stdev_20 × 2.0`, no `Close×0.05` fallback |
| 7 | Exits next-bar, like entries | done — one-sided hindsight removed |

Accounting is fixed *and enforced*: `reconcile()` fails the run if reported P&L
differs from the actual cash delta, and the scale-out leg is now fully written to
the CSV so the V5 commission defects could not hide again.

**It is not a re-optimisation.** `tp_momentum 0.18` and `trailing_stop_pct 0.10`
are the live values and no alternative was tried. This document reports what they
do.

## Limitations, worst first

### 1. Only 12.2% of Run A's trades could have been taken by live Ares — NEW defect

This was found during Run A and is not in the audit's defect list. Live Ares'
`check_momentum_breakout` (`Ares/engine/signals.py:101-114`) requires:

```python
if latest['pct_from_high'] < -0.01:   return None   # within 1% of 52-week high
if latest['vol_ratio'] < params['min_vol_ratio']: return None
if latest['macd'] < latest['macd_signal']: return None
```

Athena's `_check_entry`, inherited unchanged from V1-V5 into V6, has **no
52-week-high condition at all**, and adds an `rsi > 50` filter that live does not
have. Measured on Run A's 148 momentum_breakout trades, only **18 (12.2%)** were
within 1% of the 52-week high on their signal date.

So the backtest's "momentum_breakout" is not a breakout strategy. Run A is a valid
causal measurement of *the rule Athena implements*, but it is **not** the honest
benchmark for live Ares that the roadmap wanted, because 88% of its trades are
entries live Ares would refuse. The range branch has a smaller version of the same
problem: live counts `near_sma_support` as a fourth confluence term and Athena
omits it (75% of Run A's 8 mean_reversion entries would have qualified).

Deliberately **not fixed here.** Adding an entry gate changes the trade
population, which belongs at a declared boundary, not inside a run whose purpose
is to measure frozen parameters. Recommended next step, and it is a correctness
fix rather than a re-optimisation: a Run A′ using live's actual entry predicates.

### 2. Survivorship is not controlled for — and is now measured

11 of 227 symbols (4.8%) had to be excluded because the data source no longer
serves their history: `ARCH CEIX CFLT GPS HA HAYN MESA SAVE SIX X` returned empty
frames, and `DINE` has only 96 bars from 2026-05-05. Every one is a corporate
action — merger, acquisition, bankruptcy or symbol change.

That is the bias made concrete. The universe was written from memory in 2026, so
it can only contain companies that survived; the ones that died are absent, and
their absence removes exactly the left tail a stop-loss strategy exists to
survive. **4.8% is a floor on the bias, not an estimate** — names forgotten before
the list was written never had a chance to appear. Fixing this needs paid
point-in-time index membership.

Direction of the error is worth stating plainly: survivorship flatters. The real
result is likely *worse* than reported, not better.

### 3. 95% of signals never became trades — the result is a slot lottery

| | Universe A | Universe B |
|---|---|---|
| Signals generated | 3,135 | 2,497 |
| Entries filled | 156 (5.0%) | 243 (9.7%) |
| Signals queued | 2,931 | 2,182 |
| Entries from queue | 0 | 1 |

With `max_positions: 5` and $1,000 of capital, the 5-slot cap rejects 95% of
signals, and the queue re-check almost never fires (0 and 1 entries respectively),
so queued signals essentially all expire. The reported result therefore depends
heavily on *which* few signals happened to arrive while a slot was free — close to
arbitrary. 48 and 72 further signals were refused for producing a position under
$20.

This limits confidence in the exact figures far more than it limits the direction.
A run at a capital level where the cap does not bind would measure the rule itself
rather than the slot ordering — but that is a different question and a separate
declared run, not a tweak to this one.

### 4. Same window as V1-V5, so this is not a holdout

Run A shares the 2021-2026 window with V5. That is acceptable here only because
**nothing was fitted** — no parameter was varied or selected. It is not evidence
that the parameters generalise. A genuine re-fit would need fit 2021-2024, test
2024-2026, reporting only the test result, and would open its own sample phase.

### 5. Single vendor, retroactively adjusted

All data is yfinance `auto_adjust=True`, snapshotted once and committed. Prices are
split- and dividend-adjusted as of the snapshot date, which is not what a trader
saw at the time. No second vendor was used to cross-check.

## Verdict

**What this licenses:** the claim that the V1-V5 edge was largely an artifact of
the look-ahead is now supported by direct measurement rather than inference. The
retraction of "Athena-optimized parameters" stands, and is strengthened.

**What this does not license:** "the strategy family is dead." Run A measures a
rule that is not the live rule (limitation 1), on a survivorship-flattered
universe (2), through a slot cap that rejects 95% of signals (3). The honest
statement is: *the rule Athena implements, with these parameters, loses money
causally on this data, and the live rule has not yet been measured at all.*

**What must not happen:** re-tuning `tp_momentum` or `trailing_stop_pct` against
these numbers. That is exactly how the original figure was manufactured, and this
window is now thoroughly used.

**Recommended next step:** Run A′ — the same engine with live Ares' actual entry
predicates, closing limitation 1. That is a correctness fix, and it determines
whether the live system has ever been measured. It ranks above Run B (divergence
repaired at `i+5`), which answers a "repair or delete the dead code" question and
remains out of scope.

**Live Ares:** no change is implied. `clean_v3` continues as the only
uncontaminated evidence stream, and Run A does not touch it. Run A's disappointing
result is not grounds for restarting the live sample.

## Reproducing this

```bash
cd ~/Olympus/Athena
PYTHONPATH=vendor python3 snapshot_data.py      # idempotent; data already committed
PYTHONPATH=vendor python3 validate_v6.py        # 16 causality/accounting checks
PYTHONPATH=vendor python3 run_backtest_v6.py    # Run A
```

Outputs, none of which overwrite V1-V5:

```
results/v6_runA_A_original_130_{trades,equity,yearly,exits}.csv
results/v6_runA_B_midcap_98_{trades,equity,yearly,exits}.csv
results/v6_runA_summary.json
```

Environment traps that will bite on a fresh machine are in
[PROVENANCE.md](PROVENANCE.md) — Yahoo's 429 against yfinance's default session,
and the disappearance of `pandas_ta` 0.3.x from PyPI.
