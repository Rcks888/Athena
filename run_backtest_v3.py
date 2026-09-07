"""Athena — Backtest V3: No fixed TP, trailing stop only.

Changes from V2:
  - TP: DISABLED — let winners ride
  - Trailing stop: 10% (same as V2)
  - Exits: trailing stop, bearish divergence, emotional extreme, stop loss
  - Trend continuation: still disabled
"""
import json
import pandas as pd
from pathlib import Path
from engine.data_feed import download_universe
from engine.backtester import run_backtest, save_results, print_summary

SP500_TOP = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "JNJ", "UNH", "WMT", "MA", "PG", "HD", "ORCL", "ABBV",
    "XOM", "CVX", "AMD", "NFLX", "CRM", "SNOW", "PLTR", "CRWD", "DDOG",
    "NET", "PANW", "NOW", "ADBE", "INTU", "ANET", "SNPS", "CDNS", "FTNT",
    "COIN", "PYPL", "GS", "MS", "SCHW", "UBER", "ABNB", "ROKU", "SNAP",
    "PINS", "DIS", "SBUX", "NKE", "LULU", "CMG", "BKNG", "LLY", "NVO",
    "MRK", "PFE", "TMO", "ABT", "DHR", "VRTX", "REGN", "ISRG", "CAT",
    "DE", "GE", "HON", "RTX", "BA", "LMT", "UNP", "COP", "SLB", "LIN",
    "FCX", "NEM", "FSLR", "NEE", "KO", "PEP", "MCD", "COST", "TGT",
    "IBM", "VZ", "AMT", "PLD", "BLK", "ICE", "CME", "SPY", "QQQ", "IWM",
    "XLF", "XLE", "XLK", "XLV", "SMH", "SHOP", "SOFI", "HOOD", "MARA",
    "RBLX", "TJX", "MAR", "RCL", "BMY", "GILD", "MRNA", "BIIB", "DXCM",
    "UPS", "FDX", "WM", "ETN", "EMR", "MPC", "PSX", "APD", "SHW", "ENPH",
    "CL", "MMM", "SO", "DUK", "AEP", "O", "SPGI", "AON", "MET", "PRU"
]

def main():
    print("="*50)
    print("  ATHENA — Backtest V3 (No TP, Trailing Only)")
    print("  Changes: No fixed TP, ride winners with 10% TS")
    print("="*50)

    config_path = Path("config/strategy_params.json")
    v3_path = Path("config/strategy_params_v3.json")
    original = config_path.read_text()
    config_path.write_text(v3_path.read_text())

    try:
        download_universe(SP500_TOP)
        print("\n  Running backtest V3 (Jan 2024 - Sep 2026)...")
        print("-" * 50)
        trades = run_backtest(SP500_TOP, start_date="2024-01-01", end_date="2026-09-01")
        save_results(trades, "backtest_v3_trades.csv")
        print_summary(trades)
    finally:
        config_path.write_text(original)

    v1 = pd.read_csv("results/backtest_trades.csv")
    v2 = pd.read_csv("results/backtest_v2_trades.csv")
    v3 = pd.DataFrame(trades)

    def calc_pf(df):
        w = df[df['pnl_pct'] > 0]
        l = df[df['pnl_pct'] <= 0]
        wr = len(w) / len(df)
        avg_w = w['pnl_pct'].mean() if len(w) > 0 else 0
        avg_l = abs(l['pnl_pct'].mean()) if len(l) > 0 else 1
        return (wr * avg_w) / ((1 - wr) * avg_l) if avg_l > 0 else 0

    print(f"\n{'='*60}")
    print(f"  V1 vs V2 vs V3 COMPARISON")
    print(f"{'='*60}")
    print(f"  {'Metric':<25} {'V1':>10} {'V2':>10} {'V3':>10}")
    print(f"  {'-'*55}")

    for label, df in [("V1", v1), ("V2", v2), ("V3", v3)]:
        pass

    datasets = {"V1": v1, "V2": v2, "V3": v3}

    row = lambda name, fn: print(f"  {name:<25} " + " ".join(f"{fn(d):>10}" for d in [v1, v2, v3]))

    row("Total trades",      lambda d: f"{len(d)}")
    row("Win rate",           lambda d: f"{len(d[d['pnl_pct']>0])/len(d)*100:.1f}%")
    row("Avg win",            lambda d: f"{d[d['pnl_pct']>0]['pnl_pct'].mean():+.2f}%" if len(d[d['pnl_pct']>0])>0 else "N/A")
    row("Avg loss",           lambda d: f"{d[d['pnl_pct']<=0]['pnl_pct'].mean():+.2f}%" if len(d[d['pnl_pct']<=0])>0 else "N/A")
    row("Profit factor",      lambda d: f"{calc_pf(d):.2f}")
    row("Avg hold days",      lambda d: f"{d['holding_days'].mean():.1f}")
    row("Avg P&L per trade",  lambda d: f"{d['pnl_pct'].mean():+.2f}%")
    row("Missed upside (TP)", lambda d: f"{d[d['exit_reason']=='take_profit']['missed_upside_pct'].mean():.2f}%" if len(d[d['exit_reason']=='take_profit'])>0 else "N/A")

    print(f"\n  EXIT REASON BREAKDOWN (V3):")
    for reason, group in v3.groupby('exit_reason'):
        avg_pnl = group['pnl_pct'].mean()
        print(f"    {reason}: {len(group)} trades | Avg P&L: {avg_pnl:+.2f}%")

    print(f"{'='*60}")

if __name__ == "__main__":
    main()
