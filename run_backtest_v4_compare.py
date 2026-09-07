"""Athena V4 — Capital Comparison: $1K/5slots vs $2.5K/8slots vs $5K/10slots"""
import json
from pathlib import Path
from engine.data_feed import download_universe
from engine.portfolio_sim import run_portfolio_sim, load_params

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

SCENARIOS = [
    {"name": "$1K / 5 slots",  "capital": 1000, "slots": 5},
    {"name": "$2.5K / 8 slots", "capital": 2500, "slots": 8},
    {"name": "$5K / 10 slots",  "capital": 5000, "slots": 10},
    {"name": "$10K / 15 slots", "capital": 10000, "slots": 15},
]

def main():
    print("="*70)
    print("  ATHENA V4 — CAPITAL COMPARISON")
    print("  Period: Sep 2021 - Sep 2026 (5 years)")
    print("="*70)

    download_universe(SP500_TOP)

    config_path = Path("config/strategy_params.json")
    v4_path = Path("config/strategy_params_v4.json")
    original = config_path.read_text()
    base_params = json.loads(v4_path.read_text())

    results = []

    for scenario in SCENARIOS:
        print(f"\n{'─'*70}")
        print(f"  Running: {scenario['name']}")
        print(f"{'─'*70}")

        params = base_params.copy()
        params['starting_capital'] = scenario['capital']
        params['max_positions'] = scenario['slots']
        config_path.write_text(json.dumps(params, indent=2))

        trades, history, stats = run_portfolio_sim(
            SP500_TOP,
            start_date="2021-09-01",
            end_date="2026-09-01"
        )

        import pandas as pd
        hist = pd.DataFrame(history)
        df = pd.DataFrame(trades)
        real = df[df['exit_reason'] != 'end_of_sim']

        final = hist.iloc[-1]['portfolio_value']
        total_ret = (final - scenario['capital']) / scenario['capital'] * 100
        years = len(hist) / 252
        annual_ret = ((final / scenario['capital']) ** (1/years) - 1) * 100

        peak = hist['portfolio_value'].max()
        trough = hist.loc[hist['portfolio_value'].idxmax():, 'portfolio_value'].min()
        max_dd = (trough - peak) / peak * 100

        wins = real[real['pnl_pct'] > 0]
        wr = len(wins)/len(real)*100 if len(real) > 0 else 0

        scaled = real[real['scaled_out'] == True]

        results.append({
            'name': scenario['name'],
            'capital': scenario['capital'],
            'slots': scenario['slots'],
            'final': final,
            'total_ret': total_ret,
            'annual_ret': annual_ret,
            'max_dd': max_dd,
            'trades': len(real),
            'win_rate': wr,
            'entered': stats['signals_entered'],
            'missed': stats['signals_queued'] - stats['signals_from_queue'],
            'from_queue': stats['signals_from_queue'],
            'scaled': len(scaled),
            'total_pnl': real['pnl'].sum(),
            'avg_pnl': real['pnl_pct'].mean()
        })

    config_path.write_text(original)

    # Print comparison
    print(f"\n\n{'='*70}")
    print(f"  CAPITAL COMPARISON — FINAL RESULTS")
    print(f"{'='*70}")

    print(f"\n  {'Metric':<25}", end="")
    for r in results:
        print(f" {r['name']:>15}", end="")
    print()
    print(f"  {'─'*70}")

    def row(label, key, fmt=">15"):
        print(f"  {label:<25}", end="")
        for r in results:
            val = r[key]
            if isinstance(val, float):
                if 'ret' in key or 'dd' in key or 'rate' in key or 'pnl' == key[-3:]:
                    print(f" {val:>14.1f}%", end="")
                else:
                    print(f" ${val:>13,.2f}", end="")
            else:
                print(f" {val:>15}", end="")
        print()

    row("Starting Capital", "capital")
    row("Final Value", "final")
    row("Total Return", "total_ret")
    row("Annual Return", "annual_ret")
    row("Max Drawdown", "max_dd")
    row("Total Trades", "trades")
    row("Win Rate", "win_rate")
    row("Signals Entered", "entered")
    row("Signals Missed", "missed")
    row("From Queue", "from_queue")
    row("Scaled Out", "scaled")
    row("Total P&L", "total_pnl")

    print(f"\n  GROWTH MULTIPLIER:")
    for r in results:
        mult = r['final'] / r['capital']
        print(f"    {r['name']}: ${r['capital']:,} → ${r['final']:,.0f} ({mult:.1f}x)")

    print(f"{'='*70}")

if __name__ == "__main__":
    main()
