"""Tracker migration Phase 0 — differential equivalence harness.

NOT a Block A experiment. Block A stage 1 is closed: Policies B and D failed and
Policy A is retained. See Athena/BLOCK_A_STAGE1_STATUS.md. Nothing here reopens
that, recalculates its gates, or depends on its conclusion.

THE QUESTION
------------
Gate 1 proved the canonical module reproduces Athena's Run A' output. But Athena was
itself delegated to the module in b70bed2, so what that proved is that the delegation
was behaviour-neutral *for Athena*. The link never tested is:

    Ares/engine/tracker.py inline chain   <->   engine/exit_policy.py

The module was hand-transcribed from tracker.py and nothing has ever verified the
transcription against the live code it came from. The future swap assumes that
equivalence. This harness answers it now, separately from "is it safe to change the
live dependency", so those two questions are never entangled under deployment
pressure.

PASSING DOES NOT AUTHORIZE THE SWAP. It clears Phase 0 only. The swap remains held
until ABM and SDGR clear, under its own controlled plan.

HOW tracker.py IS DRIVEN WITHOUT BEING MODIFIED
-----------------------------------------------
check_open_trades() reads `latest = df.iloc[-1]`, so feeding a frame truncated to bar
i steps it exactly one bar. Its I/O boundary is injected: load_trades, save_trades,
load_stock, get_live_price. get_live_price is forced to None so current_price is the
daily Close, matching what the module is handed. tracker.py itself is never edited;
if it could not be driven this way the correct action would be to stop and document
that, not to refactor live code.

EQUIVALENCE IS PER-TRANSITION, NOT FINAL P&L
--------------------------------------------
Two paths can reach the same P&L through different intermediate states and diverge on
the next bar, so every bar's decisions and the full state projection are compared.

KNOWN SUSPECTED DIVERGENCE, recorded before running
---------------------------------------------------
tracker.py stores `round(peak_price, 2)`, `round(trailing_stop, 2)`,
`round(shares, 2)` and `round(scale_out_price, 2)` into trade state. The canonical
module rounds only inside instrument_close (reporting) and keeps full precision in
update_peak. Rounded state feeds the NEXT bar's comparisons, so this can flip a
decision at a boundary. Mismatches explainable by 2dp rounding are classified
separately from unexplained ones, so the report distinguishes a transcription
contract question from a genuine logic defect. Which side is "correct" is NOT
decided here: tracker.py is live, so equivalence means the module reproduces
tracker's current behaviour. If tracker itself is wrong, fixing it is a separate
production change and must not be hidden inside canonicalization.
"""
import json
import sys
from copy import deepcopy
from io import StringIO
from pathlib import Path
from contextlib import redirect_stdout

import pandas as pd

ATHENA = Path(__file__).parent
ARES = ATHENA.parent / "Ares"
# Ares FIRST so `engine` resolves to Ares' package. Athena's engine is never
# imported here; both hold byte-identical copies of exit_policy.py (md5-pinned), so
# importing the canonical one from Ares is the stronger choice anyway.
sys.path.insert(0, str(ARES))

from engine import exit_policy, tracker            # noqa: E402

OHLCV = ATHENA / "data" / "ohlcv"
RESULTS = ATHENA / "results"
DOLLAR_TOL = 1e-4          # same basis as Gate 1's dollar tolerance
ROUNDING_SLACK = 0.005001   # half of 2dp, plus float slack

# State fields projected and compared after every bar. Fields owned solely by the
# surrounding tracker (post_mortem, shadow, sample_phase, contaminated, csv/report
# bookkeeping) are excluded deliberately: the module has no contract over them.
COMPARED = (
    "peak_price", "trailing_stop", "shares", "scaled_out", "scale_out_price",
    "scale_out_shares", "scale_out_date", "status", "exit_reason", "exit_price",
    "exit_date",
)
EXCLUDED = ("post_mortem", "shadow", "sample_phase", "contaminated",
            "contamination_reasons", "scale_out_pnl", "scale_out_pnl_pct",
            "scale_out_commission", "total_commission", "pnl", "pnl_pct",
            "pnl_after_costs", "pnl_remaining", "exit_slippage", "holding_days")


def load_bars(symbol):
    f = OHLCV / f"{symbol}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, index_col=0, parse_dates=True)
    return df.sort_index()


