import numpy as np
import pandas as pd
import pytest

from config import FEATURES_PATH, KR_TICKERS, RAW_NEWS_DIR, RAW_PRICE_DIR, US_TICKERS
from preprocess import compute_features, handle_missing, merge_prices, normalize

ALL_TICKERS = US_TICKERS + list(KR_TICKERS.keys())
ZSCORE_ABS_LIMIT = 6.0
REQUIRED_NEWS_COLUMNS = ["종목명", "제목", "본문요약", "게시일", "원문URL"]


@pytest.fixture(scope="module")
def features():
    if not FEATURES_PATH.exists():
        pytest.skip(f"{FEATURES_PATH} not found; run `python main.py` first")
    return pd.read_parquet(FEATURES_PATH)


@pytest.fixture(scope="module")
def clean_features():
    if not any(RAW_PRICE_DIR.glob("*.csv")):
        pytest.skip(
            f"no price CSVs found in {RAW_PRICE_DIR}; run collect_price.py first"
        )
    prices = merge_prices()
    return handle_missing(compute_features(prices))


def test_all_12_tickers_present(features):
    assert len(ALL_TICKERS) == 12
    missing = [t for t in ALL_TICKERS if f"{t}_return" not in features.columns]
    assert not missing, f"missing tickers in features.parquet: {missing}"


def test_no_missing_values(features):
    assert features.isna().sum().sum() == 0


def test_date_index_is_sorted(features):
    assert features.index.is_monotonic_increasing


def test_normalized_values_within_expected_range(features):
    values = features.to_numpy()
    assert np.isfinite(values).all()
    assert np.abs(values).max() <= ZSCORE_ABS_LIMIT


def test_news_csv_has_required_columns():
    csv_paths = sorted(RAW_NEWS_DIR.glob("*.csv"))
    if not csv_paths:
        pytest.skip(f"no news CSVs found in {RAW_NEWS_DIR}; run collect_news.py first")

    for path in csv_paths:
        df = pd.read_csv(path)
        missing = [c for c in REQUIRED_NEWS_COLUMNS if c not in df.columns]
        assert not missing, f"{path} missing columns: {missing}"


def test_normalize_with_custom_train_end_date(clean_features):
    train_end_date = "2023-01-01"
    normalized, scaler = normalize(clean_features, train_end_date)

    train_mask = clean_features.index < train_end_date
    assert train_mask.sum() > 0
    assert (~train_mask).sum() > 0

    assert len(normalized) == len(clean_features)
    assert np.isfinite(normalized.to_numpy()).all()
    assert not scaler.mean_.isna().any()
    assert not scaler.std_.isna().any()
