"""Athena — Backtest V2: Tweaked parameters based on V1 results.

Changes from V1:
  - TP momentum: 12% → 18% (V1 missed 12.54% upside after TP)
  - TP reversal: 8% → 10%
  - Trailing stop: 8% → 10% (V1 trailing exits averaged -2.20%)
  - Trend continuation: DISABLED (V1 was 24% win rate, -1.05% avg)
"""
import json
from pathlib import Path
from engine.data_feed import download_universe
from engine.backtester import run_backtest, save_results, print_summary, load_params

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
    print("  ATHENA — Backtest V2 (Tweaked Parameters)")
    print("  Changes: TP 18%, TS 10%, No trend_continuation")
    print("="*50)

    # Swap config
    config_path = Path("config/strategy_params.json")
    v2_path = Path("config/strategy_params_v2.json")
    original = config_path.read_text()
    config_path.write_text(v2_path.read_text())

    try:
        download_universe(SP500_TOP)
        print("\n  Running backtest V2 (Jan 2024 - Sep 2026)...")
        print("-" * 50)
        trades = run_backtest(SP500_TOP, start_date="2024-01-01", end_date="2026-09-01")
        save_results(trades, "backtest_v2_trades.csv")
        print_summary(trades)
    finally:
        # Restore original config
        config_path.write_text(original)

    # Compare with V1
    import pandas as pd
    v1 = pd.read_csv("results/backtest_trades.csv")
    v2 = pd.DataFrame(trades)

    v1_wins = len(v1[v1['pnl_pct'] > 0])
    v2_wins = len(v2[v2['pnl_pct'] > 0])

    print(f"\n{'='*50}")
    print(f"  V1 vs V2 COMPARISON")
    print(f"{'='*50}")
    print(f"  {'Metric':<25} {'V1':>10} {'V2':>10} {'Better':>10}")
    print(f"  {'-'*55}")
    print(f"  {'Total trades':<25} {len(v1):>10} {len(v2):>10}")
    print(f"  {'Win rate':<25} {v1_wins/len(v1)*100:>9.1f}% {v2_wins/len(v2)*100:>9.1f}%")
    print(f"  {'Avg win':<25} {v1[v1['pnl_pct']>0]['pnl_pct'].mean():>9.2f}% {v2[v2['pnl_pct']>0]['pnl_pct'].mean():>9.2f}%")
    print(f"  {'Avg loss':<25} {v1[v1['pnl_pct']<=0]['pnl_pct'].mean():>9.2f}% {v2[v2['pnl_pct']<=0]['pnl_pct'].mean():>9.2f}%")
    print(f"  {'Avg hold days':<25} {v1['holding_days'].mean():>9.1f} {v2['holding_days'].mean():>9.1f}")
    print(f"  {'Missed upside (TP)':<25} {v1[v1['exit_reason']=='take_profit']['missed_upside_pct'].mean():>9.2f}% {v2[v2['exit_reason']=='take_profit']['missed_upside_pct'].mean() if len(v2[v2['exit_reason']=='take_profit'])>0 else 0:>9.2f}%")

    v1_pf_num = (v1_wins/len(v1)) * v1[v1['pnl_pct']>0]['pnl_pct'].mean()
    v1_pf_den = (1 - v1_wins/len(v1)) * abs(v1[v1['pnl_pct']<=0]['pnl_pct'].mean())
    v1_pf = v1_pf_num / v1_pf_den if v1_pf_den > 0 else 0

    v2_pf_num = (v2_wins/len(v2)) * v2[v2['pnl_pct']>0]['pnl_pct'].mean()
    v2_pf_den = (1 - v2_wins/len(v2)) * abs(v2[v2['pnl_pct']<=0]['pnl_pct'].mean())
    v2_pf = v2_pf_num / v2_pf_den if v2_pf_den > 0 else 0

    print(f"  {'Profit factor':<25} {v1_pf:>10.2f} {v2_pf:>10.2f}")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
