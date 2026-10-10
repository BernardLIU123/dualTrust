"""RU 分钟数据导入工具：CSV → 校验 → vnpy BarData → SQLite。

CSV 格式（UTC+8 本地时间）：
    datetime,open,high,low,close,volume,open_interest
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

import pandas as pd
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData

REQUIRED_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]
# 交易时段（小时）：夜盘 21-22 点，日盘 9-11、13-14 点
SESSION_HOURS = {21, 22, 9, 10, 11, 13, 14}
# 各交易时段开盘时间：gap 检测中，第二根 bar 落在这些时点视为合法时段间隔（不判缺失）
SESSION_OPEN_TIMES = {time(9, 0), time(10, 30), time(13, 30), time(21, 0)}


@dataclass
class ValidationReport:
    total_rows: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bars_by_day: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [f"总行数: {self.total_rows}"]
        lines += [f"[错误] {e}" for e in self.errors]
        lines += [f"[警告] {w}" for w in self.warnings]
        return "\n".join(lines)


def read_csv(path: str | Path) -> pd.DataFrame:
    """读取并基础清理：必需列校验、时间解析、按时间排序。"""
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必需列: {missing}")
    df["datetime"] = pd.to_datetime(df["datetime"], format="%Y-%m-%d %H:%M:%S")
    if "open_interest" not in df.columns:
        df["open_interest"] = 0.0
    return df.sort_values("datetime").reset_index(drop=True)


def validate(df: pd.DataFrame, calendar=None) -> ValidationReport:
    """校验数据质量；calendar 提供 is_trading_day(d) 即可（鸭子类型）。"""
    report = ValidationReport(total_rows=len(df))

    dup = df["datetime"].duplicated()
    if dup.any():
        report.errors.append(f"{int(dup.sum())} 行时间戳重复")

    if not df["datetime"].is_monotonic_increasing:
        report.errors.append("时间戳非单调递增")

    price_cols = df[["open", "high", "low", "close"]]
    bad = (df["high"] < df["low"]) | (price_cols <= 0).any(axis=1) | price_cols.isna().any(axis=1)
    if bad.any():
        report.errors.append(f"{int(bad.sum())} 行价格非法（high<low、非正值或缺失）")

    dt = df["datetime"]
    gap_min = (dt.diff().dt.total_seconds() / 60.0).dropna()
    in_session = dt.dt.hour.isin(SESSION_HOURS)
    second = dt.dt.time.iloc[1:]
    big_gap = gap_min[(gap_min > 1.5) & in_session.iloc[1:].to_numpy() & ~second.isin(SESSION_OPEN_TIMES).to_numpy()]
    if big_gap.any():
        report.warnings.append(
            f"交易时段内 {len(big_gap)} 处缺失 bar（最大间隔 {big_gap.max():.0f} 分钟）"
        )

    if calendar is not None:
        for d, rows in df.groupby(dt.dt.date):
            if not calendar.is_trading_day(d):
                report.warnings.append(f"{d} 为非交易日但存在 {len(rows)} 行数据")

    report.bars_by_day = df.groupby(dt.dt.date).size().to_dict()
    return report


def to_bar_data(df: pd.DataFrame, symbol: str, exchange: Exchange) -> list[BarData]:
    """DataFrame → vnpy BarData 列表（interval=MINUTE）。"""
    bars: list[BarData] = []
    for row in df.itertuples(index=False):
        bars.append(
            BarData(
                gateway_name="DB",
                symbol=symbol,
                exchange=exchange,
                datetime=row.datetime.to_pydatetime(),
                interval=Interval.MINUTE,
                open_price=row.open,
                high_price=row.high,
                low_price=row.low,
                close_price=row.close,
                volume=row.volume,
                open_interest=row.open_interest,
            )
        )
    return bars


def _open_sqlite_db(db_path: str | Path):
    """按 db_path 打开 vnpy sqlite 数据库（vnpy_sqlite 1.1.3 / vnpy 4.0.0 适配）。

    vnpy_sqlite 1.1.3 的 SqliteDatabase.__init__(self) 不再接受路径参数：
    数据库路径由模块导入时 SETTINGS["database.database"] 确定的模块级 peewee 连接固定。
    这里在实例化前按传入路径重绑该模块级连接与各 Model 的元数据，保持外部接口不变。
    """
    import vnpy_sqlite.sqlite_database as sq
    from peewee import SqliteDatabase as PeeweeSqliteDatabase

    sq.db = PeeweeSqliteDatabase(str(db_path))
    for model in (sq.DbBarData, sq.DbTickData, sq.DbBarOverview, sq.DbTickOverview):
        model._meta.database = sq.db
    return sq.SqliteDatabase()


def write_sqlite(bars: list[BarData], db_path: str | Path) -> int:
    """写入 vnpy sqlite 数据库，返回写入条数。"""
    db = _open_sqlite_db(db_path)
    db.save_bar_data(bars)
    return len(bars)


def load_sqlite(db_path, symbol, exchange, start, end) -> list[BarData]:
    db = _open_sqlite_db(db_path)
    return db.load_bar_data(symbol, exchange, Interval.MINUTE, start, end)


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 RU 1 分钟数据到 vnpy SQLite")
    parser.add_argument("--csv", required=True, help="数据文件路径")
    parser.add_argument("--symbol", default="ru2601")
    parser.add_argument("--exchange", default="SHFE", choices=["SHFE"])
    parser.add_argument("--db", default=str(Path.home() / ".vntrader" / "database.db"))
    parser.add_argument("--calendar", default=None, help="交易日历 JSON（可选）")
    parser.add_argument("--dry-run", action="store_true", help="只校验不写库")
    args = parser.parse_args()

    df = read_csv(args.csv)
    calendar = None
    if args.calendar:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategies"))
        from trading_calendar import TradingCalendar
        calendar = TradingCalendar.from_json(args.calendar)

    report = validate(df, calendar)
    print(report.summary())
    if report.errors:
        sys.exit(1)
    if args.dry_run:
        print("校验通过（--dry-run，未写库）")
        return

    bars = to_bar_data(df, args.symbol, getattr(Exchange, args.exchange))
    n = write_sqlite(bars, args.db)
    print(f"已写入 {n} 根 bar 到 {args.db}")


if __name__ == "__main__":
    main()
