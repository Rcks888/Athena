"""Block A stage 1 — isolated paired exit-policy replay.

Registered in Ares/ROADMAP.md before this file existed. Reads that section first.

WHAT THIS IS
------------
For every entry Run A' actually took, replay the SAME entry on the SAME price path
under Policies A, B and D, and measure the paired difference. Entries are taken
verbatim from the Run A' trade records and are never re-derived, so nothing here
can change which trades exist - only how they exit.

WHY A SEPARATE RUNNER
---------------------
run_backtest_v6_runA2.py is the reference artifact for the Policy A parity gate. If
this file modified it, the experiment would produce both sides of its own
comparison. Run A' stays immutable; this is an independent consumer of the
canonical exit module (engine/exit_policy.py, md5-pinned in engine/parity.py).

There is NO exit logic in this file. Every decision comes from the module.

WHAT THIS IS NOT
----------------
Not a portfolio replay. Alternative exits change holding periods, which changes
slot occupancy, funding and which later signals could have been admitted. Stage 2
handles that. Stage 1 diagnoses the exit mechanism only, and a policy must not be
selected on stage 1 alone.

Not an entry-edge measurement. Every result is conditional on the opportunities
Run A' generated.

Not authorized to select a production policy. The untouched validation period holds
14 (A) and 10 (B) qualifying +18% triggers against a registered 20-per-universe
bar, so Block A is exploratory and Policy A is retained regardless of outcome.

FILL SEMANTICS, reproduced exactly from run_sim
-----------------------------------------------
Decisions are taken from a day's Close and filled at the NEXT trading day's Open
with slippage against us. `trading_days` is the union of bars across the whole
universe, not one symbol's index, because run_sim iterates that union - and if a
symbol has no bar on the fill day the order is DROPPED and the position stays open.
Walking a single symbol's calendar would silently never drop an order and parity
would fail for a reason unrelated to policy.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from engine import exit_policy, parity
from engine.portfolio_sim_v6 import _fill, load_params, prepare
from engine.universe import KNOWN_UNAVAILABLE, UNIVERSE_A, UNIVERSE_B

EVALUATION_CONTRACT_VERSION = "block_a_stage1_isolated_paired_v1"
START, END = "2021-09-01", "2026-09-01"
RESULTS = ROOT / "results"
POLICIES = ("A", "B", "D")          # C removed by dated amendment, see ROADMAP
REGISTERED_BAR_PP = 0.50            # mean paired delta, per trade, per universe
BOOTSTRAP_DRAWS = 10_000
RNG_SEED = 20260925

UNIVERSES = {
    "A": {"symbols": UNIVERSE_A, "trades": "v6_runA2_A_original_130_trades.csv"},
    "B": {"symbols": UNIVERSE_B, "trades": "v6_runA2_B_midcap_98_trades.csv"},
}

# Exact-match fields: a categorical or date mismatch is never a rounding artifact.
PARITY_EXACT = ("symbol", "entry_date", "exit_date", "exit_reason",
                "scaled_out", "scale_out_date", "holding_days")
# Numeric fields compared at full precision against a fixed absolute tolerance.
# Tolerances are sub-cent. Float accumulation over three separate commission
# additions legitimately exceeds 1e-6, and 1e-4 is still four orders of magnitude
# tighter than the smallest policy effect the experiment could detect.
PARITY_NUMERIC = {
    "exit_price": 1e-4, "scale_out_price": 1e-4, "scale_out_shares": 1e-6,
    "scale_out_proceeds": 1e-4, "exit_proceeds": 1e-4, "commission_paid": 1e-4,
    "original_shares": 1e-6, "remaining_shares": 1e-6,
    "pnl": 1e-4, "pnl_pct": 1e-4, "pnl_before_commission": 1e-4,
}


def position_from_record(rec):
    """Rebuild the entry state Run A' actually filled. Entries are never re-derived."""
    return {
        "symbol": rec["symbol"], "strategy": rec["strategy"],
        "entry_date": rec["entry_date"], "entry_price": float(rec["entry_price"]),
        "shares": float(rec["original_shares"]),
        "original_shares": float(rec["original_shares"]),
        "stop_loss": float(rec["stop_loss"]),
        "initial_stop": float(rec["stop_loss"]),
        "take_profit": float(rec["take_profit"]),
        "trailing_stop": float(rec["stop_loss"]),
        "peak_price": float(rec["entry_price"]),
        "trough_price": float(rec["entry_price"]),
        "highest_trailing_stop": float(rec["stop_loss"]),
        "trail_activated": False, "trail_activation_date": None,
        "tiers_hit": 0, "scaled_out": False, "scale_out_date": None,
        "scale_out_price": 0.0, "scale_out_shares": 0.0, "scale_out_proceeds": 0.0,
        "peak_before_first_tier": float(rec["entry_price"]),
        "peak_after_first_tier": None, "time_stop_bound": False,
        "entry_commission": float(rec["entry_commission"]),
        "commission_paid": float(rec["entry_commission"]),
    }


