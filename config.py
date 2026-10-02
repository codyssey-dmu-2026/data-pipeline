from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
RAW_PRICE_DIR = RAW_DATA_DIR / "prices"
RAW_NEWS_DIR = RAW_DATA_DIR / "news"

PRICES_PATH = PROCESSED_DATA_DIR / "prices.parquet"
RETURNS_PATH = PROCESSED_DATA_DIR / "returns.parquet"
FEATURES_PATH = PROCESSED_DATA_DIR / "features.parquet"
WALK_FORWARD_MANIFEST_PATH = PROCESSED_DATA_DIR / "walk_forward_manifest.json"
PRICE_MANIFEST_PATH = PROCESSED_DATA_DIR / "manifest.json"

US_TICKERS = [
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "NVDA",
    "TLT",
    "GLD",
    "VNQ",
]

KR_TICKERS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "069500": "KODEX 200",
    "148070": "KODEX 국고채10년",
}

START_DATE = "2018-01-01"
END_DATE = date.today().strftime("%Y-%m-%d")
TRAIN_END_DATE = "2024-01-01"

# 워크포워드 윈도우 (train_start, train_end, test_end). train_end/test_end는
# exclusive: 첫 윈도우는 2018-01-01~2021-12-31로 fit하고 2022년을 테스트한다.
WALK_FORWARD_WINDOWS = [
    ("2018-01-01", "2022-01-01", "2023-01-01"),
    ("2018-01-01", "2023-01-01", "2024-01-01"),
    ("2018-01-01", "2024-01-01", "2025-01-01"),
    ("2018-01-01", "2025-01-01", "2026-01-01"),
]
