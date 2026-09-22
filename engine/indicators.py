"""Athena indicators.

MUST-FIX 1 (the defect that contaminated V1-V5) is applied here.

`_find_swing_highs` / `_find_swing_lows` compare `series.iloc[i]` against
`series.iloc[i + j]` for j = 1..window. A pivot at bar `i` is therefore not
knowable until bar `i + window`. V1-V5 wrote the divergence flag back onto bar
`i` and then used it as an exit on bar `i` — selling at a confirmed local top
with hindsight. That single back-dating produced ~96% of V5's dollar P&L.

The pivot search is unchanged; what changed is *where the flag is written*. A
divergence is now stamped on the bar at which both constituent pivots have
actually closed, `max(price_pivot, rsi_pivot) + window`. No bar ever carries
information from its own future.

Side effect worth stating: this also repairs the inverse defect in the live
system. The pivot loop stops at `len - window - 1`, so under the old code the
highest index that could ever receive a flag was `len - 6`, while live Ares reads
index `len - 1` — making `latest['bearish_div']`, `latest['bullish_div']` and
both `latest['hidden_*_div']` structurally always False in production. With
confirmation-stamping, a pivot at `len - 6` lands its flag on `len - 1`, so the
latest bar can carry a flag. Athena V6 Run A does not rely on this: Run A removes
divergence from the decision set entirely, to match what live Ares structurally
does today. The repair exists so that Run B is possible later.
"""
import pandas as pd
import pandas_ta as ta
import json
from pathlib import Path

# Bars either side of a candidate pivot that must close before it is a pivot.
SWING_WINDOW = 5

def load_params():
    config_path = Path(__file__).parent.parent / "config" / "strategy_params.json"
    with open(config_path) as f:
        return json.load(f)

def add_indicators(df):
    """Add all technical indicators to a DataFrame. Ares V2."""
    params = load_params()
    rsi_len = params.get('rsi_length', 21)

    ohlc4 = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    df['ohlc4'] = ohlc4

    df['rsi'] = ta.rsi(ohlc4, length=rsi_len)

    df['vol_avg_20'] = df['Volume'].rolling(window=20).mean()
    df['vol_ratio'] = df['Volume'] / df['vol_avg_20']

    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    df['macd'] = macd.iloc[:, 0]
    df['macd_hist'] = macd.iloc[:, 1]
    df['macd_signal'] = macd.iloc[:, 2]

    df['stdev_20'] = df['Close'].pct_change().rolling(20).std()

    df['high_52w'] = df['High'].rolling(252).max()
    df['pct_from_high'] = (df['Close'] - df['high_52w']) / df['high_52w']

    sma_len = params.get('sma_trend_length', 50)
    df['sma_50'] = df['Close'].rolling(sma_len).mean()
    df['sma_slope'] = (df['sma_50'] - df['sma_50'].shift(5)) / df['sma_50'].shift(5)

    df['regime'] = detect_market_regime(df, params)

    df['bullish_div'] = detect_bullish_divergence(df, rsi_len)
    df['bearish_div'] = detect_bearish_divergence(df, rsi_len)
    df['hidden_bull_div'] = detect_hidden_bullish_divergence(df, rsi_len)
    df['hidden_bear_div'] = detect_hidden_bearish_divergence(df, rsi_len)

    return df

def detect_market_regime(df, params):
    """Classify market as UPTREND, DOWNTREND, or RANGE."""
    result = pd.Series('range', index=df.index)
    threshold = params.get('sma_slope_threshold', 0.001)

    if 'sma_slope' not in df.columns:
        return result

    for i in range(len(df)):
        slope = df['sma_slope'].iloc[i]
        if pd.isna(slope):
            continue

        close = df['Close'].iloc[i]
        sma = df['sma_50'].iloc[i]
        if pd.isna(sma):
            continue

        if slope > threshold and close > sma:
            result.iloc[i] = 'uptrend'
        elif slope < -threshold and close < sma:
            result.iloc[i] = 'downtrend'
        else:
            result.iloc[i] = 'range'

    return result

def _find_swing_lows(series, window=SWING_WINDOW):
    """Find local minima indices."""
    lows = []
    for i in range(window, len(series) - window):
        if pd.isna(series.iloc[i]):
            continue
        is_low = True
        for j in range(1, window + 1):
            if series.iloc[i] >= series.iloc[i - j] or series.iloc[i] >= series.iloc[i + j]:
                is_low = False
                break
        if is_low:
            lows.append(i)
    return lows

def _find_swing_highs(series, window=SWING_WINDOW):
    """Find local maxima indices."""
    highs = []
    for i in range(window, len(series) - window):
        if pd.isna(series.iloc[i]):
            continue
        is_high = True
        for j in range(1, window + 1):
            if series.iloc[i] <= series.iloc[i - j] or series.iloc[i] <= series.iloc[i + j]:
                is_high = False
                break
        if is_high:
            highs.append(i)
    return highs

def _scan_divergence(df, lookback, find_pivots, price_cmp, rsi_cmp,
                     window=SWING_WINDOW):
    """Generic causal divergence scan. Shared by all four detectors.

    V1-V5 had this logic copy-pasted four times, which is how the same
    back-dating defect ended up in four places and had to be found four times.

    `price_cmp(curr, prev)` and `rsi_cmp(curr, prev)` define which of the four
    divergences is being scanned. The flag is written at the confirmation bar —
    `max(price_pivot, rsi_pivot) + window` — never at the pivot itself.
    """
    result = pd.Series(False, index=df.index)
    if len(df) < lookback * 3:
        return result

    price_pivots = find_pivots(df['Close'], window)
    rsi_pivots = find_pivots(df['rsi'], window)
    n = len(df)

    for i in range(1, len(price_pivots)):
        p_prev, p_curr = price_pivots[i - 1], price_pivots[i]
        gap = p_curr - p_prev
        if gap > lookback * 2 or gap < 3:
            continue
        if not price_cmp(df['Close'].iloc[p_curr], df['Close'].iloc[p_prev]):
            continue

        r_prev = next((r for r in rsi_pivots if abs(r - p_prev) <= 3), None)
        r_curr = next((r for r in rsi_pivots if abs(r - p_curr) <= 3), None)
        if r_prev is None or r_curr is None:
            continue
        if not rsi_cmp(df['rsi'].iloc[r_curr], df['rsi'].iloc[r_prev]):
            continue

        # MUST-FIX 1. Both pivots must have closed before the flag can exist.
        confirm_at = max(p_curr, r_curr) + window
        if confirm_at < n:
            result.iloc[confirm_at] = True

    return result

_LT = lambda curr, prev: curr < prev
_GT = lambda curr, prev: curr > prev

def detect_bullish_divergence(df, lookback=21):
    """Regular bullish: price lower low + RSI higher low -> reversal UP."""
    return _scan_divergence(df, lookback, _find_swing_lows, _LT, _GT)

def detect_bearish_divergence(df, lookback=21):
    """Regular bearish: price higher high + RSI lower high -> reversal DOWN."""
    return _scan_divergence(df, lookback, _find_swing_highs, _GT, _LT)

def detect_hidden_bullish_divergence(df, lookback=21):
    """Hidden bullish: price higher low + RSI lower low -> continuation UP."""
    return _scan_divergence(df, lookback, _find_swing_lows, _GT, _LT)

def detect_hidden_bearish_divergence(df, lookback=21):
    """Hidden bearish: price lower high + RSI higher high -> continuation DOWN."""
    return _scan_divergence(df, lookback, _find_swing_highs, _LT, _GT)