def replay_one(rec, policy, df, trading_days, params, a_exit_date, a_exit_price):
    """Replay a single entry under one policy. Returns the outcome dict.

    Mirrors run_sim's day ordering: fills queued yesterday happen at today's Open,
    then today's Close produces the next decision. Scale-out is evaluated before the
    exit chain and short-circuits it, reproducing live's `continue`.
    """
    p = dict(params)
    p["exit_policy"] = policy
    slippage = p.get("slippage_pct", 0.001)
    commission = p.get("commission_per_trade", 1.00)
    scale_out_pct = p.get("scale_out_pct", 0.50)

    pos = position_from_record(rec)
    entry_ts = pd.Timestamp(rec["entry_date"])
    a_exit_ts = pd.Timestamp(a_exit_date)

    pending_exit = None
    pending_scale = False
    sig = []          # per-bar event signature, for first_divergence_date
    ev = {"crossed_a_exit_level": False, "recovery_max_pct": None,
          "reached_tier_after_a_exit": False, "hit_initial_stop_after_a_exit": False,
          "bars_after_a_exit": 0}
    closed = None

    for day in trading_days:
        if day < entry_ts:
            continue
        day_str = str(day)[:10]
        has_bar = day in df.index

        # ---- 1. exit fill at today's open ----
        if pending_exit is not None:
            if has_bar:
                px = _fill(float(df.loc[day, "Open"]), "sell", slippage)
                proceeds = pos["shares"] * px - commission
                pos["commission_paid"] += commission
                closed = {"exit_date": day_str, "exit_price": px,
                          "exit_reason": pending_exit, "exit_proceeds": proceeds}
                sig.append((day_str, f"EXIT_FILL:{pending_exit}"))
                break
            sig.append((day_str, "EXIT_ORDER_DROPPED"))
            pending_exit = None          # dropped, exactly as run_sim drops it

        # ---- 2. scale-out fill at today's open ----
        if pending_scale:
            if has_bar and not pos["scaled_out"]:
                px = _fill(float(df.loc[day, "Open"]), "sell", slippage)
                shares = pos["original_shares"] * scale_out_pct
                proceeds = shares * px - commission
                pos["commission_paid"] += commission
                pos["shares"] -= shares
                exit_policy.record_tier_fill(pos, px, day_str)
                pos["scale_out_date"] = day_str
                pos["scale_out_price"] = px
                pos["scale_out_shares"] = shares
                pos["scale_out_proceeds"] = proceeds
                if day > a_exit_ts:
                    ev["reached_tier_after_a_exit"] = True
                sig.append((day_str, f"SCALE_FILL@{px:.4f}"))
            pending_scale = False

        if not has_bar:
            continue
        if day_str == rec["entry_date"]:
            continue

        row = df.loc[day]
        price = float(row["Close"])

        if day > a_exit_ts:
            ev["bars_after_a_exit"] += 1
            if price > a_exit_price:
                ev["crossed_a_exit_level"] = True
            rp = (price - pos["entry_price"]) / pos["entry_price"] * 100
            if ev["recovery_max_pct"] is None or rp > ev["recovery_max_pct"]:
                ev["recovery_max_pct"] = rp

        pos["_bar_date"] = day_str
        exit_policy.update_peak(pos, price, p)

        if exit_policy.decide_scale_out(pos, price, p) and not pos["scaled_out"]:
            pending_scale = True
            sig.append((day_str, "QUEUE_SCALE"))
            continue

        holding = (day - entry_ts).days
        rsi = float(row["rsi"]) if not pd.isna(row["rsi"]) else 50.0
        reason, _px = exit_policy.decide_exit(
            pos, price, rsi, bool(row.get("bearish_div", False)), p,
            holding_days=None)          # time stop inert, matching Run A'
        if reason:
            pending_exit = reason
            sig.append((day_str, f"QUEUE_EXIT:{reason}"))
            if day > a_exit_ts and reason == "stop_loss":
                ev["hit_initial_stop_after_a_exit"] = True

    invested = pos["original_shares"] * pos["entry_price"] + pos["entry_commission"]
    if closed is None:
        return {"open_at_end": True, "policy": policy, "pos": pos, "events": ev,
                "net_return": None, "pnl_pct": None, "exit_date": None,
                "exit_price": None, "exit_reason": "still_open",
                "holding_days": None, "original_shares": pos["original_shares"],
                "stop_loss": pos["stop_loss"],
                "scale_out_date": pos["scale_out_date"],
                "scale_out_price": pos["scale_out_price"],
                "scale_out_shares": pos["scale_out_shares"],
                "scale_out_proceeds": pos["scale_out_proceeds"],
                "commission_paid": pos["commission_paid"],
                "remaining_shares": pos["shares"],
                "scaled_out": bool(pos["scaled_out"]), "invested": invested,
                "sig": sig}

    returned = closed["exit_proceeds"] + pos["scale_out_proceeds"]
    pnl = returned - invested
    return {
        "open_at_end": False, "policy": policy, "pos": pos, "events": ev,
        "exit_date": closed["exit_date"], "exit_price": closed["exit_price"],
        "exit_reason": closed["exit_reason"], "exit_proceeds": closed["exit_proceeds"],
        "scaled_out": bool(pos["scaled_out"]),
        "scale_out_date": pos["scale_out_date"],
        "scale_out_price": pos["scale_out_price"],
        "scale_out_shares": pos["scale_out_shares"],
        "scale_out_proceeds": pos["scale_out_proceeds"],
        "commission_paid": pos["commission_paid"],
        "remaining_shares": pos["shares"],
        "original_shares": pos["original_shares"],
        "stop_loss": pos["stop_loss"],
        "pnl": pnl, "pnl_pct": pnl / invested * 100,
        "net_return": pnl / invested * 100,
        "pnl_before_commission": pnl + pos["commission_paid"],
        "holding_days": (pd.Timestamp(closed["exit_date"]) - entry_ts).days,
        "invested": invested, "sig": sig,
    }


