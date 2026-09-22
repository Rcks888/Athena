"""Call live Ares' entry predicates from the backtest, unmodified.

The defect class this replaces
-----------------------------
Athena re-expressed the strategy. `portfolio_sim_v6.py:_check_entry` was a
hand-written parallel implementation, and it had drifted from live in roughly
thirty ways — a missing 52-week-high gate, a phantom `rsi > 50`, a missing
`near_sma_support` term, `>` where live uses `>=`, NaN bars rejected where live
passes them, and a sign inversion that turned live's `bearish_div` HARD VETO into
positive confluence credit. Patching those individually leaves the defect class
intact, because the next edit to Ares diverges again.

So nothing here re-expresses a predicate. `engine/signals.py` is a byte-identical
copy of `Ares/engine/signals.py`, guarded by `engine/parity.py`, and this module
only feeds it data.

How causality is guaranteed structurally
----------------------------------------
Live's checkers read `df.iloc[-1]` and `df.iloc[-2]` — the latest bar and the one
before. To evaluate bar `i` historically we hand them `df.iloc[:i + 1]`. The
function then *cannot* see bar `i + 1`, whatever it does internally, because the
data is not in the frame it was given. Causality stops being a property we assert
about our own code and becomes a property of what we pass in.

This is deliberately slower than reading numpy arrays. The previous fast path is
what allowed the implementations to diverge in the first place, and it is also
where a look-ahead crept in: `portfolio_sim_v6.py:300` sized a position from
today's Close for an order filling at today's Open.
"""
import pandas as pd

from engine import parity  # noqa: F401 — asserts signals.py parity on import
from engine.signals import (
    check_momentum_breakout,
    check_range_signals,
    check_uptrend_signals,
)

# Columns live's predicates touch. Kept as documentation of the contract; the
# adapter passes the whole frame, so adding a live predicate needs no change here.
REQUIRED_COLUMNS = (
    'Open', 'High', 'Low', 'Close', 'rsi', 'vol_ratio', 'macd', 'macd_signal',
    'macd_hist', 'sma_50', 'pct_from_high', 'stdev_20', 'regime',
    'bullish_div', 'bearish_div', 'hidden_bull_div', 'hidden_bear_div',
)

def assert_frame_contract(df):
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(
            f"Indicator frame is missing columns live's predicates read: {missing}. "
            "A missing column would make live's `.get(col, default)` reads fall back "
            "to a default silently — the inert-gate defect class."
        )

def evaluate_entry(df, i, params, symbol):
    """Live Ares' entry decision for `symbol` as of the close of bar `i`.

    Mirrors the regime dispatch in `signals.scan_universe` (Ares' signals.py
    lines 172-186) exactly, including the `disable_trend_cont` gate that Ares V3
    added and Athena's stale copy had lost. The dispatch is the only strategy logic
    in this file, and `parity.py`'s checksum covers the lines it mirrors, so a
    change to live's dispatcher trips the guard rather than passing silently.

    Returns live's signal dict (whose 'trigger' joins every satisfied term, and
    whose 'confluence' is live's own count) or None.
    """
    if i < 1:
        # Live reads df.iloc[-2] in the uptrend branch; one bar is not enough.
        return None

    window = df.iloc[:i + 1]
    latest = window.iloc[-1]
    regime = str(latest.get('regime', 'range'))
    disable_trend_cont = params.get('disable_trend_continuation', False)

    signal = None
    if regime == 'uptrend':
        signal = check_momentum_breakout(symbol, window, params)
        if not signal and not disable_trend_cont:
            signal = check_uptrend_signals(symbol, window, params)
    elif regime == 'range':
        signal = check_range_signals(symbol, window, params)
    elif regime == 'downtrend':
        # Live logs a watchlist note on bullish divergence and emits no signal.
        signal = None

    return signal

def stdev_at(df, i):
    """The `stdev_20` live would have put on the signal, or None if absent.

    Live's signal builders do `round(float(latest['stdev_20']), 4)`, and
    `tracker.py` then treats a falsy or non-positive value as an absence. NaN is
    returned as None so the caller reproduces live's fallback rather than
    fabricating a number here — the distinction the `stdev_20` defect turned on.
    """
    v = df['stdev_20'].iloc[i]
    if pd.isna(v) or float(v) <= 0:
        return None
    return round(float(v), 4)
