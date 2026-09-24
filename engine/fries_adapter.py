"""Subprocess adapter for FriesTrader's seven mechanical scripts.

Their code is EXECUTED, not reimplemented. Athena Run A measured a hand-written
reimplementation of Ares' strategy that had silently drifted in ~30 ways; Run A'
fixed that by importing live's real predicates. The same rule applies to third-party
code: every number below comes out of the author's own script via stdout JSON.

Each script is pinned by md5 at the revision audited (FriesTrader @ 4584136). If the
author changes a rule, every run using this adapter fails loudly rather than
reporting a result for code we never read.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

FRIES_ROOT = Path("/home/ricksonkang/Projects/FriesTrader")
SCRIPTS = FRIES_ROOT / "scripts"

# md5 as audited 2026-09-24 at FriesTrader commit 4584136.
PINNED_MD5 = {
    "conviction_trim.py": "e198c45035a52880d4bb87bd1c4d1b22",
    "entry_gate.py": "2e6ea1e3aabc833b8d9e5e7308aef830",
    "pnl_pct.py": "253a8da9240a71c9f6fdd7162934a265",
    "position_sizing.py": "f06bbc7a7b3c58d461c363342832e6b6",
    "rank_candidates.py": "cc24d452b67aadfe98986e9b2febf76d",
    "stop_loss.py": "b330f93d08dfde2d9dafb1eee715bece",
    "take_profit.py": "335dc29d37f99fc45647901a93f3dc40",
}
PINNED_RULES_MD5 = "2129571187126e5d42022fde18055635"
FRIES_COMMIT = "4584136"


def _md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def assert_parity():
    """Fail the run if any pinned script or the rules file has changed."""
    if not SCRIPTS.is_dir():
        raise FileNotFoundError(
            f"FriesTrader scripts not found at {SCRIPTS}.\n"
            f"  git clone https://github.com/YizhiSong/FriesTrader"
        )
    drift = []
    for name, expected in PINNED_MD5.items():
        path = SCRIPTS / name
        if not path.is_file():
            drift.append(f"  {name}: MISSING")
            continue
        actual = _md5(path)
        if actual != expected:
            drift.append(f"  {name}: expected {expected}, got {actual}")
    rules = FRIES_ROOT / "risk_rules.json"
    if _md5(rules) != PINNED_RULES_MD5:
        drift.append(f"  risk_rules.json: expected {PINNED_RULES_MD5}, got {_md5(rules)}")
    if drift:
        raise AssertionError(
            "FriesTrader code has drifted from the audited revision "
            f"({FRIES_COMMIT}):\n" + "\n".join(drift) +
            "\n\nThe pre-registered ablation describes the pinned revision. Re-audit "
            "before re-pinning; do not update the hashes to make a run pass."
        )


def load_rules():
    return json.loads((FRIES_ROOT / "risk_rules.json").read_text())


def _run(script, args, stdin_payload=None):
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script)] + [str(a) for a in args],
        input=json.dumps(stdin_payload) if stdin_payload is not None else None,
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{script} exited {proc.returncode}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def _csv(values):
    return ",".join(f"{v:.10g}" for v in values)


def stop_loss(average_cost, current_price, rules, daily_closes,
              tp_tier_fired=False, daily_highs=(), trailing_high_since=None):
    cfg = rules["stop_loss"]
    args = ["--average-cost", average_cost, "--current-price", current_price,
            "--mode", cfg["mode"]]
    if cfg["mode"] == "fixed":
        args += ["--hard-stop-pct", cfg["hard_stop_pct"]]
    else:
        args += ["--volatility-multiplier", cfg["volatility_stdev_multiplier"],
                 "--min-stop-pct", cfg["min_stop_pct"],
                 "--max-stop-pct", cfg["max_stop_pct"],
                 "--fallback-stop-pct", cfg["fallback_stop_pct"],
                 "--daily-closes", _csv(daily_closes)]
    if tp_tier_fired:
        args += ["--take-profit-tier-fired", "--daily-highs", _csv(daily_highs)]
        if trailing_high_since:
            args += ["--trailing-high-since", trailing_high_since]
    return _run("stop_loss.py", args)


def take_profit(average_cost, current_price, quantity, rules, already_fired=()):
    tiers = ",".join(f"{t['gain_pct']}:{t['sell_fraction_of_position']}"
                     for t in rules["take_profit"]["tiers"])
    args = ["--average-cost", average_cost, "--current-price", current_price,
            "--quantity", quantity, "--tiers", tiers]
    if already_fired:
        args += ["--already-fired", ",".join(str(f) for f in sorted(already_fired))]
    return _run("take_profit.py", args)


def entry_gate(fresh_ask, thesis_price, rules, daily_closes, today,
               loss_sale_dates=(), last_sell=None, trading_days_since_sell=None):
    args = ["--fresh-ask", fresh_ask, "--thesis-price", thesis_price,
            "--entry-price-gap-max-pct", rules["entry_price_gap"]["max_pct"],
            "--daily-closes", _csv(daily_closes),
            "--max-extension-pct", rules["entry_extension"]["max_extension_pct"],
            "--today", today]
    if rules["wash_sale_avoidance"]["enabled"]:
        args += ["--wash-sale-enabled",
                 "--wash-sale-lookback-days", rules["wash_sale_avoidance"]["lookback_window_days"]]
        if loss_sale_dates:
            args += ["--loss-sale-dates", ",".join(loss_sale_dates)]
    if last_sell:
        args += ["--last-sell-reason", last_sell["reason"],
                 "--last-sell-price", last_sell["price"],
                 "--last-sell-date", last_sell["date"],
                 "--last-sell-was-gain", "true" if last_sell["was_gain"] else "false"]
        if last_sell["was_gain"]:
            args += ["--reentry-lock-max-trading-days",
                     rules["sell_reentry_lock"]["gain_close_max_trading_days"],
                     "--trading-days-since-sell", trading_days_since_sell]
    return _run("entry_gate.py", args)


def rank_and_size(candidates, rules, total_value, cash, concurrent_start,
                  entries_halted=False, conviction_pct="high:0.20,medium:0.12,low:0.06"):
    """Pipe candidates through rank_candidates.py then position_sizing.py, exactly as
    PHASE_B_TASK.md Step 7 specifies."""
    if not candidates:
        return {"results": [], "cash_remaining_final": round(cash, 2),
                "concurrent_positions_after_final": concurrent_start}
    ranked = _run("rank_candidates.py", [], stdin_payload=candidates)
    ps = rules["position_sizing"]
    args = ["--total-value", total_value, "--cash-start", cash,
            "--concurrent-positions-start", concurrent_start,
            "--max-position-pct", ps["max_position_pct_of_account"],
            "--max-concurrent-positions", ps["max_concurrent_positions"],
            "--min-cash-buffer-pct", ps["min_cash_buffer_pct"],
            "--min-top-up-usd", ps["min_top_up_usd"],
            "--min-top-up-pct-of-target", ps["min_top_up_pct_of_target"],
            "--conviction-pct", conviction_pct]
    if entries_halted:
        args.append("--entries-halted")
    out = _run("position_sizing.py", args, stdin_payload=ranked)
    out["ranked_symbols"] = [c["symbol"] for c in ranked]
    return out


def pnl_pct(daily_realized, weekly_realized, net_deposits, rules):
    ll = rules["loss_limits"]
    return _run("pnl_pct.py", [
        "--daily-realized-usd", daily_realized,
        "--weekly-realized-usd", weekly_realized,
        "--net-deposits-usd", net_deposits,
        "--daily-limit-pct", ll["daily_loss_limit_pct_of_account"],
        "--weekly-limit-pct", ll["weekly_loss_limit_pct_of_account"]])


def conviction_trim(conviction, current_position_value, target_size, rules,
                    prior_consecutive_cycles):
    cfg = rules["conviction_trim"]
    return _run("conviction_trim.py", [
        "--conviction", conviction,
        "--current-position-value", current_position_value,
        "--target-size", target_size,
        "--overweight-trigger-pct", cfg["overweight_trigger_pct"],
        "--prior-consecutive-overweight-cycles", prior_consecutive_cycles,
        "--min-overweight-conviction-cycles", cfg["min_overweight_conviction_cycles"]])


assert_parity()
