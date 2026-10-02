import logging

import collect_news
import collect_price
from preprocess import detect_outliers, merge_prices, run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_detect_outliers():
    prices, _is_market_open = merge_prices()
    return detect_outliers(prices)


PIPELINE_STEPS = [
    ("가격 수집 (collect_price)", collect_price.collect_all),
    ("전처리 파이프라인 (preprocess.run_pipeline)", run_pipeline),
    ("뉴스/공시 수집 (collect_news)", collect_news.collect_all),
    ("이상치 탐지 (detect_outliers)", run_detect_outliers),
]


def main():
    results = []
    for name, step in PIPELINE_STEPS:
        print(f"\n=== [{name}] 시작 ===")
        try:
            step()
            print(f"=== [{name}] 성공 ===")
            results.append((name, "SUCCESS"))
        except Exception:
            logger.exception("[%s] 실패", name)
            print(f"=== [{name}] 실패 (아래 로그 참고, 다음 단계로 계속 진행) ===")
            results.append((name, "FAILED"))

    print("\n=== 파이프라인 실행 요약 ===")
    for name, status in results:
        print(f"- {name}: {status}")


if __name__ == "__main__":
    main()
