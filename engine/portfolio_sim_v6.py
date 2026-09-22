"""Athena V6 — the first causal portfolio simulator.

This is a new engine, not a patched V5. `backtester.py`, `portfolio_sim.py` and
`portfolio_sim_v5.py` are left logically untouched as the historical record of
what actually produced V1-V5, and their runners now refuse to execute.

Every must-fix from the 2026-09-22 audit is applied here:

1. Causal swing confirmation — in `indicators.py`. Divergence flags are stamped
   at the confirmation bar, never back-dated. Run A additionally removes
   divergence from the decision set entirely (see `_check_entry`).
2. No exit is ever booked at the stop price. V1-V5 filled stop exits at exactly
   `effective_stop`, a price the market need not have traded. Exits here fill at
   the NEXT bar's open, so an unreachable limit price cannot be assumed.
3. Correct `hidden_bull_div` / `hidden_bear_div` key names. V1-V5 read
   `hidden_bullish_div` / `hidden_bearish_div`, which `add_indicators` never
   produced, so the confluence gate was inoperative and `min_confluence` never
   bound.
4. Max drawdown from the RUNNING peak, not from the global peak only.
5. `peak_after_exit` / `missed_upside_pct` are not computed at all. They are
   forward-looking by construction; the only way to guarantee they never touch
   parameter selection is for them not to exist.
6. Stop distance from the stdev of RETURNS, matching live Ares exactly:
   `entry_price - entry_price * stdev_20 * stop_loss_multiplier`. V1-V5 used
   `Close.std()` of dollar price levels, a live-vs-backtest mismatch independent
   of the look-ahead. There is also no fabricated `Close * 0.05` volatility
   fallback: a missing stdev is an absence, so the entry is refused and counted.
7. Exits are next-bar, like entries. V5 filled entries at the next open but every
   exit at the signal day's close — one-sided hindsight on every exit.

Accounting defects from the same audit are fixed and then *enforced*:

- `total_invested` includes the entry commission, and `total_returned` is net of
  every commission paid. V5 charged cash the $1 entry commission but omitted it
  from `total_invested`, and added back GROSS scale-out proceeds while the
  commission had already left cash — so reported P&L beat the real cash result on
  every trade, and on scaled winners twice.
- The scale-out leg is fully written to the trade record (price, date, shares,
  proceeds, remaining shares, commission). V1-V5 computed `scale_out_pnl` and
  `scale_out_date` and never persisted them, which is precisely why the two
  accounting defects above were undetectable from the output CSVs.
- `reconcile()` asserts that the sum of reported trade P&L equals the actual cash
  delta. Any future accounting drift becomes a hard failure rather than a
  flattering number.
"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from engine.data_feed import load_universe
from engine.indicators import add_indicators

RESULTS_DIR = Path(__file__).parent.parent / "results"
CONFIG_DIR = Path(__file__).parent.parent / "config"

# Columns the simulator reads per bar. Pulled into numpy arrays up front so the
# hot loop never touches pandas indexing.
_NUM_COLS = ['Open', 'High', 'Low', 'Close', 'rsi', 'vol_ratio', 'macd_hist',
             'stdev_20', 'sma_50', 'pct_from_high']
_BOOL_COLS = ['bullish_div', 'bearish_div', 'hidden_bull_div', 'hidden_bear_div']

def load_params(name="strategy_params_v6.json"):
    with open(CONFIG_DIR / name) as f:
        return json.load(f)

def prepare(symbols, start_date, end_date, min_bars=100):
    """Load the frozen snapshot, add indicators, slice, and vectorise.

    Indicators are computed on the FULL history before slicing, so the warm-up
    for the 252-bar and 50-bar windows comes from real bars preceding
    `start_date` rather than from NaN or a fabricated default.
    """
    raw = load_universe(symbols, min_bars=min_bars)
    prepared = {}
    for symbol, df in raw.items():
        df = add_indicators(df.sort_index())
        df = df.loc[start_date:end_date]
        if len(df) < 50:
            continue
        cols = {c: df[c].to_numpy(dtype=float) for c in _NUM_COLS if c in df.columns}
        for c in _BOOL_COLS:
            cols[c] = (df[c].to_numpy(dtype=bool) if c in df.columns
                       else np.zeros(len(df), dtype=bool))
        cols['regime'] = df['regime'].to_numpy(dtype=object)
        prepared[symbol] = {
            'dates': list(df.index),
            'idx': {d: i for i, d in enumerate(df.index)},
            'n': len(df),
            **cols,
        }
    return prepared

def _check_entry(s, i, params, use_divergence):
    """Entry rules, evaluated only on data available at the close of bar `i`.

    RUN A: `use_divergence` is False, so divergence contributes to no entry, no
    exit and no rejection. This matches what live Ares structurally does today —
    the pivot loop can never flag the latest bar, so all four divergence reads are
    permanently False in production.

    Note that under Run A the momentum_breakout confluence count is unchanged at
    2: V1-V5 awarded a point for `not bearish_div and not hidden_bear_div`, which
    was almost always True, and the `breakout` trigger already implies the volume
    term. Removing the divergence point therefore leaves the uptrend entry
    population essentially as it was. The range branch does tighten, because
    `bullish_div` could previously supply the second confluence point on its own.
    """
    regime = s['regime'][i]
    if regime == 'downtrend':
        return None

    rsi = s['rsi'][i]
    vol_ratio = s['vol_ratio'][i]
    macd_hist = s['macd_hist'][i]
    if np.isnan(rsi) or np.isnan(vol_ratio) or np.isnan(macd_hist):
        return None

    min_conf = params.get('min_confluence', 2)
    min_vol = params.get('min_vol_ratio', 1.5)

    if regime == 'uptrend':
        confluence, trigger = 0, None
        if rsi > 50 and vol_ratio > min_vol and macd_hist > 0:
            confluence += 1
            trigger = 'breakout'
        if use_divergence and not s['bearish_div'][i] and not s['hidden_bear_div'][i]:
            confluence += 1
        if vol_ratio > min_vol:
            confluence += 1
        if confluence >= min_conf and trigger:
            return {'strategy': 'momentum_breakout', 'trigger': trigger,
                    'confluence': confluence}

    elif regime == 'range':
        confluence, trigger = 0, None
        if rsi < params.get('rsi_oversold', 30):
            confluence += 1
            trigger = 'oversold'
        if use_divergence and s['bullish_div'][i]:
            confluence += 1
            trigger = trigger or 'bullish_div'
        if vol_ratio > min_vol:
            confluence += 1
        if confluence >= min_conf and trigger:
            return {'strategy': 'mean_reversion', 'trigger': trigger,
                    'confluence': confluence}

    return None

def _check_exit(s, i, pos, params, use_divergence):
    """Exit rules from the close of bar `i`. Returns a reason or None.

    MUST-FIX 2 and 7: this returns only a REASON. No price is produced here, so
    the stop price can never become a fill price, and the caller fills at the next
    bar's open rather than at this bar's close.

    Conservative ordering is preserved: the stop is tested before the target.
    """
    price = s['Close'][i]
    rsi = s['rsi'][i]

    if price > pos['peak_price']:
        pos['peak_price'] = price
        new_ts = price * (1 - params.get('trailing_stop_pct', 0.10))
        if new_ts > pos['trailing_stop']:
            pos['trailing_stop'] = new_ts

    effective_stop = max(pos['stop_loss'], pos['trailing_stop'])

    if price <= effective_stop:
        return ('trailing_stop' if pos['trailing_stop'] > pos['stop_loss']
                else 'stop_loss')
    if not np.isnan(rsi) and rsi > params.get('rsi_extreme_high', 90):
        return 'emotional_extreme'
    if (use_divergence and s['bearish_div'][i]
            and pos['strategy'] == 'momentum_breakout'):
        return 'bearish_divergence'
    if (pos['strategy'] == 'mean_reversion' and not np.isnan(rsi) and rsi > 70):
        return 'mean_reversion_complete'
    return None

def _fill(price, side, slippage):
    """Slippage always works against us: buy higher, sell lower."""
    return price * (1 + slippage) if side == 'buy' else price * (1 - slippage)

def run_sim(symbols, start_date, end_date, params, label=""):
    """Portfolio simulation with strict next-bar fills on BOTH sides.

    Day ordering, which is what makes the run causal:
      1. Fill exit orders queued yesterday, at today's open.
      2. Fill scale-out orders queued yesterday, at today's open.
      3. Fill entry orders queued yesterday, at today's open.
      4. Mark equity at today's close.
      5. Decide tomorrow's exits from today's close.
      6. Decide tomorrow's entries from today's close.
    No step ever reads a bar later than the one being processed.
    """
    capital = params.get('starting_capital', 1000)
    max_positions = params.get('max_positions', 5)
    cash_reserve_pct = params.get('cash_reserve_pct', 0.25)
    tp_momentum = params.get('tp_momentum', 0.18)
    tp_reversal = params.get('tp_reversal', 0.10)
    scale_out = params.get('scale_out', True)
    scale_out_pct = params.get('scale_out_pct', 0.50)
    queue_max_age = params.get('queue_max_age_days', 5)
    slippage = params.get('slippage_pct', 0.001)
    commission = params.get('commission_per_trade', 1.00)
    sl_mult = params.get('stop_loss_multiplier', 2.0)
    use_divergence = params.get('divergence_in_decision_set', False)

    data = prepare(symbols, start_date, end_date)
    trading_days = sorted({d for s in data.values() for d in s['dates']})

    cash = float(capital)
    positions = {}
    closed = []
    history = []
    queue = []
    pending_entries = []
    pending_exits = []
    pending_scaleouts = []

    counters = {
        'signals_total': 0, 'entries_filled': 0, 'signals_queued': 0,
        'entries_from_queue': 0, 'commissions_paid': 0.0,
        'refused_no_stdev': 0, 'refused_too_small': 0,
        'refused_no_next_bar': 0, 'queue_expired': 0,
    }

    def bar(sym, day):
        s = data.get(sym)
        if s is None:
            return None, None
        i = s['idx'].get(day)
        return (s, i) if i is not None else (s, None)

    for day in trading_days:
        day_str = str(day)[:10]

        # ---- 1. exit fills at today's open -------------------------------
        for order in pending_exits:
            sym = order['symbol']
            pos = positions.get(sym)
            if pos is None:
                continue
            s, i = bar(sym, day)
            if i is None:
                continue
            exit_price = _fill(s['Open'][i], 'sell', slippage)
            proceeds = pos['shares'] * exit_price - commission
            cash += proceeds
            counters['commissions_paid'] += commission
            pos['commission_paid'] += commission
            closed.append(_book(pos, day_str, exit_price, order['reason'],
                                proceeds, scale_out_pct))
            del positions[sym]
        pending_exits = []

        # ---- 2. scale-out fills at today's open --------------------------
        for order in pending_scaleouts:
            sym = order['symbol']
            pos = positions.get(sym)
            if pos is None or pos['scaled_out']:
                continue
            s, i = bar(sym, day)
            if i is None:
                continue
            # MUST-FIX 2, applied to the target as well as the stop: V1-V5 filled
            # the scale-out at exactly `take_profit`, a price the market need not
            # have traded.
            sell_price = _fill(s['Open'][i], 'sell', slippage)
            sell_shares = pos['original_shares'] * scale_out_pct
            proceeds = sell_shares * sell_price - commission
            cash += proceeds
            counters['commissions_paid'] += commission
            pos['commission_paid'] += commission
            pos['shares'] -= sell_shares
            pos['scaled_out'] = True
            pos['scale_out_date'] = day_str
            pos['scale_out_price'] = sell_price
            pos['scale_out_shares'] = sell_shares
            pos['scale_out_proceeds'] = proceeds
        pending_scaleouts = []

        # ---- 3. entry fills at today's open ------------------------------
        for order in pending_entries:
            sym = order['symbol']
            if sym in positions or len(positions) >= max_positions:
                continue
            s, i = bar(sym, day)
            if i is None:
                counters['refused_no_next_bar'] += 1
                continue

            buy_price = _fill(s['Open'][i], 'buy', slippage)
            equity = cash + sum(
                positions[p]['shares'] * data[p]['Close'][data[p]['idx'][day]]
                for p in positions
                if day in data[p]['idx']
            )
            available = cash - equity * cash_reserve_pct
            size = min(available, equity * 0.20)
            if size < 20:
                counters['refused_too_small'] += 1
                continue

            # MUST-FIX 6. Stop distance from the stdev of RETURNS, exactly as live
            # Ares computes it. No Close*0.05 fabrication: a missing stdev is an
            # absence, so the trade is refused and counted.
            stdev = order['stdev_20']
            if not np.isfinite(stdev) or stdev <= 0:
                counters['refused_no_stdev'] += 1
                continue

            shares = (size - commission) / buy_price
            cash -= size
            counters['commissions_paid'] += commission
            tp_pct = (tp_momentum if order['strategy'] == 'momentum_breakout'
                      else tp_reversal)
            positions[sym] = {
                'symbol': sym,
                'strategy': order['strategy'],
                'trigger': order['trigger'],
                'confluence': order['confluence'],
                'entry_date': day_str,
                'entry_price': buy_price,
                'shares': shares,
                'original_shares': shares,
                'stop_loss': buy_price - buy_price * stdev * sl_mult,
                'take_profit': buy_price * (1 + tp_pct) if tp_pct > 0 else 0.0,
                'trailing_stop': buy_price - buy_price * stdev * sl_mult,
                'peak_price': buy_price,
                'rsi_at_entry': order['rsi'],
                'vol_at_entry': order['vol_ratio'],
                'stdev_20': stdev,
                'signal_date': order['signal_date'],
                'from_queue': order['from_queue'],
                'scaled_out': False,
                'scale_out_date': None,
                'scale_out_price': 0.0,
                'scale_out_shares': 0.0,
                'scale_out_proceeds': 0.0,
                # Entry commission is part of cash at risk. V5 charged it to cash
                # but left it out of total_invested, flattering every trade.
                'entry_commission': commission,
                'commission_paid': commission,
            }
            counters['entries_filled'] += 1
        pending_entries = []

        # ---- 4. mark equity at today's close -----------------------------
        equity = cash
        for sym, pos in positions.items():
            s, i = bar(sym, day)
            if i is not None:
                equity += pos['shares'] * s['Close'][i]
        history.append({'date': day_str, 'equity': round(equity, 2),
                        'cash': round(cash, 2), 'positions': len(positions),
                        'queue_size': len(queue)})

        # ---- 5. decide tomorrow's exits from today's close ---------------
        for sym, pos in positions.items():
            s, i = bar(sym, day)
            if i is None:
                continue
            reason = _check_exit(s, i, pos, params, use_divergence)
            if reason:
                pending_exits.append({'symbol': sym, 'reason': reason})
                continue
            if (scale_out and not pos['scaled_out'] and pos['take_profit'] > 0
                    and s['Close'][i] >= pos['take_profit']):
                pending_scaleouts.append({'symbol': sym})

        # ---- 6. decide tomorrow's entries from today's close -------------
        queue = [q for q in queue
                 if (day - q['day']).days <= queue_max_age]
        exiting = {o['symbol'] for o in pending_exits}
        held = set(positions) | {o['symbol'] for o in pending_entries}

        for sym, s in data.items():
            if sym in held or sym in exiting:
                continue
            i = s['idx'].get(day)
            if i is None or i < 1:
                continue
            signal = _check_entry(s, i, params, use_divergence)
            if not signal:
                continue
            counters['signals_total'] += 1
            order = {
                'symbol': sym, 'strategy': signal['strategy'],
                'trigger': signal['trigger'], 'confluence': signal['confluence'],
                'rsi': float(s['rsi'][i]), 'vol_ratio': float(s['vol_ratio'][i]),
                'stdev_20': float(s['stdev_20'][i]),
                'signal_date': day_str, 'from_queue': False,
            }
            if len(positions) + len(pending_entries) >= max_positions:
                queue.append({'symbol': sym, 'day': day, 'order': order})
                counters['signals_queued'] += 1
            else:
                pending_entries.append(order)

        if queue and len(positions) + len(pending_entries) < max_positions:
            queue.sort(key=lambda q: q['order']['confluence'], reverse=True)
            for q in queue[:]:
                if len(positions) + len(pending_entries) >= max_positions:
                    break
                sym = q['symbol']
                if sym in positions or sym in exiting:
                    continue
                s, i = bar(sym, day)
                if i is None or not _check_entry(s, i, params, use_divergence):
                    continue
                order = dict(q['order'], from_queue=True, signal_date=day_str,
                             stdev_20=float(s['stdev_20'][i]))
                pending_entries.append(order)
                counters['entries_from_queue'] += 1
                queue.remove(q)

    # ---- close anything still open at the last available bar -------------
    last_day = trading_days[-1]
    for sym, pos in list(positions.items()):
        s = data[sym]
        i = s['idx'].get(last_day, s['n'] - 1)
        exit_price = _fill(s['Close'][i], 'sell', slippage)
        proceeds = pos['shares'] * exit_price - commission
        cash += proceeds
        counters['commissions_paid'] += commission
        pos['commission_paid'] += commission
        closed.append(_book(pos, str(s['dates'][i])[:10], exit_price,
                            'end_of_sim', proceeds, scale_out_pct))
        del positions[sym]

    counters['final_cash'] = round(cash, 2)
    counters['symbols_contributing'] = len(data)
    counters['symbols_requested'] = len(symbols)
    counters['label'] = label
    reconcile(closed, capital, cash)
    return closed, history, counters

def _book(pos, exit_date, exit_price, reason, exit_proceeds, scale_out_pct):
    """Build the trade record with the full audit trail.

    `total_invested` includes the entry commission and `total_returned` is net of
    every commission, so `pnl` equals the real cash delta of the trade. V1-V5
    omitted the entry commission from the cost basis and added back gross
    scale-out proceeds, and dropped `scale_out_price` / `remaining_shares` from
    the CSV — which is exactly why neither error was visible in the output.
    """
    invested = pos['original_shares'] * pos['entry_price'] + pos['entry_commission']
    returned = exit_proceeds + pos['scale_out_proceeds']
    pnl = returned - invested
    entry_dt = datetime.strptime(pos['entry_date'], "%Y-%m-%d")
    exit_dt = datetime.strptime(exit_date, "%Y-%m-%d")
    return {
        'symbol': pos['symbol'], 'strategy': pos['strategy'],
        'trigger': pos['trigger'], 'confluence': pos['confluence'],
        'signal_date': pos['signal_date'], 'entry_date': pos['entry_date'],
        # Precision here is deliberate. At 4dp on price and 6dp on stdev, the
        # audit fields no longer let you re-derive the stop or the cost basis to
        # better than a fraction of a cent, so a validation check cannot tell a
        # rounding artifact from a real accounting error. Being able to recompute
        # every number from the CSV is the point of the CSV.
        'entry_price': round(pos['entry_price'], 6),
        'exit_date': exit_date, 'exit_price': round(exit_price, 6),
        'exit_reason': reason,
        'original_shares': round(pos['original_shares'], 8),
        'remaining_shares': round(pos['shares'], 8),
        'scaled_out': pos['scaled_out'],
        'scale_out_date': pos['scale_out_date'],
        'scale_out_price': round(pos['scale_out_price'], 6),
        'scale_out_shares': round(pos['scale_out_shares'], 8),
        'scale_out_proceeds': round(pos['scale_out_proceeds'], 6),
        'exit_proceeds': round(exit_proceeds, 6),
        'commission_paid': round(pos['commission_paid'], 2),
        'entry_commission': round(pos['entry_commission'], 2),
        'total_invested': round(invested, 6),
        'total_returned': round(returned, 6),
        'holding_days': (exit_dt - entry_dt).days,
        'stop_loss': round(pos['stop_loss'], 6),
        'take_profit': round(pos['take_profit'], 6),
        'stdev_20': round(pos['stdev_20'], 10),
        'rsi_at_entry': round(pos['rsi_at_entry'], 2),
        'vol_at_entry': round(pos['vol_at_entry'], 3),
        'from_queue': pos['from_queue'],
        'pnl': round(pnl, 6),
        'pnl_pct': round(pnl / invested * 100, 6),
        'win': 1 if pnl > 0 else 0,
    }

def reconcile(closed, starting_capital, final_cash, tol=0.01):
    """Assert reported P&L equals the real cash delta.

    The two V5 commission defects each inflated reported P&L relative to cash
    while the printed `Commissions: $X` line made it look accounted for. An
    assertion is the only thing that stops that class of error returning, because
    the symptom is a slightly better number, not a crash.
    """
    reported = sum(t['pnl'] for t in closed)
    actual = final_cash - starting_capital
    if abs(reported - actual) > tol:
        raise AssertionError(
            f"P&L does not reconcile with cash: reported {reported:.4f} vs "
            f"actual {actual:.4f} (diff {reported - actual:.4f}). "
            "Check commission handling in _book / run_sim."
        )
    return True

def max_drawdown(equity):
    """Largest peak-to-trough decline, measured from the RUNNING peak.

    MUST-FIX 4. `portfolio_sim.py:405` and `v5:392` took the global argmax and
    then the minimum AFTER it, which only ever sees the final drawdown and misses
    every earlier one. That understated true drawdown by roughly 3.6x (V4 −17.8%
    reported as −5.0%, V5 −20.2% reported as −15.9%).
    """
    eq = pd.Series(equity, dtype=float).reset_index(drop=True)
    running_peak = eq.cummax()
    dd = (eq - running_peak) / running_peak
    if dd.empty:
        return 0.0, None
    # Positional, not label-based: the caller may pass a DatetimeIndex series.
    return float(dd.min() * 100), int(dd.to_numpy().argmin())

def summarise(closed, history, counters, params):
    """Compute the V6 metric set. No forward-looking fields exist here.

    MUST-FIX 5: `peak_after_exit` and `missed_upside_pct` are absent by
    construction, so they cannot reach parameter selection even by accident.
    """
    start = params.get('starting_capital', 1000)
    hist = pd.DataFrame(history)
    df = pd.DataFrame(closed)

    final = float(hist['equity'].iloc[-1]) if len(hist) else float(start)
    total_ret = (final - start) / start * 100
    years = len(hist) / 252 if len(hist) else 0
    cagr = ((final / start) ** (1 / years) - 1) * 100 if years > 0 and final > 0 else 0.0
    mdd, mdd_i = max_drawdown(hist['equity']) if len(hist) else (0.0, None)

    # Daily-return Sharpe, zero risk-free, for scale rather than for ranking.
    rets = hist['equity'].pct_change().dropna() if len(hist) > 1 else pd.Series(dtype=float)
    sharpe = (float(rets.mean() / rets.std() * np.sqrt(252))
              if len(rets) > 1 and rets.std() > 0 else 0.0)

    out = {
        'label': counters.get('label', ''),
        'start_capital': start, 'final_equity': round(final, 2),
        'total_return_pct': round(total_ret, 2),
        'cagr_pct': round(cagr, 2),
        'max_drawdown_pct': round(mdd, 2),
        'max_drawdown_date': (hist['equity'].index[mdd_i] and
                              hist['date'].iloc[mdd_i]) if mdd_i is not None else None,
        'sharpe': round(sharpe, 2),
        'years': round(years, 2),
        'trading_days': len(hist),
        'symbols_requested': counters.get('symbols_requested'),
        'symbols_contributing': counters.get('symbols_contributing'),
        'commissions_paid': round(counters.get('commissions_paid', 0), 2),
    }
    out.update({k: counters[k] for k in (
        'signals_total', 'entries_filled', 'signals_queued', 'entries_from_queue',
        'refused_no_stdev', 'refused_too_small', 'refused_no_next_bar') if k in counters})

    if df.empty:
        out.update({'trades': 0, 'win_rate_pct': 0.0, 'profit_factor': 0.0,
                    'expectancy_dollars': 0.0, 'expectancy_pct': 0.0})
        return out, df, hist

    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    gross_win = float(wins['pnl'].sum())
    gross_loss = float(abs(losses['pnl'].sum()))

    out.update({
        'trades': len(df),
        'win_rate_pct': round(len(wins) / len(df) * 100, 2),
        'avg_win_pct': round(float(wins['pnl_pct'].mean()), 2) if len(wins) else 0.0,
        'avg_loss_pct': round(float(losses['pnl_pct'].mean()), 2) if len(losses) else 0.0,
        'gross_profit': round(gross_win, 2),
        'gross_loss': round(gross_loss, 2),
        # True dollar profit factor, not the win-rate-weighted percentage proxy
        # V1-V5 printed as "profit factor".
        'profit_factor': round(gross_win / gross_loss, 3) if gross_loss > 0 else float('inf'),
        'expectancy_dollars': round(float(df['pnl'].mean()), 3),
        'expectancy_pct': round(float(df['pnl_pct'].mean()), 3),
        # Diagnostic only, never a parameter. If the run loses money, the first
        # question asked will be "is it just the commission?" — so answer it with
        # a number instead of leaving it open. This is what the P&L would have
        # been at zero commission, holding every decision fixed; it is NOT a
        # claim that a zero-commission broker would produce this result, since
        # position sizing also consumed the commission at entry.
        'pnl_total': round(float(df['pnl'].sum()), 2),
        'pnl_excl_commissions': round(
            float(df['pnl'].sum()) + float(df['commission_paid'].sum()), 2),
        'avg_holding_days': round(float(df['holding_days'].mean()), 1),
        'scaled_out_count': int(df['scaled_out'].sum()),
    })
    return out, df, hist

def yearly_table(df, hist):
    """Per-calendar-year equity change and trade stats, including 2022."""
    rows = []
    for year in sorted(hist['date'].str[:4].unique()):
        yh = hist[hist['date'].str[:4] == year]
        first, last = float(yh['equity'].iloc[0]), float(yh['equity'].iloc[-1])
        yt = df[df['exit_date'].str[:4] == year] if not df.empty else df
        mdd, _ = max_drawdown(yh['equity'])
        rows.append({
            'year': year,
            'start_equity': round(first, 2), 'end_equity': round(last, 2),
            'return_pct': round((last - first) / first * 100, 2) if first else 0.0,
            'max_drawdown_pct': round(mdd, 2),
            'trades': len(yt),
            'win_rate_pct': (round(float((yt['pnl'] > 0).mean() * 100), 1)
                             if len(yt) else 0.0),
            'pnl': round(float(yt['pnl'].sum()), 2) if len(yt) else 0.0,
        })
    return pd.DataFrame(rows)

def exit_reason_table(df):
    """Per-exit-reason contribution. This is the table that exposed the defect."""
    if df.empty:
        return pd.DataFrame()
    g = df.groupby('exit_reason').agg(
        trades=('pnl', 'size'),
        total_pnl=('pnl', 'sum'),
        avg_pnl=('pnl', 'mean'),
        avg_pnl_pct=('pnl_pct', 'mean'),
        win_rate_pct=('win', lambda x: round(x.mean() * 100, 1)),
    ).round(3).sort_values('total_pnl', ascending=False)
    total = df['pnl'].sum()
    g['pct_of_total_pnl'] = ((g['total_pnl'] / total * 100).round(1)
                             if total != 0 else 0.0)
    return g.reset_index()

def buy_and_hold(symbol, start_date, end_date, start_capital, slippage, commission):
    """Benchmark. A strategy that loses to its own benchmark is not an edge."""
    from engine.data_feed import load_stock
    df = load_stock(symbol).loc[start_date:end_date]
    if df.empty:
        return None
    buy = _fill(float(df['Open'].iloc[0]), 'buy', slippage)
    shares = (start_capital - commission) / buy
    equity = (df['Close'] * shares).astype(float)
    final = float(_fill(float(df['Close'].iloc[-1]), 'sell', slippage) * shares - commission)
    mdd, _ = max_drawdown(equity)
    years = len(df) / 252
    return {
        'label': f'buy_and_hold_{symbol}',
        'final_equity': round(final, 2),
        'total_return_pct': round((final - start_capital) / start_capital * 100, 2),
        'cagr_pct': round(((final / start_capital) ** (1 / years) - 1) * 100, 2) if years else 0.0,
        'max_drawdown_pct': round(mdd, 2),
    }
