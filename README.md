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
├── main.py               # collect_price → preprocess 전체 파이프라인 엔트리포인트
├── data/
│   ├── raw/
│   │   ├── prices/       # 종목별 원본 수정종가 CSV (12개)
│   │   └── news/         # 종목별 뉴스·공시 CSV
│   │   └── outlier_report.csv  # detect_outliers() 결과 (수동 실행)
│   └── processed/
│       ├── returns.parquet   # 정규화된 로그수익률만
│       └── features.parquet  # 정규화된 전체 피처(return/rsi/macd)
├── tests/
│   └── test_features.py  # features.parquet 무결성 테스트
├── .env.example          # DART_API_KEY 등 필요한 환경변수 템플릿
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

# 3. .env 준비 (DART_API_KEY 등, 절대 git에 커밋하지 않음)
cp .env.example .env
# .env를 열어 DART_API_KEY를 채워넣는다

# 4. 전체 파이프라인 실행 (가격 수집 → 병합 → 피처 → 결측치 → 정규화 → parquet 저장)
python main.py

# 5. 테스트
python -m pytest
```

`main.py`는 `collect_price.collect_all()`과 `preprocess.run_pipeline()`만 순서대로 호출한다. 뉴스/공시 수집(`collect_news.py`)은 별도 스크립트로 분리돼 있어 필요할 때 `python collect_news.py`로 따로 실행한다(요청 빈도 제약이 있는 외부 API라 가격 수집과 텀포를 분리하는 게 안전하다). 이상치 리포트도 `python -c "from preprocess import merge_prices, detect_outliers; detect_outliers(merge_prices())"` 형태로 필요할 때 수동 실행한다.

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

`preprocess.py`의 `run_pipeline()`이 아래 순서로 실행된다 (이상치 검증은 별도 수동 단계):

1. **수집** (`collect_price.py`) — yfinance(`auto_adjust=True`)/pykrx(`adjusted=True`)로 종목별 수정종가를 `data/raw/prices/*.csv`에 저장.
2. **정합성** (`merge_prices()`) — 12개 종목 CSV를 하나의 DataFrame으로 병합하고, 미국/한국 휴장일 차이를 고려해 12종목 모두 거래된 날짜(intersection)만 남긴다. 병합 전후 행 수와 손실 비율을 print로 확인할 수 있다.
3. **지표** (`compute_features()`) — 종목별 로그수익률(`{ticker}_return`), RSI 14(`{ticker}_rsi`, `indicators.py`), MACD 12/26/9(`{ticker}_macd`)를 계산한다. `pandas-ta` RSI가 워밍업 구간(첫 13행)에도 100 같은 의미 없는 값을 채우는 문제를 확인해서, 해당 구간은 수동으로 NaN 처리한다.
4. **이상치 검증** (`detect_outliers()`, 수동 실행) — 절대 로그수익률이 30%를 넘는 날짜를 종목별로 찾아 전/후일 가격, 같은 날 다른 11개 종목 수익률과 함께 `data/raw/outlier_report.csv`에 저장한다. 자동으로 값을 수정/삭제하지 않고 리포트만 생성해서 사람이 직접 검토(여러 종목이 동시에 튀면 시장 이벤트, 한 종목만 튀면 데이터 오류 의심)하도록 한다.
5. **결측치 처리** (`handle_missing()`) — `ffill()`로 먼저 채우고, 그래도 남는 행(지표 워밍업 구간 등)은 `dropna()`로 제거한다. bfill이나 미래 값으로 채우는 방식은 사용하지 않는다(look-ahead bias 방지).
6. **정규화** (`normalize()` / `ZScoreWinsorizer`) — `config.TRAIN_END_DATE` 이전 구간에서만 평균·표준편차·winsorize 상하한(평균±5표준편차)을 계산(`fit`)하고, 그 통계량을 train+test 전체 구간에 동일하게 적용(`transform`)한다. 정규화 전에 winsorize를 먼저 적용해 극단값이 평균/표준편차 계산을 왜곡하지 않게 한다. 전체 기간 통계로 계산하면 data leakage가 되므로 반드시 이 순서를 지킨다.

최종적으로 `data/processed/features.parquet`(전체 피처)와 `data/processed/returns.parquet`(로그수익률 컬럼만)로 저장된다.

## 뉴스/공시 수집 규칙과 네이버 → 한국경제 전환 이유

- **DART 공시**: `OpenDartReader`로 삼성전자(005930), SK하이닉스(000660)의 정기공시(사업보고서/분기보고서/반기보고서)를 수집한다.
- **뉴스**: 원래 네이버 뉴스 검색 API를 사용할 계획이었으나 NCP 카드 등록 문제로 사용이 막혔다. 대안으로 네이버 금융/뉴스의 RSS 피드를 찾아봤지만, `finance.naver.com`과 `news.naver.com`의 `robots.txt`가 **모든 경로를 `Disallow`** 처리하고 있고(특히 `news.naver.com`은 AI/RAG 봇을 명시적으로 차단) CLAUDE.md의 "robots.txt 준수" 원칙에 위배돼 네이버 계열 도메인 자체를 포기했다. 대신 CLAUDE.md에 이미 허용 소스로 명시된 **한국경제(hankyung.com) RSS**(`/feed/finance`, `/feed/economy`, `/feed/international`)를 사용한다. 이 경로들은 `hankyung.com/robots.txt`에서 막혀있지 않음을 확인했다. 종목별 RSS는 제공되지 않아, 카테고리 RSS의 최신 기사 중 제목에 종목 키워드(예: 삼성전자, 엔비디아, MS, AAPL 등 한글 별칭 포함)가 포함된 기사만 필터링하는 방식으로 구현했다.
- **요청 빈도**: DART/한국경제 요청 사이마다 `time.sleep(1.0)`으로 최소 1초 딜레이를 둔다.
- **저장 형식**: 종목명, 제목, 본문요약(300자 이내), 게시일, 원문URL 5개 컬럼으로 통일해 `data/raw/news/{종목코드 또는 티커}.csv`에 저장한다. RSS 자체에는 본문 요약이 없어서, 매칭된 기사는 원문 페이지(`/article/...`, robots.txt 허용 경로)에서 본문을 추출해 300자로 자른다.
- **API Key**: `DART_API_KEY`는 `.env`로 관리하고 `.gitignore`에 포함해 git에 커밋되지 않도록 했다. 한국경제 RSS/기사 수집은 별도 인증이 필요 없다.

## 알려진 한계점

- **RSS 스냅샷 한계**: 한국경제 RSS는 카테고리별 최신 약 50건만 제공한다. 그 시점에 AAPL/애플처럼 제목에 직접 언급된 기사가 없으면 수집 건수가 0이 될 수 있다(실제로 AAPL은 0건이 나온 적이 있음). 데이터 오류가 아니라 뉴스 흐름과 제목 매칭 방식의 구조적 한계다.
- **제목 매칭 방식의 재현율**: 본문 내용까지 검사하지 않고 제목만 필터링하므로, 종목이 본문에서만 언급된 기사는 누락된다. 재현율보다 정확성(오탐 최소화)을 우선한 선택이다.
- **DART 본문요약 = 제목**: DART 공시 목록 API는 본문 텍스트를 제공하지 않아, `본문요약` 컬럼에 보고서명(`report_nm`)을 그대로 사용한다. 실제 공시 본문을 요약하려면 `dart.document()`로 원문(XML)을 추가로 받아 파싱하는 별도 작업이 필요하다.
- **이상치 리포트는 수동 단계**: `detect_outliers()`는 `main.py`/`run_pipeline()` 자동 흐름에 포함돼 있지 않다. 데이터 품질 점검은 사람이 따로 실행해서 리포트를 검토해야 한다.
- **단일 walk-forward 컷**: `config.TRAIN_END_DATE` 하나로 train/test를 한 번만 나눈다. 여러 walk-forward 윈도우로 검증하려면 `normalize(features, train_end_date=...)`를 원하는 날짜로 여러 번 호출해야 한다.
- **Python 버전 제약**: `OpenDartReader==0.2.2`는 최신 0.3.x(Python 3.13+ 전용)를 설치할 수 없어 다운그레이드했고, `pyarrow==17.0.0`은 Python 3.14용 사전 빌드 wheel이 없다. 현재 `.venv`는 Python 3.12 기준으로 만들어져 있다.
- **`KRX 로그인 실패` 로그**: `pykrx`가 출력하는 안내성 메시지로, 공개 시세 조회 자체에는 영향이 없다.
