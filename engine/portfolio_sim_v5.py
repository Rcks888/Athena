"""Athena V5 — Realistic Portfolio Simulator

Fixes from V4:
1. Next-bar execution: signals on day N, buy/sell at day N+1 open
2. Slippage: 0.1% per trade (bid-ask spread)
3. Commission: $1 per trade (IBKR)
4. Full 2021-2026 period with V3 logic
5. Also tests a different universe (random mid-caps) for sensitivity
"""
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from engine.data_feed import load_stock
from engine.indicators import add_indicators

CONFIG_PATH = Path(__file__).parent.parent / "config" / "strategy_params.json"
RESULTS_DIR = Path(__file__).parent.parent / "results"

def load_params():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def _check_entry(row, params):
    """Check entry conditions."""
    regime = str(row.get('regime', 'range'))
    rsi = float(row.get('rsi', 50))
    vol_ratio = float(row.get('vol_ratio', 1.0))
    macd_hist = float(row.get('macd_hist', 0))
    bearish_div = bool(row.get('bearish_div', False))
    hidden_bear_div = bool(row.get('hidden_bearish_div', False))
    bullish_div = bool(row.get('bullish_div', False))
    min_confluence = params.get('min_confluence', 2)

    if regime == 'downtrend':
        return None

    if regime == 'uptrend':
        confluence = 0
        trigger = None
        if rsi > 50 and vol_ratio > 1.5 and macd_hist > 0:
            confluence += 1
            trigger = 'breakout'
        if not bearish_div and not hidden_bear_div:
            confluence += 1
        if vol_ratio > 1.5:
            confluence += 1
        if confluence >= min_confluence and trigger:
            return {'strategy': 'momentum_breakout', 'trigger': trigger, 'confluence': confluence}

    elif regime == 'range':
        confluence = 0
        trigger = None
        if rsi < params.get('rsi_oversold', 30):
            confluence += 1
            trigger = 'oversold'
        if bullish_div:
            confluence += 1
            if not trigger:
                trigger = 'bullish_div'
        if vol_ratio > params.get('min_vol_ratio', 1.5):
            confluence += 1
        if confluence >= min_confluence and trigger:
            return {'strategy': 'mean_reversion', 'trigger': trigger, 'confluence': confluence}

    return None

def apply_slippage(price, direction, slippage_pct):
    """Apply slippage: buy higher, sell lower."""
    if direction == 'buy':
        return price * (1 + slippage_pct)
    else:
        return price * (1 - slippage_pct)

