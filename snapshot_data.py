"""Snapshot the OHLCV data that Athena V6 runs against, then commit it.

V1-V5 are unreproducible: `data/ohlcv/` was gitignored and empty, and yfinance
adjusts prices retroactively, so the data that produced those numbers no longer
exists anywhere. This script freezes the input and writes a manifest recording
the yfinance version, the download date, and each symbol's row count and span.

Resumable: symbols already present are kept, so a rate-limited run can simply be
re-run until the manifest reports no failures.

    PYTHONPATH=vendor python3 snapshot_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "vendor"))
sys.path.insert(0, str(Path(__file__).parent))

from engine.data_feed import snapshot_universe
from engine.universe import ALL_SYMBOLS, UNIVERSE_A, UNIVERSE_B, KNOWN_UNAVAILABLE

def main():
    print("=" * 62)
    print("  ATHENA V6 — OHLCV SNAPSHOT")
    print(f"  Universe A: {len(UNIVERSE_A)} | Universe B: {len(UNIVERSE_B)} | "
          f"unique: {len(ALL_SYMBOLS)}")
    print(f"  Recorded unavailable: {len(KNOWN_UNAVAILABLE)}")
    print("=" * 62)
    # Anything missing that is NOT in KNOWN_UNAVAILABLE raises SnapshotIncomplete.
    # A transient rate-limit must never be allowed to quietly shrink the universe.
    ok, failed, short = snapshot_universe(
        ALL_SYMBOLS, period="5y", min_bars=100,
        allow_missing=set(KNOWN_UNAVAILABLE),
    )
    print(f"\n  Snapshot complete: {len(ok)} symbols usable.")
    print("  Commit data/ohlcv/ and data/snapshot_manifest.json.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
