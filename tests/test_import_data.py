"""import_data 的解析、校验、转换与 sqlite 回环测试。"""
from datetime import datetime

import pandas as pd
import pytest

from import_data import ValidationReport, load_sqlite, read_csv, to_bar_data, validate, write_sqlite
from vnpy.trader.constant import Exchange, Interval

HEADER = "datetime,open,high,low,close,volume,open_interest\n"


def make_csv(tmp_path, body: str) -> str:
    p = tmp_path / "data.csv"
    p.write_text(HEADER + body, encoding="utf-8")
    return str(p)


def rows(start_day=5, n=3, minutes_apart=1):
    """生成 n 行合法数据（21:00 起）。"""
    out = []
    for i in range(n):
        hh = 21 + i // 60
        mm = i % 60
        ts = f"2026-01-{start_day:02d} {hh:02d}:{mm:02d}:00"
        out.append(f"{ts},105.0,110.0,100.0,105.0,1000,0")
    return "\n".join(out)


def test_read_csv_valid(tmp_path):
    path = make_csv(tmp_path, rows(n=3))
    df = read_csv(path)
    assert list(df.columns) == ["datetime", "open", "high", "low", "close", "volume", "open_interest"]
    assert len(df) == 3


def test_read_csv_missing_column(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("datetime,open,high,low,close\n2026-01-05 21:00:00,1,2,0,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="缺少必需列"):
        read_csv(str(p))


def test_validate_ok(tmp_path):
    df = read_csv(make_csv(tmp_path, rows(n=3)))
    report = validate(df)
    assert report.ok
    assert report.total_rows == 3


def test_validate_duplicate_datetime(tmp_path):
    body = rows(n=2) + "\n" + rows(n=1) + "\n"
    df = read_csv(make_csv(tmp_path, body))
    report = validate(df)
    assert not report.ok
    assert any("重复" in e for e in report.errors)


def test_validate_bad_price(tmp_path):
    body = "2026-01-05 21:00:00,105.0,95.0,100.0,105.0,1000,0\n"  # high < low
    df = read_csv(make_csv(tmp_path, body))
    report = validate(df)
    assert any("非法" in e for e in report.errors)


def test_validate_gap_warning(tmp_path):
    # 21:00 与 21:05 之间缺 4 根 bar
    body = ("2026-01-05 21:00:00,105.0,110.0,100.0,105.0,1000,0\n"
            "2026-01-05 21:05:00,106.0,111.0,101.0,106.0,1000,0\n")
    df = read_csv(make_csv(tmp_path, body))
    report = validate(df)
    assert report.ok
    assert any("缺失" in w for w in report.warnings)


def test_validate_nan_price(tmp_path):
    body = "2026-01-05 21:00:00,105.0,110.0,100.0,,1000,0\n"  # close 为空 → NaN
    df = read_csv(make_csv(tmp_path, body))
    report = validate(df)
    assert not report.ok
    assert any("非法" in e for e in report.errors)


def test_validate_session_break_not_warning(tmp_path):
    # 22:59 → 次日 09:00 为合法时段间隔（夜盘收盘→日盘开盘），不判缺失 bar
    body = ("2026-01-05 22:59:00,105.0,110.0,100.0,105.0,1000,0\n"
            "2026-01-06 09:00:00,106.0,111.0,101.0,106.0,1000,0\n")
    df = read_csv(make_csv(tmp_path, body))
    report = validate(df)
    assert report.ok
    assert not any("缺失" in w for w in report.warnings)


def test_validate_holiday_warning(tmp_path):
    class FakeCalendar:
        def is_trading_day(self, d):
            return d != datetime(2026, 1, 5).date()
    df = read_csv(make_csv(tmp_path, rows(n=3)))
    report = validate(df, calendar=FakeCalendar())
    assert any("非交易日" in w for w in report.warnings)


def test_to_bar_data(tmp_path):
    df = read_csv(make_csv(tmp_path, rows(n=3)))
    bars = to_bar_data(df, "ru2601", Exchange.SHFE)
    assert len(bars) == 3
    b = bars[0]
    assert b.symbol == "ru2601"
    assert b.exchange == Exchange.SHFE
    assert b.interval == Interval.MINUTE
    assert b.open_price == 105.0 and b.high_price == 110.0 and b.low_price == 100.0
    assert b.volume == 1000


def test_sqlite_roundtrip(tmp_path):
    df = read_csv(make_csv(tmp_path, rows(n=3)))
    bars = to_bar_data(df, "ru2601", Exchange.SHFE)
    db = tmp_path / "test.db"
    n = write_sqlite(bars, str(db))
    assert n == 3
    loaded = load_sqlite(
        str(db), "ru2601", Exchange.SHFE,
        datetime(2026, 1, 1), datetime(2026, 12, 31),
    )
    assert len(loaded) == 3
    assert loaded[0].close_price == bars[0].close_price
