"""Athena Backtester — Simulates Ares V2.1 on historical data."""
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from engine.data_feed import load_stock
from engine.indicators import add_indicators

CONFIG_PATH = Path(__file__).parent.parent / "config" / "strategy_params.json"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def load_params():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def simulate_trades(symbol, start_date="2024-01-01", end_date="2026-09-01"):
    """Walk through historical data day by day, simulating Ares V2.1 logic."""
    params = load_params()
    df = load_stock(symbol)
    if df is None or len(df) < 100:
        return []

    df = add_indicators(df)
    df = df.loc[start_date:end_date]
    if len(df) < 50:
        return []

    trades = []
    in_trade = False
    trade = None

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        date_str = str(row.name)[:10]

        if not in_trade:
            signal = _check_entry(row, prev, symbol, params)
            if signal:
                stdev_20 = float(df.iloc[max(0,i-20):i]['Close'].std()) if i >= 20 else float(row['Close']) * 0.05
                stop_loss = float(row['Close']) - (stdev_20 * 2)
                strategy = signal['strategy']
                tp_pct = params.get('tp_momentum', 0.12) if strategy in ('momentum_breakout', 'trend_continuation') else params.get('tp_reversal', 0.08)

                trade = {
                    'symbol': symbol,
                    'strategy': strategy,
                    'trigger': signal['trigger'],
                    'regime': str(row.get('regime', 'range')),
                    'entry_date': date_str,
                    'entry_price': float(row['Close']),
                    'stop_loss': round(stop_loss, 2),
                    'take_profit': round(float(row['Close']) * (1 + tp_pct), 2),
                    'trailing_stop': round(stop_loss, 2),
                    'peak_price': float(row['Close']),
                    'rsi_at_entry': float(row['rsi']),
                    'volume_ratio': float(row.get('vol_ratio', 1.0)),
                    'confluence': signal.get('confluence', 1),
                    'macd_hist': float(row.get('macd_hist', 0)),
                    'sma50_dist': float((row['Close'] - row.get('sma_50', row['Close'])) / row['Close'] * 100) if row.get('sma_50') else 0,
                    'spy_rsi': 0,
                    'holding_days': 0,
                }
                in_trade = True

        elif in_trade and trade:
            price = float(row['Close'])
            rsi = float(row['rsi'])
            trailing_pct = params.get('trailing_stop_pct', 0.08)
            rsi_extreme = params.get('rsi_extreme_high', 90)

            if price > trade['peak_price']:
                trade['peak_price'] = price
                new_ts = price * (1 - trailing_pct)
                if new_ts > trade['trailing_stop']:
                    trade['trailing_stop'] = round(new_ts, 2)

            effective_stop = max(trade['stop_loss'], trade['trailing_stop'])
            exit_reason = None
            exit_price = None

            if price <= effective_stop:
                exit_reason = 'trailing_stop' if trade['trailing_stop'] > trade['stop_loss'] else 'stop_loss'
                exit_price = effective_stop
            elif price >= trade['take_profit']:
                exit_reason = 'take_profit'
                exit_price = trade['take_profit']
            elif rsi > rsi_extreme:
                exit_reason = 'emotional_extreme'
                exit_price = price
            elif bool(row.get('bearish_div', False)) and trade['strategy'] in ('momentum_breakout', 'trend_continuation'):
                exit_reason = 'bearish_divergence'
                exit_price = price
            elif trade['strategy'] == 'mean_reversion' and rsi > 70:
                exit_reason = 'mean_reversion_complete'
                exit_price = price

            if exit_reason:
                trade['exit_date'] = date_str
                trade['exit_price'] = round(exit_price, 2)
                trade['exit_reason'] = exit_reason
                trade['pnl_pct'] = round((exit_price - trade['entry_price']) / trade['entry_price'] * 100, 2)
                entry_dt = datetime.strptime(trade['entry_date'], "%Y-%m-%d")
                exit_dt = datetime.strptime(date_str, "%Y-%m-%d")
                trade['holding_days'] = (exit_dt - entry_dt).days
                trade['peak_after_exit'] = float(df.iloc[i:min(i+30, len(df))]['Close'].max()) if i+1 < len(df) else exit_price
                trade['missed_upside_pct'] = round((trade['peak_after_exit'] - exit_price) / exit_price * 100, 2)
                trade['win'] = 1 if trade['pnl_pct'] > 0 else 0
                trades.append(trade)
                in_trade = False
                trade = None

    return trades

