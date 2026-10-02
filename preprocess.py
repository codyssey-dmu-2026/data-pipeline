import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    FEATURES_PATH,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    RAW_PRICE_DIR,
    RETURNS_PATH,
    TRAIN_END_DATE,
    WALK_FORWARD_MANIFEST_PATH,
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
    before_na = int(merged.isna().sum().sum())

    # 한국/미국 휴장일은 직전 종가로 채운다 (ffill만 사용, 미래 값으로 채우지 않음).
    # ffill 후에도 남는 결측치(일부 종목의 상장/수집 시작 이전 구간)만 제거한다.
    filled = merged.ffill()
    filled_na = before_na - int(filled.isna().sum().sum())
    common = filled.dropna(how="any")
    common_rows = len(common)

    print(
        f"merge_prices: {total_rows} rows, {filled_na} NaNs forward-filled -> "
        f"{common_rows} rows ({total_rows - common_rows} leading rows dropped)"
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

        # MACD는 가격 수준에 비례하므로 가격으로 나눠 스케일을 제거한다
        features[f"{ticker}_macd"] = compute_macd(price) / price
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


def _scaler_manifest_entry(
    scaler, window_idx, train_start, train_end, test_end, columns, path
):
    return {
        "window": window_idx,
        "path": str(path),
        "train_start": str(pd.Timestamp(train_start).date()),
        "train_end": str(pd.Timestamp(train_end).date()),
        "test_end": str(pd.Timestamp(test_end).date()),
        "n_std": scaler.n_std,
        "columns": list(columns),
        "mean": scaler.mean_.to_dict(),
        "std": scaler.std_.to_dict(),
        "lower": scaler.lower_.to_dict(),
        "upper": scaler.upper_.to_dict(),
    }


def normalize_walk_forward(
    features,
    windows,
    n_std=5.0,
    output_dir=PROCESSED_DATA_DIR,
    manifest_path=WALK_FORWARD_MANIFEST_PATH,
):
    """워크포워드 윈도우별로 각각 독립적인 fit/transform을 수행한다.

    windows: (train_start, train_end, test_end) 튜플 리스트.
    각 윈도우는 [train_start, train_end) 구간만으로 평균/표준편차/winsorize
    기준을 계산(fit)하고, [train_start, test_end) 구간에 transform을 적용한다
    (다른 윈도우의 train 구간 데이터가 섞이지 않도록 fit은 윈도우별로 독립).
    결과는 윈도우별 parquet(features_window{n}.parquet)로 저장하고,
    통계량/구간/컬럼 순서는 manifest_path에 JSON으로 저장해 추론 시 재사용한다.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(manifest_path)

    results = []
    manifest = {"n_std": n_std, "windows": []}

    for i, (train_start, train_end, test_end) in enumerate(windows, start=1):
        train = features[(features.index >= train_start) & (features.index < train_end)]
        if train.empty:
            raise ValueError(
                f"window {i}: no training rows in [{train_start}, {train_end})"
            )

        window_slice = features[
            (features.index >= train_start) & (features.index < test_end)
        ]

        scaler = ZScoreWinsorizer(n_std=n_std)
        scaler.fit(train)
        normalized = scaler.transform(window_slice)

        out_path = output_dir / f"features_window{i}.parquet"
        normalized.to_parquet(out_path)

        manifest["windows"].append(
            _scaler_manifest_entry(
                scaler, i, train_start, train_end, test_end, features.columns, out_path
            )
        )

        print(
            f"normalize_walk_forward: window {i} fit (winsorize ±{n_std} std + "
            f"z-score) on {len(train)} rows [{train_start}, {train_end}), "
            f"transformed {len(normalized)} rows [{train_start}, {test_end}) -> {out_path}"
        )

        results.append((normalized, scaler))

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(
        f"normalize_walk_forward: saved manifest ({len(windows)} windows) -> {manifest_path}"
    )

    return results, manifest


def run_pipeline(train_end_date=TRAIN_END_DATE):
    prices = merge_prices()
    features = compute_features(prices)
    clean = handle_missing(features)
    normalized, _scaler = normalize(clean, train_end_date)

    FEATURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_parquet(FEATURES_PATH)
    print(f"run_pipeline: saved features -> {FEATURES_PATH} (shape={normalized.shape})")

    # returns.parquet은 RL 보상 계산용이므로 정규화 전 원래 로그 수익률을 저장한다
    return_cols = [c for c in clean.columns if c.endswith("_return")]
    returns = clean[return_cols]
    returns.to_parquet(RETURNS_PATH)
    print(f"run_pipeline: saved returns -> {RETURNS_PATH} (shape={returns.shape})")

    return normalized, returns


if __name__ == "__main__":
    run_pipeline()
