import numpy as np
import pandas as pd
import ta
import time
from datetime import datetime
import ccxt

# Binance API keys
API_KEY = ''
SECRET_KEY = ''

# Initialize Binance exchange with API keys
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
})
exchange.set_sandbox_mode(True)

# Fetch historical data
def fetch_binance_data(symbol='BTC/USDT', timeframe='1h', since=None, limit=None):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

# Feature engineering
def feature_engineering(df, spans=[7,21], rsi_window=9):
    df = df.copy()
    for w in spans:
        df[f'EMA_{w}'] = df['Close'].ewm(span=w, adjust=False).mean()
    
    df['MACD'] = ta.trend.macd(df['Close'], window_slow=26, window_fast=12)
    df['MACD_Signal'] = ta.trend.macd_signal(df['Close'], window_slow=26, window_fast=12, window_sign=9)
    
    df['RSI'] = ta.momentum.rsi(df['Close'], window=rsi_window)

    df.dropna(inplace=True)
    
    return df

# Generate buy/sell signals
def generate_signals(df):
    df = df.iloc[:-1].copy()
    df['Signal'] = 'Hold'
    
    ema = df.columns[df.columns.str.startswith('EMA')]
    # Apply the conditions to set 'Buy' and 'Sell' signals
    
    df.loc[(df['MACD'].shift(1) > 0) & (df['MACD'] > 0), 'Signal'] = 'Buy'
    df.loc[(df['MACD'].shift(1) < 0) & (df['MACD'] < 0), 'Signal'] = 'Sell'
    df.Signal = df.Signal.shift(1) # Shift the signal to avoid look-ahead bias
    df.dropna(inplace=True)

    return df

# Execute a trade on Binance
def execute_trade(symbol, signal, cash_balance, invest_percent=0.1, min_buy=2):
    # Check the current price
    current_price = exchange.fetch_ticker(symbol)['last']
    
    cash_to_invest = cash_balance * invest_percent
    if signal == 'Buy' and cash_balance > cash_to_invest and cash_balance > min_buy:
        # Calculate the amount to buy
        amount_to_buy = cash_to_invest / current_price if cash_to_invest > min_buy else min_buy / current_price
        
        # order = exchange.create_market_buy_order(symbol, amount_to_buy)
        order = exchange.create_limit_buy_order(symbol, amount_to_buy, current_price)
        print(f"Executed Buy Order: {amount_to_buy} of {symbol} at {current_price}")
        return cash_to_invest
        
    elif signal == 'Sell':
        # Assuming we sell all the holdings
        balance = exchange.fetch_balance()
        amount_to_sell = balance[symbol.split('/')[0]]['free']
        
        if amount_to_sell > 0:
            # order = exchange.create_market_sell_order(symbol, amount_to_sell)
            order = exchange.create_market_sell_order(symbol, amount_to_sell)
            print(f"Executed Sell Order: {amount_to_sell} of {symbol} at {current_price}")
            return -amount_to_sell * current_price
    
    return 0

# Main loop to check signals and execute trades
def run_trading_bot(symbol='BTC/USDT', timeframe='1h', spans=[8,21], rsi_window=9, invest_percent=0.1, min_buy=1):
    # Fetch initial cash balance from Binance
    balance = exchange.fetch_balance()
    cash_balance = balance['USDT']['free']  # Use the free (available) USDT balance as initial cash
    
    print(f"Initial Cash Balance: {cash_balance} USDT")
    
    in_position = False
    
    # Calculate the interval in seconds for the given timeframe
    interval_seconds = exchange.parse_timeframe(timeframe)
    
    while True:
        # Get the current time and the next expected candle time
        current_time = datetime.utcnow()
        if timeframe[-1] == 'm':
            next_candle_time = (current_time + pd.Timedelta(seconds=interval_seconds)).replace(second=0, microsecond=0)
        elif timeframe[-1] == 'h':
            next_candle_time = (current_time + pd.Timedelta(seconds=interval_seconds)).replace(minute=0, second=0, microsecond=0)

        # Sleep until the next candle
        time_to_sleep = (next_candle_time - current_time).total_seconds()
        if time_to_sleep > 0:
            print(f"Waiting for the next candle... Sleeping for {time_to_sleep} seconds.")
            time.sleep(time_to_sleep)
        
        # Fetch the latest data and generate signals
        df = fetch_binance_data(symbol, timeframe)
        df = feature_engineering(df, spans, rsi_window)
        df = generate_signals(df)
        
        last_signal = df['Signal'].iloc[-1]
        print(f"Last Signal: {last_signal}")

        # Execute trades based on the last signal
        # if last_signal == 'Buy' and not in_position:
        if last_signal == 'Buy':
            trade_amount = execute_trade(symbol, last_signal, cash_balance, invest_percent, min_buy)
            if trade_amount > 0:
                cash_balance = exchange.fetch_balance()['USDT']['free']
                in_position = True
                
        elif last_signal == 'Sell' and in_position:
            trade_amount = execute_trade(symbol, last_signal, cash_balance, invest_percent, min_buy)
            if trade_amount < 0:
                cash_balance = exchange.fetch_balance()['USDT']['free']
                in_position = False

        print(f"Current Cash Balance: {cash_balance} USDT")
        
if __name__ == '__main__':
    run_trading_bot(symbol='SOL/USDT', timeframe='1h', spans=[9,18], invest_percent=0.25, min_buy=5.2)