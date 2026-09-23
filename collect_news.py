import html
import logging
import os
import re
import time
from datetime import datetime

import feedparser
import OpenDartReader
import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from config import END_DATE, RAW_NEWS_DIR, START_DATE

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

DART_API_KEY = os.getenv("DART_API_KEY")

REQUEST_DELAY_SEC = 1.0
SUMMARY_LIMIT = 300
USER_AGENT = "Mozilla/5.0 (educational data-pipeline project; +https://github.com/)"

DART_TARGETS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
}
DART_REPORT_KEYWORDS = ("사업보고서", "분기보고서", "반기보고서")

# 네이버 금융 뉴스 API는 더 이상 사용하지 않음: finance.naver.com/news.naver.com은
# robots.txt에서 전체 경로를 Disallow하고 있어(CLAUDE.md의 robots.txt 준수 요건 위반) 사용 불가.
# 대신 CLAUDE.md에 허용 소스로 명시된 한국경제(hankyung.com)의 공개 RSS 피드를 사용한다.
# hankyung.com/robots.txt는 /feed/, /article/ 경로를 막지 않음(2026-09-23 확인).
HANKYUNG_FEED_URL = "https://www.hankyung.com/feed/{category}"
HANKYUNG_FEED_CATEGORIES = ["finance", "economy", "international"]
MAX_ARTICLES_PER_TICKER = 20

NEWS_TARGETS = {
    "AAPL": {"corp_name": "AAPL", "aliases": ["애플", "AAPL"]},
    "MSFT": {"corp_name": "MSFT", "aliases": ["마이크로소프트", "MSFT", "MS"]},
    "NVDA": {"corp_name": "NVDA", "aliases": ["엔비디아", "NVDA"]},
    "005930": {"corp_name": "삼성전자", "aliases": ["삼성전자"]},
    "000660": {"corp_name": "SK하이닉스", "aliases": ["SK하이닉스", "하이닉스"]},
}

COLUMNS = ["종목명", "제목", "본문요약", "게시일", "원문URL"]


def _clean_text(text, limit=None):
    text = re.sub(r"<.*?>", "", text or "")
    text = html.unescape(text).strip()
    return text[:limit] if limit else text


def collect_dart_disclosures(corp_code, corp_name):
    dart = OpenDartReader(DART_API_KEY)
    disclosures = dart.list(corp_code, start=START_DATE, end=END_DATE, kind="A")
    if disclosures is None or disclosures.empty:
        return []

    mask = disclosures["report_nm"].str.contains("|".join(DART_REPORT_KEYWORDS))
    disclosures = disclosures[mask].sort_values("rcept_dt", ascending=False)

    rows = []
    for _, r in disclosures.iterrows():
        rows.append(
            {
                "종목명": corp_name,
                "제목": r["report_nm"],
                "본문요약": _clean_text(r["report_nm"], SUMMARY_LIMIT),
                "게시일": r["rcept_dt"],
                "원문URL": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}",
            }
        )
    return rows


def fetch_feed_entries(category):
    url = HANKYUNG_FEED_URL.format(category=category)
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    response.raise_for_status()
    return feedparser.parse(response.content).entries


def _title_matches(title, aliases):
    for alias in aliases:
        pattern = rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])"
        if re.search(pattern, title):
            return True
    return False


def fetch_article_summary(url, limit=SUMMARY_LIMIT):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    body = soup.find(id="articletxt")
    text = body.get_text(separator=" ", strip=True) if body else ""
    return text[:limit]


def collect_hankyung_news():
    entries = []
    seen_links = set()
    for category in HANKYUNG_FEED_CATEGORIES:
        for entry in fetch_feed_entries(category):
            if entry.link not in seen_links:
                seen_links.add(entry.link)
                entries.append(entry)
        time.sleep(REQUEST_DELAY_SEC)

    rows_by_ticker = {ticker: [] for ticker in NEWS_TARGETS}
    for ticker, target in NEWS_TARGETS.items():
        for entry in entries:
            if len(rows_by_ticker[ticker]) >= MAX_ARTICLES_PER_TICKER:
                break
            if not _title_matches(entry.title, target["aliases"]):
                continue

            summary = fetch_article_summary(entry.link)
            time.sleep(REQUEST_DELAY_SEC)

            pub_date = datetime(*entry.published_parsed[:6])
            rows_by_ticker[ticker].append(
                {
                    "종목명": target["corp_name"],
                    "제목": _clean_text(entry.title),
                    "본문요약": summary,
                    "게시일": pub_date.strftime("%Y-%m-%d"),
                    "원문URL": entry.link,
                }
            )
    return rows_by_ticker


def save_news(ticker, rows):
    df = pd.DataFrame(rows, columns=COLUMNS)
    path = RAW_NEWS_DIR / f"{ticker}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def collect_all():
    RAW_NEWS_DIR.mkdir(parents=True, exist_ok=True)
    collected = {}

    for code, name in DART_TARGETS.items():
        try:
            rows = collect_dart_disclosures(code, name)
            collected.setdefault(code, []).extend(rows)
            print(f"[DART {name}({code})] {len(rows)} disclosures collected")
        except Exception:
            logger.exception(
                "Failed to collect DART disclosures for %s (%s)", code, name
            )
        time.sleep(REQUEST_DELAY_SEC)

    try:
        rows_by_ticker = collect_hankyung_news()
        for ticker, rows in rows_by_ticker.items():
            collected.setdefault(ticker, []).extend(rows)
            print(
                f"[Hankyung RSS {NEWS_TARGETS[ticker]['corp_name']}] {len(rows)} news collected"
            )
    except Exception:
        logger.exception("Failed to collect Hankyung RSS news")

    for ticker, rows in collected.items():
        path = save_news(ticker, rows)
        print(f"saved {len(rows)} rows -> {path}")


if __name__ == "__main__":
    collect_all()
