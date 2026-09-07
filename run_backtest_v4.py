"""Athena — Backtest V4: Full Portfolio Simulation

$1,000 starting capital, 5 max positions, scale-out, watchlist queue.
5-year simulation (Sep 2021 - Sep 2026).
"""
from engine.data_feed import download_universe
from engine.portfolio_sim import run_portfolio_sim, print_portfolio_summary, load_params
from pathlib import Path

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
    print("="*60)
    print("  ATHENA V4 — Full Portfolio Simulation")
    print("  $1,000 Capital | 5 Slots | Scale-Out | Queue")
    print("  Period: Sep 2021 - Sep 2026 (5 years)")
    print("="*60)

    # Swap config
    config_path = Path("config/strategy_params.json")
    v4_path = Path("config/strategy_params_v4.json")
    original = config_path.read_text()
    config_path.write_text(v4_path.read_text())

    try:
        download_universe(SP500_TOP)
        trades, history, stats = run_portfolio_sim(
            SP500_TOP,
            start_date="2021-09-01",
            end_date="2026-09-01"
        )
        print_portfolio_summary(trades, history, stats)
    finally:
        config_path.write_text(original)

if __name__ == "__main__":
    main()
