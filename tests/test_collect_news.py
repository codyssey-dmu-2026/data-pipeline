from datetime import datetime

import pandas as pd
import pytest

import collect_news as cn


@pytest.fixture
def news_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cn, "RAW_NEWS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(cn.time, "sleep", lambda _seconds: None)


def _row(url, title="t"):
    return {
        "종목명": "삼성전자",
        "제목": title,
        "본문요약": "s",
        "게시일": "2024-01-01T00:00:00+09:00",
        "원문URL": url,
    }


def _filings(forms, dates, acceptance=None):
    filings = {
        "form": forms,
        "filingDate": dates,
        "accessionNumber": [f"0000000000-26-00000{i}" for i in range(len(forms))],
        "reportDate": dates,
        "primaryDocument": [f"doc{i}.htm" for i in range(len(forms))],
    }
    if acceptance is not None:
        filings["acceptanceDateTime"] = acceptance
    return filings


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_save_news_appends_and_keeps_latest_row_per_url(news_dir):
    cn.save_news("005930", [_row("u1", "old"), _row("u2")])
    cn.save_news("005930", [_row("u1", "new"), _row("u3")])

    df = pd.read_csv(news_dir / "005930.csv", encoding="utf-8-sig")
    assert sorted(df["원문URL"]) == ["u1", "u2", "u3"]
    assert df.loc[df["원문URL"] == "u1", "제목"].item() == "new"


def test_save_news_rerun_does_not_grow_file(news_dir):
    rows = [_row("u1"), _row("u2")]
    cn.save_news("AAPL", rows)
    cn.save_news("AAPL", rows)
    assert len(pd.read_csv(news_dir / "AAPL.csv")) == 2


def test_to_kst_iso_treats_date_only_value_as_kst_midnight():
    assert cn._to_kst_iso(datetime(2026, 9, 29)) == "2026-09-29T00:00:00+09:00"


def test_to_kst_iso_converts_utc_and_drops_subseconds():
    utc = datetime.fromisoformat("2026-09-29T00:35:51.123Z")
    assert cn._to_kst_iso(utc) == "2026-09-29T09:35:51+09:00"


@pytest.mark.parametrize(
    "title, ticker, expected",
    [
        ("모건스탠리(MS) 목표가 상향", "MSFT", False),
        ("새 애플리케이션 출시 봇물", "AAPL", False),
        ("파인애플 수출 호조", "AAPL", False),
        ("애플 아이폰 신제품 발표", "AAPL", True),
        ("AAPL 목표가 상향", "AAPL", True),
        ("마이크로소프트, 클라우드 매출 급증", "MSFT", True),
        ("'○○○' 팔고 하이닉스 풀베팅", "000660", True),
    ],
)
def test_title_matches(title, ticker, expected):
    assert cn._title_matches(title, cn.NEWS_TARGETS[ticker]["aliases"]) is expected


def test_rows_from_sec_filings_filters_forms_dates_and_uses_placeholder():
    filings = _filings(
        ["10-Q", "8-K", "4", "10-K"],
        ["2024-05-01", "2024-04-01", "2024-03-01", "2017-12-01"],
        acceptance=["2024-05-01T20:05:00.000Z", "", "", ""],
    )
    rows = cn._rows_from_sec_filings(filings, "AAPL", 320193)

    assert [r["제목"].split()[0] for r in rows] == ["10-Q", "8-K"]
    assert rows[0]["게시일"] == "2024-05-02T05:05:00+09:00"
    assert rows[1]["게시일"] == "2024-04-01T00:00:00+09:00"
    assert rows[0]["원문URL"].endswith("/320193/000000000026000000/doc0.htm")
    assert all(r["본문요약"] == cn.NO_SUMMARY_PLACEHOLDER for r in rows)