def tracker_trade(case):
    """Trade dict in tracker.py's own schema."""
    e = case["entry_price"]
    return {
        "symbol": case["symbol"], "strategy": case["strategy"], "status": "open",
        "entry_date": case["entry_date"], "entry_price": e,
        "shares": case["shares"], "original_shares": case["shares"],
        "stop_loss": case["stop_loss"], "take_profit": case["take_profit"],
        "trailing_stop": case["stop_loss"], "peak_price": e,
        "entry_commission": 1.0, "total_commission": 1.0,
        "scaled_out": False, "signal_date": case["entry_date"],
        "sample_phase": "harness", "rsi_at_entry": 50.0, "stdev_20": 0.02,
    }


def module_pos(case):
    """Position dict in the canonical module's schema."""
    e = case["entry_price"]
    return {
        "symbol": case["symbol"], "strategy": case["strategy"],
        "entry_date": case["entry_date"], "entry_price": e,
        "shares": case["shares"], "original_shares": case["shares"],
        "stop_loss": case["stop_loss"], "initial_stop": case["stop_loss"],
        "take_profit": case["take_profit"], "trailing_stop": case["stop_loss"],
        "peak_price": e, "trough_price": e, "highest_trailing_stop": case["stop_loss"],
        "trail_activated": False, "tiers_hit": 0, "scaled_out": False,
        "scale_out_date": None, "scale_out_price": 0.0, "scale_out_shares": 0.0,
        "scale_out_proceeds": 0.0, "peak_before_first_tier": e,
        "peak_after_first_tier": None, "entry_commission": 1.0,
        "commission_paid": 1.0,
    }


def step_tracker(trade, df_slice):
    """Run ONE bar of the real tracker.check_open_trades against injected I/O.

    tracker.py is not modified. Its module-level I/O names are swapped for the
    duration of the call and restored after.
    """
    saved = {}
    for name in ("load_trades", "save_trades", "load_stock", "get_live_price",
                 "add_indicators", "expire_queue"):
        saved[name] = getattr(tracker, name)
    trades = [trade]
    try:
        tracker.load_trades = lambda: trades
        tracker.save_trades = lambda t: None
        tracker.load_stock = lambda sym: df_slice
        tracker.get_live_price = lambda sym: None      # force daily Close
        # The slice is already indicator-augmented once, by run_case. Letting
        # tracker apply add_indicators a second time is not what live does, and on
        # short pre-entry history it returns None, which tracker's bare `except`
        # swallows into a silent no-op indistinguishable from "no action".
        tracker.add_indicators = lambda d: d
        tracker.expire_queue = lambda: []
        buf = StringIO()
        with redirect_stdout(buf):
            tracker.check_open_trades()
        out = buf.getvalue()
    finally:
        for name, fn in saved.items():
            setattr(tracker, name, fn)
    # tracker wraps each trade in `except Exception` and only prints. A swallowed
    # error would otherwise look identical to "no action taken".
    err = "Error checking" in out
    return trade, out, err


def step_module(pos, row, params, day_str):
    """Run ONE bar through the canonical module at the call sites the swap will use.

    This function is, in effect, the proposed post-swap call site. It performs no
    exit logic of its own: update_peak, decide_scale_out, effective_stop and
    decide_exit come from the module. Booking mirrors tracker's same-bar scale-out
    fill, deliberately WITHOUT tracker's 2dp rounding, so any rounding divergence is
    detected rather than masked.
    """
    price = float(row["Close"])
    rsi = float(row["rsi"]) if not pd.isna(row["rsi"]) else 50.0
    div = bool(row.get("bearish_div", False))
    pos["_bar_date"] = day_str

    exit_policy.update_peak(pos, price, params)
    eff = exit_policy.effective_stop(pos, params)

    tier = exit_policy.decide_scale_out(pos, price, params)
    if tier and not pos["scaled_out"]:
        slip = params.get("slippage_pct", 0.001)
        comm = params.get("commission_per_trade", 1.00)
        fill = price * (1 - slip)
        sell = pos["original_shares"] * tier["fraction"]
        pos["shares"] = pos["shares"] - sell
        exit_policy.record_tier_fill(pos, fill, day_str)
        pos["scale_out_date"] = day_str
        pos["scale_out_price"] = fill
        pos["scale_out_shares"] = sell
        pos["scale_out_proceeds"] = sell * fill - comm
        pos["commission_paid"] += comm
        return {"action": "scale_out", "effective_stop": eff}   # short-circuits

    reason, px = exit_policy.decide_exit(pos, price, rsi, div, params,
                                         holding_days=None)
    if reason:
        return {"action": "exit", "exit_reason": reason, "exit_price": px,
                "exit_date": day_str, "effective_stop": eff}
    return {"action": "hold", "effective_stop": eff}


