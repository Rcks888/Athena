"""Athena data feed — snapshotted historical OHLCV for backtesting.

V6 rewrite. Three defects in the V1-V5 feed are fixed here:

1. `yf.download` returns MultiIndex columns (('Close','AAPL'), ...). V1-V5 wrote
   that frame verbatim and re-read it with `header=0`, so the ticker row became a
   data row. Worse, on a *cache miss* the raw MultiIndex frame was returned
   directly to the caller, where `df['Close']` yields a DataFrame rather than a
   Series — so the first run of a backtest differed from every later run.
   Columns are now flattened to Open/High/Low/Close/Volume before anything is
   written or returned, and write and read go through one normalisation path.

2. Symbols were skipped silently on download failure or insufficient history, and
   the count of symbols *attempted* versus *contributing* was never persisted.
   A partial download therefore yielded a quietly smaller backtest. Loading is
   now snapshot-only and raises; the runner records both counts.

3. The snapshot was unreproducible: `data/ohlcv/` was gitignored and empty, and
   yfinance adjusts retroactively, so V1-V5 cannot be re-run against the data
   that produced them. `snapshot_universe` writes a manifest recording the
   yfinance version, the download date and the per-symbol row count and date
   span, and the CSVs are committed.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data" / "ohlcv"
MANIFEST_PATH = DATA_DIR.parent / "snapshot_manifest.json"
OHLCV_COLS = ['Open', 'High', 'Low', 'Close', 'Volume']

class SnapshotMissing(Exception):
    """Raised when a symbol is requested that is not in the committed snapshot."""

class SnapshotIncomplete(Exception):
    """Raised when the snapshot is missing symbols or has too few bars.

    This is deliberately fatal. During the V6 bootstrap, Yahoo returned HTTP 429
    to yfinance's default session and the snapshot produced ZERO rows for every
    symbol — the audit's "silent symbol skips" defect recurring live, while the
    run looked like it was working. A row-count check that merely warns would have
    let that through. Making it raise converts the bug class from silent to
    impossible: a symbol either has data or the run stops.
    """

# Yahoo returns HTTP 429 to yfinance's default session from this egress, but
# serves normally to a browser-shaped one. Without this the snapshot silently
# produces zero rows for every symbol, which is exactly the class of failure
# V1-V5 swallowed. Built once and shared so we present a stable client.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_SESSION = None

def _session():
    global _SESSION
    if _SESSION is None:
        from curl_cffi import requests as cr
        _SESSION = cr.Session(impersonate='chrome')
        _SESSION.headers.update({'User-Agent': _UA})
    return _SESSION

def _flatten(df, symbol):
    """Reduce any yfinance column layout to flat Open/High/Low/Close/Volume.

    yfinance returns a MultiIndex (field, ticker) for `download`, and a flat
    index for `Ticker.history`. Both are accepted; the output is always flat.
    """
    if isinstance(df.columns, pd.MultiIndex):
        # Pick the level that carries the OHLCV field names.
        field_level = 0
        for lvl in range(df.columns.nlevels):
            if 'Close' in df.columns.get_level_values(lvl):
                field_level = lvl
                break
        df = df.copy()
        df.columns = df.columns.get_level_values(field_level)

    df = df.loc[:, ~df.columns.duplicated()]
    missing = [c for c in OHLCV_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{symbol}: snapshot missing columns {missing}")

    out = df[OHLCV_COLS].apply(pd.to_numeric, errors='coerce')
    out.index = pd.to_datetime(out.index, utc=True).tz_localize(None).normalize()
    out.index.name = 'Date'
    out = out[~out.index.duplicated(keep='last')].sort_index()
    return out.dropna(subset=['Close'])

def load_stock(symbol):
    """Load a symbol from the committed snapshot. Never downloads.

    V1-V5 silently fell back to a live download on a cache miss, which is what
    made the first run differ from later runs. A backtest must read frozen data
    or fail loudly, so this raises instead.
    """
    filepath = DATA_DIR / f"{symbol}.csv"
    if not filepath.exists():
        raise SnapshotMissing(
            f"{symbol}: no snapshot at {filepath}. Run `python3 snapshot_data.py` first."
        )
    df = pd.read_csv(filepath, index_col=0, parse_dates=True)
    return _flatten(df, symbol)

def snapshot_symbol(symbol, period="5y", max_retries=6, base_sleep=2.0):
    """Download one symbol and write it to the snapshot. Returns the frame or None.

    Yahoo rate-limits aggressively, so failures are retried with exponential
    backoff rather than being swallowed the way V1-V5 swallowed them.
    """
    import yfinance as yf

    last_err = None
    empty_attempts = 0
    for attempt in range(max_retries):
        try:
            raw = yf.Ticker(symbol, session=_session()).history(
                period=period, auto_adjust=True)
            if raw is not None and len(raw) > 0:
                df = _flatten(raw, symbol)
                df.to_csv(DATA_DIR / f"{symbol}.csv")
                return df
            # An empty frame with no exception means Yahoo answered and has no
            # data — a delisted or renamed ticker. That is permanent, so do not
            # burn the full exponential backoff on it; a rate-limit raises
            # instead, and those are the ones worth waiting out.
            last_err = "empty frame (delisted or renamed?)"
            empty_attempts += 1
            if empty_attempts >= 2:
                break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(base_sleep * (2 ** attempt))

    print(f"  ! {symbol}: download FAILED ({last_err})")
    return None

def snapshot_universe(symbols, period="5y", min_bars=100, pause=1.0,
                      allow_missing=()):
    """Download every symbol, write a provenance manifest, fail loudly on gaps.

    LOAD-BEARING row-count check. Any symbol that returns zero rows, or fewer
    than `min_bars`, raises SnapshotIncomplete. It is never skipped. A symbol may
    only be excluded by naming it explicitly in `allow_missing`, which forces the
    exclusion to be a recorded decision rather than an accident — and the manifest
    persists both the attempted and the contributing count either way.
    """
    import yfinance as yf

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    symbols = sorted(set(symbols))
    print(f"  Snapshotting {len(symbols)} symbols ({period})...")

    entries, failed, short = {}, [], []
    for n, symbol in enumerate(symbols, 1):
        path = DATA_DIR / f"{symbol}.csv"
        if path.exists():
            try:
                df = load_stock(symbol)
            except Exception:
                df = snapshot_symbol(symbol, period)
        else:
            df = snapshot_symbol(symbol, period)
            time.sleep(pause)

        if df is None or len(df) == 0:
            failed.append(symbol)
            continue
        if len(df) < min_bars:
            short.append(symbol)

        entries[symbol] = {
            'rows': int(len(df)),
            'first': str(df.index[0].date()),
            'last': str(df.index[-1].date()),
        }
        if n % 25 == 0:
            print(f"    {n}/{len(symbols)} done ({len(failed)} failed)")

    manifest = {
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'yfinance_version': getattr(yf, '__version__', 'unknown'),
        'pandas_version': pd.__version__,
        'period': period,
        'auto_adjust': True,
        'symbols_attempted': len(symbols),
        'symbols_snapshotted': len(entries),
        'symbols_failed': sorted(failed),
        'symbols_under_min_bars': sorted(short),
        'min_bars': min_bars,
        'note': (
            "yfinance adjusts retroactively. These CSVs are the frozen input for "
            "Athena V6 and are committed so the run is reproducible."
        ),
        'symbols': entries,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))

    print(f"  Snapshot: {len(entries)}/{len(symbols)} symbols, "
          f"{len(failed)} failed, {len(short)} under {min_bars} bars")
    print(f"  Manifest: {MANIFEST_PATH}")

    unexplained = sorted((set(failed) | set(short)) - set(allow_missing))
    if unexplained:
        raise SnapshotIncomplete(
            f"{len(unexplained)} symbol(s) have no data or fewer than {min_bars} "
            f"bars: {' '.join(unexplained)}\n"
            "The snapshot will NOT silently proceed with a smaller universe. "
            "Either re-run to retry a transient rate-limit, or add genuinely "
            "unavailable tickers to KNOWN_UNAVAILABLE in engine/universe.py with "
            "a reason."
        )
    return sorted(entries), failed, short

def load_universe(symbols, min_bars=100, allow_missing=()):
    """Load every symbol from the snapshot, or fail. Returns {symbol: DataFrame}.

    V1-V5 skipped unloadable symbols inside a bare `except`, so a partial download
    quietly produced a smaller backtest and the difference was never recorded
    anywhere. Same load-bearing rule as the snapshot: no silent shrinkage.
    """
    data, bad = {}, []
    for symbol in symbols:
        if symbol in allow_missing:
            continue
        try:
            df = load_stock(symbol)
        except Exception as e:
            bad.append(f"{symbol} ({type(e).__name__})")
            continue
        if len(df) < min_bars:
            bad.append(f"{symbol} ({len(df)} bars < {min_bars})")
            continue
        data[symbol] = df

    if bad:
        raise SnapshotIncomplete(
            f"{len(bad)} symbol(s) unusable: {', '.join(bad)}. "
            "Re-run snapshot_data.py, or record them in KNOWN_UNAVAILABLE."
        )
    return data

def available_symbols():
    """Symbols present in the committed snapshot."""
    if not DATA_DIR.exists():
        return []
    return sorted(p.stem for p in DATA_DIR.glob("*.csv"))
