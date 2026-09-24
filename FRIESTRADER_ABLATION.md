# FriesTrader mechanical-layer ablation — PRE-REGISTERED

**Written 2026-09-24, before any result exists.** Committed ahead of the run so the
decision rule cannot be adjusted after seeing the number. Same discipline as the
momentum substitution test, where pre-registration caught a specification error in
our own gate.

Subject: `github.com/YizhiSong/FriesTrader` @ `4584136`

---

## What is being tested, and what cannot be

FriesTrader splits cleanly into a deterministic layer and a judgment layer.

| Decides | Mechanism | In scope |
|---|---|---|
| Universe filters, signal gate | `risk_rules.json` | YES |
| Stop loss (2.5 x sigma20, clamp 5-15%) | `stop_loss.py` | YES |
| Tiered take profit (+15/+30/+50%, 25% each) | `take_profit.py` | YES |
| Entry gap <= 3%, extension <= 10% over MA20 | `entry_gate.py` | YES |
| Sizing, slots, cash buffer, loss limits | `position_sizing.py`, `pnl_pct.py` | YES |
| Ranking | `rank_candidates.py` | YES |
| **`direction`: long vs avoid** | **Claude** | **NO** |
| **`conviction`: high / medium / low** | **Claude** | **NO** |
| **`risk_flags` from live news search** | **Claude** | **NO** |

The judgment layer is not backtestable and this run does not pretend otherwise.
Three independent reasons, any one of which is sufficient:

1. **Training-data leakage.** The model's weights already contain the outcome of any
   historical date. Unlike Athena's own look-ahead bug, this is not repairable by
   changing the loop.
2. **No point-in-time news archive.** `risk_flags` and the thesis depend on a live
   web search that cannot be replayed as of a past date.
3. **Non-determinism and model drift.** There is nothing stable to checksum.

**Therefore this run answers one question only:** does the mechanical layer, with
stock selection stripped out, have an edge? It does not and cannot measure Claude's
contribution.

## Method

Their scripts are **executed by subprocess, not reimplemented**, with md5 pinning on
each. Run A measured a hand-written reimplementation that had drifted from live in
~30 ways; Run A' fixed that by importing the real code. The same rule applies here.

```
conviction_trim.py  e198c45035a52880d4bb87bd1c4d1b22
entry_gate.py       2e6ea1e3aabc833b8d9e5e7308aef830
pnl_pct.py          253a8da9240a71c9f6fdd7162934a265
position_sizing.py  f06bbc7a7b3c58d461c363342832e6b6
rank_candidates.py  cc24d452b67aadfe98986e9b2febf76d
stop_loss.py        b330f93d08dfde2d9dafb1eee715bece
take_profit.py      335dc29d37f99fc45647901a93f3dc40
risk_rules.json     2129571187126e5d42022fde18055635
```

**Null selection replaces the LLM.** Two arms:

- **Arm M (mechanical)** — every symbol passing the screen is `direction: long`,
  `conviction` fixed, `risk_flags` empty. Their own `rank_candidates.py` then
  orders candidates. With conviction fixed and no risk flags the sort degenerates to
  `pct_below_52wk_high` descending, which is a real tiebreak in their code, not one
  we invented. Fully deterministic.
- **Arm R (random)** — random pick from qualifying candidates, 200 seeds, producing
  a distribution rather than a point estimate.

Arm R matters because it lets the author's reported weeks be placed as a percentile
against luck, which is the comparison his own data cannot supply.

**Exposure arms.** `conviction` is run at both `high` (0.20 x 4 = 80% invested) and
`medium` (0.12 x 4 = 48%), because exposure is not a free parameter — it drives the
SPY comparison directly. Return on deployed capital is reported alongside total
return, the correction Run A' required.