def classify(field, tv, mv, mres=None, params=None):
    """Classify one field mismatch. Does NOT decide which side is correct.

    A numeric mismatch is only called "explained by rounding" when tracker's own
    rounding discipline, applied to the module's value, REPRODUCES tracker's stored
    value exactly. That is a derivation, not a widened tolerance.
    """
    if isinstance(tv, bool) or isinstance(mv, bool) or tv is None or mv is None \
            or isinstance(tv, str) or isinstance(mv, str):
        return "categorical_mismatch"
    tvf, mvf = float(tv), float(mv)
    if abs(tvf - mvf) <= DOLLAR_TOL:
        return None
    # Direct: tracker stores round(x, 2) of the module's value.
    if abs(round(mvf, 2) - tvf) <= DOLLAR_TOL:
        return "tracker_2dp_rounding"
    # Compounded: tracker derives effective_stop from ALREADY-ROUNDED state, applies
    # the fill model, then rounds again. Rebuild that exact sequence.
    if field == "exit_price" and mres is not None and params is not None:
        slip = params.get("slippage_pct", 0.001)
        eff = mres.get("effective_stop")
        for cand in ([round(round(eff, 2) * (1 - slip), 2)] if eff is not None else []):
            if abs(cand - tvf) <= DOLLAR_TOL:
                return "tracker_rounding_compounded"
    return "unexplained_numeric"


def compare(trade, pos, mres, bar, case, params):
    """Compare the two state projections after one bar."""
    proj_m = {
        "peak_price": pos["peak_price"], "trailing_stop": pos["trailing_stop"],
        "shares": pos["shares"], "scaled_out": bool(pos["scaled_out"]),
        "scale_out_price": pos["scale_out_price"] or 0.0,
        "scale_out_shares": pos["scale_out_shares"] or 0.0,
        "scale_out_date": pos["scale_out_date"],
        "status": "closed" if mres["action"] == "exit" else "open",
        "exit_reason": mres.get("exit_reason"),
        # decide_exit returns the DECISION price; tracker's _close_trade owns the
        # fill and applies exit slippage. Athena discards the module's price
        # entirely and fills at next open. So the module price is mapped through
        # Ares' fill model before comparison, or this compares a decision to a fill.
        "exit_price": (None if mres.get("exit_price") is None else
                       mres["exit_price"] * (1 - params.get("slippage_pct", 0.001))),
        "exit_date": mres.get("exit_date"),
    }
    proj_t = {
        "peak_price": trade.get("peak_price"),
        "trailing_stop": trade.get("trailing_stop"),
        "shares": trade.get("shares"),
        "scaled_out": bool(trade.get("scaled_out", False)),
        "scale_out_price": trade.get("scale_out_price") or 0.0,
        "scale_out_shares": trade.get("scale_out_shares") or 0.0,
        "scale_out_date": trade.get("scale_out_date"),
        "status": trade.get("status"),
        "exit_reason": trade.get("exit_reason"),
        "exit_price": trade.get("exit_price"),
        "exit_date": trade.get("exit_date"),
    }
    out = []
    for f in COMPARED:
        tv, mv = proj_t[f], proj_m[f]
        if f in ("exit_reason", "exit_price", "exit_date") and proj_t["status"] == "open":
            continue          # tracker leaves these absent until it closes
        if tv == mv:
            continue
        kind = classify(f, tv, mv, mres, params)
        if kind is None:
            continue
        out.append({"case": case["id"], "bar": bar, "field": f,
                    "tracker": tv, "module": mv, "kind": kind})
    return out


