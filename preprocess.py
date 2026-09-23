import numpy as np
import pandas as pd

from config import (
    FEATURES_PATH,
    RAW_DATA_DIR,
    RAW_PRICE_DIR,
    RETURNS_PATH,
    TRAIN_END_DATE,
)
from indicators import compute_macd, compute_rsi


def merge_prices():
    csv_paths = sorted(RAW_PRICE_DIR.glob("*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"No price CSV files found in {RAW_PRICE_DIR}")

    series_list = []
    for path in csv_paths:
        ticker = path.stem
        df = pd.read_csv(path, index_col="date", parse_dates=True)
        series_list.append(df["adj_close"].rename(ticker))

    merged = pd.concat(series_list, axis=1).sort_index()
    total_rows = len(merged)

    common = merged.dropna(how="any")
    common_rows = len(common)

    dropped_pct = (total_rows - common_rows) / total_rows * 100 if total_rows else 0.0
    print(
        f"merge_prices: {total_rows} rows -> {common_rows} common rows "
        f"({dropped_pct:.2f}% dropped)"
    )

    return common


def compute_features(prices, rsi_length=14):
    features = pd.DataFrame(index=prices.index)
    for ticker in prices.columns:
        price = prices[ticker]
        features[f"{ticker}_return"] = np.log(price / price.shift(1))

        rsi = compute_rsi(price, length=rsi_length)
        rsi.iloc[: rsi_length - 1] = np.nan
        features[f"{ticker}_rsi"] = rsi

        features[f"{ticker}_macd"] = compute_macd(price)
    return features


def detect_outliers(prices, threshold=0.30):
    returns = np.log(prices / prices.shift(1))

    rows = []
    for ticker in prices.columns:
        ticker_returns = returns[ticker]
        flagged_dates = ticker_returns[ticker_returns.abs() > threshold].index

        for flag_date in flagged_dates:
            idx = prices.index.get_loc(flag_date)
            prev_price = prices[ticker].iloc[idx - 1] if idx > 0 else np.nan
            next_price = (
                prices[ticker].iloc[idx + 1] if idx < len(prices) - 1 else np.nan
            )

            other_tickers = [t for t in prices.columns if t != ticker]
            other_returns = returns.loc[flag_date, other_tickers]

            row = {
                "date": flag_date,
                "ticker": ticker,
                "return": ticker_returns.loc[flag_date],
                "prev_price": prev_price,
                "curr_price": prices[ticker].iloc[idx],
                "next_price": next_price,
                "n_other_tickers_also_outlier": int(
                    (other_returns.abs() > threshold).sum()
                ),
            }
            for other_ticker in other_tickers:
                row[f"{other_ticker}_return"] = other_returns[other_ticker]
            rows.append(row)

    report = pd.DataFrame(rows)
    if not report.empty:
        report = report.sort_values(["date", "ticker"]).reset_index(drop=True)

    path = RAW_DATA_DIR / "outlier_report.csv"
    report.to_csv(path, index=False)

    print(
        f"detect_outliers: {len(report)} outlier events found "
        f"(|log return| > {threshold:.0%}), saved to {path}"
    )
    return report


def handle_missing(features):
    before_na = int(features.isna().sum().sum())

    filled = features.ffill()
    cleaned = filled.dropna()

    after_na = int(cleaned.isna().sum().sum())
    print(
        f"handle_missing: {before_na} NaNs before -> {after_na} NaNs after "
        f"({len(features)} -> {len(cleaned)} rows)"
    )
    return cleaned


class ZScoreWinsorizer:
    def __init__(self, n_std=5.0):
        self.n_std = n_std
        self.lower_ = None
        self.upper_ = None
        self.mean_ = None
        self.std_ = None

    def fit(self, train_df):
        mean = train_df.mean()
        std = train_df.std()
        self.lower_ = mean - self.n_std * std
        self.upper_ = mean + self.n_std * std

        clipped = train_df.clip(lower=self.lower_, upper=self.upper_, axis=1)
        self.mean_ = clipped.mean()
        self.std_ = clipped.std()
        return self

    def transform(self, df):
        clipped = df.clip(lower=self.lower_, upper=self.upper_, axis=1)
        return (clipped - self.mean_) / self.std_


def normalize(features, train_end_date, n_std=5.0):
    train = features[features.index < train_end_date]
    if train.empty:
        raise ValueError(f"No training rows found before {train_end_date}")

    scaler = ZScoreWinsorizer(n_std=n_std)
    scaler.fit(train)
    normalized = scaler.transform(features)

    print(
        f"normalize: fit (winsorize ±{n_std} std + z-score) on {len(train)} rows "
        f"before {train_end_date}, transformed all {len(features)} rows"
    )
    return normalized, scaler


def run_pipeline(train_end_date=TRAIN_END_DATE):
    prices = merge_prices()
    features = compute_features(prices)
    clean = handle_missing(features)
    normalized, _scaler = normalize(clean, train_end_date)

    FEATURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_parquet(FEATURES_PATH)
    print(f"run_pipeline: saved features -> {FEATURES_PATH} (shape={normalized.shape})")

    return_cols = [c for c in normalized.columns if c.endswith("_return")]
    returns = normalized[return_cols]
    returns.to_parquet(RETURNS_PATH)
    print(f"run_pipeline: saved returns -> {RETURNS_PATH} (shape={returns.shape})")

    return normalized, returns


if __name__ == "__main__":
    run_pipeline()
