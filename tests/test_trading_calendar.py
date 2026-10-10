"""TradingCalendar：周末/节假日判断、下一交易日、JSON 回环。"""
from datetime import date

from trading_calendar import TradingCalendar


def test_weekend_not_trading():
    cal = TradingCalendar([])
    assert cal.is_trading_day(date(2026, 1, 5))   # 周一
    assert not cal.is_trading_day(date(2026, 1, 10))  # 周六


def test_holiday_not_trading():
    cal = TradingCalendar(["2026-02-17"])
    assert not cal.is_trading_day(date(2026, 2, 17))


def test_next_trading_day_skips_weekend():
    cal = TradingCalendar([])
    assert cal.next_trading_day(date(2026, 1, 9)) == date(2026, 1, 12)  # 周五→周一


def test_next_trading_day_skips_holiday():
    cal = TradingCalendar(["2026-02-17", "2026-02-18"])
    assert cal.next_trading_day(date(2026, 2, 16)) == date(2026, 2, 19)


def test_json_roundtrip(tmp_path):
    cal = TradingCalendar(["2026-02-17", "2026-10-01"])
    p = tmp_path / "cal.json"
    cal.to_json(p)
    cal2 = TradingCalendar.from_json(p)
    assert cal2.holidays == cal.holidays