def run_case(case, params):
    """Replay one case bar by bar on independently cloned state objects."""
    df = case["bars"]
    from engine.indicators import add_indicators
    df = add_indicators(df.sort_index())
    trade = tracker_trade(case)
    pos = module_pos(case)
    if case.get("preset_scaled"):
        half = case["shares"] * 0.5
        for st in (trade, pos):
            st["scaled_out"] = True
            st["shares"] = case["shares"] - half
        trade["scale_out_price"] = round(case["take_profit"], 2)
        trade["scale_out_shares"] = round(half, 2)
        trade["scale_out_date"] = case["entry_date"]
        pos["scale_out_price"] = round(case["take_profit"], 2)
        pos["scale_out_shares"] = round(half, 2)
        pos["scale_out_date"] = case["entry_date"]
        pos["tiers_hit"] = 1
        pos["peak_before_first_tier"] = case["entry_price"]
    findings, bars_run, closed_at = [], 0, None

    for i in range(len(df)):
        day_str = str(df.index[i])[:10]
        if day_str < case["entry_date"]:
            continue
        if day_str == case["entry_date"]:
            continue          # both sides suppress the entry bar
        sl = df.iloc[: i + 1]
        # deepcopy so neither implementation's mutation can reach the other
        t_before = deepcopy(trade)
        trade, out, err = step_tracker(trade, sl)
        if err:
            findings.append({"case": case["id"], "bar": i, "field": "<exception>",
                             "tracker": out.strip()[:200], "module": None,
                             "kind": "tracker_raised"})
            break
        mres = step_module(pos, df.iloc[i], params, day_str)
        bars_run += 1
        findings.extend(compare(trade, pos, mres, i, case, params))
        t_closed = trade.get("status") == "closed"
        m_closed = mres["action"] == "exit"
        if t_closed or m_closed:
            if t_closed != m_closed:
                findings.append({
                    "case": case["id"], "bar": i, "field": "<termination>",
                    "tracker": "closed" if t_closed else "open",
                    "module": "closed" if m_closed else "open",
                    "kind": "categorical_mismatch"})
            closed_at = day_str
            break
    return findings, bars_run, closed_at


def synth(closes, start="2025-01-02", gap_after=None):
    """Deterministic frame: oscillating warmup so indicators are defined, then the
    shaped closes. Flat warmup would leave rsi undefined and silently disable the
    emotional_extreme branch on both sides."""
    warm = [99.9 if i % 2 else 100.1 for i in range(110)]
    px = warm + list(closes)
    idx = pd.bdate_range(start, periods=len(px))
    if gap_after is not None:
        keep = [i for i in range(len(px)) if i != 110 + gap_after]
        px = [px[i] for i in keep]
        idx = idx[: len(px)]
    return pd.DataFrame({
        "Open": px, "High": [p * 1.001 for p in px], "Low": [p * 0.999 for p in px],
        "Close": px, "Volume": [1_000_000] * len(px),
    }, index=pd.DatetimeIndex(idx, name="Date"))


def boundary_fixtures():
    """Registered boundary cases. The confound found in Block A was a
    strategy-specific scale-out branch that happy-path replay did not expose, so
    thresholds are probed from below, at, and above on BOTH strategies."""
    cases, e = [], 100.0
    entry_date = str(pd.bdate_range("2025-01-02", periods=111)[109])[:10]
    base = {"symbol": "SYN", "entry_price": e, "shares": 10.0, "stop_loss": 90.0,
            "entry_date": entry_date}

    for strat, tp in (("mean_reversion", 110.0), ("momentum_breakout", 118.0)):
        tag = "rev" if strat == "mean_reversion" else "mom"
        for name, mult in (("just_below", 0.9999), ("exact", 1.0),
                           ("just_above", 1.0001)):
            cases.append({**base, "id": f"tp_{tag}_{name}", "strategy": strat,
                          "take_profit": tp, "bars": synth([tp * mult] * 3)})

    # Stop boundary. eff_stop = max(stop_loss, trailing_stop); with no peak above
    # entry the trail stays at 90, so these probe stop_loss directly and the
    # trailing_stop-vs-stop_loss reason branch.
    for name, px in (("just_above", 90.01), ("exact", 90.0), ("just_below", 89.99)):
        cases.append({**base, "id": f"stop_{name}", "strategy": "momentum_breakout",
                      "take_profit": 118.0, "bars": synth([px] * 3)})

    # Trail vs initial stop. Peak must exceed 100 for trail to climb off 90.
    for name, peak in (("trail_below_stop", 99.0), ("trail_equals_stop", 100.0),
                       ("trail_above_stop", 105.0)):
        cases.append({**base, "id": name, "strategy": "momentum_breakout",
                      "take_profit": 118.0, "bars": synth([peak, peak * 0.88])})

    # Peak either side of +11.11%, where peak x 0.90 crosses the entry price.
    for name, peak in (("peak_below_1111", 111.0), ("peak_at_1111", 111.11),
                       ("peak_above_1111", 111.2)):
        cases.append({**base, "id": name, "strategy": "momentum_breakout",
                      "take_profit": 118.0, "bars": synth([peak, peak * 0.85])})

    # Scale-out then trail exit on a later bar. NOTE: "scale-out and exit both
    # eligible on the SAME bar with scaled_out False" is structurally unreachable
    # under Policy A, because update_peak runs first, so effective_stop is at most
    # close x 0.90 < close on the bar that first crosses TP. Asserted separately.
    cases.append({**base, "id": "scaled_then_trail_exit",
                  "strategy": "momentum_breakout", "take_profit": 118.0,
                  "bars": synth([150.0, 134.0, 120.0])})
    # Already-scaled precondition: the scale-out block must stay skipped.
    cases.append({**base, "id": "preset_scaled_out", "strategy": "momentum_breakout",
                  "take_profit": 118.0, "preset_scaled": True,
                  "bars": synth([125.0, 130.0, 100.0])})
    # Flat path, zero realised volatility.
    cases.append({**base, "id": "zero_volatility", "strategy": "momentum_breakout",
                  "take_profit": 118.0, "bars": synth([100.0] * 5)})
    # Missing bar mid-path.
    cases.append({**base, "id": "missing_bar", "strategy": "momentum_breakout",
                  "take_profit": 118.0, "bars": synth([105.0, 106.0, 92.0],
                                                      gap_after=1)})
    # mean_reversion_complete requires rsi > 70 and is the branch the latent
    # divergence elif can starve. Sharp rally drives rsi up.
    cases.append({**base, "id": "rev_complete_rsi", "strategy": "mean_reversion",
                  "take_profit": 999.0,
                  "bars": synth([100 + i for i in range(1, 12)])})
    return cases


