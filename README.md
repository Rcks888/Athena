# 🦉 Athena — Backtesting Engine for Ares

Athena simulates Ares V2.1 trading logic on historical data to generate ML training data. Named after the Greek goddess of wisdom and strategy — she teaches Ares what works.

## Purpose

1. **Backtest** Ares V2.1 strategies on 2+ years of historical data
2. **Generate** 500+ simulated trades with full feature data
3. **Analyze** win rate, profit factor, exit reasons, shadow tracking
4. **Train** ML models to score future signals

## Quick Start

```bash
pip install yfinance pandas pandas_ta numpy scikit-learn
python run_backtest.py
```

## Output

- `results/backtest_trades.csv` — All simulated trades with features (ML training data)
- Console summary: win rate, profit factor, strategy breakdown, shadow analysis

## Architecture

```
Athena/
├── engine/
│   ├── data_feed.py      # yfinance 5yr historical data
│   ├── indicators.py     # Shared with Ares (RSI, MACD, regime, divergence)
│   ├── signals.py        # Shared with Ares (entry logic)
│   └── backtester.py     # Day-by-day trade simulation + shadow tracking
├── config/
│   └── strategy_params.json  # Same params as Ares V2.1
├── data/ohlcv/           # Cached historical CSV files
├── results/              # Backtest output CSV (ML training data)
├── models/               # Trained ML models (future)
└── run_backtest.py       # Main entry point
```

## Relationship to Ares

```
Athena (wisdom)              Ares (action)
  ├── Backtests strategies ──→ Validates approach
  ├── Generates ML data    ──→ Trains prediction model
  ├── Finds optimal TP/SL  ──→ Updates parameters
  └── Shadow analysis      ──→ Improves exit timing
```

## Author

Built by **Rickson Kang**