def run_realistic_sim(symbols, start_date, end_date, label=""):
    """Full portfolio simulation with realistic friction."""
    params = load_params()
    capital = params.get('starting_capital', 1000)
    max_positions = params.get('max_positions', 5)
    cash_reserve_pct = params.get('cash_reserve_pct', 0.25)
    trailing_pct = params.get('trailing_stop_pct', 0.10)
    tp_momentum = params.get('tp_momentum', 0.18)
    tp_reversal = params.get('tp_reversal', 0.10)
    scale_out = params.get('scale_out', True)
    scale_out_pct = params.get('scale_out_pct', 0.50)
    queue_max_age = params.get('queue_max_age_days', 5)
    rsi_extreme = params.get('rsi_extreme_high', 90)
    slippage = params.get('slippage_pct', 0.001)
    commission = params.get('commission_per_trade', 1.00)
    next_bar = params.get('next_bar_execution', True)

    # Load data
    stock_data = {}
    for symbol in symbols:
        df = load_stock(symbol)
        if df is not None and len(df) > 100:
            df = add_indicators(df)
            df = df.sort_index()
            df = df.loc[start_date:end_date]
            if len(df) > 50:
                stock_data[symbol] = df

    all_dates = set()
    for df in stock_data.values():
        all_dates.update(df.index)
    trading_days = sorted(all_dates)

    cash = capital
    open_positions = []
    closed_trades = []
    queue = []
    portfolio_history = []
    total_signals = 0
    signals_entered = 0
    signals_queued = 0
    signals_from_queue = 0
    total_commissions = 0

    # Pending entries (for next-bar execution)
    pending_entries = []

    for day_idx, day in enumerate(trading_days):
        day_str = str(day)[:10]

        # Execute pending entries from yesterday's signals
        if next_bar and pending_entries:
            for pe in pending_entries:
                sym = pe['symbol']
                if sym not in stock_data or day not in stock_data[sym].index:
                    continue
                if len(open_positions) >= max_positions:
                    continue
                if sym in [p['symbol'] for p in open_positions]:
                    continue

                row = stock_data[sym].loc[day]
                buy_price = float(row['Open']) if 'Open' in row.index else float(row['Close'])
                buy_price = apply_slippage(buy_price, 'buy', slippage)

                portfolio_value = cash
                for pos in open_positions:
                    if pos['symbol'] in stock_data and day in stock_data[pos['symbol']].index:
                        portfolio_value += float(stock_data[pos['symbol']].loc[day, 'Close']) * pos['shares']

                available_cash = cash - (portfolio_value * cash_reserve_pct)
                position_size = min(available_cash, portfolio_value * 0.20)
                if position_size < 20:
                    continue

                position_size -= commission
                total_commissions += commission
                cash -= commission
                shares = position_size / buy_price

                stdev = pe.get('stdev', buy_price * 0.05)
                stop_loss = buy_price - (stdev * 2)
                tp_pct = tp_momentum if pe['strategy'] == 'momentum_breakout' else tp_reversal
                take_profit = buy_price * (1 + tp_pct)

                pos = {
                    'symbol': sym,
                    'strategy': pe['strategy'],
                    'trigger': pe['trigger'],
                    'confluence': pe['confluence'],
                    'entry_date': day_str,
                    'entry_price': round(buy_price, 2),
                    'shares': shares,
                    'original_shares': shares,
                    'stop_loss': round(stop_loss, 2),
                    'take_profit': round(take_profit, 2),
                    'trailing_stop': round(stop_loss, 2),
                    'peak_price': buy_price,
                    'rsi_at_entry': pe.get('rsi', 50),
                    'vol_at_entry': pe.get('vol_ratio', 1.0),
                    'scaled_out': False,
                    'from_queue': pe.get('from_queue', False)
                }
                open_positions.append(pos)
                cash -= position_size
                signals_entered += 1

            pending_entries = []

        # Portfolio value
        portfolio_value = cash
        for pos in open_positions:
            sym = pos['symbol']
            if sym in stock_data and day in stock_data[sym].index:
                portfolio_value += float(stock_data[sym].loc[day, 'Close']) * pos['shares']

        portfolio_history.append({
            'date': day_str,
            'portfolio_value': round(portfolio_value, 2),
            'cash': round(cash, 2),
            'positions': len(open_positions),
            'queue_size': len(queue)
        })

        # Check exits
        positions_to_remove = []
        for pos in open_positions:
            sym = pos['symbol']
            if sym not in stock_data or day not in stock_data[sym].index:
                continue

            row = stock_data[sym].loc[day]
            price = float(row['Close'])
            rsi = float(row.get('rsi', 50))

            if price > pos['peak_price']:
                pos['peak_price'] = price
                new_ts = price * (1 - trailing_pct)
                if new_ts > pos['trailing_stop']:
                    pos['trailing_stop'] = new_ts

            effective_stop = max(pos['stop_loss'], pos['trailing_stop'])
            exit_reason = None
            exit_price = None

            if price <= effective_stop:
                exit_reason = 'trailing_stop' if pos['trailing_stop'] > pos['stop_loss'] else 'stop_loss'
                exit_price = apply_slippage(effective_stop, 'sell', slippage)
            elif rsi > rsi_extreme:
                exit_reason = 'emotional_extreme'
                exit_price = apply_slippage(price, 'sell', slippage)
            elif bool(row.get('bearish_div', False)) and pos['strategy'] == 'momentum_breakout':
                exit_reason = 'bearish_divergence'
                exit_price = apply_slippage(price, 'sell', slippage)
            elif pos['strategy'] == 'mean_reversion' and rsi > 70:
                exit_reason = 'mean_reversion_complete'
                exit_price = apply_slippage(price, 'sell', slippage)

            # Scale-out
            if scale_out and not pos.get('scaled_out', False) and pos.get('take_profit'):
                if price >= pos['take_profit']:
                    sell_shares = pos['original_shares'] * scale_out_pct
                    sell_price = apply_slippage(pos['take_profit'], 'sell', slippage)
                    sell_value = sell_shares * sell_price - commission
                    total_commissions += commission
                    cash += sell_value
                    pos['shares'] -= sell_shares
                    pos['scaled_out'] = True
                    pos['scale_out_price'] = round(sell_price, 2)

            if exit_reason:
                sell_value = pos['shares'] * exit_price - commission
                total_commissions += commission
                cash += sell_value

                total_invested = pos['original_shares'] * pos['entry_price']
                total_returned = sell_value
                if pos.get('scaled_out'):
                    total_returned += pos['original_shares'] * scale_out_pct * pos['scale_out_price']

                entry_dt = datetime.strptime(pos['entry_date'], "%Y-%m-%d")
                exit_dt = datetime.strptime(day_str, "%Y-%m-%d")

                trade = {
                    'symbol': sym, 'strategy': pos['strategy'],
                    'trigger': pos['trigger'], 'confluence': pos['confluence'],
                    'entry_date': pos['entry_date'], 'entry_price': pos['entry_price'],
                    'exit_date': day_str, 'exit_price': round(exit_price, 2),
                    'exit_reason': exit_reason,
                    'original_shares': round(pos['original_shares'], 4),
                    'scaled_out': pos.get('scaled_out', False),
                    'holding_days': (exit_dt - entry_dt).days,
                    'pnl': round(total_returned - total_invested, 2),
                    'pnl_pct': round((total_returned - total_invested) / total_invested * 100, 2),
                    'rsi_at_entry': pos['rsi_at_entry'],
                    'vol_at_entry': pos['vol_at_entry'],
                    'win': 1 if total_returned > total_invested else 0
                }
                closed_trades.append(trade)
                positions_to_remove.append(pos)

        for pos in positions_to_remove:
            open_positions.remove(pos)

        # Expire queue
        queue = [q for q in queue if (datetime.strptime(day_str, "%Y-%m-%d") - datetime.strptime(q['date'], "%Y-%m-%d")).days <= queue_max_age]

        # Scan for new signals
        open_symbols = [p['symbol'] for p in open_positions] + [pe['symbol'] for pe in pending_entries]

        for sym in stock_data:
            if sym in open_symbols:
                continue
            if day not in stock_data[sym].index:
                continue

            row = stock_data[sym].loc[day]
            prev_idx = stock_data[sym].index.get_loc(day)
            if prev_idx < 1:
                continue

            signal = _check_entry(row, params)
            if not signal:
                continue

            total_signals += 1
            price = float(row['Close'])

            stdev = float(stock_data[sym].iloc[max(0,prev_idx-20):prev_idx]['Close'].std()) if prev_idx >= 20 else price * 0.05

            entry_data = {
                'symbol': sym, 'strategy': signal['strategy'],
                'trigger': signal['trigger'], 'confluence': signal['confluence'],
                'price': price, 'rsi': float(row.get('rsi', 50)),
                'vol_ratio': float(row.get('vol_ratio', 1.0)),
                'stdev': stdev, 'from_queue': False
            }

            if len(open_positions) + len(pending_entries) >= max_positions:
                queue.append({'symbol': sym, 'date': day_str, 'data': entry_data})
                signals_queued += 1
                continue

            if next_bar:
                pending_entries.append(entry_data)
            else:
                pending_entries.append(entry_data)

        # Check queue
        if len(open_positions) + len(pending_entries) < max_positions and queue:
            queue.sort(key=lambda q: q['data']['confluence'], reverse=True)
            for q in queue[:]:
                if len(open_positions) + len(pending_entries) >= max_positions:
                    break
                sym = q['symbol']
                if sym in open_symbols:
                    continue
                if sym not in stock_data or day not in stock_data[sym].index:
                    continue
                row = stock_data[sym].loc[day]
                recheck = _check_entry(row, params)
                if not recheck:
                    continue
                q['data']['from_queue'] = True
                pending_entries.append(q['data'])
                signals_from_queue += 1
                queue.remove(q)

    # Close remaining
    for pos in open_positions:
        sym = pos['symbol']
        if sym in stock_data and len(stock_data[sym]) > 0:
            last_price = float(stock_data[sym].iloc[-1]['Close'])
            total_invested = pos['original_shares'] * pos['entry_price']
            total_returned = pos['shares'] * last_price
            if pos.get('scaled_out'):
                total_returned += pos['original_shares'] * scale_out_pct * pos['scale_out_price']
            closed_trades.append({
                'symbol': sym, 'strategy': pos['strategy'],
                'trigger': pos['trigger'], 'confluence': pos['confluence'],
                'entry_date': pos['entry_date'], 'entry_price': pos['entry_price'],
                'exit_date': str(trading_days[-1])[:10], 'exit_price': round(last_price, 2),
                'exit_reason': 'end_of_sim',
                'original_shares': round(pos['original_shares'], 4),
                'scaled_out': pos.get('scaled_out', False),
                'holding_days': 0,
                'pnl': round(total_returned - total_invested, 2),
                'pnl_pct': round((total_returned - total_invested) / total_invested * 100, 2),
                'rsi_at_entry': pos['rsi_at_entry'], 'vol_at_entry': pos['vol_at_entry'],
                'win': 1 if total_returned > total_invested else 0
            })

    return closed_trades, portfolio_history, {
        'label': label,
        'total_signals': total_signals,
        'signals_entered': signals_entered,
        'signals_queued': signals_queued,
        'signals_from_queue': signals_from_queue,
        'total_commissions': round(total_commissions, 2)
    }

