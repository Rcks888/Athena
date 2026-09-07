"""Athena — Ares V2.1 Backtesting Engine
Simulates Ares trading logic on historical data to generate ML training data.
"""
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
    print("  ATHENA — Ares V2.1 Backtesting Engine")
    print("="*50)

    download_universe(SP500_TOP)

    print("\n  Running backtest (Jan 2024 - Sep 2026)...")
    print("-" * 50)
    trades = run_backtest(SP500_TOP, start_date="2024-01-01", end_date="2026-09-01")

    df = save_results(trades)
    print_summary(trades)

if __name__ == "__main__":
    main()
