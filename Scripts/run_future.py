import ccxt
import pandas as pd
import numpy as np
import time
import ta
from math import floor
from datetime import datetime

# Initialize Binance Futures with API keys
API_KEY = ''
SECRET_KEY = ''

exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'options': {'defaultType': 'future'}  # Use the 'future' market type
})
exchange.set_sandbox_mode(True)

# Fetch historical data
def fetch_binance_futures_data(symbol='BTC/USDT', timeframe='1h', since=None, limit=1000):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

# Feature engineering including ATR
def feature_engineering(df, spans=[7, 21], rsi_window=9):
    df = df.copy()
    for w in spans:
        df[f'EMA_{w}'] = df['Close'].ewm(span=w, adjust=False).mean()
        
    df['MACD'] = ta.trend.macd(df['Close'], window_slow=26, window_fast=12)
    df['MACD_Signal'] = ta.trend.macd_signal(df['Close'], window_slow=26, window_fast=12, window_sign=9)
    
    df['RSI'] = ta.momentum.rsi(df['Close'], window=rsi_window)
    
    df['Bollinger_Upper'] = ta.volatility.bollinger_hband(df['Close'], window=20)
    df['Bollinger_Lower'] = ta.volatility.bollinger_lband(df['Close'], window=20)
    
    df['ATR'] = df['High'].rolling(window=14).max() - df['Low'].rolling(window=14).min()
    
    df.dropna(inplace=True)
    return df

# Generate buy/sell signals
def generate_signals(df):
    df = df.copy()
    df['Signal'] = 'Hold'
    
    # Apply the conditions to set 'Buy' and 'Sell' signals
    df.loc[(df['MACD'] > df['MACD_Signal']), 'Signal'] = 'Buy'
    df.loc[(df['MACD'] < df['MACD_Signal']), 'Signal'] = 'Sell'
    df.Signal = df.Signal.shift(1)
    df.dropna(inplace=True)
    
    return df

# Execute a trade on Binance Futures
def execute_futures_trade(symbol, signal, position_size, leverage=10):
    exchange.fapiPrivatePostLeverage({'symbol': symbol.replace('/', ''), 'leverage': leverage})
    current_price = exchange.fetch_ticker(symbol)['last']
    
    if signal == 'Buy':
        order = exchange.create_market_buy_order(symbol, position_size)
        print(f"Executed Buy Order: {position_size} of {symbol} at {current_price}")
        return position_size * current_price
    
    elif signal == 'Sell':
        balance = exchange.fetch_balance()
        amount_to_sell = floor(balance[symbol.split('/')[0]]['free'])
        order = exchange.create_market_sell_order(symbol, amount_to_sell)
        print(f"Executed Sell Order: {amount_to_sell} of {symbol} at {current_price}")
        return amount_to_sell * current_price

    return 0

# Main loop to check signals and execute trades
def run_futures_trading_bot(symbol='BTC/USDT', timeframe='1h', leverage=10, tpsl_ratio=2, spans=[7, 21], rsi_window=9, invest_percent=0.25, min_buy=5):
    balance = exchange.fetch_balance()
    initial_cash = balance['total']['USDT']
    
    print(f"Initial Cash Balance: {initial_cash} USDT")
    
    in_position = False
    position_side = None
    entry_price = None
    interval_seconds = exchange.parse_timeframe(timeframe)
    
    while True:
        current_time = datetime.utcnow()
        if timeframe[-1] == 'm':
            next_candle_time = (current_time + pd.Timedelta(seconds=interval_seconds)).replace(second=0, microsecond=0)
        elif timeframe[-1] == 'h':
            next_candle_time = (current_time + pd.Timedelta(seconds=interval_seconds)).replace(minute=0, second=0, microsecond=0)
        time_to_sleep = (next_candle_time - current_time).total_seconds()
        
        if time_to_sleep > 0:
            print(f"Waiting for the next candle...\n")
            time.sleep(time_to_sleep)

        df = fetch_binance_futures_data(symbol=symbol, timeframe=timeframe, limit=100)
        df = feature_engineering(df, spans, rsi_window)
        df = generate_signals(df)
        
        last_signal = df['Signal'].iloc[-1]
        last_close = df['Close'].iloc[-1]
        atr_value = df['ATR'].iloc[-1]
        print(f"Last Signal: {last_signal}")
        
        free_cash = balance['free']['USDT']
        
        position_size = ((free_cash * invest_percent) / last_close) * leverage if free_cash > min_buy else (min_buy / last_close) * leverage
        position_size = floor(position_size)
        if last_signal == 'Buy' and not in_position and free_cash > min_buy:
            entry_price = execute_futures_trade(symbol, last_signal, position_size, leverage)
            if entry_price > 0:
                in_position = True
                position_side = 'long'
                stop_loss_price = last_close - 1 * atr_value
                take_profit_price = last_close + tpsl_ratio * atr_value
                print(f"Set TP for LONG at {take_profit_price}")
                print(f"Set SL for LONG at {stop_loss_price}\n")

        elif last_signal == 'Sell' and not in_position and free_cash > min_buy:
            entry_price = execute_futures_trade(symbol, last_signal, position_size, leverage)
            if entry_price > 0:
                in_position = True
                position_side = 'short'
                stop_loss_price = last_close + 1 * atr_value
                take_profit_price = last_close - tpsl_ratio * atr_value
                print(f"Set TP for LONG at {take_profit_price}")
                print(f"Set SL for LONG at {stop_loss_price}\n")

        elif in_position:
            if position_side == 'long':
                if last_close <= stop_loss_price:
                    execute_futures_trade(symbol, 'Sell', position_size, leverage)
                    in_position = False
                    position_side = None
                    print(f"Long position hits SL at {last_close}")
                elif last_close >= take_profit_price:
                    execute_futures_trade(symbol, 'Sell', position_size, leverage)
                    in_position = False
                    position_side = None
                    print(f"Long position hits TP at {last_close}")

            elif position_side == 'short':
                if last_close >= stop_loss_price:
                    execute_futures_trade(symbol, 'Buy', position_size, leverage)
                    in_position = False
                    position_side = None
                    print(f"Short position hits SL at {last_close}")
                elif last_close <= take_profit_price:
                    execute_futures_trade(symbol, 'Buy', position_size, leverage)
                    in_position = False
                    position_side = None
                    print(f"Short position hits TP at {last_close}")

        print(f"Current Cash Balance: {exchange.fetch_balance()['total']['USDT']} USDT")

if __name__ == '__main__':
    run_futures_trading_bot(symbol='XRP/USDT', timeframe='1m', leverage=75, tpsl_ratio=2, spans=[7, 21], invest_percent=0.25, min_buy=5.5)