def classify(res, a_net_return):
    """Frozen precedence. Event flags are preserved separately; this is for summary
    reporting only, and a trade may satisfy several underlying facts at once."""
    ev = res["events"]
    if res["open_at_end"]:
        return "still_open"
    if ev["reached_tier_after_a_exit"]:
        return "reached_tier"
    if res["net_return"] is not None and res["net_return"] > a_net_return:
        return "recovered_and_improved"
    if ev["crossed_a_exit_level"]:
        return "recovered_insufficiently"
    if res["exit_reason"] == "stop_loss":
        return "hit_initial_stop"
    if res["exit_reason"] == "time_stop":
        return "time_stop"
    return "other_rule"


def parity_check(rows, baseline):
    """Exact on categorical and date fields, fixed absolute tolerance on numerics.
    Full-precision comparison - values are formatted only for the report."""
    fails = []
    base = baseline.set_index("symbol_entry")
    for r in rows:
        key = f"{r['symbol']}|{r['entry_date']}"
        if key not in base.index:
            fails.append({"key": key, "field": "<row>", "baseline": "MISSING",
                          "replay": "present", "diff": None, "tol": None})
            continue
        b = base.loc[key]
        for f in PARITY_EXACT:
            bv, rv = b[f], r.get(f)
            if f == "scaled_out":
                bv, rv = bool(bv), bool(rv)
            if f == "scale_out_date":
                bv = None if pd.isna(bv) else str(bv)
                rv = None if rv is None else str(rv)
            if str(bv) != str(rv):
                fails.append({"key": key, "field": f, "baseline": bv,
                              "replay": rv, "diff": None, "tol": "exact"})
        for f, tol in PARITY_NUMERIC.items():
            if f not in b.index:
                continue
            bv = float(b[f]); rv = r.get(f)
            if rv is None:
                fails.append({"key": key, "field": f, "baseline": bv,
                              "replay": None, "diff": None, "tol": tol})
                continue
            d = abs(float(rv) - bv)
            if d > tol:
                fails.append({"key": key, "field": f, "baseline": bv,
                              "replay": float(rv), "diff": d, "tol": tol})
    return fails


