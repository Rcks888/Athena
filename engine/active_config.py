"""The single source of truth for which strategy config a run is using.

`indicators.load_params()` read `config/strategy_params.json` directly, which still
holds V2.1 values (`trailing_stop_pct 0.08`, `tp_momentum 0.12`) rather than the
V6 values a V6 run believes it is using. The three keys indicators actually reads —
`rsi_length`, `sma_trend_length`, `sma_slope_threshold` — happen to be identical in
both files, so Run A produced no numeric error. It agreed by luck, and was one
config edit away from computing indicators under one parameter set while sizing
trades under another, with nothing to reveal it.

Two modules therefore resolve the config through here instead of hardcoding a
filename. `engine/signals.py` is exempt: it is a byte-identical copy of live and
must not be edited, and it only reads params that are passed in explicitly by the
adapter, so its own `load_strategy_params` is never called on the backtest path.
"""
import json
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"
DEFAULT = "strategy_params_v6.json"

_active = DEFAULT

def set_active(name):
    """Point every consumer at one config file. Call once, before loading data."""
    global _active
    if not (CONFIG_DIR / name).exists():
        raise FileNotFoundError(f"No such config: {CONFIG_DIR / name}")
    _active = name
    return _active

def active_name():
    return _active

def active_path():
    return CONFIG_DIR / _active

def load():
    with open(active_path()) as f:
        return json.load(f)
