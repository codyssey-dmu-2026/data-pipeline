import pandas_ta as ta


def compute_rsi(prices, length=14):
    return ta.rsi(prices, length=length)


def compute_macd(prices, fast=12, slow=26, signal=9):
    macd_df = ta.macd(prices, fast=fast, slow=slow, signal=signal)
    return macd_df[f"MACD_{fast}_{slow}_{signal}"]
