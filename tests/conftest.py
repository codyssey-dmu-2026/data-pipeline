import numpy as np
import pandas as pd
import pytest

import preprocess
from config import KR_TICKERS, US_TICKERS

ALL_TICKERS = US_TICKERS + list(KR_TICKERS.keys())

# 처음 2개 종목은 공통 구간보다 LATE_START_OFFSET만큼 늦게 상장/수집이
# 시작된 것처럼 흉내내어, merge_prices()의 "선행 결측 제거" 로직을 실제로
# 발동시킨다.
LATE_START_OFFSET = 10
# 짝수 인덱스 종목(지연 상장 종목 제외)의 휴장일을 흉내내는 간격.
EVEN_DROP_STEP = 15
EVEN_DROP_PHASE = 20  # LATE_START_OFFSET 이후 첫 드랍 날짜가 되도록 선택
ODD_DROP_STEP = 17
ODD_DROP_PHASE = 11


def _write_synthetic_price_csvs(price_dir, n_days=300, seed=42):
    """merge_prices()가 읽는 것과 동일한 형식의 가짜 가격 CSV를 생성한다.

    - 모든 종목에 랜덤워크 가격(log-return 기반)을 부여한다.
    - 처음 2개 종목은 늦게 시작하게 하여 "공통 구간 이전 선행 결측 제거"를 유발.
    - 나머지 종목은 서로 다른 날짜를 듬성듬성 비워서(시장별 휴장일 불일치)
      ffill 로직과 is_market_open 플래그를 실제로 검증할 수 있게 한다.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)

    for i, ticker in enumerate(ALL_TICKERS):
        log_returns = rng.normal(loc=0.0002, scale=0.01, size=n_days)
        prices = 100 * np.exp(np.cumsum(log_returns))
        series = pd.Series(prices, index=dates, name="adj_close")

        if i < 2:
            series = series.iloc[LATE_START_OFFSET:]
        elif i % 2 == 0:
            drop_dates = dates[EVEN_DROP_PHASE::EVEN_DROP_STEP]
            series = series.drop(index=drop_dates)
        else:
            drop_dates = dates[ODD_DROP_PHASE::ODD_DROP_STEP]
            series = series.drop(index=drop_dates)

        df = series.to_frame()
        df.index.name = "date"
        df.to_csv(price_dir / f"{ticker}.csv")

    return dates


@pytest.fixture(scope="module")
def synthetic_price_dir(tmp_path_factory):
    """merge_prices()가 합성 가격 CSV만 보도록 RAW_PRICE_DIR을 임시로 바꾼다.

    실제 data/raw/prices/*.csv 유무와 무관하게 항상 실행되므로, 새로 clone한
    레포에서도 테스트가 skip되지 않는다.
    """
    price_dir = tmp_path_factory.mktemp("prices")
    dates = _write_synthetic_price_csvs(price_dir)

    original = preprocess.RAW_PRICE_DIR
    preprocess.RAW_PRICE_DIR = price_dir
    try:
        yield dates
    finally:
        preprocess.RAW_PRICE_DIR = original


@pytest.fixture(scope="module")
def synthetic_news_dir(tmp_path_factory):
    """collect_news.py 출력 포맷과 동일한 구조의 가짜 뉴스 CSV를 생성한다."""
    news_dir = tmp_path_factory.mktemp("news")
    df = pd.DataFrame(
        {
            "종목명": ["삼성전자", "SK하이닉스"],
            "제목": ["[테스트] 실적 발표", "[테스트] 신규 투자 공시"],
            "본문요약": ["테스트용 합성 본문 요약입니다." * 1, "테스트용 합성 본문 요약 2."],
            "게시일": ["2024-01-02", "2024-01-03"],
            "원문URL": [
                "https://example.com/news/1",
                "https://example.com/news/2",
            ],
        }
    )
    df.to_csv(news_dir / "005930.csv", index=False)
    return news_dir