def block_bootstrap(deltas, dates, draws=BOOTSTRAP_DRAWS, seed=RNG_SEED):
    """Date-block resample. Trade-level resampling would understate uncertainty
    because overlapping holdings share market periods; blocks are calendar months."""
    rng = np.random.default_rng(seed)
    blocks = {}
    for d, x in zip(dates, deltas):
        blocks.setdefault(str(d)[:7], []).append(x)
    keys = list(blocks)
    if not keys:
        return (float("nan"), float("nan"))
    means = np.empty(draws)
    for i in range(draws):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        vals = [v for j in pick for v in blocks[keys[j]]]
        means[i] = np.mean(vals) if vals else np.nan
    return (float(np.nanpercentile(means, 5)), float(np.nanpercentile(means, 95)))


def assert_scale_out_policy_invariant(params):
    """A/B/D share an identical tiers list and differ ONLY in trail_activation, so
    scale-out eligibility must not depend on which policy is running. Regression
    guard for the confound found by trace_mismatch.py: a policy-gated take_profit
    branch moved the mean_reversion tier from +10% to +18% under B and D."""
    for tp_mult, strategy in ((1.10, "mean_reversion"), (1.18, "momentum_breakout")):
        entry = 100.0
        pos = {"entry_price": entry, "take_profit": entry * tp_mult,
               "tiers_hit": 0, "strategy": strategy, "scaled_out": False,
               "peak_price": entry, "stop_loss": entry * 0.9,
               "trailing_stop": entry * 0.9}
        for price in (entry * tp_mult - 0.01, entry * tp_mult + 0.01, entry * 1.25):
            got = {}
            for pol in POLICIES:
                p = dict(params); p["exit_policy"] = pol
                got[pol] = exit_policy.decide_scale_out(pos, price, p) is not None
            if len(set(got.values())) != 1:
                raise AssertionError(
                    f"scale-out eligibility is policy-dependent: {strategy} "
                    f"tp={entry * tp_mult:.2f} price={price:.2f} -> {got}. "
                    f"A/B/D differ only in trail_activation; this is a confound.")
    print("  invariant  scale-out eligibility is policy-independent: PASS")