def historical_cases(limit=None):
    """Run A' entries replayed on the frozen snapshot. Supplementary: symbols absent
    from the 220-symbol snapshot are skipped and the coverage is reported."""
    cases, missing, short = [], set(), set()
    for f, uni in (("v6_runA2_A_original_130_trades.csv", "A"),
                   ("v6_runA2_B_midcap_98_trades.csv", "B")):
        p = RESULTS / f
        if not p.exists():
            continue
        for _, r in pd.read_csv(p).iterrows():
            bars = load_bars(r["symbol"])
            if bars is None:
                missing.add(r["symbol"])
                continue
            # Indicators need real preceding bars. Fewer than 100 before entry and
            # the frame cannot support the 50-bar warm-ups, so the case is a
            # coverage gap, not a result.
            pre = (bars.index < pd.Timestamp(r["entry_date"])).sum()
            if pre < 100:
                short.add(f"{r['symbol']}@{r['entry_date']}({pre})")
                continue
            cases.append({
                "id": f"hist_{uni}_{r['symbol']}_{r['entry_date']}",
                "symbol": r["symbol"], "strategy": r["strategy"],
                "entry_date": r["entry_date"],
                "entry_price": float(r["entry_price"]),
                "shares": float(r["original_shares"]),
                "stop_loss": float(r["stop_loss"]),
                "take_profit": float(r["take_profit"]),
                "bars": bars,
            })
    if limit:
        cases = cases[:limit]
    return cases, sorted(missing), sorted(short)


def assert_same_bar_unreachable(params):
    """Property, not a fixture. Under Policy A, update_peak runs before the scale-out
    test, so on the bar that first crosses TP the peak IS that close and
    effective_stop is at most close x 0.90, strictly below close. So an exit and a
    first scale-out can never both be eligible on one bar. If this ever fails, the
    scale-out `continue` ordering starts to matter for outcome, not just sequencing."""
    for tp_mult in (1.10, 1.18):
        for close in (100.0, 150.0, 1000.0):
            pos = module_pos({"symbol": "P", "strategy": "momentum_breakout",
                              "entry_date": "2025-01-02", "entry_price": 100.0,
                              "shares": 10.0, "stop_loss": 90.0,
                              "take_profit": 100.0 * tp_mult})
            exit_policy.update_peak(pos, close, params)
            if exit_policy.decide_scale_out(pos, close, params) is None:
                continue
            if close <= exit_policy.effective_stop(pos, params):
                raise AssertionError(
                    f"same-bar scale-out AND exit both eligible at close={close}, "
                    f"tp_mult={tp_mult}; the continue ordering now changes outcomes")
    return True


