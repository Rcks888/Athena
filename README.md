# 🦉 Athena — Backtesting Engine for Ares

Athena simulates Ares trading logic on historical data to generate ML training data and optimize strategy parameters. Named after the Greek goddess of wisdom and strategy — she teaches Ares what works.

## Purpose

1. **Backtest** Ares strategies on 5 years of historical data (130 S&P 500 stocks)
2. **Generate** 800-1000+ simulated trades with full feature data for ML training
3. **Optimize** parameters through iterative testing (V1 → V2 → V3 → V4)
4. **Simulate** real portfolio performance with capital management, scale-out, and queuing

## Quick Start

```bash
pip install yfinance pandas pandas_ta numpy scikit-learn

# Individual strategy backtests
python3 run_backtest.py          # V1: Original parameters
python3 run_backtest_v2.py       # V2: Optimized TP/SL
python3 run_backtest_v3.py       # V3: No TP, trailing only

# Full portfolio simulation
python3 run_backtest_v4.py       # V4: $1K capital, scale-out, queue

# Capital comparison
python3 run_backtest_v4_compare.py  # $1K vs $2.5K vs $5K vs $10K
```

## Backtest Results Summary

### Strategy Optimization (V1 → V3)

130 stocks, Jan 2024 - Sep 2026 per-trade analysis:

| Metric | V1 | V2 | V3 |
|--------|----|----|-----|
| **Total trades** | 1,060 | 930 | 829 |
| **Win rate** | 52.5% | 51.2% | 50.4% |
| **Avg win** | +8.24% | +10.53% | +13.14% |
| **Avg loss** | -4.30% | -4.56% | -4.45% |
| **Profit factor** | 2.12 | 2.42 | **3.00** 🏆 |
| **Avg P&L/trade** | +2.29% | +3.16% | **+4.42%** 🏆 |
| **Avg hold days** | 25 | 32 | 40 |

#### V1 → V2 Changes
- TP: 12% → 18% (V1 missed 12.54% upside after selling)
- Trailing stop: 8% → 10%
- Disabled trend_continuation strategy (24% win rate, losing money)

#### V2 → V3 Changes
- Removed fixed TP entirely — let winners ride
- Trailing stop becomes the only exit for winners
- Result: trailing stop went from **-2.20% avg** to **+5.66% avg**

### Full Portfolio Simulation (V4)

$1,000 starting capital, 5 max positions, Sep 2021 - Sep 2026:

```
PORTFOLIO PERFORMANCE:
  Starting capital:    $1,000.00
  Final value:         $4,045.71
  Total return:        +304.6%
  Annual return:       +32.5%
  Max drawdown:        -5.0%

YEARLY BREAKDOWN:
  2021: $1,000 → $1,052  (+5.2%)    Getting started
  2022: $1,057 → $1,070  (+1.2%)    Bear market survived
  2023: $1,073 → $1,248  (+16.3%)   Building momentum
  2024: $1,215 → $1,887  (+55.3%)   Breakout year
  2025: $1,866 → $2,527  (+35.4%)   Compounding
  2026: $2,559 → $4,046  (+58.1%)   Best year

SCALE-OUT ANALYSIS:
  Trades scaled out:   44
  Avg P&L (scaled):    +23.01%
  Avg P&L (no scale):  -0.60%
```

### Capital Comparison

Same strategy, different starting capital:

| Capital | Slots | Final Value | Multiplier | Annual Return | Max Drawdown |
|---------|-------|-------------|-----------|---------------|-------------|
| **$1,000** | 5 | **$4,046** | **4.0x** 🏆 | **32.5%** 🏆 | **-5.0%** 🏆 |
| $2,500 | 8 | $8,599 | 3.4x | 28.2% | -15.5% |
| $5,000 | 10 | $17,754 | 3.6x | 29.1% | -14.3% |
| $10,000 | 15 | $36,507 | 3.7x | 29.8% | -14.5% |

**Key finding:** $1K/5 slots has the best return % AND lowest risk. More capital means more absolute profit but slightly worse efficiency and higher drawdown.

### V5 — Realistic Backtest (With Friction)

V4 was challenged on missing transaction costs, same-bar execution, and survivorship bias.
V5 addresses all concerns with realistic friction and a different stock universe.

**Friction applied:**
- 0.1% slippage per trade (bid-ask spread)
- $1 commission per trade (IBKR)
- Next-bar execution (signal on day N → buy at day N+1 open)

#### V5 Summary Table

| Metric | Test 1: Original 130 + Friction | Test 2: Mid-cap 100 + Friction | V4 Baseline (No Friction) |
|--------|-------------------------------|-------------------------------|--------------------------|
| **Starting Capital** | $1,000 | $1,000 | $1,000 |
| **Final Value** | **$2,774** | **$4,051** | $4,046 |
| **Total Return** | +177.4% | +305.1% | +304.6% |
| **Annual Return** | **+22.8%** | **+32.5%** | +32.5% |
| **Max Drawdown** | **-15.9%** | **-5.4%** | -5.0% |
| **Total Trades** | 204 | 311 | 223 |
| **Win Rate** | 51.0% | 48.6% | 50.2% |
| **Profit Factor** | **2.41** | **1.73** | 2.42 |
| **Avg Win** | +13.54% | +13.08% | +12.80% |
| **Avg Loss** | -5.83% | -7.15% | -5.09% |
| **Avg Hold Days** | 39 | 24 | 38 |
| **Commissions Paid** | $458 | $706 | $0 |
| **Signals Entered** | 209 / 3,196 (7%) | 315 / 2,485 (13%) | 224 / 3,194 (7%) |

