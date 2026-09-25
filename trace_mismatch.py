"""Bounded reconciliation: why can policies differing only in trail activation
produce different scale-out paths? Diagnostic only. Not part of Block A's outputs.

Logs state AROUND the canonical module's calls; it never reimplements a decision.
Self-checks by asserting the traced outcome equals replay_one's for the same trade.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "vendor")); sys.path.insert(0, str(ROOT))
import pandas as pd
from engine import exit_policy
from engine.portfolio_sim_v6 import _fill, load_params, prepare
from engine.universe import KNOWN_UNAVAILABLE, UNIVERSE_A
from run_exit_replay import position_from_record, replay_one, START, END

TARGETS = ["GILD", "AMT", "BMY", "UBER"]


def trace(rec, policy, df, trading_days, params):
    p = dict(params); p["exit_policy"] = policy
    slip = p.get("slippage_pct", 0.001); comm = p.get("commission_per_trade", 1.00)
    sop = p.get("scale_out_pct", 0.50)
    pos = position_from_record(rec)
    entry_ts = pd.Timestamp(rec["entry_date"])
    pending_exit, pending_scale, log, closed = None, False, [], None

    for day in trading_days:
        if day < entry_ts: continue
        ds = str(day)[:10]; has = day in df.index
        e = {"date": ds, "has_bar": has, "pend_exit_in": pending_exit,
             "pend_scale_in": pending_scale, "shares_in": pos["shares"],
             "scaled_in": pos["scaled_out"], "event": None}

        if pending_exit is not None:
            if has:
                px = _fill(float(df.loc[day, "Open"]), "sell", slip)
                e["event"] = f"EXIT_FILL {pending_exit} @{px:.4f}"
                closed = {"exit_date": ds, "exit_price": px, "exit_reason": pending_exit,
                          "exit_proceeds": pos["shares"] * px - comm}
                pos["commission_paid"] += comm
                log.append(e); break
            e["event"] = "EXIT_ORDER_DROPPED"; pending_exit = None

        if pending_scale:
            if has and not pos["scaled_out"]:
                px = _fill(float(df.loc[day, "Open"]), "sell", slip)
                sh = pos["original_shares"] * sop
                pos["commission_paid"] += comm; pos["shares"] -= sh
                exit_policy.record_tier_fill(pos, px, ds)
                pos["scale_out_date"] = ds; pos["scale_out_price"] = px
                pos["scale_out_shares"] = sh
                pos["scale_out_proceeds"] = sh * px - comm
                e["event"] = (e["event"] or "") + f" SCALE_FILL @{px:.4f}"
            else:
                e["event"] = (e["event"] or "") + " SCALE_ORDER_DROPPED"
            pending_scale = False

        if not has or ds == rec["entry_date"]:
            e["note"] = "no_bar" if not has else "entry_bar"; log.append(e); continue

        row = df.loc[day]; price = float(row["Close"])
        pos["_bar_date"] = ds
        exit_policy.update_peak(pos, price, p)
        so = exit_policy.decide_scale_out(pos, price, p)
        rsi = float(row["rsi"]) if not pd.isna(row["rsi"]) else 50.0
        reason, _ = exit_policy.decide_exit(pos, price, rsi,
                                           bool(row.get("bearish_div", False)), p)
        e.update({"close": price, "peak": pos["peak_price"],
                  "trail": pos["trailing_stop"],
                  "trail_act": exit_policy.trail_is_active(pos, p),
                  "eff_stop": exit_policy.effective_stop(pos, p),
                  "tp": pos["take_profit"], "so_cond": bool(so),
                  "exit_cond": reason, "both_true": bool(so) and bool(reason)})
        if so and not pos["scaled_out"]:
            pending_scale = True; e["event"] = "QUEUE_SCALE (short-circuits exit chain)"
        elif reason:
            pending_exit = reason; e["event"] = f"QUEUE_EXIT {reason}"
        log.append(e)

    inv = pos["original_shares"] * pos["entry_price"] + pos["entry_commission"]
    pnl = None if closed is None else (closed["exit_proceeds"]
                                       + pos["scale_out_proceeds"] - inv)
    return log, {"exit_date": None if not closed else closed["exit_date"],
                 "exit_reason": None if not closed else closed["exit_reason"],
                 "scaled_out": pos["scaled_out"],
                 "net": None if pnl is None else pnl / inv * 100}


params = load_params()
syms = [s for s in UNIVERSE_A if s not in KNOWN_UNAVAILABLE]
data = prepare(syms, START, END, params)
tdays = sorted({d for df in data.values() for d in df.index})
base = pd.read_csv("results/v6_runA2_A_original_130_trades.csv")

for sym in TARGETS:
    recs = base[base.symbol == sym]
    for _, rec in recs.iterrows():
        df = data[sym]
        la, oa = trace(rec, "A", df, tdays, params)
        # self-check against the production replay path
        ra = replay_one(rec, "A", df, tdays, params, rec["exit_date"],
                        float(rec["exit_price"]))
        ok = (oa["exit_date"] == ra["exit_date"]
              and oa["exit_reason"] == ra["exit_reason"]
              and oa["scaled_out"] == ra["scaled_out"])
        for pol in ("B", "D"):
            lp, op = trace(rec, pol, df, tdays, params)
            same_exit = (op["exit_date"] == oa["exit_date"]
                         and op["exit_reason"] == oa["exit_reason"])
            differs = (op["scaled_out"] != oa["scaled_out"]
                       or abs((op["net"] or 0) - (oa["net"] or 0)) > 1e-9)
            if not (same_exit and differs):
                continue   # legitimate trail-suppression path changes are not the puzzle
            print(f"\n{'=' * 78}")
            print(f"{sym} entry {rec['entry_date']}  A vs {pol}   trace_selfcheck="
                  f"{'OK' if ok else 'MISMATCH'}")
            print(f"  A: {oa['exit_date']} {oa['exit_reason']} so={oa['scaled_out']} "
                  f"net={oa['net']:+.3f}%   {pol}: {op['exit_date']} "
                  f"{op['exit_reason']} so={op['scaled_out']} net={op['net']:+.3f}%")
            ma = {e["date"]: e for e in la}; mp = {e["date"]: e for e in lp}
            first = None
            for d in sorted(set(ma) | set(mp)):
                a, b = ma.get(d), mp.get(d)
                if a is None or b is None:
                    first = d; break
                keys = ("event", "so_cond", "exit_cond", "shares_in", "scaled_in")
                if any(a.get(k) != b.get(k) for k in keys):
                    first = d; break
            print(f"  FIRST DIVERGENCE: {first}")
            for d in sorted(set(ma) | set(mp)):
                if first and d < first: continue
                a, b = ma.get(d, {}), mp.get(d, {})
                if not a.get("has_bar", True) and not a.get("event"): continue
                print(f"    {d}  close={a.get('close')}")
                for nm, x in (("A ", a), (pol + " ", b)):
                    print(f"      {nm} trail={x.get('trail')} act={x.get('trail_act')}"
                          f" eff={x.get('eff_stop')} tp={x.get('tp')}"
                          f" so_cond={x.get('so_cond')} exit_cond={x.get('exit_cond')}"
                          f" both={x.get('both_true')} | {x.get('event')}")
                if d >= max([k for k in (set(ma) | set(mp))
                             if k <= (first or d)] + [first or d]) and d != first:
                    pass
                if len([1 for k in sorted(set(ma) | set(mp)) if k >= (first or d)
                        and k <= d]) >= 4: break
