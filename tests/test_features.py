import numpy as np
import pandas as pd
import pytest

import preprocess
from config import KR_TICKERS, US_TICKERS
from preprocess import compute_features, handle_missing, merge_prices, normalize

ALL_TICKERS = US_TICKERS + list(KR_TICKERS.keys())
ZSCORE_ABS_LIMIT = 6.0
RAW_RETURN_STD_LIMIT = 0.2
REQUIRED_NEWS_COLUMNS = ["종목명", "제목", "본문요약", "게시일", "원문URL"]


@pytest.fixture(scope="module")
def clean_features(synthetic_price_dir):
    prices, _is_market_open = merge_prices()
    return handle_missing(compute_features(prices))


@pytest.fixture(scope="module")
def train_end_date(synthetic_price_dir):
    dates = synthetic_price_dir
    return dates[len(dates) // 2]


@pytest.fixture(scope="module")
def features(clean_features, train_end_date):
    normalized, _scaler = normalize(clean_features, train_end_date)
    return normalized


@pytest.fixture(scope="module")
def returns(clean_features):
    return_cols = [c for c in clean_features.columns if c.endswith("_return")]
    return clean_features[return_cols]


def test_all_12_tickers_present(features):
    assert len(ALL_TICKERS) == 12
    missing = [t for t in ALL_TICKERS if f"{t}_return" not in features.columns]
    assert not missing, f"missing tickers in features: {missing}"


def test_no_missing_values(features):
    assert features.isna().sum().sum() == 0


def test_date_index_is_sorted(features):
    assert features.index.is_monotonic_increasing


def test_normalized_values_within_expected_range(features):
    values = features.to_numpy()
    assert np.isfinite(values).all()
    assert np.abs(values).max() <= ZSCORE_ABS_LIMIT


def test_news_csv_has_required_columns(synthetic_news_dir):
    csv_paths = sorted(synthetic_news_dir.glob("*.csv"))
    assert csv_paths, "synthetic_news_dir fixture should have written at least one CSV"

    for path in csv_paths:
        df = pd.read_csv(path)
        missing = [c for c in REQUIRED_NEWS_COLUMNS if c not in df.columns]
        assert not missing, f"{path} missing columns: {missing}"


def test_normalize_with_custom_train_end_date(clean_features, train_end_date):
    normalized, scaler = normalize(clean_features, train_end_date)

    train_mask = clean_features.index < train_end_date
    assert train_mask.sum() > 0
    assert (~train_mask).sum() > 0

    assert len(normalized) == len(clean_features)
    assert np.isfinite(normalized.to_numpy()).all()
    assert not scaler.mean_.isna().any()
    assert not scaler.std_.isna().any()


def test_returns_are_raw_log_returns(returns, features):
    # 정규화된 값이면 std가 ~1이 되므로, 일간 로그 수익률 범위인지 확인한다
    assert returns.index.equals(features.index)
    assert (returns.std() < RAW_RETURN_STD_LIMIT).all()
    assert returns.isna().sum().sum() == 0


def test_merge_prices_forward_fills_holidays(synthetic_price_dir):
    prices, _is_market_open = merge_prices()
    raw = pd.concat(
        [
            pd.read_csv(p, index_col="date", parse_dates=True)["adj_close"]
            for p in preprocess.RAW_PRICE_DIR.glob("*.csv")
        ],
        axis=1,
    )
    first_complete = raw.dropna(how="any").index.min()
    # 공통 시작일 이후의 모든 거래일(한쪽 시장 휴장일 포함)이 보존되어야 한다
    assert len(prices) == (raw.index >= first_complete).sum()


def test_is_market_open_flags_ffilled_holidays(synthetic_price_dir):
    dates = synthetic_price_dir
    prices, is_market_open = merge_prices()

    # conftest의 합성 데이터 생성 규칙: ALL_TICKERS[2](AAPL, 짝수 인덱스)는
    # dates[20::15]에 해당하는 날짜의 데이터가 비어 있어 ffill로 채워진다.
    ticker = ALL_TICKERS[2]
    dropped_date = dates[20]
    open_date = dates[21]

    assert dropped_date in prices.index
    assert is_market_open.loc[dropped_date, f"{ticker}_is_market_open"] == 0
    assert is_market_open.loc[open_date, f"{ticker}_is_market_open"] == 1

    # is_market_open은 prices와 동일한 인덱스를 가져야 한다
    assert is_market_open.index.equals(prices.index)
