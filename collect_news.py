import html
import logging
import os
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import feedparser
import OpenDartReader
import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from config import END_DATE, RAW_NEWS_DIR, START_DATE

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DART_API_KEY = os.getenv("DART_API_KEY")

REQUEST_DELAY_SEC = 1.0
SUMMARY_LIMIT = 300
USER_AGENT = "Mozilla/5.0 (educational data-pipeline project; +https://github.com/)"

DART_TARGETS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
}
# DART 공시유형 코드(OpenDartReader.list의 kind): A=정기공시, B=주요사항보고,
# I=거래소공시(수시공시). DART API는 kind를 한 번에 하나만 받으므로 종목당
# 여러 번 호출해서 합친다.
DART_PERIODIC_KIND = "A"
DART_MATERIAL_EVENT_KIND = "B"
DART_TIMELY_DISCLOSURE_KIND = "I"
DART_KINDS = (DART_PERIODIC_KIND, DART_MATERIAL_EVENT_KIND, DART_TIMELY_DISCLOSURE_KIND)
# 정기공시(A)는 사업/분기/반기보고서만 남긴다(그 외 잡다한 정기 서류 제외).
# B/I는 그 자체가 이미 원하는 카테고리라 별도 키워드 필터가 필요 없다.
DART_REPORT_KEYWORDS = ("사업보고서", "분기보고서", "반기보고서")

# SEC EDGAR는 요청자를 식별할 수 있는 이메일이 포함된 User-Agent를 요구한다
# (https://www.sec.gov/os/webmaster-faq#developers). .env의 SEC_EDGAR_CONTACT_EMAIL로 설정.
SEC_CONTACT_EMAIL = os.getenv("SEC_EDGAR_CONTACT_EMAIL")
SEC_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# filings.recent가 다 못 담은 과거분이 올라가는 페이지. filings.files[i].name이
# 파일명을 알려준다(예: CIK0000789019-submissions-001.json).
SEC_SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
SEC_FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{doc}"
SEC_TARGETS = {"AAPL": "AAPL", "MSFT": "MSFT", "NVDA": "NVDA"}
SEC_FORM_TYPES = ("10-K", "10-Q", "8-K")

_sec_cik_cache = None

# 네이버 금융 뉴스 API는 더 이상 사용하지 않음: finance.naver.com/news.naver.com은
# robots.txt에서 전체 경로를 Disallow하고 있어(CLAUDE.md의 robots.txt 준수 요건 위반) 사용 불가.
# 대신 CLAUDE.md에 허용 소스로 명시된 한국경제(hankyung.com)의 공개 RSS 피드를 사용한다.
# hankyung.com/robots.txt는 /feed/, /article/ 경로를 막지 않음(2026-09-23 확인).
HANKYUNG_FEED_URL = "https://www.hankyung.com/feed/{category}"
HANKYUNG_FEED_CATEGORIES = ["finance", "economy", "international"]
MAX_ARTICLES_PER_TICKER = 20

NEWS_TARGETS = {
    # "MS"는 모건스탠리/MS경영대학원 등과 겹쳐 오탐이 많아 별칭에서 제외.
    "AAPL": {"corp_name": "AAPL", "aliases": ["애플", "AAPL"]},
    "MSFT": {"corp_name": "MSFT", "aliases": ["마이크로소프트", "MSFT"]},
    "NVDA": {"corp_name": "NVDA", "aliases": ["엔비디아", "NVDA"]},
    "005930": {"corp_name": "삼성전자", "aliases": ["삼성전자"]},
    "000660": {"corp_name": "SK하이닉스", "aliases": ["SK하이닉스", "하이닉스"]},
}

COLUMNS = ["종목명", "제목", "본문요약", "게시일", "원문URL"]

KST = ZoneInfo("Asia/Seoul")


def _clean_text(text, limit=None):
    text = re.sub(r"<.*?>", "", text or "")
    text = html.unescape(text).strip()
    return text[:limit] if limit else text


