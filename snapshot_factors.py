"""Freeze the factor and risk-free series for the pre-registered momentum test.

Uses the SAME snapshot path and the SAME pinned yfinance as the 217-symbol equity
snapshot, so the regression inputs are frozen exactly like the strategy inputs. The
curl_cffi browser-impersonating session in `data_feed` is load-bearing here too:
without it Yahoo returns HTTP 429 and yfinance yields ZERO rows silently.

Writes a SEPARATE manifest. `snapshot_universe` rebuilds
`data/snapshot_manifest.json` wholesale from whatever symbol list it is handed, so
calling it with four tickers would silently replace the 217-symbol provenance record
with a four-symbol one — destroying the reproducibility claim it exists to support.

    PYTHONPATH=vendor python3 snapshot_factors.py
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

import pandas as pd

from engine.data_feed import DATA_DIR, load_stock, snapshot_symbol

FACTOR_MANIFEST = ROOT / "data" / "factor_manifest.json"

# MTUM is the pre-registered momentum proxy; SPY and QQQ give the second proxy
# (QQQ - SPY) and the benchmark. BIL is the T-bill proxy for the risk-free rate and
# for the idle-cash credit the simulator omits. ^IRX is carried only as a
# cross-check on BIL's implied level, never as a regression input.
FACTORS = {
    'MTUM': 'iShares MSCI USA Momentum Factor ETF — pre-registered momentum proxy',
    'SPY': 'S&P 500 ETF — benchmark and the short leg of QQQ - SPY',
    'QQQ': 'Nasdaq-100 ETF — long leg of the QQQ - SPY momentum proxy',
    'BIL': 'SPDR Bloomberg 1-3 Month T-Bill ETF — risk-free and idle-cash proxy',
}
CROSSCHECK = {'^IRX': '13-week T-bill discount rate — level cross-check only'}

# The regression needs 59 monthly observations from ~1241 daily bars. A series that
# silently returned a partial history would quietly shorten the window.
MIN_BARS = 1200

def grab(symbol, period="10y"):
    path = DATA_DIR / f"{symbol.replace('^', '_')}.csv"
    if symbol.startswith('^'):
        # data_feed derives the filename from the symbol; carets are handled by
        # snapshotting under a sanitised name via a direct write.
        import yfinance as yf
        from engine.data_feed import _flatten, _session
        df = yf.Ticker(symbol, session=_session()).history(
            period=period, auto_adjust=True)
        if df is None or len(df) == 0:
            return None, path
        df = _flatten(df, symbol)
        df.to_csv(path)
        return df, path
    if path.exists():
        try:
            return load_stock(symbol), path
        except Exception:
            pass
    df = snapshot_symbol(symbol, period)
    time.sleep(1.0)
    return df, path

def main():
    entries, failed, short = {}, [], []

    for symbol, why in {**FACTORS, **CROSSCHECK}.items():
        df, path = grab(symbol)
        required = symbol in FACTORS
        if df is None or len(df) == 0:
            # LOAD-BEARING. A zero-row series must never pass silently; that is the
            # exact failure that produced an empty first snapshot.
            failed.append(symbol)
            print(f"  FAIL {symbol:<6} zero rows")
            continue
        if required and len(df) < MIN_BARS:
            short.append(symbol)
        entries[symbol] = {
            'rows': int(len(df)),
            'first': str(df.index[0].date()),
            'last': str(df.index[-1].date()),
            'purpose': why,
            'required_for_regression': required,
            'file': path.name,
        }
        print(f"  ok   {symbol:<6} {len(df):>5} bars  "
              f"{df.index[0].date()} -> {df.index[-1].date()}")

    missing = [s for s in FACTORS if s not in entries]
    if missing:
        raise SystemExit(
            f"Required factor series missing: {missing}. The pre-registered test "
            f"cannot run on a partial input set, and substituting a different proxy "
            f"would modify the registered method. Re-run once the source responds."
        )
    if short:
        raise SystemExit(
            f"Series shorter than {MIN_BARS} bars: {short}. A partial history would "
            f"silently shorten the 59-month regression window."
        )

    import yfinance as yf
    FACTOR_MANIFEST.write_text(json.dumps({
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'purpose': 'Frozen inputs for the pre-registered momentum substitution test',
        'yfinance_version': getattr(yf, '__version__', 'unknown'),
        'pandas_version': pd.__version__,
        'period': '10y',
        'auto_adjust': True,
        'min_bars': MIN_BARS,
        'series': entries,
        'failed': failed,
        'note': ('Separate from snapshot_manifest.json on purpose: '
                 'snapshot_universe rebuilds that file from its symbol list, so '
                 'reusing it here would replace the 217-symbol provenance record. '
                 'auto_adjust=True means these are total-return series, which is '
                 'what the regression and the T-bill credit both require.'),
    }, indent=2))
    print(f"\n  Wrote {FACTOR_MANIFEST.relative_to(ROOT)} "
          f"({len(entries)} series, {len(failed)} failed)")

if __name__ == "__main__":
    main()
