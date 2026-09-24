"""FriesTrader mechanical-layer ablation — portfolio simulation.

Runs the author's own risk/sizing/exit scripts (via engine.fries_adapter, md5-pinned)
over historical bars, with the LLM's judgment layer replaced by a null model. See
FRIESTRADER_ABLATION.md for the pre-registered scope and decision rule.

CAUSALITY. Screening for day i uses bars 0..i inclusive and produces candidates that
are filled on day i+1, so an entry never uses a price it could not have seen. Exits
are evaluated and filled on the same bar, matching Phase B's single-session
check-and-execute; the approximation is that a stop fills at the close rather than
intraday, which flatters nothing systematically but is not exact.

STRUCTURAL NOTE, worth reading before the numbers. With the judgment layer removed
the ONLY full exit is stop_loss. take_profit sells 25% per tier and explicitly holds
the remainder (0.75^3 = 42.19% after all three fire); conviction_trim only trims to
target; exit_existing is an LLM decision and out of scope. There is no time-based
exit. A position can therefore occupy one of four slots indefinitely.
"""
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from engine import fries_adapter as fries

ROOT = Path(__file__).parent.parent
OHLCV = ROOT / "data" / "ohlcv"
SLIPPAGE = 0.0005      # 0.05%
COMMISSION = 0.0       # Robinhood
CONVICTION_PCT = {"high": 0.20, "medium": 0.12, "low": 0.06}


def load(symbol):
    df = pd.read_csv(OHLCV / f"{symbol}.csv", parse_dates=["Date"]).set_index("Date")
    return df.sort_index()


def prepare(symbol, rules):
    """Attach every mechanical screening input as a causal column.

    Calendar-day windows are used where PHASE_A_TASK.md specifies calendar days --
    the 60-day price move explicitly warns that counting 60 BARS drifts to ~85-90
    calendar days and overstates the move.
    """
    df = load(symbol)
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]

    df["sma200"] = close.rolling(rules["universe"]["trend_filter_lookback_trading_days"]).mean()
    df["ma20"] = close.rolling(rules["entry_extension"]["lookback_trading_days"]).mean()
    df["avgvol30"] = vol.rolling("30D").mean()
    df["high52"] = high.rolling("365D").max()
    df["low52"] = low.rolling("365D").min()

    # 60 CALENDAR days back, per spec: earliest bar at or after date - 60 days.
    idx = df.index.values
    target = (df.index - timedelta(days=60)).values
    pos = np.searchsorted(idx, target, side="left")
    df["close_60cal_ago"] = close.to_numpy()[np.clip(pos, 0, len(df) - 1)]

    df["move60"] = (close - df["close_60cal_ago"]).abs() / df["close_60cal_ago"]
    df["volspike"] = vol / df["avgvol30"]
    df["from52h"] = (df["high52"] - close) / df["high52"]
    df["from52l"] = (close - df["low52"]) / df["low52"]
    df["pct_below_52wk_high"] = df["from52h"]
    return df


def passes_universe(row, rules):
    u = rules["universe"]
    if u["penny_stock_filter_enabled"] and row["Close"] < u["penny_stock_price_threshold_usd"]:
        return False, "penny_stock"
    if row["avgvol30"] < u["min_avg_daily_volume"]:
        return False, "min_avg_daily_volume"
    if u["trend_filter_enabled"]:
        if pd.isna(row["sma200"]):
            return False, "insufficient_bars_for_trend_filter"
        if row["Close"] < row["sma200"]:
            return False, "below_200dma"
    return True, None


def has_signal(row, rules):
    """Phase A Step 2. ANY ONE of three qualifies. Note move60 is an ABSOLUTE move and
    the 52-week test covers high OR low -- this gate is 'something notable happened',
    not 'price went up'. The 200-day filter above is what makes the system long-biased."""
    t = rules["signal_thresholds"]
    if row["move60"] >= t["price_move_60d_pct"]:
        return True, "price_move_60d"
    if row["volspike"] >= t["volume_spike_multiple"]:
        return True, "volume_spike"
    if row["from52h"] <= t["pct_from_52wk_extreme"]:
        return True, "near_52wk_high"
    if row["from52l"] <= t["pct_from_52wk_extreme"]:
        return True, "near_52wk_low"
    return False, None