def _to_kst_iso(dt):
    """소스마다 다른 날짜/시각 표현을 KST 기준 ISO 8601 문자열로 통일한다.

    tz 정보가 없는 datetime(DART rcept_dt처럼 날짜만 있는 값)은 이미 KST
    벽시계 값이라고 간주해 그대로 KST로 태깅한다. tz-aware datetime(SEC
    acceptanceDateTime의 UTC, RSS published_parsed의 UTC 정규화 값 등)은
    KST로 변환한다. 초 단위까지만 남겨(micro/milli초 버림) 소스 간 형식을
    통일한다. 예: 2026-09-29T09:35:51+09:00
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).replace(microsecond=0).isoformat()


def collect_dart_disclosures(corp_code, corp_name):
    dart = OpenDartReader(DART_API_KEY)

    rows = []
    for kind in DART_KINDS:
        disclosures = dart.list(corp_code, start=START_DATE, end=END_DATE, kind=kind)
        time.sleep(REQUEST_DELAY_SEC)
        if disclosures is None or disclosures.empty:
            continue

        if kind == DART_PERIODIC_KIND:
            mask = disclosures["report_nm"].str.contains("|".join(DART_REPORT_KEYWORDS))
            disclosures = disclosures[mask]

        for _, r in disclosures.iterrows():
            # DART list API는 접수일자(rcept_dt, YYYYMMDD)만 주고 접수 시각은 주지
            # 않으므로, 해당 날짜의 00:00:00 KST로 채운다(시각 정밀도 없음).
            published_at = _to_kst_iso(datetime.strptime(r["rcept_dt"], "%Y%m%d"))
            rows.append(
                {
                    "종목명": corp_name,
                    "제목": r["report_nm"],
                    "본문요약": _clean_text(r["report_nm"], SUMMARY_LIMIT),
                    "게시일": published_at,
                    "원문URL": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}",
                }
            )

    rows.sort(key=lambda row: row["게시일"], reverse=True)
    return rows


def _sec_headers():
    if not SEC_CONTACT_EMAIL:
        logger.warning(
            "SEC_EDGAR_CONTACT_EMAIL not set in .env; SEC EDGAR requires a real "
            "contact email in the User-Agent header, requests may be blocked."
        )
    email = SEC_CONTACT_EMAIL or "unknown@example.com"
    return {"User-Agent": f"data-pipeline educational project ({email})"}


def _get_cik(ticker):
    global _sec_cik_cache
    if _sec_cik_cache is None:
        response = requests.get(SEC_TICKER_CIK_URL, headers=_sec_headers(), timeout=10)
        response.raise_for_status()
        _sec_cik_cache = {row["ticker"]: row["cik_str"] for row in response.json().values()}
    cik = _sec_cik_cache.get(ticker)
    if cik is None:
        raise ValueError(f"CIK not found for ticker {ticker}")
    return cik


def _rows_from_sec_filings(filings, ticker, cik):
    """filings.recent 또는 filings.files의 한 페이지(평탄한 병렬 배열 dict)에서
    행을 추출한다. 두 구조 모두 동일한 키(form/filingDate/accessionNumber/...)를
    가진다."""
    acceptance_times = filings.get("acceptanceDateTime") or []

    rows = []
    for i, form in enumerate(filings["form"]):
        filing_date = filings["filingDate"][i]
        if form not in SEC_FORM_TYPES or filing_date < START_DATE:
            continue

        # acceptanceDateTime(UTC, 분/초 단위)이 있으면 그걸 쓰고, 없는 건은
        # filingDate(날짜만)를 00:00:00 KST로 채운다.
        acceptance = acceptance_times[i] if i < len(acceptance_times) else None
        if acceptance:
            published_at = _to_kst_iso(datetime.fromisoformat(acceptance))
        else:
            published_at = _to_kst_iso(datetime.strptime(filing_date, "%Y-%m-%d"))

        accession_nodash = filings["accessionNumber"][i].replace("-", "")
        doc_url = SEC_FILING_URL.format(
            cik=cik, accession_nodash=accession_nodash, doc=filings["primaryDocument"][i]
        )
        title = f"{form} ({filings['reportDate'][i]})"
        rows.append(
            {
                "종목명": ticker,
                "제목": title,
                "본문요약": _clean_text(title, SUMMARY_LIMIT),
                "게시일": published_at,
                "원문URL": doc_url,
            }
        )
    return rows


def collect_sec_filings(ticker):
    """SEC EDGAR 제출 내역을 수집한다.

    filings.recent는 최근 최대 1000건 정도만 담고 있어서, 공시가 많은 회사는
    START_DATE까지 거슬러 올라가지 못하고 중간에 끊길 수 있다(예: MSFT/NVDA는
    recent가 2020년 중반부터만 커버해 2018~2020 구간의 10-K/10-Q가 통째로
    빠짐). recent의 가장 오래된 filingDate가 START_DATE보다 늦으면,
    filings.files에 있는 과거 페이지도 필요한 범위만큼 추가로 읽는다.
    """
    cik = _get_cik(ticker)
    url = SEC_SUBMISSIONS_URL.format(cik=cik)
    response = requests.get(url, headers=_sec_headers(), timeout=10)
    response.raise_for_status()
    filings = response.json()["filings"]

    rows = _rows_from_sec_filings(filings["recent"], ticker, cik)

    earliest_recent = min(filings["recent"]["filingDate"], default=None)
    if earliest_recent is not None and earliest_recent > START_DATE:
        for file_meta in filings.get("files", []):
            if file_meta["filingTo"] < START_DATE:
                continue  # 이 페이지 전체가 START_DATE 이전 -> 요청할 필요 없음
            time.sleep(REQUEST_DELAY_SEC)
            file_url = SEC_SUBMISSIONS_FILE_URL.format(name=file_meta["name"])
            file_response = requests.get(file_url, headers=_sec_headers(), timeout=10)
            file_response.raise_for_status()
            rows.extend(_rows_from_sec_filings(file_response.json(), ticker, cik))

    return rows


def fetch_feed_entries(category):
    url = HANKYUNG_FEED_URL.format(category=category)
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    response.raise_for_status()
    return feedparser.parse(response.content).entries


_WORD_CHAR_CLASS = r"[A-Za-z가-힣]"


def _title_matches(title, aliases):
    """별칭이 제목에서 독립된 단어로 등장할 때만 매칭한다.

    경계 문자 클래스에 영문뿐 아니라 한글 음절(가-힣)도 포함한다. 그래서
    "애플" 별칭이 "애플리케이션"(뒤에 한글 '리' 연속) 안에 묻혀 있거나
    "파인애플"(앞에 한글 '인' 연속) 끝에 붙어 있는 경우는 매칭에서 제외된다.
    다만 이 규칙은 "애플이", "엔비디아는"처럼 별칭 뒤에 조사가 공백 없이
    바로 붙는 정상적인 멘션도 함께 걸러낸다는 트레이드오프가 있다.
    """
    for alias in aliases:
        pattern = rf"(?<!{_WORD_CHAR_CLASS}){re.escape(alias)}(?!{_WORD_CHAR_CLASS})"
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

            # feedparser의 published_parsed는 UTC로 정규화된 struct_time이다.
            pub_date_utc = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            rows_by_ticker[ticker].append(
                {
                    "종목명": target["corp_name"],
                    "제목": _clean_text(entry.title),
                    "본문요약": summary,
                    "게시일": _to_kst_iso(pub_date_utc),
                    "원문URL": entry.link,
                }
            )
    return rows_by_ticker


def save_news(ticker, rows):
    """기존 CSV에 새 수집 결과를 덧붙이고, 원문URL 기준으로 중복을 제거한다.

    원문URL이 DART rcept_no/SEC accession number/기사 링크로부터 만들어지는
    고유 식별자이므로 dedup 키로 쓴다. 같은 URL이 다시 수집되면(예: 매일 실행
    시 최근 공시/기사가 재수집되는 경우) 최신 수집 결과로 덮어쓴다.
    """
    path = RAW_NEWS_DIR / f"{ticker}.csv"
    new_df = pd.DataFrame(rows, columns=COLUMNS)

    if path.exists():
        existing_df = pd.read_csv(path, encoding="utf-8-sig")
    else:
        existing_df = pd.DataFrame(columns=COLUMNS)

    combined = pd.concat([existing_df, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["원문URL"], keep="last").reset_index(drop=True)
    n_duplicates = len(existing_df) + len(new_df) - len(combined)

    combined.to_csv(path, index=False, encoding="utf-8-sig")
    print(
        f"save_news({ticker}): +{len(new_df)} new rows, {n_duplicates} duplicates "
        f"removed -> {len(combined)} total rows"
    )
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
            logger.exception("Failed to collect DART disclosures for %s (%s)", code, name)
        time.sleep(REQUEST_DELAY_SEC)

    for ticker, name in SEC_TARGETS.items():
        try:
            rows = collect_sec_filings(ticker)
            collected.setdefault(ticker, []).extend(rows)
            print(f"[SEC EDGAR {name}] {len(rows)} filings collected")
        except Exception:
            logger.exception("Failed to collect SEC EDGAR filings for %s", ticker)
        time.sleep(REQUEST_DELAY_SEC)

    try:
        rows_by_ticker = collect_hankyung_news()
        for ticker, rows in rows_by_ticker.items():
            collected.setdefault(ticker, []).extend(rows)
            print(f"[Hankyung RSS {NEWS_TARGETS[ticker]['corp_name']}] {len(rows)} news collected")
    except Exception:
        logger.exception("Failed to collect Hankyung RSS news")

    for ticker, rows in collected.items():
        path = save_news(ticker, rows)
        print(f"saved {len(rows)} rows -> {path}")


if __name__ == "__main__":
    collect_all()
