# Data Pipeline

에이전틱 RAG + 강화학습 기반 로보어드바이저 프로젝트의 **Data Pipeline** 파트다. 가격·뉴스·공시 원천 데이터를 수집·전처리해서 RL(PPO) 엔진과 RAG 에이전트에 각각 공급한다. 프로젝트 전체 요건은 [CLAUDE.md](./CLAUDE.md) 참고.

## 폴더 구조

```
data_pipeline/
├── config.py           # 자산 유니버스, 기간, 경로 등 상수 정의
├── collect_price.py     # yfinance/pykrx로 가격 수집
├── collect_news.py      # DART 공시 + 한국경제 RSS 뉴스 수집
├── preprocess.py        # 병합/피처/이상치/결측치/정규화/파이프라인 실행
├── indicators.py        # RSI, MACD 계산 (pandas-ta)
├── utils.py
├── main.py               # 가격수집 → 전처리 → 뉴스/공시수집 → 이상치탐지 순서로 실행하는 엔트리포인트
├── data/
│   ├── raw/
│   │   ├── prices/       # 종목별 원본 수정종가 CSV (12개)
│   │   └── news/         # 종목별 뉴스·공시 CSV
│   │   └── outlier_report.csv  # detect_outliers() 결과 (main.py 마지막 단계)
│   └── processed/
│       ├── returns.parquet   # 정규화 전 로그수익률 (RL 보상 계산용)
│       └── features.parquet  # 정규화된 피처 36개 + is_market_open 플래그 12개 = 48컬럼
├── tests/
│   └── test_features.py  # features.parquet 무결성 테스트
├── .env.example          # DART_API_KEY, SEC_EDGAR_CONTACT_EMAIL 환경변수 템플릿
├── requirements.txt
└── README.md
```

## 실행 방법

```bash
# 1. 가상환경 준비 (Python 3.12 권장 — 아래 "알려진 한계점" 참고)
python3.12 -m venv .venv
source .venv/bin/activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. .env 준비 (절대 git에 커밋하지 않음)
cp .env.example .env
# .env를 열어 두 값을 채운다
#   DART_API_KEY             DART OpenAPI 인증키
#   SEC_EDGAR_CONTACT_EMAIL  본인 연락처 이메일. SEC EDGAR는 요청 User-Agent에 실제 연락처를
#                            요구한다. 비워 두면 경고만 뜨고 unknown@example.com으로 요청된다.

# 4. 전체 파이프라인 실행 (가격수집 → 전처리 → 뉴스/공시수집 → 이상치탐지)
python main.py

# 5. 테스트
python -m pytest
```

`main.py`는 가격수집(`collect_price.collect_all()`) → 전처리(`preprocess.run_pipeline()`) → 뉴스/공시수집(`collect_news.collect_all()`) → 이상치탐지(`detect_outliers()`) 순서로 실행한다. 한 단계가 실패해도 로그를 남기고 다음 단계로 넘어가며, 마지막에 단계별 성공/실패 요약을 출력한다. 각 단계는 `python collect_price.py`, `python collect_news.py`처럼 따로 실행할 수도 있다.

## 자산 유니버스 (12개) 및 선정 근거

| 티커/코드 | 종목명 | 자산군 | 선정 근거 |
|---|---|---|---|
| SPY | S&P500 ETF | 미국 대형주 지수 | 미국 증시 전체를 대표하는 벤치마크 |
| QQQ | 나스닥100 ETF | 미국 기술주 지수 | 빅테크 중심 성장주 익스포저 |
| AAPL | Apple | 미국 개별주 | 시총 최상위 빅테크, 소비자 기술 대표 |
| MSFT | Microsoft | 미국 개별주 | 시총 최상위 빅테크, 클라우드/AI 대표 |
| NVDA | NVIDIA | 미국 개별주 | AI/반도체 테마 대표, 최근 변동성·성장성 높음 |
| TLT | 미국 장기국채 ETF | 채권 | 주식과 역상관 경향, 금리 리스크 헤지 자산 |
| GLD | 금 ETF | 원자재/안전자산 | 인플레이션·위기 헤지, 낮은 주식 상관성 |
| VNQ | 리츠 ETF | 부동산 | 금리에 민감한 대체자산, 분산 효과 |
| 005930 | 삼성전자 | 한국 개별주 | 코스피 대표 반도체·전자 기업 |
| 000660 | SK하이닉스 | 한국 개별주 | 메모리 반도체 대표, 글로벌 반도체 사이클 연동 |
| 069500 | KODEX 200 | 한국 지수 ETF | 코스피200 추종, 한국 대형주 전체 익스포저 |
| 148070 | KODEX 국고채10년 | 한국 채권 ETF | 한국 금리 리스크/채권 익스포저 |

