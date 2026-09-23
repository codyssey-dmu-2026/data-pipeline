import numpy as np
import pandas as pd
import pytest

from config import FEATURES_PATH, KR_TICKERS, US_TICKERS

ALL_TICKERS = US_TICKERS + list(KR_TICKERS.keys())
ZSCORE_ABS_LIMIT = 6.0


@pytest.fixture(scope="module")
def features():
    if not FEATURES_PATH.exists():
        pytest.skip(f"{FEATURES_PATH} not found; run `python main.py` first")
    return pd.read_parquet(FEATURES_PATH)


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