def main():
    parity.assert_signals_parity()
    exits_md5 = parity.assert_exit_policy_parity()
    params = load_params()

    print("=" * 74)
    print("  BLOCK A STAGE 1 — ISOLATED PAIRED EXIT-POLICY REPLAY")
    print("=" * 74)
    print(f"  contract   {EVALUATION_CONTRACT_VERSION}")
    print(f"  exit md5   {exits_md5}")
    print(f"  policies   {', '.join(POLICIES)}   (C removed by dated amendment)")
    print(f"  bar        mean paired delta >= {REGISTERED_BAR_PP:+.2f}pp/trade, "
          f"per universe, not pooled")
    print("  EXPLORATORY — cannot select a production policy. Policy A is retained")
    print("  regardless of outcome. Registered prior: B and D are EXPECTED to fail.")
    assert_scale_out_policy_invariant(params)

    all_rows, report = [], {}
    for uni, cfg in UNIVERSES.items():
        base = pd.read_csv(RESULTS / cfg["trades"])
        base["symbol_entry"] = base["symbol"] + "|" + base["entry_date"]
        print(f"\n{'=' * 74}\n  UNIVERSE {uni}  —  {len(base)} entries from Run A'\n{'=' * 74}")
        # Same exclusion Run A' applies before run_sim. Filtering differently here
        # would change the trading-day union and therefore which fill orders get
        # dropped, which is a parity-relevant difference, not a cosmetic one.
        syms = [s for s in cfg["symbols"] if s not in KNOWN_UNAVAILABLE]
        data = prepare(syms, START, END, params)
        trading_days = sorted({d for df in data.values() for d in df.index})

        outcomes = {pol: [] for pol in POLICIES}
        for _, rec in base.iterrows():
            df = data.get(rec["symbol"])
            if df is None:
                print(f"    !! {rec['symbol']} absent from prepared data — skipped")
                continue
            for pol in POLICIES:
                r = replay_one(rec, pol, df, trading_days, params,
                               rec["exit_date"], float(rec["exit_price"]))
                r["symbol"] = rec["symbol"]
                r["entry_date"] = rec["entry_date"]
                r["signal_date"] = rec["signal_date"]
                r["strategy"] = rec["strategy"]
                r["entry_price"] = float(rec["entry_price"])
                outcomes[pol].append(r)

        # ---- GATE 1: Policy A parity ----
        fails = parity_check(outcomes["A"], base)
        print(f"\n  GATE 1 — POLICY A PARITY vs Run A'")
        if fails:
            print(f"    FAIL — {len(fails)} mismatch(es). First 25:")
            print(f"    {'symbol|entry':<26} {'field':<22} {'baseline':>14} "
                  f"{'replay':>14} {'diff':>12} {'tol':>8}")
            for f in fails[:25]:
                dd = "" if f["diff"] is None else f"{f['diff']:.3e}"
                print(f"    {f['key']:<26} {f['field']:<22} {str(f['baseline'])[:14]:>14} "
                      f"{str(f['replay'])[:14]:>14} {dd:>12} {str(f['tol']):>8}")
            print("\n  POLICY_A_PARITY_FAILED")
            print("  Alternative policies were NOT evaluated.")
            sys.exit(2)
        print(f"    PASS — all {len(outcomes['A'])} Policy A trades reproduce Run A'")
        print(f"           exact on {', '.join(PARITY_EXACT)}")

        # ---- mechanism invariants, per strategy ----
        print(f"\n  MECHANISM INVARIANTS (Policy A)")
        a = outcomes["A"]
        v_struct = sum(1 for r in a if r["scaled_out"] and r["exit_reason"] == "stop_loss")
        print(f"    scale_out => exit_reason != stop_loss        : "
              f"{'PASS' if v_struct == 0 else f'FAIL ({v_struct})'}")
        for strat, label in (("momentum_breakout", "+18% momentum tier"),
                             ("mean_reversion", "+10% reversal tier")):
            sub = [r for r in a if r["strategy"] == strat and r["scaled_out"]]
            neg = [r for r in sub if r["net_return"] is not None and r["net_return"] < 0]
            print(f"    {label:<28} : {len(neg)} net-loss of {len(sub)} executions"
                  f"{'  (observed, not guaranteed)' if neg else ''}")

        report[uni] = {"parity": "PASS", "n": len(a), "policies": {}}

        # ---- GATES 2-4 per alternative ----
        a_by_key = {(r["symbol"], r["entry_date"]): r for r in a}
        for pol in POLICIES:
            if pol == "A":
                continue
            deltas, dates, affected, rows = [], [], [], []
            for r in outcomes[pol]:
                ar = a_by_key[(r["symbol"], r["entry_date"])]
                an = ar["net_return"]
                cn = r["net_return"]
                d = 0.0 if (cn is None or an is None) else cn - an
                # trail_suppressed described only the immediate intervention and
                # undercounted: trades exist with identical exit date AND reason but
                # a different scale-out path. Affected is now path divergence.
                exit_differed = (r["exit_date"] != ar["exit_date"]
                                 or r["exit_reason"] != ar["exit_reason"])
                scale_differed = (r.get("scale_out_date") != ar.get("scale_out_date")
                                  or abs((r.get("scale_out_proceeds") or 0)
                                         - (ar.get("scale_out_proceeds") or 0)) > 1e-9)
                share_differed = abs((r.get("remaining_shares") or 0)
                                     - (ar.get("remaining_shares") or 0)) > 1e-9
                comm_differed = abs((r.get("commission_paid") or 0)
                                    - (ar.get("commission_paid") or 0)) > 1e-9
                fd, fe = None, None
                for x, y in zip(ar["sig"], r["sig"]):
                    if x != y:
                        fd, fe = x[0], f"A:{x[1]} vs {pol}:{y[1]}"
                        break
                else:
                    if len(ar["sig"]) != len(r["sig"]):
                        longer = ar["sig"] if len(ar["sig"]) > len(r["sig"]) else r["sig"]
                        k = min(len(ar["sig"]), len(r["sig"]))
                        fd, fe = longer[k][0], f"extra {longer[k][1]}"
                changed = (exit_differed or scale_differed or share_differed
                           or comm_differed or abs(d) > 1e-9)
                deltas.append(d); dates.append(r["entry_date"])
                if changed:
                    affected.append((r, ar, d))
                rows.append({
                    "universe": uni, "symbol": r["symbol"],
                    "signal_date": r["signal_date"], "entry_date": r["entry_date"],
                    "entry_price": r["entry_price"], "strategy": r["strategy"],
                    "policy": pol, "exit_policy_version": exits_md5,
                    "evaluation_contract_version": EVALUATION_CONTRACT_VERSION,
                    "policy_a_exit_date": ar["exit_date"],
                    "policy_a_exit_price": ar["exit_price"],
                    "policy_a_exit_reason": ar["exit_reason"],
                    "policy_a_net_return": an,
                    "policy_a_holding_days": ar["holding_days"],
                    "policy_a_scale_out_triggered": ar["scaled_out"],
                    "counterfactual_exit_date": r["exit_date"],
                    "counterfactual_exit_price": r["exit_price"],
                    "counterfactual_exit_reason": r["exit_reason"],
                    "counterfactual_net_return": cn,
                    "counterfactual_holding_days": r["holding_days"],
                    "counterfactual_scale_out_triggered": r["scaled_out"],
                    "paired_delta": d,
                    "trail_suppressed": exit_differed,
                    "policy_path_diverged": changed,
                    "first_divergence_date": fd,
                    "first_divergence_event": fe,
                    "scale_out_path_differed": scale_differed,
                    "share_path_differed": share_differed,
                    "commission_path_differed": comm_differed,
                    "exit_path_differed": exit_differed,
                    "policy_a_exit_crossed": r["events"]["crossed_a_exit_level"],
                    "recovery_max_pct": r["events"]["recovery_max_pct"],
                    "recovered_and_improved": (cn is not None and an is not None
                                               and cn > an),
                    "reached_tier_after_policy_a_exit":
                        r["events"]["reached_tier_after_a_exit"],
                    "hit_initial_stop_after_policy_a_exit":
                        r["events"]["hit_initial_stop_after_a_exit"],
                    "hit_time_stop": r["exit_reason"] == "time_stop",
                    "bars_after_policy_a_exit": r["events"]["bars_after_a_exit"],
                    "still_open": r["open_at_end"],
                    "post_exit_classification": classify(r, an if an is not None else 0.0),
                })
            all_rows.extend(rows)

            arr = np.array(deltas)
            nz = arr[arr != 0]
            lo, hi = block_bootstrap(arr.tolist(), dates)
            n = len(arr)
            mean_d = float(arr.mean())
            req = (REGISTERED_BAR_PP * n / len(affected)) if affected else float("nan")
            asub = [x[1]["net_return"] for x in affected if x[1]["net_return"] is not None]

            print(f"\n  {'-' * 70}\n  POLICY {pol} vs A  —  UNIVERSE {uni}\n  {'-' * 70}")
            print(f"  GATE 2 — affected-subset recovery hurdle")
            print(f"    NOT an upper bound. Policy A's peaks are truncated at A's exit,")
            print(f"    so under {pol} these trades run longer and may exceed them.")
            print(f"      trades altered          : {len(affected)} of {n} "
                  f"({100 * len(affected) / n:.1f}%)")
            if asub:
                print(f"      their Policy A mean ret : {np.mean(asub):+.2f}%")
                print(f"      losses among them       : "
                      f"{sum(1 for x in asub if x < 0)} of {len(asub)}")
            print(f"      required per altered    : {req:+.2f}pp to move the "
                  f"{n}-trade mean by {REGISTERED_BAR_PP:+.2f}pp")

            print(f"  GATE 3 — paired result")
            print(f"      mean paired delta       : {mean_d:+.4f}pp")
            print(f"      median paired delta     : {float(np.median(arr)):+.4f}pp")
            print(f"      90% date-block interval : [{lo:+.4f}, {hi:+.4f}]pp")
            print(f"      non-zero deltas         : {len(nz)}   zero: {n - len(nz)}")
            if len(nz):
                print(f"      positive share (non-0)  : "
                      f"{100 * (nz > 0).mean():.1f}%")
                pos = np.sort(nz[nz > 0])[::-1]
                if len(pos):
                    tot = pos.sum()
                    c10 = pos[:10].sum() / tot * 100 if tot > 0 else float("nan")
                    print(f"      concentration_10        : {c10:.1f}%  "
                          f"(gross positive denominator; unsupported if > 50%)")
            verdict = ("CLEARS" if mean_d >= REGISTERED_BAR_PP and lo > 0
                       else "FAILS")
            print(f"      registered bar {REGISTERED_BAR_PP:+.2f}pp   : {verdict}")

            print(f"  GATE 4 — mechanism explanation (affected subset only)")
            cls = pd.Series([r["post_exit_classification"] for r in rows
                             if r["policy_path_diverged"]]).value_counts()
            for k, v in cls.items():
                print(f"      {k:<28} {v:4d}")

            report[uni]["policies"][pol] = {
                "n": n, "affected": len(affected), "mean_delta_pp": mean_d,
                "median_delta_pp": float(np.median(arr)),
                "ci90": [lo, hi], "required_per_affected_pp": req,
                "verdict": verdict,
                "classification": {k: int(v) for k, v in cls.items()},
            }

    out = pd.DataFrame(all_rows)
    out.to_csv(RESULTS / "block_a_stage1_paired.csv", index=False)
    (RESULTS / "block_a_stage1_summary.json").write_text(json.dumps(report, indent=2))

    print(f"\n{'=' * 74}\n  GATE 5 — CROSS-UNIVERSE DECISION (no pooling)\n{'=' * 74}")
    for pol in POLICIES:
        if pol == "A":
            continue
        cells = [(u, report[u]["policies"][pol]) for u in UNIVERSES if u in report]
        both = all(c[1]["verdict"] == "CLEARS" for c in cells)
        for u, c in cells:
            print(f"    Policy {pol}  Universe {u}: {c['mean_delta_pp']:+.4f}pp  "
                  f"CI90 [{c['ci90'][0]:+.4f}, {c['ci90'][1]:+.4f}]  -> {c['verdict']}")
        print(f"    Policy {pol}: {'ELIGIBLE for stage 2' if both else 'NOT ELIGIBLE'}"
              f" — conjunctive rule requires both universes\n")
    print("  Stage 1 cannot select a policy. Portfolio expressibility is stage 2,")
    print("  and confirmatory support requires 20 triggers per universe, which the")
    print("  validation period does not supply. Default outcome: retain Policy A.")
    print(f"\n  Saved results/block_a_stage1_paired.csv and _summary.json")


if __name__ == "__main__":
    main()