def _check_entry(row, prev, symbol, params):
    """Check if entry conditions are met (simplified Ares V2.1 logic)."""
    regime = str(row.get('regime', 'range'))
    rsi = float(row.get('rsi', 50))
    vol_ratio = float(row.get('vol_ratio', 1.0))
    macd_hist = float(row.get('macd_hist', 0))
    bullish_div = bool(row.get('bullish_div', False))
    hidden_bull_div = bool(row.get('hidden_bullish_div', False))
    bearish_div = bool(row.get('bearish_div', False))
    hidden_bear_div = bool(row.get('hidden_bearish_div', False))
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

        confluence = 0
        trigger = None
        if hidden_bull_div:
            confluence += 1
            trigger = 'hidden_bullish_div'
        if 40 <= rsi <= 50:
            confluence += 1
            if not trigger:
                trigger = 'pullback_buy'
        if macd_hist > 0:
            confluence += 1

        if confluence >= min_confluence and trigger:
            return {'strategy': 'trend_continuation', 'trigger': trigger, 'confluence': confluence}

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

def run_backtest(symbols, start_date="2024-01-01", end_date="2026-09-01"):
    """Run backtest on all symbols and return combined results."""
    all_trades = []

    for i, symbol in enumerate(symbols):
        trades = simulate_trades(symbol, start_date, end_date)
        all_trades.extend(trades)
        if trades:
            wins = sum(1 for t in trades if t['win'])
            print(f"  [{i+1}/{len(symbols)}] {symbol}: {len(trades)} trades, "
                  f"{wins}/{len(trades)} wins")

    return all_trades

def save_results(trades, filename="backtest_trades.csv"):
    """Save trades to CSV for ML training."""
    if not trades:
        print("  No trades to save.")
        return

    df = pd.DataFrame(trades)
    csv_path = RESULTS_DIR / filename
    df.to_csv(csv_path, index=False)
    print(f"\n  Saved {len(trades)} trades to {csv_path}")
    return df

def print_summary(trades):
    """Print backtest performance summary."""
    if not trades:
        print("  No trades to summarize.")
        return

    df = pd.DataFrame(trades)
    wins = df[df['pnl_pct'] > 0]
    losses = df[df['pnl_pct'] <= 0]

    total = len(df)
    win_count = len(wins)
    win_rate = win_count / total * 100

    avg_win = wins['pnl_pct'].mean() if len(wins) > 0 else 0
    avg_loss = losses['pnl_pct'].mean() if len(losses) > 0 else 0
    avg_hold = df['holding_days'].mean()

    profit_factor = (win_rate/100 * avg_win) / ((1 - win_rate/100) * abs(avg_loss)) if avg_loss != 0 else 0

    avg_missed = df['missed_upside_pct'].mean()

    print(f"\n{'='*50}")
    print(f"  ATHENA BACKTEST RESULTS")
    print(f"{'='*50}")
    print(f"  Total trades:      {total}")
    print(f"  Win rate:          {win_count}/{total} ({win_rate:.1f}%)")
    print(f"  Avg win:           {avg_win:+.2f}%")
    print(f"  Avg loss:          {avg_loss:+.2f}%")
    print(f"  Profit factor:     {profit_factor:.2f}")
    print(f"  Avg holding days:  {avg_hold:.1f}")
    print(f"  Avg missed upside: {avg_missed:.2f}% (after exit)")
    print(f"")

    print(f"  BY STRATEGY:")
    for strat, group in df.groupby('strategy'):
        w = group[group['pnl_pct'] > 0]
        wr = len(w) / len(group) * 100
        avg_pnl = group['pnl_pct'].mean()
        print(f"    {strat}: {len(w)}/{len(group)} wins ({wr:.0f}%) | "
              f"Avg P&L: {avg_pnl:+.2f}%")

    print(f"\n  BY EXIT REASON:")
    for reason, group in df.groupby('exit_reason'):
        avg_pnl = group['pnl_pct'].mean()
        print(f"    {reason}: {len(group)} trades | Avg P&L: {avg_pnl:+.2f}%")

    print(f"\n  SHADOW ANALYSIS:")
    print(f"    Avg missed upside after TP:  "
          f"{df[df['exit_reason']=='take_profit']['missed_upside_pct'].mean():.2f}%"
          if len(df[df['exit_reason']=='take_profit']) > 0 else "    No TP exits yet")
    print(f"    Avg missed upside after SL:  "
          f"{df[df['exit_reason']=='stop_loss']['missed_upside_pct'].mean():.2f}%"
          if len(df[df['exit_reason']=='stop_loss']) > 0 else "    No SL exits yet")

    print(f"\n  ML TRAINING DATA:")
    print(f"    Features: {len(df.columns)} columns")
    print(f"    Samples:  {len(df)} trades")
    print(f"    Ready for model training ✅")
    print(f"{'='*50}")