#### Yearly Breakdown (V5 Test 1: Original + Friction)

| Year | Start | End | Return | Trades | Win Rate |
|------|-------|-----|--------|--------|----------|
| 2021 | $1,000 | $1,034 | +3.4% | 4 | 0% |
| 2022 | $1,038 | $975 | **-6.1%** | 45 | 49% |
| 2023 | $980 | $1,035 | +5.7% | 39 | 54% |
| 2024 | $993 | $1,471 | **+48.1%** | 34 | 62% |
| 2025 | $1,457 | $1,766 | +21.2% | 37 | 43% |
| 2026 | $1,776 | $2,774 | **+56.2%** | 45 | 53% |

#### V5 Key Findings

| Concern | Finding |
|---------|---------|
| **Friction impact** | Reduces annual return by ~10% (32.5% → 22.8%). Commissions cost $458 over 5yr. Still highly profitable. |
| **Max drawdown** | Realistic -15.9% (was -5.0% without friction). 2022 bear market = -6.1% year. |
| **Survivorship bias** | Disproven — mid-cap universe performed BETTER (+32.5%) than original large-caps (+22.8%). Strategy works across stock types. |
| **Universe sensitivity** | Moderate ⚠️ — 10% difference between universes. Mid-caps have more volatility = more opportunities. |
| **Next-bar execution** | Buying at next-day open instead of same-day close adds realistic entry price delay. |

#### Realistic Expectations

| Metric | Optimistic (V4) | **Realistic (V5)** |
|--------|-----------------|-------------------|
| Annual return | +32% | **+18-25%** |
| Max drawdown | -5% | **-10-16%** |
| 5yr growth | $1K → $4K | **$1K → $2.5-3K** |
| Profit factor | 2.42 | **1.7-2.4** |

> **+20% annual return with -15% max drawdown is still an excellent strategy.**
> Most hedge funds target 15-20% annual. S&P 500 averages ~10%.

## Key Insights

### What Works
- **Momentum breakout in uptrends** — 51% win rate, +4.48% avg P&L
- **Bearish divergence exit** — +12.53% avg P&L, best exit signal
- **Scale-out (50% at TP, 50% rides)** — scaled trades average +23%
- **Never buy in downtrends** — avoided massive losses in 2022 bear market

### What Doesn't Work
- **Trend continuation strategy** — 24% win rate, removed in V2+
- **Fixed TP** — leaves 12%+ upside on the table every time
- **Too many positions** — increases drawdown without proportional returns

## Architecture

```
Athena/
├── engine/
│   ├── data_feed.py       # yfinance 5yr historical data
│   ├── indicators.py      # Shared with Ares (RSI 21, MACD, regime, divergence)
│   ├── signals.py         # Shared with Ares (entry logic)
│   ├── backtester.py      # Per-trade simulation (V1, V2, V3)
│   ├── portfolio_sim.py   # Full portfolio simulation (V4)
│   └── portfolio_sim_v5.py # Realistic sim with friction (V5)
├── config/
│   ├── strategy_params.json     # V1 base params
│   ├── strategy_params_v2.json  # V2: TP 18%, TS 10%, no trend_cont
│   ├── strategy_params_v3.json  # V3: No TP, trailing only
│   ├── strategy_params_v4.json  # V4: Portfolio sim params
│   └── strategy_params_v5.json  # V5: Realistic friction params
├── results/
│   ├── backtest_trades.csv       # V1: 1,060 trades
│   ├── backtest_v2_trades.csv    # V2: 930 trades
│   ├── backtest_v3_trades.csv    # V3: 829 trades
│   ├── backtest_v4_trades.csv    # V4: 223 trades (portfolio sim)
│   ├── backtest_v4_portfolio.csv # V4: daily portfolio value
│   ├── backtest_v5_realistic.csv # V5: 204 trades (with friction)
│   ├── backtest_v5_midcap.csv    # V5: 311 trades (different universe)
│   └── backtest_v5_portfolio.csv # V5: daily portfolio value
├── data/ohlcv/            # Cached historical CSV (gitignored)
├── models/                # Future ML models
├── run_backtest.py        # V1 backtest
├── run_backtest_v2.py     # V2 backtest + V1 comparison
├── run_backtest_v3.py     # V3 backtest + V1/V2/V3 comparison
├── run_backtest_v4.py     # V4 full portfolio simulation
├── run_backtest_v4_compare.py  # Capital comparison ($1K-$10K)
└── run_backtest_v5.py     # V5 realistic (friction + universe sensitivity)
```

## Relationship to Ares

```
Athena (wisdom)                    Ares (action)
  ├── Backtests strategies     ──→ Validates approach
  ├── Generates ML data        ──→ Trains prediction model
  ├── Finds optimal parameters ──→ Updates strategy_params.json
  ├── Shadow analysis          ──→ Improves exit timing
  ├── Scale-out testing        ──→ Partial profit taking
  └── Capital planning         ──→ Position sizing
```

## Part of Project Olympus

```
🏛️ Olympus/
├── ⚔️  Ares    — Live trading signal scanner
└── 🦉 Athena  — Backtesting engine & ML training
```

## Author

Built by **Rickson Kang** — learning trading through building.
