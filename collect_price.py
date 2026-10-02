import json
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from pykrx import stock

from config import (
    KR_TICKERS,
    PRICE_MANIFEST_PATH,
    RAW_PRICE_DIR,
    START_DATE,
    US_TICKERS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

US_MARKET_TZ = ZoneInfo("America/New_York")
US_MARKET_CLOSE = time(16, 0)
KR_MARKET_TZ = ZoneInfo("Asia/Seoul")
KR_MARKET_CLOSE = time(15, 30)


def _last_completed_trading_day(tz, close_time, now=None):
    """주말을 제외한, 해당 시장에서 장이 이미 마감된 마지막 거래일을 반환한다.

    거래소 공식 휴장일 캘린더는 반영하지 않는다. 휴장일은 애초에 데이터가
    존재하지 않으므로, 당일을 범위에 포함시켜도 미완료(장중) 데이터가 섞일
    위험은 없다 — 이 함수가 막는 것은 "아직 장이 끝나지 않은 당일"뿐이다.
    """
    now = (now or datetime.now(tz)).astimezone(tz)
    candidate = now.date()
    if now.time() < close_time:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:  # 5=Sat, 6=Sun
        candidate -= timedelta(days=1)
    return candidate


def get_us_end_date(now=None):
    return _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now)


def get_kr_end_date(now=None):
    return _last_completed_trading_day(KR_MARKET_TZ, KR_MARKET_CLOSE, now)


def collect_us_price(ticker, end_date):
    # yfinance의 end는 exclusive이므로, end_date를 포함시키려면 +1일을 넘겨야 한다.
    end_exclusive = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=START_DATE, end=end_exclusive, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"{ticker}: no data returned")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    adj_close = df[["Close"]].rename(columns={"Close": "adj_close"})
    adj_close.index.name = "date"
    return adj_close


def collect_kr_price(ticker, end_date):
    # pykrx의 todate는 inclusive이므로 end_date를 그대로 넘긴다.
    # 주의: adjusted=True는 KRX가 아니라 네이버 금융의 일별 시세를 그대로 가져온다
    # (pykrx 내부적으로 naver.get_market_ohlcv_by_date에 위임). 무상증자/액면분할
    # 같은 주식수 변동은 네이버 차트 자체가 과거값을 되돌려 반영하지만, 현금 배당이나
    # ETF 분배금(148070 등)은 반영되지 않는다 — 배당(분배)지급일에 가격이 그만큼
    # 빠지는 것이 그대로 로그 수익률에 잡힌다. yfinance(auto_adjust=True)는 미국
    # 종목의 현금배당을 반영하므로, 한국/미국 수익률의 "배당 처리 방식"이 다르다는
    # 점을 RL/RAG 쪽에 공유해야 한다.
    fromdate = START_DATE.replace("-", "")
    todate = end_date.strftime("%Y%m%d")
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


def _record_manifest_version(collected_at, us_end_date, kr_end_date):
    PRICE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    if PRICE_MANIFEST_PATH.exists():
        with open(PRICE_MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {"versions": []}

    manifest["versions"].append(
        {
            "version": len(manifest["versions"]) + 1,
            "collected_at": collected_at.isoformat(),
            "start_date": START_DATE,
            "us_end_date": us_end_date.isoformat(),
            "kr_end_date": kr_end_date.isoformat(),
        }
    )

    with open(PRICE_MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info(
        "manifest: recorded version %d -> %s",
        manifest["versions"][-1]["version"],
        PRICE_MANIFEST_PATH,
    )


def collect_all():
    RAW_PRICE_DIR.mkdir(parents=True, exist_ok=True)

    collected_at = datetime.now(timezone.utc)
    us_end_date = get_us_end_date()
    kr_end_date = get_kr_end_date()
    logger.info("US end_date=%s (America/New_York 16:00 마감 기준)", us_end_date)
    logger.info("KR end_date=%s (Asia/Seoul 15:30 마감 기준)", kr_end_date)

    for ticker in US_TICKERS:
        try:
            df = collect_us_price(ticker, us_end_date)
            save_price(ticker, df)
            report(ticker, df)
        except Exception:
            logger.exception("Failed to collect US ticker %s", ticker)

    for ticker, name in KR_TICKERS.items():
        try:
            df = collect_kr_price(ticker, kr_end_date)
            save_price(ticker, df)
            report(f"{ticker} ({name})", df)
        except Exception:
            logger.exception("Failed to collect KR ticker %s (%s)", ticker, name)

    _record_manifest_version(collected_at, us_end_date, kr_end_date)


if __name__ == "__main__":
    collect_all()
