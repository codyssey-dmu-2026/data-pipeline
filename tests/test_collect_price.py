from datetime import date, datetime
from zoneinfo import ZoneInfo

from collect_price import (
    KR_MARKET_CLOSE,
    KR_MARKET_TZ,
    US_MARKET_CLOSE,
    US_MARKET_TZ,
    _last_completed_trading_day,
    get_kr_end_date,
    get_us_end_date,
)


def test_us_before_close_excludes_today():
    # 2026-10-01(목) 14:00 ET, 장 마감 전 -> 당일 미완료, 전날(09-30 수)이 완료 거래일
    now = datetime(2026, 10, 1, 14, 0, tzinfo=US_MARKET_TZ)
    assert _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now) == date(
        2026, 9, 30
    )


def test_us_after_close_includes_today():
    # 2026-10-01(목) 16:30 ET, 장 마감 후 -> 당일이 완료 거래일
    now = datetime(2026, 10, 1, 16, 30, tzinfo=US_MARKET_TZ)
    assert _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now) == date(
        2026, 10, 1
    )


def test_us_weekend_backs_up_to_friday():
    # 2026-10-03(토) -> 금요일(10-02)로
    now = datetime(2026, 10, 3, 12, 0, tzinfo=US_MARKET_TZ)
    assert _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now) == date(
        2026, 10, 2
    )

    # 2026-10-04(일) -> 역시 금요일(10-02)로
    now = datetime(2026, 10, 4, 12, 0, tzinfo=US_MARKET_TZ)
    assert _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now) == date(
        2026, 10, 2
    )


def test_us_monday_before_close_backs_up_to_friday():
    # 2026-10-05(월) 09:00 ET, 장 시작 전 -> 지난 금요일(10-02)이 완료 거래일
    now = datetime(2026, 10, 5, 9, 0, tzinfo=US_MARKET_TZ)
    assert _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now) == date(
        2026, 10, 2
    )


def test_kr_before_close_excludes_today():
    # 2026-10-02(금) 10:00 KST, 장중 -> 당일 미완료, 전날 완료
    now = datetime(2026, 10, 2, 10, 0, tzinfo=KR_MARKET_TZ)
    assert _last_completed_trading_day(KR_MARKET_TZ, KR_MARKET_CLOSE, now) == date(
        2026, 10, 1
    )


def test_kr_after_close_includes_today():
    now = datetime(2026, 10, 2, 16, 0, tzinfo=KR_MARKET_TZ)
    assert _last_completed_trading_day(KR_MARKET_TZ, KR_MARKET_CLOSE, now) == date(
        2026, 10, 2
    )


def test_us_and_kr_can_diverge_on_same_wall_clock_instant():
    # 같은 순간이라도 시차 때문에 미국/한국 완료 거래일이 다를 수 있다.
    # 2026-10-02 07:00 UTC = 2026-10-02 03:00 ET(금, 마감 전) = 2026-10-02 16:00 KST(금, 마감 후)
    now_utc = datetime(2026, 10, 2, 7, 0, tzinfo=ZoneInfo("UTC"))
    assert get_us_end_date(now_utc) == date(2026, 10, 1)  # 목요일(전날)로 후퇴
    assert get_kr_end_date(now_utc) == date(2026, 10, 2)  # 금요일 당일 마감 완료
