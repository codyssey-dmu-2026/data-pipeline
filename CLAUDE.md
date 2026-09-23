# 프로젝트: 에이전틱 RAG + 강화학습 기반 로보어드바이저

## 전체 미션
- RL(PPO) 기반 동적 자산배분 엔진 + LLM 기반 에이전틱 투자 리서치(RAG)를 결합한 로보어드바이저
- RAG가 뉴스/공시에서 탐지한 리스크 이벤트를 risk_tag로 변환해 RL 관측공간에 반영하는 것이 핵심 차별점
- 최종 산출물: FastAPI 서버 + Streamlit 대시보드 + Docker Compose (나는 그 중 Data Pipeline 파트만 담당)

## 내 담당: Data Pipeline 파트
역할: 원천 데이터(가격/뉴스/공시) 수집 및 전처리. RL 엔진과 RAG 팀 둘 다에 데이터를 공급.

### 필수 요건 (미션 문서 기준, 반드시 지킬 것)
1. yfinance(미국)/pykrx(국내)로 10개 이상 자산, 5년 이상 수정주가(adjusted price) 자동 수집
2. 수익률은 반드시 로그 수익률(log return) 사용
3. 결측치: Forward Fill 먼저 적용 후, 남는 결측치는 제거. 절대 미래 값으로 과거를 채우지 않음 (look-ahead bias 금지)
4. 정규화(Z-score 또는 Min-Max) 적용. 단, 평균/표준편차 등 통계량은 전체 기간이 아니라 walk-forward 학습 구간 데이터만으로 계산할 것 (data leakage 절대 금지)
5. 시계열은 반드시 시간 순서 유지, 테스트 구간 라벨(미래 수익률)을 학습에 사용 금지

### 자산 유니버스 (12개: 미국 8 + 국내 4)
미국 (yfinance, auto_adjust=True):
- SPY (S&P500 ETF), QQQ (나스닥100 ETF), AAPL, MSFT, NVDA (개별주)
- TLT (장기채), GLD (금), VNQ (리츠)

국내 (pykrx):
- 005930 삼성전자, 000660 SK하이닉스 (개별주)
- 069500 KODEX 200 (지수ETF), 148070 KODEX 국고채10년 (채권ETF)

수집 기간: 2018-01-01 ~ 현재 (5년 요건보다 여유 있게, walk-forward 여러 윈도우 확보용)

### 뉴스/공시 수집 규칙 (미션 제약사항 그대로)
- 허용 소스: DART 공시(OpenDartReader), 한국경제 뉴스 RSS(hankyung.com/feed/*), 한국경제 오픈 API 등 공개 API 우선
  (네이버 금융 뉴스 API는 NCP 카드 등록 문제로 사용 불가, 대체 검토한 네이버 금융/뉴스 RSS도 robots.txt가 전체 경로를 Disallow해서 제외함 - 2026-09-23)
- 요청 빈도: robots.txt 준수, 초당 1회 이하 요청
- 저장 포맷: 제목, 본문 요약(300자 이내), 게시일, 원문 URL을 구조화하여 저장
- 원문 URL은 반드시 보존 (RAG 팀이 인용 출처로 사용함)
- API Key는 .env 파일로 관리, 절대 git에 커밋하지 않음 (.gitignore에 .env 추가)
- 교육 목적 전용, 재배포 금지

### 폴더 구조
data_pipeline/
├── config.py
├── collect_price.py
├── collect_news.py
├── preprocess.py
├── indicators.py
├── utils.py
├── data/
│   ├── raw/
│   │   ├── prices/
│   │   └── news/
│   └── processed/
│       ├── returns.parquet
│       └── features.parquet
├── tests/
├── requirements.txt
└── README.md

### 산출물이 넘어가는 곳
- features.parquet → RL 엔진(PPO) 관측공간 입력
- data/raw/news/* → RAG 에이전트가 ChromaDB에 벡터화할 원본
- Risk Tag는 RAG 팀이 만들어서 RL 관측공간에 별도 합류 (내 담당 아님, 인터페이스 스키마만 맞추면 됨)

### 코드 스타일
- flake8/black 린터 준수, 설정값 하드코딩 금지 (config.py 또는 .env 사용)
