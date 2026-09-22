"""Athena V6 Run A' — the first simulator that runs live Ares' own strategy code.

What changed from Run A, and why it is a restructure rather than a patch
-----------------------------------------------------------------------
Run A (committed, `results/v6_runA_*`) was causal but measured a **hand-written
parallel implementation** of the strategy. A parity audit found ~30 divergences
from live and one look-ahead introduced by the reimplementation itself. The defect
was structural: this module re-expressed the entry rules instead of calling them,
and `engine/signals.py` sat beside it as a stale near-copy that nothing imported.

Run A' therefore **calls live's predicates** through `engine/live_adapter.py`
against a byte-identical vendored `engine/signals.py`, checksum-guarded by
`engine/parity.py`. Entry logic is no longer expressed here at all.

The four that move the number, all now taken from live
-----------------------------------------------------
1. **Position sizing is static and non-compounding.** Live `tracker.py:123` is
   `(starting_capital * (1 - cash_reserve_pct) / max_positions) - commission`
   = **$149**, fixed for the whole run, and live tracks no cash at all. Run A used
   `min(cash - equity*0.25, equity*0.20)`, which compounds — positions started
   ~33% larger and grew with the equity curve. **Run A's CAGR came from sizing
   Ares does not use, so the two runs' headline returns are not comparable.**
2. **Queue promotion does not re-require the signal.** Live `_validate_queued`
   promotes on drift alone (see `REPRODUCED_LIVE_DEFECTS below); Run A demanded a
   full fresh signal on the promotion bar, so ~2,900 signals that live would have
   promoted expired unentered.
3. **Scale-out is checked BEFORE exits, and short-circuits them.** Live
   `tracker.py:814-839` banks 50% at the target and then `continue`s, so no exit
   can fire on a target bar. Run A checked exits first, letting an
   `emotional_extreme` (rsi > 90, common exactly at the target) liquidate the whole
   position where live keeps half and rides it. This hit winners specifically.
4. **A missing `stdev_20` fills, it does not refuse.** Live `tracker.py:136`
   substitutes `0.05`, marks the trade contaminated, and fills. Run A refused,
   excluding a class of wide-stop trades that live's real population contains. The
   contamination flag is carried through to the output so they can be segmented.

Also fixed here: **a look-ahead of Run A's own making.** `:300` sized the position
from today's Close for an order filling at today's Open. Static sizing removes the
equity read entirely, so the defect cannot recur by construction, and
`validate_v6.py` now has a perturbation test that would catch its return.

Preserved from Run A because the audit verified them
----------------------------------------------------
The exit chain order, the trailing-stop ratchet and its seeding, the fractional
`stdev_20` stop formula with its 2.0 multiplier, `rsi_extreme_high 90`,
`mean_reversion_complete > 70`, must-fixes 1-5 and 7, `reconcile()`, and
`data_feed`'s flatten-and-raise path. None of those were churned.
"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from engine import active_config
from engine.data_feed import load_universe
from engine.indicators import add_indicators
from engine.live_adapter import (
    assert_frame_contract, evaluate_entry, stdev_at,
)

RESULTS_DIR = Path(__file__).parent.parent / "results"

# Live constants that live reads from its own module scope rather than config.
LIVE_PENDING_MAX_AGE_DAYS = 4      # tracker.py pending lifecycle
LIVE_MAX_FILL_ATTEMPTS = 3         # tracker.py MAX_FILL_ATTEMPTS
LIVE_QUEUE_MAX_SIZE = 10           # tracker.py queue_max_size
LIVE_QUEUE_MAX_DRIFT_PCT = 5.0     # tracker.py queue_max_drift_pct
LIVE_STDEV_FALLBACK = 0.05         # tracker.py:141

# Divergence columns. Forced False when the decision set excludes divergence.
_DIV_COLS = ['bullish_div', 'bearish_div', 'hidden_bull_div', 'hidden_bear_div']

REPRODUCED_LIVE_DEFECTS = """\
Defects reproduced deliberately, because Run A' measures the system Ares IS:

1. Queue promotion gates are inert. `tracker.py:400,403` read
   `latest.get('RSI', 50)` and `latest.get('EMA_20', 0)`, but `add_indicators`
   produces lowercase `rsi` and never produces `EMA_20`. So the RSI check always
   sees 50 and can never reject, and the EMA20 check always compares against 0 and
   can never reject. Live promotion is `|drift| <= 5%` and nothing else. This was
   found while building Run A' and is NOT in the parity audit's list.

