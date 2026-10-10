"""SHFE 交易日历：周末 + 法定节假日休市。

数据来源：上期所年度交易日历公告，每年初更新 config/trading_calendar.json。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path


class TradingCalendar:
    def __init__(self, holidays: list[str] | None = None):
        self.holidays = {date.fromisoformat(s) for s in (holidays or [])}

    @classmethod
    def from_json(cls, path: str | Path) -> "TradingCalendar":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data.get("holidays", []))

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps({"holidays": sorted(str(d) for d in self.holidays)},
                       indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def is_trading_day(self, d: date | datetime) -> bool:
        if isinstance(d, datetime):
            d = d.date()
        return d.weekday() < 5 and d not in self.holidays

    def next_trading_day(self, d: date) -> date:
        nxt = d + timedelta(days=1)
        while not self.is_trading_day(nxt):
            nxt += timedelta(days=1)
        return nxt