Window **2021-09-01 to 2026-09-01**, which includes 2022. $1,000 notional,
compounding (their sizing is a percentage of `total_value`, unlike Ares' fixed stake).
$0 commission, since the deployment is Robinhood. Slippage 0.05%.

## Known deviations — declared in advance

| Deviation | Effect |
|---|---|
| **No point-in-time market cap.** The $2B-$50B band cannot be applied; Universe B (midcap_98) is the proxy | Universe differs from the live deployment's |
| **Fixed universe chosen in 2026** | **Survivorship and hindsight. Biases results UPWARD** |
| No Robinhood supplementary scan | Only the watchlist path is modelled |
| `conviction_trim` inert under fixed conviction | Documented, not silently dropped |
| Daily bars, close-to-close | Intraday stop fills are approximated |

## Pre-registered decision rule

Primary metrics on Arm M, `conviction: high`:

1. **Net excess vs SPY total return**, on deployed capital
2. **Annualised alpha vs MTUM**, same regression as the momentum substitution test
3. **Max drawdown**, 2022 included

**The rule, fixed now:**

- **alpha >= -2%/yr AND net excess vs SPY >= 0** -> the mechanical layer has a
  foundation. The open question becomes the LLM's contribution, and forward paper
  testing with pre-registration is justified.
- **alpha <= -3%/yr OR net excess vs SPY < 0** -> **ADVERSE.** The mechanical
  foundation subtracts. Any edge would have to come entirely from LLM stock
  selection, for which the whole evidence base is eight live weeks containing at
  least three different rule sets. **Do not fund.**
- **alpha between -3% and -2%** -> INCONCLUSIVE, which defaults to not funding.
  No action requires no evidence.

Economic magnitude first, significance second. Report the CI; do **not** require
p < 0.05. Low power must never read as absolution. Eight weeks at n=8 has no power
to speak of, and neither does a −2% reading with a ±15% interval.

## The asymmetry that makes this worth running

The universe is contaminated **in the strategy's favour**. It is a list of symbols
that existed and were liquid in 2026, screened over a window ending at the list's own
construction date.

So the two outcomes are not symmetric:

- **A negative result is strong.** If the rules cannot beat SPY even with a
  hindsight-selected universe and zero commission, the real deployment faces worse.
- **A positive result is weak.** It would require a clean point-in-time universe
  before meaning anything, and would not yet be grounds to fund.

Stated before the run so neither outcome can be reinterpreted afterwards.

---

# RESULT — run 2026-09-24

Gate applied verbatim from the pre-registration above. Both arms: **ADVERSE.**

| | Arm M `high` (primary) | Arm M `medium` |
|---|---|---|
| Final equity from 1,000 | **1,054.88** (+5.49%) | 1,096.10 (+9.61%) |
| Mean exposure | 46.5% | 28.5% |
| Return on deployed capital | +11.80% | +33.77% |
| **SPY total return, same window** | **+85.55%** | +85.55% |
| **Net excess vs SPY (deployed)** | **−73.75%** | −51.78% |
| Max drawdown | **−40.05%** | −24.59% |
| Closed trades / still open | 140 / 4 | 137 / 4 |
| Win rate | 36.4% | 35.0% |
| alpha vs MTUM, annualised | −2.42% | −2.46% |
| alpha 95% CI | [−21.03%, +20.14%] | [−13.70%, +10.10%] |
| beta / R2 vs MTUM | +0.245 / **0.048** | +0.156 / 0.057 |
| **Gate** | **ADVERSE** | **ADVERSE** |

## The gate fired on excess, not on alpha — say so plainly

Annualised alpha is **−2.42%**, which lands in the pre-registered INCONCLUSIVE band
(−3% to −2%), *not* in ADVERSE. The ADVERSE verdict comes entirely from the
net-excess-vs-SPY criterion, which the rule joins by OR.

The MTUM regression is close to **uninformative** here and must not be quoted as
though it were evidence: R2 = 0.048 means the momentum factor explains ~5% of monthly
variance, and the alpha CI spans **41 percentage points**. Unlike Ares — beta 0.39 to
0.47, R2 0.19 to 0.29 — this is not a momentum clone. The `abs()` on the 60-day move
and the near-52-week-**low** branch mean the signal gate fires on notable moves in
either direction, so the strategy is not factor-aligned.

**Decisive finding is the raw comparison, not the regression.**

## Realised P&L over five years is approximately zero

Reconciliation is exact (`1000 + realised + unrealised = equity`, to the cent):

| | Arm `high` | Arm `medium` |
|---|---|---|
| Closed P&L on residual quantity | **−827.45** | −517.60 |
| Scale-out P&L from take-profit tiers | **+782.13** | +542.76 |
| **Total realised, 5 years, 140 trades** | **−45.33** | **+25.16** |
| Unrealised on the 4 open positions | +100.21 | +70.94 |

**The entire reported gain is unrealised mark-to-market on four positions still open
on the final day.** Five years and 140 round trips produced a realised result of
−45.33 on 1,000.

Per-trade expectancy confirms it directly:

```
win rate 36.4%   winners +16.36%   losers −11.09%
0.364 x 16.36 + 0.636 x (−11.09) = −1.10% per trade
```

The tiered take-profit is doing real work — 52 of 140 trades reached at least the +15%
tier, booking +782 — and the stop-loss exits give it all back.

## Structural properties the run exposed

- **Only two exit reasons exist:** `stop_loss` 88, `trailing_stop` 52. Predicted in
  advance from reading the code, confirmed here. With the judgment layer removed there
  is no other way out, and no time-based exit.
- **The system is structurally half-invested.** 46.5% mean exposure at `high`, with
  **17.8% of days holding nothing at all** and only 25.9% holding the full four. The
  binding constraint is 4 slots x 20%, then the re-entry lock (1,271 blocks),
  `entry_extension` (486) and `entry_price_gap` (342).
- **Smaller positions performed better.** `medium` beat `high` on return (+9.61% vs
  +5.49%) *and* on drawdown (−24.59% vs −40.05%). If selection carried an edge,
  concentrating into it should help. It hurt.
- **Worse return and worse risk.** −40.05% drawdown against SPY's roughly −24% over
  the same window.

## What this does NOT say

It does **not** say the LLM adds nothing. Claude's `direction` and `conviction` calls
were never measured and cannot be, for the three reasons registered above. This run
measures the foundation those calls sit on.

What it does establish is the size of the claim. The live system is mechanical layer
**plus** LLM selection. The mechanical layer alone, with a hindsight-selected universe
and zero commission, returned +5.49% while SPY returned +85.55%. For the full system
to beat SPY, **Claude's stock picking must supply the entire ~74-point gap** — against
a −1.10% per-trade expectancy it has to overcome first.

The evidence offered for that is eight live weeks containing at least three different
rule sets, with no drawdown reported and one name (GitLab) credited for the largest
gains in two separate weeks.

## Limitations, stated against our own result

Honesty runs both directions, so these cut toward the strategy:

1. **Idle cash earned nothing.** At ~53% idle over five years, T-bills at prevailing
   rates would add very roughly +8% total. Real, and nowhere near a 74-point gap.
2. **Universe is our proxy, not his watchlist.** `UNIVERSE_B` midcap_98 stands in for
   the 2B–50B market-cap band, which needs point-in-time shares outstanding we do not
   have. His watchlist is hand-picked — itself unmeasured judgment, so substituting a
   list is not obviously harsher.
3. **Stops fill at the close**, not intraday. Real fills would differ in both
   directions.
4. **Universe bias favours the strategy** and it still failed, which is the asymmetry
   registered before the run.

## Bottom line

The rules are well engineered — deterministic, documented, genuinely better than Ares
in two specific respects (the trail engages only after +15%, so it cannot trail into a
loss; take-profit is tiered rather than a single scale). **Good engineering is not an
edge.** On five years of history the mechanical layer is a −1.10%-per-trade system
that finished flat on realised P&L with a −40% drawdown.

**Do not fund.** Per the pre-registered rule, and per the same bar Ares failed.
