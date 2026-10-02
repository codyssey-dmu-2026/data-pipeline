from datetime import date, datetime
from zoneinfo import ZoneInfo

from collect_price import (
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
    assert _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now) == date(2026, 9, 30)


def test_us_after_close_includes_today():
    # 2026-10-01(목) 16:30 ET, 장 마감 후 -> 당일이 완료 거래일
    now = datetime(2026, 10, 1, 16, 30, tzinfo=US_MARKET_TZ)
    assert _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now) == date(2026, 10, 1)


def test_us_weekend_backs_up_to_friday():
    # 2026-10-03(토) -> 금요일(10-02)로
    now = datetime(2026, 10, 3, 12, 0, tzinfo=US_MARKET_TZ)
    assert _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now) == date(2026, 10, 2)

    # 2026-10-04(일) -> 역시 금요일(10-02)로
    now = datetime(2026, 10, 4, 12, 0, tzinfo=US_MARKET_TZ)
    assert _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now) == date(2026, 10, 2)


def test_us_monday_before_close_backs_up_to_friday():
    # 2026-10-05(월) 09:00 ET, 장 시작 전 -> 지난 금요일(10-02)이 완료 거래일
    now = datetime(2026, 10, 5, 9, 0, tzinfo=US_MARKET_TZ)
    assert _last_completed_trading_day(US_MARKET_TZ, US_MARKET_CLOSE, now) == date(2026, 10, 2)


def test_kr_during_session_uses_previous_day():
    now = datetime(2026, 10, 2, 10, 0, tzinfo=KR_MARKET_TZ)  # 금 10:00 장중
    assert get_kr_end_date(now) == date(2026, 10, 1)


def test_kr_excludes_today_even_after_close():
    # 15:30 마감 후에도 당일 종가가 바뀔 수 있어 당일은 항상 제외한다
    now = datetime(2026, 10, 2, 23, 30, tzinfo=KR_MARKET_TZ)  # 금 23:30
    assert get_kr_end_date(now) == date(2026, 10, 1)


def test_kr_monday_backs_up_to_friday():
    now = datetime(2026, 10, 5, 20, 0, tzinfo=KR_MARKET_TZ)  # 월 20:00
    assert get_kr_end_date(now) == date(2026, 10, 2)


def test_kr_weekend_backs_up_to_friday():
    assert get_kr_end_date(datetime(2026, 10, 3, 12, 0, tzinfo=KR_MARKET_TZ)) == date(2026, 10, 2)
    assert get_kr_end_date(datetime(2026, 10, 4, 12, 0, tzinfo=KR_MARKET_TZ)) == date(2026, 10, 2)


def test_us_and_kr_can_diverge_on_same_wall_clock_instant():
    # 2026-10-01 18:00 UTC = 10-01(목) 14:00 ET(마감 전) = 10-02(금) 03:00 KST
    now_utc = datetime(2026, 10, 1, 18, 0, tzinfo=ZoneInfo("UTC"))
    assert get_us_end_date(now_utc) == date(2026, 9, 30)
    assert get_kr_end_date(now_utc) == date(2026, 10, 1)