def print_results(trades, history, stats, start_capital=1000):
    """Print results for one simulation."""
    if not trades or not history:
        print("  No results.")
        return

    df = pd.DataFrame(trades)
    hist = pd.DataFrame(history)
    real = df[df['exit_reason'] != 'end_of_sim']

    final = hist.iloc[-1]['portfolio_value']
    total_ret = (final - start_capital) / start_capital * 100
    years = len(hist) / 252
    annual_ret = ((final / start_capital) ** (1/years) - 1) * 100 if years > 0 else 0

    peak = hist['portfolio_value'].max()
    trough_after = hist.loc[hist['portfolio_value'].idxmax():, 'portfolio_value'].min()
    max_dd = (trough_after - peak) / peak * 100

    wins = real[real['pnl_pct'] > 0]
    losses = real[real['pnl_pct'] <= 0]
    wr = len(wins)/len(real)*100 if len(real) > 0 else 0
    avg_win = wins['pnl_pct'].mean() if len(wins) > 0 else 0
    avg_loss = losses['pnl_pct'].mean() if len(losses) > 0 else 0
    pf_num = (wr/100) * avg_win
    pf_den = (1 - wr/100) * abs(avg_loss) if avg_loss != 0 else 1
    pf = pf_num / pf_den if pf_den > 0 else 0

    label = stats.get('label', '')
    print(f"\n  [{label}]")
    print(f"    ${start_capital:,} → ${final:,.2f} ({total_ret:+.1f}%)")
    print(f"    Annual: {annual_ret:+.1f}% | Max DD: {max_dd:.1f}%")
    print(f"    Trades: {len(real)} | Win rate: {wr:.1f}% | PF: {pf:.2f}")
    print(f"    Avg win: {avg_win:+.2f}% | Avg loss: {avg_loss:+.2f}%")
    print(f"    Avg hold: {real['holding_days'].mean():.0f} days")
    print(f"    Commissions: ${stats['total_commissions']:.2f}")
    print(f"    Signals: {stats['total_signals']} total, {stats['signals_entered']} entered, {stats['signals_queued']} queued")

    print(f"\n    Yearly:")
    for year in sorted(hist['date'].str[:4].unique()):
        yh = hist[hist['date'].str[:4] == year]
        yt = real[real['exit_date'].str[:4] == year]
        s = yh.iloc[0]['portfolio_value']
        e = yh.iloc[-1]['portfolio_value']
        yr = (e - s) / s * 100
        yw = len(yt[yt['pnl_pct'] > 0])
        ywr = yw/len(yt)*100 if len(yt) > 0 else 0
        print(f"      {year}: ${s:,.0f} → ${e:,.0f} ({yr:+.1f}%) | {len(yt)} trades, {ywr:.0f}% WR")

    return {
        'label': label, 'final': final, 'total_ret': total_ret,
        'annual_ret': annual_ret, 'max_dd': max_dd,
        'trades': len(real), 'win_rate': wr, 'pf': pf,
        'avg_win': avg_win, 'avg_loss': avg_loss,
        'commissions': stats['total_commissions']
    }
