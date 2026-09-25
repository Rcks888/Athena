"""Parity guard between Athena's vendored strategy code and live Ares.

Why this file exists
--------------------
Every Athena run before Run A' measured a **hand-written parallel implementation**
of the strategy. `portfolio_sim_v6.py` imported only `data_feed` and `indicators`
and re-expressed the entry rules in its own `_check_entry`, while
`engine/signals.py` sat next to it as a near-copy that nothing imported. A parity
audit found ~30 divergences between the two.

The drift was already measurable when this guard was written. Athena's dead copy
of `signals.py` was one functional line behind live: Ares V3 added

    disable_trend_cont = params.get('disable_trend_continuation', False)
    if not signal and not disable_trend_cont:

and the copy still had the ungated `if not signal:`. One line, in the dispatcher,
silently changing which strategies can fire. That is the whole argument: a copy
maintained by hand diverges, and nothing tells you.

So `engine/signals.py` is now a **byte-identical** copy of
`Ares/engine/signals.py`, and this module asserts that on import. Re-expressing
the predicates is what failed; copying without a checksum is how the copy rotted.

Consequence worth being explicit about: importing live code means importing live
**defects**, deliberately. Two examples that are live and reproduced on purpose:

- `tracker.py:400,403` read `latest.get('RSI', 50)` and `latest.get('EMA_20', 0)`.
  `add_indicators` produces lowercase `rsi` and never produces `EMA_20` at all, so
  both queue-promotion gates are inert: RSI always reads 50 and EMA20 always
  compares against 0. Live queue promotion is `|drift| <= 5%` and nothing else.
- All four divergence reads at `latest` are structurally False in production.

Run A' measures the system Ares actually is, not the one its source appears to
describe. Fixing either of those here would recreate the divergence this file
exists to prevent.
"""
import hashlib
from pathlib import Path

ENGINE_DIR = Path(__file__).parent

# md5 of Ares/engine/signals.py as vendored on 2026-09-22. Line endings are part
# of the hash: Ares' files are CRLF and the copy must preserve them byte for byte.
LIVE_SIGNALS_MD5 = "da2ba2596cf43f6405dfd4521824c33d"

# md5 of Ares/engine/exit_policy.py as vendored on 2026-09-25. Block A step 2.
# Exits were the last parallel reimplementation: _decide_exit re-expressed live's
# chain by hand and stayed correct only because someone kept checking. Same failure
# shape as the dead signals.py copy this file was written for.
LIVE_EXIT_POLICY_MD5 = "1efad9500d86d4acbb9aaddc24b3cdb4"

# Where live lives, for the operator-facing message. Athena must never write here.
ARES_SIGNALS_HINT = "~/Olympus/Ares/engine/signals.py"
ARES_EXIT_POLICY_HINT = "~/Olympus/Ares/engine/exit_policy.py"

# ---------------------------------------------------------------------------
# DECLARED, SCOPED DIVERGENCE from live — engine/indicators.py
#
# This file is NOT byte-identical to Ares' and is not required to be. The
# divergence detectors were deliberately rewritten (must-fix 1): live's pivot loop
# writes its flag back onto the PIVOT bar, which is the original look-ahead defect,
# and stops at `len - window - 1` while live reads `len - 1`, which is why all four
# columns are permanently False in production. Athena's version writes the flag at
# the CONFIRMATION bar, `max(price_pivot, rsi_pivot) + window`.
#
# Scope of the divergence, deliberately narrow:
#   - four copy-pasted detectors collapsed into one `_scan_divergence`
#   - flag written at the confirmation bar instead of back-dated to the pivot
#   - `SWING_WINDOW` named rather than repeated as a literal 5
#   - `load_params` resolves the ACTIVE config instead of a hardcoded filename
# Unchanged: lookback 21, pivot window 5, RSI pivot matching tolerance 3, every
# indicator formula, and `detect_market_regime`.
#
# Recorded rather than silenced. Run A' MASKS all four columns to False so the
# repaired detector cannot fire, reproducing production exactly. Run B un-masks them,
# and is therefore the ONLY configuration in which this divergence is active — which
# is precisely the concept-versus-defect question Run B exists to answer.
# ---------------------------------------------------------------------------
LIVE_INDICATORS_MD5 = "f2cf8af87476b03b5c27e220de5abcec"
ATHENA_INDICATORS_MD5 = "d4db2c84185279a4c442b22b7a83441b"

