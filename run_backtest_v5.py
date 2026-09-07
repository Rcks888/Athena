"""Athena V5 — Realistic Backtest with Friction

Addresses all reviewer concerns:
1. Next-bar execution (no same-bar fills)
2. Slippage (0.1% per trade)
3. Commission ($1 per trade)
4. Full 5-year period (Sep 2021 - Sep 2026) with V3 logic
5. Tests TWO universes: original 130 stocks + different 100 mid-caps
"""
import json
from pathlib import Path
from engine.data_feed import download_universe
from engine.portfolio_sim_v5 import run_realistic_sim, print_results

# Original universe (same as V1-V4)
UNIVERSE_A = [
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

# Different universe — mid-caps, less popular, more diverse
UNIVERSE_B = [
    "BILL", "HUBS", "DKNG", "DASH", "RIVN", "LCID", "BROS", "CAVA",
    "DUOL", "IOT", "CELH", "BIRK", "TOST", "MNDY", "GLBE", "PCOR",
    "WDAY", "VEEV", "ZM", "DOCU", "OKTA", "TWLO", "ESTC", "MDB",
    "CFLT", "PATH", "GTLB", "ROKU", "LYFT", "RIVN", "OPEN", "UPST",
    "AFRM", "ASAN", "FVRR", "FIVERR", "U", "RKLB", "SMCI", "ARM",
    "ONON", "DECK", "CROX", "LEVI", "GPS", "ANF", "URBN", "RL",
    "TPR", "CPRI", "CHEF", "WING", "SHAK", "DPZ", "TXRH", "JACK",
    "EAT", "DINE", "PLAY", "SIX", "FUN", "LUV", "DAL", "UAL",
    "AAL", "JBLU", "SAVE", "ALK", "HA", "SKYW", "MESA", "CPA",
    "CLF", "X", "NUE", "STLD", "RS", "ATI", "HAYN", "CMC",
    "AA", "CENX", "KALU", "TECK", "RIO", "BHP", "VALE", "MT",
    "PKX", "SCCO", "HBM", "ARLP", "BTU", "ARCH", "CEIX", "CNX",
    "FANG", "DVN", "OVV", "AR"
]

def main():
    print("="*60)
    print("  ATHENA V5 — REALISTIC BACKTEST")
    print("  Next-bar execution | 0.1% slippage | $1 commission")
    print("  Period: Sep 2021 - Sep 2026 (5 years)")
    print("="*60)

    config_path = Path("config/strategy_params.json")
    v5_path = Path("config/strategy_params_v5.json")
    original = config_path.read_text()
    config_path.write_text(v5_path.read_text())

    all_symbols = list(set(UNIVERSE_A + UNIVERSE_B))
    print(f"\n  Downloading {len(all_symbols)} unique stocks...")
    download_universe(all_symbols)

    results = []

    try:
        # Test 1: Original universe with friction
        print(f"\n{'='*60}")
        print("  TEST 1: Original 130 stocks (with friction)")
        print(f"{'='*60}")
        t1, h1, s1 = run_realistic_sim(UNIVERSE_A, "2021-09-01", "2026-09-01", "Original 130 + friction")
        r1 = print_results(t1, h1, s1)
        results.append(r1)

        # Test 2: Different universe (mid-caps)
        print(f"\n{'='*60}")
        print("  TEST 2: Different 100 mid-cap stocks (sensitivity test)")
        print(f"{'='*60}")
        t2, h2, s2 = run_realistic_sim(UNIVERSE_B, "2021-09-01", "2026-09-01", "Mid-cap 100 + friction")
        r2 = print_results(t2, h2, s2)
        results.append(r2)

        # Test 3: Original universe WITHOUT friction (for comparison)
        no_friction = json.loads(v5_path.read_text())
        no_friction['slippage_pct'] = 0
        no_friction['commission_per_trade'] = 0
        no_friction['next_bar_execution'] = False
        config_path.write_text(json.dumps(no_friction))

        print(f"\n{'='*60}")
        print("  TEST 3: Original 130 stocks (NO friction — V4 comparison)")
        print(f"{'='*60}")
        t3, h3, s3 = run_realistic_sim(UNIVERSE_A, "2021-09-01", "2026-09-01", "Original 130 NO friction")
        r3 = print_results(t3, h3, s3)
        results.append(r3)

    finally:
        config_path.write_text(original)

    # Final comparison
    print(f"\n\n{'='*60}")
    print(f"  V5 REALISTIC COMPARISON")
    print(f"{'='*60}")
    print(f"  {'Metric':<20} {'Orig+Fric':>14} {'MidCap+Fric':>14} {'Orig NoFric':>14}")
    print(f"  {'-'*62}")

    if all(r is not None for r in results):
        for key, label in [
            ('final', 'Final Value'),
            ('total_ret', 'Total Return %'),
            ('annual_ret', 'Annual Return %'),
            ('max_dd', 'Max Drawdown %'),
            ('trades', 'Total Trades'),
            ('win_rate', 'Win Rate %'),
            ('pf', 'Profit Factor'),
            ('avg_win', 'Avg Win %'),
            ('avg_loss', 'Avg Loss %'),
            ('commissions', 'Commissions $')
        ]:
            vals = []
            for r in results:
                v = r[key]
                if key in ('final', 'commissions'):
                    vals.append(f"${v:>12,.2f}")
                elif key == 'trades':
                    vals.append(f"{v:>14}")
                else:
                    vals.append(f"{v:>13.1f}%")
            print(f"  {label:<20} {vals[0]} {vals[1]} {vals[2]}")

    print(f"\n  FRICTION IMPACT:")
    if results[0] and results[2]:
        ret_diff = results[2]['annual_ret'] - results[0]['annual_ret']
        print(f"    Slippage + commission reduces annual return by ~{ret_diff:.1f}%")
        print(f"    Total commissions: ${results[0]['commissions']:.2f}")

    print(f"\n  UNIVERSE SENSITIVITY:")
    if results[0] and results[1]:
        print(f"    Original stocks:  {results[0]['annual_ret']:+.1f}% annual")
        print(f"    Mid-cap stocks:   {results[1]['annual_ret']:+.1f}% annual")
        diff = abs(results[0]['annual_ret'] - results[1]['annual_ret'])
        if diff < 5:
            print(f"    Verdict: Strategy is ROBUST across universes ✅")
        elif diff < 10:
            print(f"    Verdict: Moderate sensitivity to stock selection ⚠️")
        else:
            print(f"    Verdict: HIGH sensitivity — possible overfitting ❌")

    print(f"{'='*60}")

    # Save
    import pandas as pd
    pd.DataFrame(t1).to_csv(RESULTS_DIR / "backtest_v5_realistic.csv", index=False)
    pd.DataFrame(h1).to_csv(RESULTS_DIR / "backtest_v5_portfolio.csv", index=False)
    pd.DataFrame(t2).to_csv(RESULTS_DIR / "backtest_v5_midcap.csv", index=False)
    print(f"\n  Saved to results/backtest_v5_*.csv")

    RESULTS_DIR = Path("results")

if __name__ == "__main__":
    main()