2. All four divergence reads are structurally False in production. Live's pivot
   loop stops at `len - window - 1` while live reads index `len - 1`, so
   `latest['bearish_div']` and friends can never be True. `indicators.py` is now
   causal and CAN flag the latest bar, so faithfulness requires forcing those four
   columns to False — otherwise the backtest would fire an exit live is incapable
   of firing. That is what `divergence_in_decision_set: false` does.

Neither is fixed here. Fixing live behaviour inside the backtest is exactly how the
backtest and the live system drifted apart in the first place.
"""

def load_params(name=None):
    """Load the active config. `indicators` resolves through the same module."""
    if name:
        active_config.set_active(name)
    return active_config.load()

def static_position_size(params):
    """Live's sizing: fixed dollar stake, no compounding, no cash awareness.

    `tracker.py:120-124`. Note `starting_capital` is a NOTIONAL used only to derive
    the stake; live never reduces it, never grows it, and never checks a balance.
    At the frozen config this is $149.
    """
    capital = params.get('starting_capital', 1000)
    reserve = params.get('cash_reserve_pct', 0.25)
    slots = params.get('max_positions', 5)
    commission = params.get('commission_per_trade', 1.00)
    return (capital * (1 - reserve) / slots) - commission

def prepare(symbols, start_date, end_date, params, min_bars=100):
    """Load the frozen snapshot, add indicators, slice, and validate the contract.

    Frames stay as DataFrames rather than numpy arrays: live's predicates are handed
    `df.iloc[:i+1]` so they physically cannot read the future. Run A's numpy fast
    path is what let the two implementations drift, and is where the sizing
    look-ahead hid.

    Indicators are computed on the FULL history before slicing, so the 252-bar and
    50-bar warm-ups come from real bars preceding `start_date`.
    """
    use_divergence = params.get('divergence_in_decision_set', False)
    raw = load_universe(symbols, min_bars=min_bars)
    prepared = {}
    for symbol, df in raw.items():
        df = add_indicators(df.sort_index())
        if not use_divergence:
            # See REPRODUCED_LIVE_DEFECTS item 2. Live cannot see a divergence at
            # `latest`; a causal detector can, so it must be masked to match.
            for c in _DIV_COLS:
                df[c] = False
        df = df.loc[start_date:end_date]
        if len(df) < 50:
            continue
        assert_frame_contract(df)
        prepared[symbol] = df
    return prepared

def _fill(price, side, slippage):
    """Slippage always works against us: buy higher, sell lower."""
    return price * (1 + slippage) if side == 'buy' else price * (1 - slippage)

def _decide_exit(row, pos, params):
    """Live's exit chain, in live's order, with live's elif semantics.

    Reproduces `tracker.py:812-858` including two behaviours Run A got wrong:

    - The `bearish_div` branch is an `elif` whose *inner* test is the strategy. A
      `mean_reversion` position on a `bearish_div` bar therefore enters the branch,
      does nothing, and — crucially — never reaches the `mean_reversion_complete`
      test below it. Run A folded the strategy test into the condition and fell
      through, producing exits live cannot produce.
    - Scale-out is NOT here. Live checks it before this chain and `continue`s, so a
      target bar never evaluates an exit at all. The caller enforces that.

    Returns an exit reason, or None.
    """
    price = float(row['Close'])
    rsi = float(row['rsi']) if not pd.isna(row['rsi']) else 50.0
    effective_stop = max(pos['stop_loss'], pos['trailing_stop'])

    if price <= effective_stop:
        return ('trailing_stop' if pos['trailing_stop'] > pos['stop_loss']
                else 'stop_loss')
    elif rsi > params.get('rsi_extreme_high', 90):
        return 'emotional_extreme'
    elif bool(row.get('bearish_div', False)):
        if pos['strategy'] in ('momentum_breakout', 'trend_continuation'):
            return 'bearish_divergence'
        return None          # swallowed, exactly as live swallows it
    elif pos['strategy'] == 'mean_reversion' and rsi > 70:
        return 'mean_reversion_complete'
    return None

def run_sim(symbols, start_date, end_date, params, label=""):
    """Portfolio simulation running live Ares' strategy code.

    Day ordering. Every step reads only bars at or before the day being processed,
    and fills happen at the open of the day AFTER the decision:
      1. Exit fills queued yesterday, at today's open.
      2. Scale-out fills queued yesterday, at today's open.
      3. Entry fills queued yesterday, at today's open (live's pending lifecycle).
      4. Mark equity at today's close.
      5. Exit decisions from today's close — scale-out FIRST, then live's chain.
      6. Entry signals from today's close, via live's predicates.
      7. Queue maintenance and promotion, on live's drift-only rule.

    Cash is tracked for accounting only. Live tracks none, and no decision here
    reads it, so the simulated population is cash-independent exactly as live's is;
    the balance exists so `reconcile()` can prove the P&L.
    """
    capital = params.get('starting_capital', 1000)
    max_positions = params.get('max_positions', 5)
    tp_momentum = params.get('tp_momentum', 0.18)
    tp_reversal = params.get('tp_reversal', 0.10)
    scale_out = params.get('scale_out', True)
    scale_out_pct = params.get('scale_out_pct', 0.50)
    queue_max_age = params.get('queue_max_age_days', 5)
    slippage = params.get('slippage_pct', 0.001)
    commission = params.get('commission_per_trade', 1.00)
    sl_mult = params.get('stop_loss_multiplier', 2.0)
    stake = static_position_size(params)

    data = prepare(symbols, start_date, end_date, params)
    trading_days = sorted({d for df in data.values() for d in df.index})

    cash = float(capital)
    positions = {}
    closed = []
    history = []
    queue = []
    pending = []
    pending_exits = []
    pending_scaleouts = []

    c = {
        'signals_total': 0, 'entries_filled': 0, 'signals_queued': 0,
        'entries_from_queue': 0, 'commissions_paid': 0.0,
        'queue_evicted_size': 0, 'queue_expired_age': 0,
        'queue_rejected_drift': 0, 'pending_expired': 0,
        'pending_fill_attempts_exhausted': 0, 'stdev_fallback_fills': 0,
        'queue_promotions_attempted': 0,
    }

    for day in trading_days:
        day_str = str(day)[:10]

        # ---- 1. exit fills at today's open -------------------------------
        for order in pending_exits:
            pos = positions.get(order['symbol'])
            if pos is None or day not in data[order['symbol']].index:
                continue
            px = _fill(float(data[order['symbol']].loc[day, 'Open']), 'sell', slippage)
            proceeds = pos['shares'] * px - commission
            cash += proceeds
            c['commissions_paid'] += commission
            pos['commission_paid'] += commission
            closed.append(_book(pos, day_str, px, order['reason'], proceeds))
            del positions[order['symbol']]
        pending_exits = []

        # ---- 2. scale-out fills at today's open --------------------------
        for order in pending_scaleouts:
            pos = positions.get(order['symbol'])
            if pos is None or pos['scaled_out'] or day not in data[order['symbol']].index:
                continue
            px = _fill(float(data[order['symbol']].loc[day, 'Open']), 'sell', slippage)
            shares = pos['original_shares'] * scale_out_pct
            proceeds = shares * px - commission
            cash += proceeds
            c['commissions_paid'] += commission
            pos['commission_paid'] += commission
            pos['shares'] -= shares
            pos['scaled_out'] = True
            pos['scale_out_date'] = day_str
            pos['scale_out_price'] = px
            pos['scale_out_shares'] = shares
            pos['scale_out_proceeds'] = proceeds
        pending_scaleouts = []

        # ---- 3. entry fills at today's open, live's pending lifecycle ----
        still_pending = []
        for order in pending:
            sym = order['symbol']
            age = (day - order['signal_day']).days
            if age > LIVE_PENDING_MAX_AGE_DAYS:
                c['pending_expired'] += 1
                continue
            if order['attempts'] >= LIVE_MAX_FILL_ATTEMPTS:
                c['pending_fill_attempts_exhausted'] += 1
                continue
            if sym in positions or len(positions) >= max_positions:
                continue
            if day not in data[sym].index:
                # Live's "last bar != today" branch: retain and retry, which is
                # also its 48-hour weekend gap guard. Run A dropped these silently.
                order['attempts'] += 1
                still_pending.append(order)
                continue

            buy = _fill(float(data[sym].loc[day, 'Open']), 'buy', slippage)

            # Live substitutes 0.05 and FILLS, flagging the trade. Run A refused.
            stdev = order['stdev_20']
            contaminated = stdev is None
            if contaminated:
                stdev = LIVE_STDEV_FALLBACK
                c['stdev_fallback_fills'] += 1

            # Static stake. No equity read, no cash gate, no minimum size.
            shares = stake / buy
            cash -= (shares * buy + commission)
            c['commissions_paid'] += commission
            tp_pct = (tp_momentum if order['strategy'] in
                      ('momentum_breakout', 'trend_continuation') else tp_reversal)
            positions[sym] = {
                'symbol': sym, 'strategy': order['strategy'],
                'trigger': order['trigger'], 'confluence': order['confluence'],
                'signal_date': order['signal_date'], 'entry_date': day_str,
                'entry_price': buy, 'shares': shares, 'original_shares': shares,
                'stop_loss': buy - buy * stdev * sl_mult,
                'take_profit': buy * (1 + tp_pct) if tp_pct > 0 else 0.0,
                'trailing_stop': buy - buy * stdev * sl_mult,
                'peak_price': buy,
                'rsi_at_entry': order['rsi'], 'vol_at_entry': order['vol_ratio'],
                'stdev_20': stdev, 'stdev_fallback': contaminated,
                'from_queue': order['from_queue'],
                'scaled_out': False, 'scale_out_date': None,
                'scale_out_price': 0.0, 'scale_out_shares': 0.0,
                'scale_out_proceeds': 0.0,
                'entry_commission': commission, 'commission_paid': commission,
            }
            c['entries_filled'] += 1
        pending = still_pending

        # ---- 4. mark equity at today's close -----------------------------
        equity = cash
        for sym, pos in positions.items():
            if day in data[sym].index:
                equity += pos['shares'] * float(data[sym].loc[day, 'Close'])
        history.append({'date': day_str, 'equity': round(equity, 2),
                        'cash': round(cash, 2), 'positions': len(positions),
                        'queue_size': len(queue), 'pending': len(pending)})

        # ---- 5. exit decisions from today's close ------------------------
        for sym, pos in positions.items():
            if day not in data[sym].index:
                continue
            # Live suppresses ALL exit logic on the entry bar (tracker.py:788).
            # Run A permitted 1-bar trades live cannot produce.
            if pos['entry_date'] == day_str:
                continue
            row = data[sym].loc[day]
            price = float(row['Close'])

            if price > pos['peak_price']:
                pos['peak_price'] = price
                new_ts = price * (1 - params.get('trailing_stop_pct', 0.10))
                if new_ts > pos['trailing_stop']:
                    pos['trailing_stop'] = new_ts

            # Scale-out FIRST, and it short-circuits the exit chain, exactly as
            # live's `continue` does. This is the ordering that protects winners.
            if (scale_out and not pos['scaled_out'] and pos['take_profit'] > 0
                    and price >= pos['take_profit']):
                pending_scaleouts.append({'symbol': sym})
                continue

            reason = _decide_exit(row, pos, params)
            if reason:
                pending_exits.append({'symbol': sym, 'reason': reason})

        # ---- 6. entry signals from today's close, via LIVE predicates -----
        exiting = {o['symbol'] for o in pending_exits}
        busy = set(positions) | {o['symbol'] for o in pending} | exiting

        for sym, df in data.items():
            if sym in busy:
                continue
            i = df.index.get_indexer([day])[0]
            if i < 1:
                continue
            signal = evaluate_entry(df, i, params, sym)
            if not signal:
                continue
            c['signals_total'] += 1
            order = {
                'symbol': sym, 'strategy': signal['strategy'],
                'trigger': signal['trigger'],
                'confluence': signal.get('confluence', 1),
                'rsi': signal.get('rsi', 50.0),
                'vol_ratio': signal.get('vol_ratio', 1.0),
                'stdev_20': stdev_at(df, i),
                'price_at_signal': float(df['Close'].iloc[i]),
                'signal_date': day_str, 'signal_day': day,
                'attempts': 0, 'from_queue': False,
            }
            if len(positions) + len(pending) >= max_positions:
                queue.append(dict(order, date_added=day))
                c['signals_queued'] += 1
            else:
                pending.append(order)

        # ---- 7. queue maintenance and live's drift-only promotion ---------
        queue = [q for q in queue if q['symbol'] not in set(positions)
                 | {o['symbol'] for o in pending}]
        kept = []
        for q in queue:
            if (day - q['date_added']).days > queue_max_age:
                c['queue_expired_age'] += 1
                continue
            kept.append(q)
        queue = kept

        # De-duplicate by symbol, keeping the strongest, then evict to max size on
        # live's ranking key: highest confluence, then smallest drift, then oldest.
        best = {}
        for q in queue:
            cur = best.get(q['symbol'])
            if cur is None or q['confluence'] > cur['confluence']:
                best[q['symbol']] = q
        queue = list(best.values())
        queue.sort(key=lambda q: (-q['confluence'],
                                  abs(_drift(data, q, day)),
                                  q['date_added']))
        if len(queue) > LIVE_QUEUE_MAX_SIZE:
            c['queue_evicted_size'] += len(queue) - LIVE_QUEUE_MAX_SIZE
            queue = queue[:LIVE_QUEUE_MAX_SIZE]

        if queue and len(positions) + len(pending) < max_positions:
            for q in queue[:]:
                if len(positions) + len(pending) >= max_positions:
                    break
                sym = q['symbol']
                if sym in positions or sym in exiting or day not in data[sym].index:
                    continue
                c['queue_promotions_attempted'] += 1
                drift = _drift(data, q, day)
                # Live's _validate_queued. The RSI and EMA20 gates are inert
                # because the columns they read do not exist, so drift is the only
                # live constraint. Run A instead demanded a full fresh signal here,
                # which is the single largest population difference between the runs.
                if abs(drift) > params.get('queue_max_drift_pct',
                                           LIVE_QUEUE_MAX_DRIFT_PCT):
                    c['queue_rejected_drift'] += 1
                    continue
                promoted = dict(q, from_queue=True, attempts=0,
                                signal_day=day, signal_date=day_str,
                                stdev_20=stdev_at(data[sym],
                                                  data[sym].index.get_indexer([day])[0]))
                pending.append(promoted)
                c['entries_from_queue'] += 1
                queue.remove(q)

    # ---- no end_of_sim liquidation: live has no analogue ------------------
    last_day = trading_days[-1]
    open_positions = []
    open_value = 0.0
    for sym, pos in positions.items():
        df = data[sym]
        i = df.index.get_indexer([last_day])[0]
        if i < 0:
            i = len(df) - 1
        mark = float(df['Close'].iloc[i])
        value = pos['shares'] * mark
        open_value += value
        open_positions.append({
            'symbol': sym, 'strategy': pos['strategy'],
            'entry_date': pos['entry_date'], 'entry_price': round(pos['entry_price'], 6),
            'shares': round(pos['shares'], 8), 'mark_price': round(mark, 6),
            'market_value': round(value, 2),
            'cost_basis': round(pos['original_shares'] * pos['entry_price']
                                + pos['entry_commission'], 6),
            'scaled_out': pos['scaled_out'],
            'scale_out_proceeds': round(pos['scale_out_proceeds'], 6),
            'unrealised_pnl': round(value + pos['scale_out_proceeds']
                                    - pos['original_shares'] * pos['entry_price']
                                    - pos['entry_commission'], 2),
            'stdev_fallback': pos['stdev_fallback'],
        })

    c.update({
        'final_cash': round(cash, 2),
        'open_positions': len(open_positions),
        'open_market_value': round(open_value, 2),
        'final_equity': round(cash + open_value, 2),
        'static_stake': round(stake, 2),
        'symbols_contributing': len(data),
        'symbols_requested': len(symbols),
        'label': label,
    })
    if cash < 0:
        raise AssertionError(
            f"Cash went negative (${cash:.2f}). Live never checks a balance, but at "
            f"{max_positions} slots x ${stake:.2f} it cannot overdraw — so this "
            f"means the sizing or booking logic is wrong, not that live is."
        )
    reconcile(closed, open_positions, capital, cash, open_value)
    return closed, history, c, open_positions

def _drift(data, q, day):
    """Percent move from the signal price to the latest close, as live measures it."""
    df = data.get(q['symbol'])
    if df is None or day not in df.index:
        return 0.0
    base = q.get('price_at_signal') or 0.0
    if not base:
        return 0.0
    return (float(df.loc[day, 'Close']) - base) / base * 100

def _book(pos, exit_date, exit_price, reason, exit_proceeds):
    """Trade record with the full audit trail.

    `total_invested` includes the entry commission and `total_returned` is net of
    every commission, so `pnl` is the real cash delta. Precision is high enough
    that every figure can be re-derived from the CSV — at 4dp a validation check
    cannot distinguish a rounding artifact from an accounting error.

    `stdev_fallback` travels with the trade so the wide-stop population live fills
    and Run A refused can be segmented later rather than silently averaged in.
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
        'stdev_fallback': pos['stdev_fallback'],
        'rsi_at_entry': round(float(pos['rsi_at_entry']), 2),
        'vol_at_entry': round(float(pos['vol_at_entry']), 3),
        'from_queue': pos['from_queue'],
        'pnl': round(pnl, 6),
        'pnl_pct': round(pnl / invested * 100, 6),
        'win': 1 if pnl > 0 else 0,
    }

