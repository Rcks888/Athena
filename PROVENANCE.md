# Athena provenance and environment traps

Two traps were found while bootstrapping V6. Both are permanent: they will recur
on any fresh machine, and each one silently produces *plausible* output rather
than an error. Recorded here so they are not rediscovered.

## Trap 1 — Yahoo rate-limits yfinance's default session to zero rows

Yahoo returns **HTTP 429** to yfinance's default session from this egress, and
serves a browser-shaped session normally. Unpatched, the snapshot produced
**zero rows for every one of the 227 symbols** while printing a cheerful progress
log. That is precisely the "silent symbol skips" defect from the audit
(`data_feed.py:19`, `backtester.py:22,28`) recurring in real time — a backtest
that appears to run and measures nothing.

**Mitigation, two parts.** Documenting the session alone is not enough, because
the next failure mode will not be a 429.

1. `engine/data_feed.py` builds one shared `curl_cffi` session with
   `impersonate='chrome'` plus an explicit Chrome `User-Agent`.
2. **The row-count check is load-bearing.** `snapshot_universe` and
   `load_universe` raise `SnapshotIncomplete` if any symbol returns zero rows or
   fewer than `min_bars`. Nothing is ever skipped. A symbol may only leave a run
   by being named in `KNOWN_UNAVAILABLE` in `engine/universe.py` with a reason.

That assertion is the actual fix. The session is just today's workaround; the
assertion converts the whole bug class from silent to impossible.

## Trap 2 — `pandas_ta` 0.3.x no longer exists on PyPI

V1-V5 were written against `pandas_ta` 0.3.x. It has been **removed from PyPI** —
only 0.4.67b0 and 0.4.71b0 remain, and the GitHub tag is not reachable from here
either. Live Ares happens to run **0.4.71b0**, so live-vs-backtest indicator
parity is still achievable. Had Ares been left on 0.3.x, parity would have been
unreachable and V6 could not have been built at all. That was luck, not design.

### `vendor/` pins are load-bearing for comparability

`vendor/` is pinned to live Ares' exact versions:

| Package | Version | Source of truth |
|---|---|---|
| numpy | 2.2.6 | `Ares/venv/Lib/site-packages` |
| pandas | 3.0.5 | same |
| pandas_ta | 0.4.71b0 | same |
| yfinance | 1.6.0 | same |

**Ares' versions must not drift without re-snapshotting Athena.** If Ares is
upgraded, RSI/MACD values can move, and V6's claim to measure the live system
quietly stops being true — with no error anywhere. Treat an Ares dependency bump
as invalidating the Athena snapshot until it is re-taken.

Athena's `venv/` was unusable (no `pip`, no `ensurepip`), which is why
dependencies live in `vendor/` and every entry point prepends it to `sys.path`.

## Data snapshot

`data/ohlcv/` is committed from V6 onward and is **no longer gitignored**.
yfinance adjusts retroactively, so an uncommitted cache makes a backtest
unreproducible — that is why V1-V5 cannot be re-run at all.
`data/snapshot_manifest.json` records the yfinance version, download timestamp,
`auto_adjust` setting, per-symbol row counts and date spans, and both the
attempted and contributing symbol counts.

## Known limitation carried forward

**Survivorship is not controlled for.** Both universes were written in 2026 with
hindsight about which companies still exist and are liquid. Fixing this needs
paid point-in-time index membership. V6 states it as a known, unquantified
limitation rather than pretending to have controlled for it.
