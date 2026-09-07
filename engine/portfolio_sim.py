"""Athena V4 — Full Portfolio Simulator with Scale-Out and Watchlist Queue.

Simulates Ares V2.2 with:
- $1,000 starting capital
- 5 max positions, 25% cash reserve
- Scale-out: sell 50% at TP, ride 50% with trailing stop
- Watchlist queue: log blocked signals, enter when slot opens
- Tracks portfolio value day by day
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
    """Check entry conditions (same as backtester)."""
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

def run_portfolio_sim(symbols, start_date="2021-09-01", end_date="2026-09-01"):
    """Full portfolio simulation with capital management."""
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

    # Load and prepare all data
    print(f"\n  Preparing data for {len(symbols)} stocks...")
    stock_data = {}
    for symbol in symbols:
        df = load_stock(symbol)
        if df is not None and len(df) > 100:
            df = add_indicators(df)
            df = df.sort_index()
            df = df.loc[start_date:end_date]
            if len(df) > 50:
                stock_data[symbol] = df

    print(f"  {len(stock_data)} stocks ready")

    # Get all trading dates
    all_dates = set()
    for df in stock_data.values():
        all_dates.update(df.index)
    trading_days = sorted(all_dates)

    # Portfolio state
    cash = capital
    open_positions = []
    closed_trades = []
    queue = []
    portfolio_history = []
    total_signals = 0
    signals_queued = 0
    signals_entered = 0
    signals_from_queue = 0

    print(f"\n  Starting capital: ${capital}")
    print(f"  Max positions: {max_positions}")
    print(f"  Cash reserve: {cash_reserve_pct*100:.0f}%")
    print(f"  Scale-out: {'Yes (50% at TP)' if scale_out else 'No'}")
    print(f"  Simulating {len(trading_days)} trading days...\n")

    for day in trading_days:
        day_str = str(day)[:10]

        # Calculate portfolio value
        portfolio_value = cash
        for pos in open_positions:
            sym = pos['symbol']
            if sym in stock_data and day in stock_data[sym].index:
                price = float(stock_data[sym].loc[day, 'Close'])
                portfolio_value += price * pos['shares']

        portfolio_history.append({
            'date': day_str,
            'portfolio_value': round(portfolio_value, 2),
            'cash': round(cash, 2),
            'positions': len(open_positions),
            'queue_size': len(queue)
        })

        # Check exits for open positions
        positions_to_remove = []
        for pos in open_positions:
            sym = pos['symbol']
            if sym not in stock_data or day not in stock_data[sym].index:
                continue

            row = stock_data[sym].loc[day]
            price = float(row['Close'])
            rsi = float(row.get('rsi', 50))

            # Update peak and trailing stop
            if price > pos['peak_price']:
                pos['peak_price'] = price
                new_ts = price * (1 - trailing_pct)
                if new_ts > pos['trailing_stop']:
                    pos['trailing_stop'] = new_ts

            effective_stop = max(pos['stop_loss'], pos['trailing_stop'])
            exit_reason = None
            exit_price = None

            # Check exits
            if price <= effective_stop:
                exit_reason = 'trailing_stop' if pos['trailing_stop'] > pos['stop_loss'] else 'stop_loss'
                exit_price = effective_stop
            elif rsi > rsi_extreme:
                exit_reason = 'emotional_extreme'
                exit_price = price
            elif bool(row.get('bearish_div', False)) and pos['strategy'] == 'momentum_breakout':
                exit_reason = 'bearish_divergence'
                exit_price = price
            elif pos['strategy'] == 'mean_reversion' and rsi > 70:
                exit_reason = 'mean_reversion_complete'
                exit_price = price

            # Scale-out: check TP for first half
            if scale_out and not pos.get('scaled_out', False) and pos.get('take_profit'):
                if price >= pos['take_profit']:
                    sell_shares = pos['shares'] * scale_out_pct
                    sell_value = sell_shares * pos['take_profit']
                    cash += sell_value
                    pos['shares'] -= sell_shares
                    pos['scaled_out'] = True
                    pos['scale_out_price'] = round(pos['take_profit'], 2)
                    pos['scale_out_date'] = day_str
                    pos['scale_out_pnl'] = round((pos['take_profit'] - pos['entry_price']) / pos['entry_price'] * 100, 2)

            if exit_reason:
                sell_value = pos['shares'] * exit_price
                cash += sell_value
                entry_dt = datetime.strptime(pos['entry_date'], "%Y-%m-%d")
                exit_dt = datetime.strptime(day_str, "%Y-%m-%d")

                total_invested = pos['original_shares'] * pos['entry_price']
                total_returned = sell_value
                if pos.get('scaled_out'):
                    total_returned += pos['original_shares'] * scale_out_pct * pos['scale_out_price']

                total_pnl = total_returned - total_invested
                total_pnl_pct = (total_returned - total_invested) / total_invested * 100

                trade = {
                    'symbol': sym,
                    'strategy': pos['strategy'],
                    'trigger': pos['trigger'],
                    'confluence': pos['confluence'],
                    'entry_date': pos['entry_date'],
                    'entry_price': pos['entry_price'],
                    'exit_date': day_str,
                    'exit_price': round(exit_price, 2),
                    'exit_reason': exit_reason,
                    'original_shares': pos['original_shares'],
                    'remaining_shares': round(pos['shares'], 2),
                    'scaled_out': pos.get('scaled_out', False),
                    'scale_out_price': pos.get('scale_out_price'),
                    'holding_days': (exit_dt - entry_dt).days,
                    'pnl': round(total_pnl, 2),
                    'pnl_pct': round(total_pnl_pct, 2),
                    'peak_price': round(pos['peak_price'], 2),
                    'rsi_at_entry': pos['rsi_at_entry'],
                    'vol_at_entry': pos['vol_at_entry'],
                    'portfolio_value': round(portfolio_value, 2),
                    'win': 1 if total_pnl > 0 else 0
                }
                closed_trades.append(trade)
                positions_to_remove.append(pos)

        for pos in positions_to_remove:
            open_positions.remove(pos)

        # Expire old queue entries
        queue = [q for q in queue if (datetime.strptime(day_str, "%Y-%m-%d") - datetime.strptime(q['date'], "%Y-%m-%d")).days <= queue_max_age]

        # Check for new signals
        available_cash = cash - (portfolio_value * cash_reserve_pct)
        open_symbols = [p['symbol'] for p in open_positions]

        for sym in stock_data:
            if sym in open_symbols:
                continue
            if day not in stock_data[sym].index:
                continue

            row = stock_data[sym].loc[day]
            prev_idx = stock_data[sym].index.get_loc(day)
            if prev_idx < 1:
                continue
            prev = stock_data[sym].iloc[prev_idx - 1]

            signal = _check_entry(row, params)
            if not signal:
                continue

            total_signals += 1
            price = float(row['Close'])

            if len(open_positions) >= max_positions or available_cash < 50:
                queue.append({
                    'symbol': sym,
                    'date': day_str,
                    'signal': signal,
                    'price': price,
                    'rsi': float(row.get('rsi', 50)),
                    'vol_ratio': float(row.get('vol_ratio', 1.0)),
                    'confluence': signal['confluence']
                })
                signals_queued += 1
                continue

            # Enter trade
            position_size = min(available_cash, portfolio_value * 0.20)
            if position_size < 20:
                continue

            shares = position_size / price
            stdev = float(stock_data[sym].iloc[max(0,prev_idx-20):prev_idx]['Close'].std()) if prev_idx >= 20 else price * 0.05
            stop_loss = price - (stdev * 2)

            tp_pct = tp_momentum if signal['strategy'] == 'momentum_breakout' else tp_reversal
            take_profit = price * (1 + tp_pct)

            pos = {
                'symbol': sym,
                'strategy': signal['strategy'],
                'trigger': signal['trigger'],
                'confluence': signal['confluence'],
                'entry_date': day_str,
                'entry_price': price,
                'shares': shares,
                'original_shares': shares,
                'stop_loss': round(stop_loss, 2),
                'take_profit': round(take_profit, 2),
                'trailing_stop': round(stop_loss, 2),
                'peak_price': price,
                'rsi_at_entry': float(row.get('rsi', 50)),
                'vol_at_entry': float(row.get('vol_ratio', 1.0)),
                'scaled_out': False,
                'from_queue': False
            }
            open_positions.append(pos)
            cash -= position_size
            available_cash -= position_size
            signals_entered += 1

        # Check queue for entries if slot opened
        if len(open_positions) < max_positions and queue:
            queue.sort(key=lambda q: q['confluence'], reverse=True)
            for q in queue[:]:
                if len(open_positions) >= max_positions:
                    break
                sym = q['symbol']
                if sym in [p['symbol'] for p in open_positions]:
                    continue
                if sym not in stock_data or day not in stock_data[sym].index:
                    continue

                row = stock_data[sym].loc[day]
                recheck = _check_entry(row, params)
                if not recheck:
                    continue

                price = float(row['Close'])
                available_cash = cash - (portfolio_value * cash_reserve_pct)
                position_size = min(available_cash, portfolio_value * 0.20)
                if position_size < 20:
                    continue

                shares = position_size / price
                prev_idx = stock_data[sym].index.get_loc(day)
                stdev = float(stock_data[sym].iloc[max(0,prev_idx-20):prev_idx]['Close'].std()) if prev_idx >= 20 else price * 0.05
                stop_loss = price - (stdev * 2)

                tp_pct = tp_momentum if recheck['strategy'] == 'momentum_breakout' else tp_reversal
                take_profit = price * (1 + tp_pct)

                pos = {
                    'symbol': sym,
                    'strategy': recheck['strategy'],
                    'trigger': recheck['trigger'],
                    'confluence': recheck['confluence'],
                    'entry_date': day_str,
                    'entry_price': price,
                    'shares': shares,
                    'original_shares': shares,
                    'stop_loss': round(stop_loss, 2),
                    'take_profit': round(take_profit, 2),
                    'trailing_stop': round(stop_loss, 2),
                    'peak_price': price,
                    'rsi_at_entry': float(row.get('rsi', 50)),
                    'vol_at_entry': float(row.get('vol_ratio', 1.0)),
                    'scaled_out': False,
                    'from_queue': True
                }
                open_positions.append(pos)
                cash -= position_size
                signals_from_queue += 1
                queue.remove(q)

    # Close remaining open positions at last day price
    for pos in open_positions:
        sym = pos['symbol']
        if sym in stock_data and len(stock_data[sym]) > 0:
            last_price = float(stock_data[sym].iloc[-1]['Close'])
            total_invested = pos['original_shares'] * pos['entry_price']
            total_returned = pos['shares'] * last_price
            if pos.get('scaled_out'):
                total_returned += pos['original_shares'] * scale_out_pct * pos['scale_out_price']
            total_pnl = total_returned - total_invested
            closed_trades.append({
                'symbol': sym, 'strategy': pos['strategy'],
                'trigger': pos['trigger'], 'confluence': pos['confluence'],
                'entry_date': pos['entry_date'], 'entry_price': pos['entry_price'],
                'exit_date': str(trading_days[-1])[:10], 'exit_price': round(last_price, 2),
                'exit_reason': 'end_of_sim', 'original_shares': pos['original_shares'],
                'remaining_shares': round(pos['shares'], 2),
                'scaled_out': pos.get('scaled_out', False),
                'scale_out_price': pos.get('scale_out_price'),
                'holding_days': 0, 'pnl': round(total_pnl, 2),
                'pnl_pct': round(total_pnl / total_invested * 100, 2),
                'peak_price': round(pos['peak_price'], 2),
                'rsi_at_entry': pos['rsi_at_entry'], 'vol_at_entry': pos['vol_at_entry'],
                'portfolio_value': 0, 'win': 1 if total_pnl > 0 else 0
            })

    return closed_trades, portfolio_history, {
        'total_signals': total_signals,
        'signals_entered': signals_entered,
        'signals_queued': signals_queued,
        'signals_from_queue': signals_from_queue
    }

def print_portfolio_summary(trades, history, stats, start_capital=1000):
    """Print full portfolio simulation results."""
    if not trades or not history:
        print("  No results.")
        return

    df = pd.DataFrame(trades)
    hist = pd.DataFrame(history)

    final_value = hist.iloc[-1]['portfolio_value']
    total_return = (final_value - start_capital) / start_capital * 100
    years = len(hist) / 252
    annual_return = ((final_value / start_capital) ** (1/years) - 1) * 100 if years > 0 else 0

    peak = hist['portfolio_value'].max()
    trough_after_peak = hist.loc[hist['portfolio_value'].idxmax():, 'portfolio_value'].min()
    max_drawdown = (trough_after_peak - peak) / peak * 100

    wins = df[df['pnl_pct'] > 0]
    losses = df[df['pnl_pct'] <= 0]
    real_trades = df[df['exit_reason'] != 'end_of_sim']

    scaled = df[df['scaled_out'] == True]

    print(f"\n{'='*60}")
    print(f"  ATHENA V4 — FULL PORTFOLIO SIMULATION")
    print(f"{'='*60}")

    print(f"\n  PORTFOLIO PERFORMANCE:")
    print(f"    Starting capital:    ${start_capital:,.2f}")
    print(f"    Final value:         ${final_value:,.2f}")
    print(f"    Total return:        {total_return:+,.1f}%")
    print(f"    Annual return:       {annual_return:+,.1f}%")
    print(f"    Max drawdown:        {max_drawdown:,.1f}%")
    print(f"    Peak value:          ${peak:,.2f}")
    print(f"    Simulation period:   {years:.1f} years")

    print(f"\n  TRADE STATISTICS:")
    print(f"    Total trades:        {len(real_trades)}")
    real_wins = real_trades[real_trades['pnl_pct'] > 0]
    real_losses = real_trades[real_trades['pnl_pct'] <= 0]
    wr = len(real_wins)/len(real_trades)*100 if len(real_trades) > 0 else 0
    print(f"    Win rate:            {len(real_wins)}/{len(real_trades)} ({wr:.1f}%)")
    print(f"    Avg win:             {real_wins['pnl_pct'].mean():+.2f}%" if len(real_wins) > 0 else "    Avg win:             N/A")
    print(f"    Avg loss:            {real_losses['pnl_pct'].mean():+.2f}%" if len(real_losses) > 0 else "    Avg loss:            N/A")
    print(f"    Avg hold days:       {real_trades['holding_days'].mean():.0f}")
    print(f"    Total P&L:           ${real_trades['pnl'].sum():+,.2f}")

    print(f"\n  SIGNAL FLOW:")
    print(f"    Total signals:       {stats['total_signals']}")
    print(f"    Entered directly:    {stats['signals_entered']}")
    print(f"    Queued (slots full): {stats['signals_queued']}")
    print(f"    Entered from queue:  {stats['signals_from_queue']}")
    missed = stats['signals_queued'] - stats['signals_from_queue']
    print(f"    Missed (expired):    {missed}")

    print(f"\n  SCALE-OUT ANALYSIS:")
    if len(scaled) > 0:
        print(f"    Trades scaled out:   {len(scaled)}")
        print(f"    Avg P&L (scaled):    {scaled['pnl_pct'].mean():+.2f}%")
        not_scaled = df[(df['scaled_out'] == False) & (df['exit_reason'] != 'end_of_sim')]
        if len(not_scaled) > 0:
            print(f"    Avg P&L (no scale):  {not_scaled['pnl_pct'].mean():+.2f}%")
    else:
        print(f"    No trades hit TP for scale-out")

    print(f"\n  BY EXIT REASON:")
    for reason, group in real_trades.groupby('exit_reason'):
        avg_pnl = group['pnl_pct'].mean()
        print(f"    {reason}: {len(group)} trades | Avg P&L: {avg_pnl:+.2f}%")

    print(f"\n  YEARLY BREAKDOWN:")
    for year in sorted(hist['date'].str[:4].unique()):
        year_hist = hist[hist['date'].str[:4] == year]
        year_trades = real_trades[(real_trades['exit_date'].str[:4] == year)]
        start_val = year_hist.iloc[0]['portfolio_value']
        end_val = year_hist.iloc[-1]['portfolio_value']
        yr_return = (end_val - start_val) / start_val * 100
        yr_wins = year_trades[year_trades['pnl_pct'] > 0]
        yr_wr = len(yr_wins)/len(year_trades)*100 if len(year_trades) > 0 else 0
        print(f"    {year}: ${start_val:,.0f} → ${end_val:,.0f} ({yr_return:+.1f}%) | "
              f"{len(year_trades)} trades, {yr_wr:.0f}% win rate")

    print(f"{'='*60}")

    # Save results
    df.to_csv(RESULTS_DIR / "backtest_v4_trades.csv", index=False)
    hist.to_csv(RESULTS_DIR / "backtest_v4_portfolio.csv", index=False)
    print(f"\n  Saved: results/backtest_v4_trades.csv")
    print(f"  Saved: results/backtest_v4_portfolio.csv")