미국 8종목 + 한국 4종목으로 자산군(주식/채권/원자재/리츠)과 지역(미국/한국)을 분산해, RL 에이전트가 상관관계가 낮은 자산들 사이에서 배분을 학습할 수 있게 구성했다.

## 전처리 파이프라인 단계

전체 흐름은 아래와 같다. 1번은 `collect_price.py`, 4번은 `main.py`가 따로 호출하고, 나머지는 `preprocess.py`의 `run_pipeline()`이 실행한다.

1. **수집** (`collect_price.py`) — yfinance(`auto_adjust=True`)/pykrx(`adjusted=True`)로 종목별 수정종가를 `data/raw/prices/*.csv`에 저장.
2. **정합성** (`merge_prices()`) — 12개 종목 CSV를 날짜 기준으로 모두 합친 뒤(intersection이 아님), 한쪽 시장만 쉬는 휴장일은 직전 종가로 forward-fill해 전체 날짜를 유지한다. 미래 값으로 과거를 채우지 않으며, ffill 후에도 남는 결측(일부 종목의 수집 시작 이전 구간)만 앞에서 제거한다. 날짜·종목별 실제 거래 여부는 `{ticker}_is_market_open`(1/0) 플래그로 함께 만든다. 병합 전후 행 수와 ffill한 결측 수를 print로 확인할 수 있다.
3. **지표** (`compute_features()`) — 종목별 로그수익률(`{ticker}_return`), RSI 14(`{ticker}_rsi`, `indicators.py`), MACD 12/26/9(`{ticker}_macd`)를 계산한다. `pandas-ta` RSI가 워밍업 구간(첫 13행)에도 100 같은 의미 없는 값을 채우는 문제를 확인해서, 해당 구간은 수동으로 NaN 처리한다.
4. **이상치 검증** (`detect_outliers()`, `main.py` 마지막 단계) — 절대 로그수익률이 30%를 넘는 날짜를 종목별로 찾아 전/후일 가격, 같은 날 다른 11개 종목 수익률과 함께 `data/raw/outlier_report.csv`에 저장한다. 자동으로 값을 수정/삭제하지 않고 리포트만 생성해서 사람이 직접 검토(여러 종목이 동시에 튀면 시장 이벤트, 한 종목만 튀면 데이터 오류 의심)하도록 한다.
5. **결측치 처리** (`handle_missing()`) — `ffill()`로 먼저 채우고, 그래도 남는 행(지표 워밍업 구간 등)은 `dropna()`로 제거한다. bfill이나 미래 값으로 채우는 방식은 사용하지 않는다(look-ahead bias 방지).
6. **정규화** (`normalize()` / `ZScoreWinsorizer`) — `config.TRAIN_END_DATE` 이전 구간에서만 평균·표준편차·winsorize 상하한(평균±5표준편차)을 계산(`fit`)하고, 그 통계량을 train+test 전체 구간에 동일하게 적용(`transform`)한다. 정규화 전에 winsorize를 먼저 적용해 극단값이 평균/표준편차 계산을 왜곡하지 않게 한다. 전체 기간 통계로 계산하면 data leakage가 되므로 반드시 이 순서를 지킨다.

7. **워크포워드 정규화** (`normalize_walk_forward()`) — `config.WALK_FORWARD_WINDOWS`의 윈도우마다(train 2018~2021/test 2022부터 train 2018~2024/test 2025까지 4개) 해당 train 구간만으로 따로 fit하고 `[train_start, test_end)` 구간을 transform한다. 윈도우별 기간·평균·표준편차·winsorize 상하한·변수 순서는 `walk_forward_manifest.json`에 저장되고, 파일 경로는 manifest 기준 상대경로라 API 서버에서도 그대로 쓸 수 있다.

