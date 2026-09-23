import logging

import pandas as pd
import yfinance as yf
from pykrx import stock

from config import END_DATE, KR_TICKERS, RAW_PRICE_DIR, START_DATE, US_TICKERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def collect_us_price(ticker):
    df = yf.download(ticker, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"{ticker}: no data returned")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    adj_close = df[["Close"]].rename(columns={"Close": "adj_close"})
    adj_close.index.name = "date"
    return adj_close


def collect_kr_price(ticker):
    fromdate = START_DATE.replace("-", "")
    todate = END_DATE.replace("-", "")
    df = stock.get_market_ohlcv(fromdate, todate, ticker, adjusted=True)
    if df.empty:
        raise ValueError(f"{ticker}: no data returned")
    adj_close = df[["종가"]].rename(columns={"종가": "adj_close"})
    adj_close.index.name = "date"
    return adj_close


def save_price(ticker, df):
    path = RAW_PRICE_DIR / f"{ticker}.csv"
    df.to_csv(path)
    return path


def report(label, df):
    start = df.index.min().strftime("%Y-%m-%d")
    end = df.index.max().strftime("%Y-%m-%d")
    print(f"[{label}] rows={len(df)}, start={start}, end={end}")


def collect_all():
    RAW_PRICE_DIR.mkdir(parents=True, exist_ok=True)

    for ticker in US_TICKERS:
        try:
            df = collect_us_price(ticker)
            save_price(ticker, df)
            report(ticker, df)
        except Exception:
            logger.exception("Failed to collect US ticker %s", ticker)

    for ticker, name in KR_TICKERS.items():
        try:
            df = collect_kr_price(ticker)
            save_price(ticker, df)
            report(f"{ticker} ({name})", df)
        except Exception:
            logger.exception("Failed to collect KR ticker %s (%s)", ticker, name)


if __name__ == "__main__":
    collect_all()