def reconcile(closed, open_positions, starting_capital, final_cash, open_value,
              tol=0.01):
    """Assert reported P&L equals the real cash delta, including open positions.

    V5's two commission defects each inflated reported P&L relative to cash while
    the printed `Commissions: $X` line made it look accounted for. The symptom of
    that bug class is a slightly better number, never a crash, so an assertion is
    the only thing that catches it.

    With no end-of-sim liquidation, the identity spans both books: realised P&L plus
    unrealised P&L must equal final equity minus starting capital.
    """
    realised = sum(t['pnl'] for t in closed)
    unrealised = sum(p['unrealised_pnl'] for p in open_positions)
    reported = realised + unrealised
    actual = (final_cash + open_value) - starting_capital
    if abs(reported - actual) > max(tol, 0.01 * len(open_positions)):
        raise AssertionError(
            f"P&L does not reconcile with equity: reported {reported:.4f} "
            f"(realised {realised:.4f} + unrealised {unrealised:.4f}) vs actual "
            f"{actual:.4f}, diff {reported - actual:.4f}. Check commission handling."
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

def summarise(closed, history, counters, params, open_positions=()):
    """Compute the Run A' metric set, on a FIXED-STAKE basis.

    MUST-FIX 5: `peak_after_exit` and `missed_upside_pct` are absent by
    construction, so they cannot reach parameter selection even by accident.

    Sizing is static $149 and does not compound, because that is what live does.
    The primary figures are therefore total dollar P&L and return on the notional
    $1,000. `cagr_pct` is still reported for scale but is a NON-COMPOUNDING rate on
    a fixed stake, so it is **not comparable to Run A's CAGR**, which was produced
    under a compounding sizing rule Ares does not use. `return_basis` records which
    regime produced the number so the two can never be tabulated as like for like.

    Open positions are not liquidated, since live has no end-of-sim analogue. They
    are excluded from every trade statistic and reported separately, with their
    unrealised value included in equity.
    """
    start = params.get('starting_capital', 1000)
    hist = pd.DataFrame(history)
    df = pd.DataFrame(closed)
    open_positions = list(open_positions)

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
        'return_basis': 'fixed_stake_non_compounding',
        'static_stake': counters.get('static_stake'),
        'cagr_comparable_to_run_a': False,
        'start_capital': start, 'final_equity': round(final, 2),
        'total_return_pct': round(total_ret, 2),
        'cagr_pct': round(cagr, 2),
        'open_positions': counters.get('open_positions', 0),
        'open_market_value': counters.get('open_market_value', 0.0),
        'unrealised_pnl': round(sum(p['unrealised_pnl'] for p in open_positions), 2),
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
        'queue_promotions_attempted', 'queue_rejected_drift', 'queue_expired_age',
        'queue_evicted_size', 'pending_expired',
        'pending_fill_attempts_exhausted', 'stdev_fallback_fills') if k in counters})

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
        'from_queue_count': int(df['from_queue'].sum()),
        # The wide-stop population live fills and Run A refused. Segmented rather
        # than averaged in, so its effect on the headline is visible.
        'stdev_fallback_trades': int(df['stdev_fallback'].sum()),
        'stdev_fallback_pnl': round(
            float(df.loc[df['stdev_fallback'], 'pnl'].sum()), 2),
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
    # Deliberately NOT a percentage of net P&L. When net P&L is near zero — which
    # is exactly the regime a break-even strategy sits in — dividing by it produces
    # figures like "13006% of total P&L" that look like findings and are arithmetic
    # noise. Share of gross flow is stable and answers the real question: which
    # exit reason moves the money.
    gross = float(df['pnl'].abs().sum())
    g['pct_of_gross_flow'] = ((g['total_pnl'].abs() / gross * 100).round(1)
                              if gross > 0 else 0.0)
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