최종적으로 `data/processed/`에 다음 파일이 저장된다.
- `prices.parquet`: 정규화 전 병합 수정종가와 종목별 `{ticker}_is_market_open`(1 = 실제 거래일, 0 = ffill로 채운 휴장일)
- `features.parquet`: 정규화된 피처 36개(return/rsi/macd × 12종목) 뒤에 `{ticker}_is_market_open` 12개를 붙인 48개 컬럼. `TRAIN_END_DATE` 기준 단일 분할이다. 플래그는 정규화하지 않은 0/1이다. ffill로 채운 휴장일 수익률은 z-score 후 0이 아닌 작은 값(예: 2026-09-24 005930은 −0.02)이 되므로 플래그로 실제 보합일과 구분해야 한다
- `features_window{1..4}.parquet`, `walk_forward_manifest.json`: 워크포워드 윈도우별 피처(같은 48개 컬럼)와 통계량. manifest의 `columns`는 정규화한 컬럼(평균·표준편차 있음), `passthrough_columns`는 그대로 붙인 플래그이고, 파일 컬럼 순서는 `columns` 다음 `passthrough_columns`다
- `returns.parquet`: 정규화 전 로그수익률 (RL 보상 계산용)
- `manifest.json`: `collect_price.py` 실행마다 수집 시각과 시장별 종료일을 버전으로 누적 기록. 미국은 뉴욕 16:00 마감이 지난 마지막 거래일, 한국은 시각과 상관없이 당일을 뺀 전 거래일이다(네이버 일별 시세는 장 마감 뒤에도 당일 종가가 바뀐 사례가 있어 확정값만 쓴다)

## 뉴스/공시 수집 규칙과 네이버 → 한국경제 전환 이유

- **DART 공시**: `OpenDartReader`로 삼성전자(005930), SK하이닉스(000660)의 정기공시(A: 사업/분기/반기보고서), 주요사항보고(B), 거래소공시(I, 수시공시)를 수집한다.
- **SEC EDGAR**: AAPL, MSFT, NVDA의 10-K, 10-Q, 8-K를 수집한다. `filings.recent`가 2018년까지 닿지 않는 회사는 `filings.files`의 과거 페이지도 읽는다.
- **뉴스**: 원래 네이버 뉴스 검색 API를 사용할 계획이었으나 NCP 카드 등록 문제로 사용이 막혔다. 대안으로 네이버 금융/뉴스의 RSS 피드를 찾아봤지만, `finance.naver.com`과 `news.naver.com`의 `robots.txt`가 **모든 경로를 `Disallow`** 처리하고 있고(특히 `news.naver.com`은 AI/RAG 봇을 명시적으로 차단) CLAUDE.md의 "robots.txt 준수" 원칙에 위배돼 네이버 계열 도메인 자체를 포기했다. 대신 CLAUDE.md에 이미 허용 소스로 명시된 **한국경제(hankyung.com) RSS**(`/feed/finance`, `/feed/economy`, `/feed/international`)를 사용한다. 이 경로들은 `hankyung.com/robots.txt`에서 막혀있지 않음을 확인했다. 종목별 RSS는 제공되지 않아, 카테고리 RSS의 최신 기사 중 제목에 종목 키워드(예: 삼성전자, 엔비디아, MS, AAPL 등 한글 별칭 포함)가 포함된 기사만 필터링하는 방식으로 구현했다.
- **요청 빈도**: DART/한국경제 요청 사이마다 `time.sleep(1.0)`으로 최소 1초 딜레이를 둔다.
- **저장 형식**: 종목명, 제목, 본문요약(300자 이내), 게시일, 원문URL 5개 컬럼으로 통일해 `data/raw/news/{종목코드 또는 티커}.csv`에 저장한다. RSS 자체에는 본문 요약이 없어서, 매칭된 기사는 원문 페이지(`/article/...`, robots.txt 허용 경로)에서 본문을 추출해 300자로 자른다. 유료/회원 전용 기사처럼 본문을 찾지 못하면 `유료/비공개 기사(원문URL 참고)`를 저장하고 경고 로그를 남긴다.
- **API Key·연락처**: `DART_API_KEY`와 `SEC_EDGAR_CONTACT_EMAIL`은 `.env`로 관리하고, `.env`는 `.gitignore`에 포함해 git에 커밋되지 않도록 했다. 한국경제 RSS/기사 수집은 별도 인증이 필요 없다.
- **자동 누적 수집**: `.github/workflows/collect-news.yml`이 6시간마다(UTC 00:23, 06:23, 12:23, 18:23) `collect_news.py`를 실행하고, 새 행이 있으면 `data/raw/news/*.csv`를 main에 커밋한다. 한국경제 RSS는 카테고리당 최신 50건, 약 12~14시간 분량(2026-10-31 측정)이라 하루 한 번으로는 기사가 빠진다. 저장소 Settings → Secrets에 `DART_API_KEY`, `SEC_EDGAR_CONTACT_EMAIL`을 넣어야 DART·SEC가 수집된다. Actions 탭에서 수동 실행(`Run workflow`)도 된다. 뉴스 CSV만 git으로 추적하므로(`.gitignore`), 팀원은 `git pull`로 같은 데이터를 받는다. 수집 뉴스는 재배포 금지이므로 이 저장소를 public으로 바꾸거나 다른 public 저장소에 복사하지 않는다.