def run_sim(symbols, start, end, conviction, rules, start_capital=1000.0, label=""):
    fries.assert_parity()
    data = {}
    for s in symbols:
        try:
            data[s] = prepare(s, rules)
        except FileNotFoundError:
            continue

    spy = load("SPY")
    cal = spy.loc[start:end].index
    conv_pct_arg = ",".join(f"{k}:{v}" for k, v in CONVICTION_PCT.items())

    cash = start_capital
    positions = {}        # symbol -> dict
    last_sell = {}        # symbol -> {reason, price, date, was_gain, day_index}
    loss_sales = {}       # symbol -> [iso dates]
    trim_streak = {}
    pending = []          # candidates screened yesterday
    closed, equity_hist, skips = [], [], {}
    realized_by_date = {}

    def note(reason):
        skips[reason] = skips.get(reason, 0) + 1

    for di, day in enumerate(cal):
        iso = day.date().isoformat()

        def bar(s):
            d = data.get(s)
            if d is None or day not in d.index:
                return None
            return d.loc[day]

        # ---- mark to market ----
        def mtm():
            v = 0.0
            for s, p in positions.items():
                b = bar(s)
                p["last_price"] = b["Close"] if b is not None else p["last_price"]
                v += p["qty"] * p["last_price"]
            return v

        pos_value = mtm()
        total_value = cash + pos_value

        # ---- Phase B Step 5: sell side, always runs ----
        for s in list(positions):
            p = positions[s]
            b = bar(s)
            if b is None:
                continue
            price = float(b["Close"])
            p["daily_highs"].append(float(b["High"]))
            d = data[s]
            upto = d.loc[:day]
            closes20 = upto["Close"].iloc[-21:].tolist()

            sl = fries.stop_loss(p["avg_cost"], price, rules, closes20,
                                 tp_tier_fired=bool(p["tiers_fired"]),
                                 daily_highs=p["daily_highs"][:-1] or [p["avg_cost"]],
                                 trailing_high_since=p["entry_date"])
            if sl["triggered"]:
                fill = price * (1 - SLIPPAGE)
                proceeds = p["qty"] * fill - COMMISSION
                pnl = proceeds - p["qty"] * p["avg_cost"]
                cash += proceeds
                realized_by_date[iso] = realized_by_date.get(iso, 0.0) + pnl
                closed.append({
                    "symbol": s, "entry_date": p["entry_date"], "exit_date": iso,
                    "entry_price": p["avg_cost"], "exit_price": fill,
                    "qty": p["qty"], "pnl": pnl,
                    "pnl_pct": (fill - p["avg_cost"]) / p["avg_cost"] * 100,
                    "reason": "trailing_stop" if sl["stop_reference_basis"] == "trailing_high" else "stop_loss",
                    "stop_pct_used": sl.get("stop_pct_used"),
                    "tiers_fired": sorted(p["tiers_fired"]),
                    "held_days": (day - pd.Timestamp(p["entry_date"])).days,
                    "scaled_pnl": p["scaled_pnl"],
                })
                was_gain = fill > p["avg_cost"]
                last_sell[s] = {"reason": "stop_loss", "price": fill, "date": iso,
                                "was_gain": was_gain, "day_index": di}
                if not was_gain:
                    loss_sales.setdefault(s, []).append(iso)
                del positions[s]
                continue

            tp = fries.take_profit(p["avg_cost"], price, p["qty"], rules,
                                   already_fired=p["tiers_fired"])
            if tp["triggered"]:
                for f in tp["fired_this_cycle"]:
                    qty_sold = f["quantity_sold"]
                    fill = price * (1 - SLIPPAGE)
                    proceeds = qty_sold * fill - COMMISSION
                    pnl = proceeds - qty_sold * p["avg_cost"]
                    cash += proceeds
                    p["qty"] -= qty_sold
                    p["scaled_pnl"] += pnl
                    p["tiers_fired"].add(f["tier_gain_pct"])
                    realized_by_date[iso] = realized_by_date.get(iso, 0.0) + pnl
                last_sell[s] = {"reason": "take_profit", "price": price * (1 - SLIPPAGE),
                                "date": iso, "was_gain": True, "day_index": di}

            # conviction trim (inert at conviction 'high' by construction)
            if rules["conviction_trim"]["enabled"] and s in positions:
                p = positions[s]
                target = CONVICTION_PCT[conviction] * total_value
                ct = fries.conviction_trim(conviction, p["qty"] * price, target, rules,
                                           trim_streak.get(s, 0))
                trim_streak[s] = ct["consecutive_cycles"]
                if ct["triggered"] and ct["trim_dollar_amount"]:
                    qty_sold = min(p["qty"], ct["trim_dollar_amount"] / price)
                    fill = price * (1 - SLIPPAGE)
                    proceeds = qty_sold * fill - COMMISSION
                    pnl = proceeds - qty_sold * p["avg_cost"]
                    cash += proceeds
                    p["qty"] -= qty_sold
                    p["scaled_pnl"] += pnl
                    realized_by_date[iso] = realized_by_date.get(iso, 0.0) + pnl
                    note("conviction_trim_fired")

        pos_value = mtm()
        total_value = cash + pos_value

        # ---- loss limits ----
        wk_start = day - timedelta(days=int(day.dayofweek))
        weekly = sum(v for k, v in realized_by_date.items()
                     if pd.Timestamp(k) >= wk_start and pd.Timestamp(k) <= day)
        halted = fries.pnl_pct(realized_by_date.get(iso, 0.0), weekly,
                               start_capital, rules)["entries_halted"]
        if halted:
            note("entries_halted_loss_limit")

        # ---- Phase B Steps 4-8: fill yesterday's candidates ----
        if pending and not halted:
            cands = []
            for c in pending:
                s = c["symbol"]
                if s in positions:
                    b = bar(s)
                    if b is None:
                        continue
                    cands.append({"symbol": s, "group": "held", "conviction": conviction,
                                  "risk_flags": [],
                                  "pct_below_52wk_high": float(c["pct_below_52wk_high"]),
                                  "current_position_value": positions[s]["qty"] * float(b["Close"])})
                else:
                    cands.append({"symbol": s, "group": "new", "conviction": conviction,
                                  "risk_flags": [],
                                  "pct_below_52wk_high": float(c["pct_below_52wk_high"])})
            sized = fries.rank_and_size(cands, rules, total_value, cash,
                                        len(positions), entries_halted=False,
                                        conviction_pct=conv_pct_arg)
            thesis = {c["symbol"]: c["thesis_price"] for c in pending}
            for res in sized["results"]:
                s = res["symbol"]
                if not res["passed"]:
                    note("sizing:" + res["reason"].split(" -- ")[0][:44])
                    continue
                b = bar(s)
                if b is None:
                    continue
                price = float(b["Close"])
                upto = data[s].loc[:day]
                closes20 = upto["Close"].iloc[-rules["entry_extension"]["lookback_trading_days"]:].tolist()
                ls = last_sell.get(s)
                gate = fries.entry_gate(
                    price, thesis[s], rules, closes20, iso,
                    loss_sale_dates=loss_sales.get(s, []),
                    last_sell=ls,
                    trading_days_since_sell=(di - ls["day_index"]) if ls else None)
                if not gate["passed"]:
                    for bc in gate["blocking_conditions"]:
                        note("gate:" + bc)
                    continue
                fill = price * (1 + SLIPPAGE)
                amount = min(res["dollar_amount"], cash)
                qty = amount / fill
                if qty <= 0:
                    continue
                cash -= amount
                if s in positions:
                    p = positions[s]
                    tot = p["qty"] + qty
                    p["avg_cost"] = (p["avg_cost"] * p["qty"] + fill * qty) / tot
                    p["qty"] = tot
                    note("top_up")
                else:
                    positions[s] = {"qty": qty, "avg_cost": fill, "entry_date": iso,
                                    "tiers_fired": set(), "daily_highs": [float(b["High"])],
                                    "last_price": price, "scaled_pnl": 0.0}
        pending = []

        # ---- Phase A: screen today for tomorrow ----
        held = set(positions)
        qualified = []
        for s, d in data.items():
            if day not in d.index:
                continue
            row = d.loc[day]
            if pd.isna(row["avgvol30"]) or pd.isna(row["ma20"]):
                continue
            if s in held:
                qualified.append((s, row, "currently_held"))
                continue
            ok, why = passes_universe(row, rules)
            if not ok:
                continue
            sig, _ = has_signal(row, rules)
            if not sig:
                continue
            qualified.append((s, row, "signal"))
        cap = rules["universe"]["watchlist_max_candidates"]
        non_held = [q for q in qualified if q[2] != "currently_held"]
        non_held.sort(key=lambda q: -q[1]["move60"])
        for s, row, src in [q for q in qualified if q[2] == "currently_held"] + non_held[:cap]:
            pending.append({"symbol": s, "thesis_price": float(row["Close"]),
                            "pct_below_52wk_high": float(row["pct_below_52wk_high"])})

        equity_hist.append({"date": iso, "cash": cash, "positions_value": mtm(),
                            "equity": cash + mtm(), "n_positions": len(positions),
                            "exposure": (mtm() / (cash + mtm())) if (cash + mtm()) else 0.0})

    return {"closed": closed, "open": positions, "equity": pd.DataFrame(equity_hist),
            "skips": skips, "label": label, "conviction": conviction,
            "start_capital": start_capital}