def main():
    params = tracker._load_params()
    params.setdefault("exit_policy", "A")
    hist_limit = None
    if "--quick" in sys.argv:
        hist_limit = 40

    print("=" * 74)
    print("  TRACKER MIGRATION PHASE 0 — DIFFERENTIAL EQUIVALENCE")
    print("=" * 74)
    print("  Compares Ares/engine/tracker.py's inline exit chain against the")
    print("  canonical engine/exit_policy.py, per bar, on cloned state.")
    print("  NOT a Block A experiment. Passing does NOT authorize the live swap.")
    print(f"  tracker.py modified: NO   dollar tolerance: {DOLLAR_TOL}")
    assert_same_bar_unreachable(params)
    print("  property   same-bar scale-out+exit is unreachable under A: PASS")

    fx = boundary_fixtures()
    hist, missing, short = historical_cases(limit=hist_limit)
    print(f"  fixtures {len(fx)}   historical {len(hist)}"
          f"   absent from snapshot {len(missing)}"
          f"   skipped for insufficient warm-up {len(short)}")

    all_find, stats = [], {}
    for label, pop in (("BOUNDARY FIXTURES", fx), ("HISTORICAL PATHS", hist)):
        print(f"\n  --- {label} ({len(pop)} cases) ---")
        nb = 0
        for case in pop:
            try:
                f, bars, _ = run_case(case, params)
            except Exception as exc:
                f = [{"case": case["id"], "bar": -1, "field": "<harness>",
                      "tracker": None, "module": None,
                      "kind": f"harness_error:{type(exc).__name__}:{exc}"}]
                bars = 0
            nb += bars
            all_find.extend(f)
        kinds = {}
        for x in all_find:
            kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
        stats[label] = {"cases": len(pop), "bars": nb}
        print(f"      bars stepped {nb}")

    kinds = {}
    for x in all_find:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1

    print(f"\n{'=' * 74}\n  RESULT\n{'=' * 74}")
    if not all_find:
        print("  PASS — decision- and state-equivalent across every compared field,")
        print("  on all boundary fixtures and every replayed historical path.")
    else:
        print(f"  {len(all_find)} mismatch(es) by classification:")
        for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]):
            print(f"      {k:<28} {v}")
        print("\n  First 20, unclassified-by-side (tracker is live; equivalence means")
        print("  the module reproduces tracker, NOT that tracker is correct):")
        print(f"    {'case':<34} {'bar':>4} {'field':<17} {'tracker':>13} {'module':>15}")
        for x in all_find[:20]:
            print(f"    {str(x['case'])[:34]:<34} {x['bar']:>4} {x['field']:<17} "
                  f"{str(x['tracker'])[:13]:>13} {str(x['module'])[:15]:>15}")
        unexplained = [x for x in all_find
                       if x["kind"] in ("unexplained_numeric", "categorical_mismatch",
                                        "tracker_raised")]
        print(f"\n  Requiring contract resolution before Phase 0 can close: "
              f"{len(unexplained)}")
        print("  Do NOT fix either side automatically. Classify each as canonical")
        print("  module defect, tracker inline defect, intentional difference,")
        print("  ambiguous contract, or instrumentation mismatch.")

    out = {"phase": "tracker_migration_phase_0",
           "authorizes_swap": False,
           "tracker_modified": False,
           "dollar_tolerance": DOLLAR_TOL,
           "rounding_note": ("tracker stores 2dp-rounded peak_price, trailing_stop, "
                            "shares and scale_out_price; the canonical module keeps "
                            "full precision. Rounded state feeds the next bar, so "
                            "this is a contract difference to resolve before the "
                            "swap, not a cosmetic one."),
           "populations": stats,
           "snapshot_missing_symbols": missing,
           "skipped_insufficient_warmup": short,
           "excluded_fields": list(EXCLUDED),
           "compared_fields": list(COMPARED),
           "mismatch_counts": kinds,
           "mismatches": all_find[:500]}
    (RESULTS / "tracker_equivalence_summary.json").write_text(json.dumps(out, indent=2))
    print(f"\n  Saved results/tracker_equivalence_summary.json")
    residual = [x for x in all_find
                if x["kind"] not in ("tracker_2dp_rounding",
                                     "tracker_rounding_compounded")]
    # Decision equivalence is the question Phase 0 must answer. Stored-precision
    # differences matter only if they ever changed an outcome.
    decisions = [x for x in all_find
                 if x["field"] in ("exit_reason", "status", "<termination>",
                                   "scaled_out", "scale_out_date")]
    print(f"\n  DECISION-CHANGING mismatches (exit_reason, status, termination,")
    print(f"  scaled_out, scale_out_date): {len(decisions)}")
    if not decisions:
        print("  => No rounding difference ever altered a decision in this")
        print("     population. Divergence is confined to stored precision.")
    return 1 if residual else 0


if __name__ == "__main__":
    sys.exit(main())