## 알려진 한계점

- **RSS 스냅샷 한계**: 한국경제 RSS는 카테고리별 최신 약 50건만 제공한다. 그 시점에 AAPL/애플처럼 제목에 직접 언급된 기사가 없으면 수집 건수가 0이 될 수 있다(실제로 AAPL은 0건이 나온 적이 있음). 데이터 오류가 아니라 뉴스 흐름과 제목 매칭 방식의 구조적 한계다.
- **제목 매칭 방식의 재현율**: 본문 내용까지 검사하지 않고 제목만 필터링하므로, 종목이 본문에서만 언급된 기사는 누락된다. 재현율보다 정확성(오탐 최소화)을 우선한 선택이다.
- **DART·SEC 행에는 본문 요약이 없다**: DART 공시 목록 API와 SEC EDGAR submissions API는 제목·날짜·URL만 주고 본문을 주지 않는다. 그래서 이 두 소스의 행은 `본문요약`이 `요약 없음(원문URL 참고)`로 채워지고, 실제 내용은 `원문URL`에서 확인해야 한다(2026-10-02 기준 1,172건 중 1,165건). 한국경제 RSS 기사만 원문 페이지에서 추출한 실제 본문 300자를 갖는다(유료/회원 전용 기사는 제외). 원문 앞부분을 받아 채우는 방식은 확인해 보고 쓰지 않았다:
  - DART 주요사항보고서(B): 앞 약 250자가 표지(회사명, 대표이사, 주소, 작성책임자 이름·전화번호)다.
  - DART 거래소공시(I): `dart.document()`로 원문을 받을 수 없다(status 014 "파일이 존재하지 않습니다").
  - SEC 8-K: 앞 300자가 inline XBRL 태그이고, 실제 "Item" 섹션은 약 2,800자 이후에 시작한다.

  의미 있는 요약을 만들려면 소스별 섹션 파싱(8-K의 Item 섹션 등)이 필요하고, 실행마다 약 1,000건의 추가 요청이 생긴다.
- **이상치는 리포트만 만든다**: `detect_outliers()`는 `main.py` 마지막 단계에서 실행되지만 값을 수정하지 않는다. `data/raw/outlier_report.csv`는 사람이 직접 검토해야 한다.
- **`features.parquet`는 단일 분할이다**: 하위 호환용으로 `config.TRAIN_END_DATE`(2024-01-01) 이전 구간으로만 fit한다. 그 이전 구간(2022·2023)을 테스트하면 미래 통계가 섞이므로, 그 경우 워크포워드 윈도우별 파일(`features_window{n}.parquet`)을 쓴다.
- **Python 버전 제약**: `OpenDartReader==0.2.2`는 최신 0.3.x(Python 3.13+ 전용)를 설치할 수 없어 다운그레이드했고, `pyarrow==17.0.0`은 Python 3.14용 사전 빌드 wheel이 없다. 현재 `.venv`는 Python 3.12 기준으로 만들어져 있다.
- **`KRX 로그인 실패` 로그**: `pykrx`가 출력하는 안내성 메시지로, 공개 시세 조회 자체에는 영향이 없다.