def test_collect_sec_filings_reads_older_page_when_recent_starts_late(monkeypatch, no_sleep):
    main = {
        "filings": {
            "recent": _filings(["10-Q"], ["2021-05-01"]),
            "files": [
                {"name": "needed.json", "filingTo": "2021-04-30"},
                {"name": "too_old.json", "filingTo": "2015-12-31"},
            ],
        }
    }
    requested = []

    def fake_get(url, **_kwargs):
        requested.append(url)
        if url.endswith("too_old.json"):
            raise AssertionError("a page entirely before START_DATE must not be fetched")
        if url.endswith("needed.json"):
            return _FakeResponse(_filings(["10-Q"], ["2019-05-01"]))
        return _FakeResponse(main)

    monkeypatch.setattr(cn, "_get_cik", lambda _ticker: 320193)
    monkeypatch.setattr(cn.requests, "get", fake_get)

    rows = cn.collect_sec_filings("AAPL")
    assert sorted(r["게시일"][:10] for r in rows) == ["2019-05-01", "2021-05-01"]
    assert len(requested) == 2


def test_collect_sec_filings_skips_pages_when_recent_covers_start(monkeypatch, no_sleep):
    main = {
        "filings": {
            "recent": _filings(["10-Q", "10-K"], ["2021-05-01", "2017-11-01"]),
            "files": [{"name": "page.json", "filingTo": "2019-01-01"}],
        }
    }
    requested = []

    def fake_get(url, **_kwargs):
        requested.append(url)
        return _FakeResponse(main)

    monkeypatch.setattr(cn, "_get_cik", lambda _ticker: 320193)
    monkeypatch.setattr(cn.requests, "get", fake_get)

    cn.collect_sec_filings("AAPL")
    assert len(requested) == 1


def test_collect_dart_disclosures_combines_kinds_and_filters_periodic(monkeypatch, no_sleep):
    by_kind = {
        "A": pd.DataFrame(
            {
                "report_nm": ["사업보고서 (2023.12)", "증권발행실적보고서"],
                "rcept_dt": ["20240312", "20240101"],
                "rcept_no": ["1", "2"],
            }
        ),
        "B": pd.DataFrame(
            {
                "report_nm": ["주요사항보고서(자기주식취득결정)"],
                "rcept_dt": ["20240501"],
                "rcept_no": ["3"],
            }
        ),
        "I": pd.DataFrame(
            {"report_nm": ["기업설명회(IR)개최"], "rcept_dt": ["20240201"], "rcept_no": ["4"]}
        ),
    }

    class FakeDart:
        def __init__(self, _api_key):
            pass

        def list(self, _corp_code, start, end, kind):
            return by_kind[kind]

    monkeypatch.setattr(cn, "OpenDartReader", FakeDart)

    rows = cn.collect_dart_disclosures("005930", "삼성전자")
    assert [r["제목"] for r in rows] == [
        "주요사항보고서(자기주식취득결정)",
        "사업보고서 (2023.12)",
        "기업설명회(IR)개최",
    ]
    assert rows[0]["게시일"] == "2024-05-01T00:00:00+09:00"
    assert rows[0]["원문URL"].endswith("rcpNo=3")
    assert all(r["본문요약"] == cn.NO_SUMMARY_PLACEHOLDER for r in rows)


class _FakeHtml:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_fetch_article_summary_marks_paywalled_article(monkeypatch, caplog):
    page = "<html><body><p>회원 전용 기사입니다</p></body></html>"
    monkeypatch.setattr(cn.requests, "get", lambda _url, **_kwargs: _FakeHtml(page))
    url = "https://www.hankyung.com/article/202610029306i"

    with caplog.at_level("WARNING"):
        assert cn.fetch_article_summary(url) == cn.PAYWALLED_SUMMARY_PLACEHOLDER
    assert url in caplog.text


def test_fetch_article_summary_truncates_body(monkeypatch):
    page = f'<div id="articletxt">{"가" * 500}</div>'
    monkeypatch.setattr(cn.requests, "get", lambda _url, **_kwargs: _FakeHtml(page))
    assert (
        cn.fetch_article_summary("https://www.hankyung.com/article/1") == "가" * cn.SUMMARY_LIMIT
    )
