"""Athena data feed — downloads historical data via yfinance for backtesting."""
import yfinance as yf
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "ohlcv"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def download_stock(symbol, period="5y"):
    """Download 5 years of OHLCV data for backtesting."""
    try:
        df = yf.download(symbol, period=period, progress=False)
        if df is not None and len(df) > 0:
            filepath = DATA_DIR / f"{symbol}.csv"
            df.to_csv(filepath)
            return df
    except Exception as e:
        print(f"  Error downloading {symbol}: {e}")
    return None

def load_stock(symbol):
    """Load cached stock data from disk."""
    filepath = DATA_DIR / f"{symbol}.csv"
    if not filepath.exists():
        return download_stock(symbol)
    df = pd.read_csv(filepath, index_col=0, parse_dates=True, date_format='ISO8601')
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

def download_universe(symbols):
    """Download data for all symbols."""
    print(f"  Downloading {len(symbols)} stocks (5yr history)...")
    count = 0
    for symbol in symbols:
        df = download_stock(symbol)
        if df is not None and len(df) > 50:
            count += 1
    print(f"  Done: {count}/{len(symbols)} stocks downloaded")
    return count