INDICATORS_DIVERGENCE_DECLARED = (
    "engine/indicators.py intentionally differs from live: divergence flags are "
    "written at the confirmation bar rather than back-dated onto the pivot bar "
    "(must-fix 1). Live's back-dating is the original look-ahead defect and also "
    "why all four columns are permanently False in production. Lookback, pivot "
    "window, RSI tolerance and every formula are unchanged."
)

def indicators_divergence_status():
    """Report the indicators divergence without failing on it.

    A checksum assertion here would be wrong: the divergence is intended. What must
    not happen is the divergence going UNRECORDED, or Athena's own copy drifting
    further without anyone noticing, so both hashes are pinned and reported.
    """
    path = ENGINE_DIR / "indicators.py"
    actual = _md5(path)
    return {
        'athena_md5': actual,
        'athena_md5_matches_record': actual == ATHENA_INDICATORS_MD5,
        'live_md5_at_record_time': LIVE_INDICATORS_MD5,
        'byte_identical_to_live': False,
        'declared': INDICATORS_DIVERGENCE_DECLARED,
    }

class ParityDrift(Exception):
    """Raised when vendored strategy code no longer matches what was recorded."""

def _md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()

def assert_signals_parity():
    """Fail loudly if engine/signals.py is not the recorded live copy.

    A warning would be useless here. The failure mode being guarded against is a
    backtest that keeps running and keeps producing plausible numbers for a rule
    the live system no longer implements.
    """
    path = ENGINE_DIR / "signals.py"
    if not path.exists():
        raise ParityDrift(
            f"engine/signals.py is missing. Re-vendor it:\n"
            f"    cp {ARES_SIGNALS_HINT} engine/signals.py"
        )
    actual = _md5(path)
    if actual != LIVE_SIGNALS_MD5:
        raise ParityDrift(
            f"engine/signals.py has drifted from the recorded live copy.\n"
            f"  expected md5 {LIVE_SIGNALS_MD5}\n"
            f"  actual   md5 {actual}\n\n"
            f"Either Ares' strategy changed or this copy was edited. Do NOT patch\n"
            f"around this. Re-vendor and re-run, and treat the result as a new\n"
            f"measurement of a different system:\n"
            f"    cp {ARES_SIGNALS_HINT} engine/signals.py\n"
            f"    # then update LIVE_SIGNALS_MD5 in engine/parity.py\n\n"
            f"If Ares' dependency versions also moved, the OHLCV snapshot must be\n"
            f"re-taken as well — see PROVENANCE.md."
        )
    return actual

def assert_exit_policy_parity():
    """Fail loudly if engine/exit_policy.py is not the recorded live copy."""
    path = ENGINE_DIR / "exit_policy.py"
    if not path.exists():
        raise ParityDrift(
            f"engine/exit_policy.py is missing. Re-vendor it:\n"
            f"    cp {ARES_EXIT_POLICY_HINT} engine/exit_policy.py"
        )
    actual = _md5(path)
    if actual != LIVE_EXIT_POLICY_MD5:
        raise ParityDrift(
            f"engine/exit_policy.py has drifted from the recorded live copy.\n"
            f"  expected md5 {LIVE_EXIT_POLICY_MD5}\n"
            f"  actual   md5 {actual}\n\n"
            f"Exit rules define the Block B label. A drifted copy means every label\n"
            f"describes an exit policy the live system does not implement. Re-vendor\n"
            f"and treat the result as a measurement of a different system:\n"
            f"    cp {ARES_EXIT_POLICY_HINT} engine/exit_policy.py\n"
            f"    # then update LIVE_EXIT_POLICY_MD5 in engine/parity.py"
        )
    return actual

# Asserted at import so no code path can reach a simulation without it holding.
assert_signals_parity()
assert_exit_policy_parity()
