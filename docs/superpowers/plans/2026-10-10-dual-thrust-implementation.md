# Dual Thrust 分钟级交易策略 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为天然橡胶期货（RU）实现一套分钟级 Dual Thrust 日内突破量化交易系统：算法文档、策略核心与 vn.py 胶水、数据导入工具、批量回测/参数寻优脚本、风控告警、实盘配置与上线清单。

**Architecture:** vn.py 一体化架构——`DualThrustCore`（纯算法状态机，不依赖 vn.py，可单测）承载全部决策逻辑，`DualThrustStrategy(CtaTemplate)` 只做胶水（发单、风控接线、告警）。回测与实盘运行同一份核心代码，杜绝逻辑漂移。

**Tech Stack:** Python ≥ 3.11、vnpy ≥ 3.9、vnpy_ctastrategy、vnpy_ctp、pandas、pytest、matplotlib。Windows 11。

**Spec:** `docs/superpowers/specs/2026-10-10-dual-thrust-design.md`（本计划从该 spec 推导，执行者需同时阅读）

## Global Constraints

- 时间统一为 **UTC+8 本地 naive datetime**，含夜盘；交易日定义：夜盘 21:00 开盘 → 次日 15:00 收盘
- 合约口径：pricetick = 5 元/吨，合约乘数 size = 10 吨/手；回测默认手续费 rate = 0.00002（≈3 元/手 @ 15000 元/吨）、滑点 slippage = 5 元/吨（1 tick）
- 策略核心默认参数（与 spec 3.4 一致）：`window_minutes=15, k1=0.5, k2=0.5, atr_length=30, stop_atr_mult=2.0, fixed_size=1, force_close_time=14:55`
- **模块平级导入约定**：`strategies/` 内模块互相用平级导入（`from dual_thrust_core import ...`），tests 与 tools 通过 conftest/脚本把仓库根目录与 `strategies/`、`tools/` 加入 `sys.path`。这样 vn.py 部署时 4 个策略文件可平铺复制到 vnpy strategies 目录
- 所有测试用 `pytest` 运行，测试数据一律在测试内构造（tmp_path），不依赖真实行情数据
- 代码注释与文档用中文；git 提交信息以 `feat:`/`docs:`/`test:` 开头，并以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾
- vn.py 内部 API（`vnpy_sqlite.SqliteDatabase` 构造签名、`EVENT_GATEWAY` 事件数据字段、`BacktestingEngine` 的 `history_data` 注入、`calculate_statistics` 输出列名）随版本有差异：**每个任务首次用到时，先用 `python -c "import inspect; print(inspect.signature(...))"` 核对，与计划不一致时以最小改动适配并在提交信息中注明**

---

### Task 0: 项目脚手架与环境

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `pytest.ini`
- Create: `conftest.py`
- Create: `README.md`

**Interfaces:**
- Produces: 后续所有任务的运行前提——`.venv` 虚拟环境、`pytest` 可运行、`conftest.py` 保证测试能平级导入 `strategies/` 与 `tools/` 模块

- [ ] **Step 1: 检查 Python 版本并创建虚拟环境**

Run: `python --version`
Expected: `Python 3.11` 或更高（若 < 3.11，先安装 Python 3.11+）

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
```

- [ ] **Step 2: 写 requirements.txt**

```text
vnpy>=3.9
vnpy_ctastrategy>=1.1.9
vnpy_ctp>=1.0.2
pandas>=2.0
pytest>=8.0
matplotlib>=3.8
```

（`vnpy_ctp` 为实盘必需；Windows 下均为 wheel 安装。安装顺序由 pip 自行解析。）

- [ ] **Step 3: 安装并验证依赖**

```bash
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -c "import vnpy, vnpy_ctastrategy, vnpy_ctp, pandas, pytest, matplotlib; print('OK')"
```

Expected: 输出 `OK`。若 `vnpy_ctp` 安装失败，先注释掉它继续（回测/开发不需要），在实盘任务前解决。

- [ ] **Step 4: 写 pytest.ini**

```ini
[pytest]
testpaths = tests
addopts = -q
```

- [ ] **Step 5: 写 conftest.py（路径注入 + 共享工具函数）**

```python
"""pytest 全局配置：把仓库根目录、strategies/、tools/ 加入 sys.path。

约定：strategies/ 内模块平级导入（vn.py 部署时文件平铺复制可用），
tests 与 tools 以平级名直接 import。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "strategies"))
sys.path.insert(0, str(ROOT / "tools"))
```

- [ ] **Step 6: 写 .gitignore**

```text
.venv/
__pycache__/
*.pyc
.pytest_cache/
.vntrader/
*.db
output/
```

- [ ] **Step 7: 写 README.md（骨架）**

内容：项目名与一句话简介（橡胶期货 RU 分钟级 Dual Thrust 日内突破策略，Python + vn.py）；目录结构表；快速开始（创建环境 → 导入数据 → 回测）；文档链接（`docs/algorithm/`、`docs/superpowers/specs/`）；风险免责声明一行（量化策略仅供研究，实盘风险自负）。

- [ ] **Step 8: 跑一次空测试确认环境**

Run: `.venv/Scripts/python -m pytest`
Expected: `no tests ran`（0 collected 也视为通过，说明 pytest 与 conftest 无语法错误）

- [ ] **Step 9: Commit**

```bash
git add requirements.txt .gitignore pytest.ini conftest.py README.md
git commit -m "chore: 项目脚手架（venv 依赖、pytest 配置、README）

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 1: 《Dual Thrust 算法文档》（第一交付物）

**Files:**
- Create: `docs/algorithm/dual-thrust-算法文档.md`

**Interfaces:**
- Consumes: spec `docs/superpowers/specs/2026-10-10-dual-thrust-design.md`（第 1、3、5、6 章）
- Produces: 面向交易员/开发者的人读文档，独立成篇；后续任务不再修改本文件（如参数调整，另行更新）

- [ ] **Step 1: 创建文档骨架（全部章节标题 + 每节 2-3 句内容要点）**

章节结构（按此顺序，节号照写）：

1. 策略概述——适用品种（上期所 RU）、K 线周期（1 分钟）、交易时段（夜盘 21:00 起）、策略类型（日内开盘区间突破，不隔夜）
2. 市场逻辑与适用性——为什么橡胶适合：国际联动、夜盘流动性、日内波动性；策略适合趋势日、不适合窄幅震荡日的说明
3. 算法原理与公式——15 分钟开盘区间、Range、上/下轨公式、K1/K2 含义与图示说明（用文字+ASCII 图示意轨道结构）
4. 交易规则——观察期（21:00–21:15 不交易）、突破开仓、每方向每日一次、反手、止损公式 `max(ATR(30)×stop_atr_mult, 0.5×Range)`、14:55 强平；每条规则附触发条件、动作、理由
5. 参数说明——spec 3.4 参数表全文（默认值 + 优化范围），每个参数附"调大/调小的效果"说明
6. 合约特性与实盘参数——合约单位 10 吨/手、最小变动 5 元/吨、交易时段表、手续费默认 3 元/手（以交易所公告为准）、保证金默认 10%、涨跌停保护、主力换月说明
7. 风险控制——spec 5.1 三层风控体系全文
8. 回测方法与绩效评估——spec 6.1–6.3 全文（回测设置表、指标清单与公式、样本内/外设计、验收门槛表）
9. 实盘部署——vn.py 架构图（ASCII）、四阶段上线路径表（Phase 0–3）、监控告警项表（spec 5.2）、容灾要点（spec 5.3）
10. 边界情形与异常处理——区间零宽度、开盘数据缺失、涨停封板、行情中断、持仓不一致、换月跳空：各附系统行为说明
11. 附录——术语表（ORB、ATR、tick、主力连续等）、参数速查卡（一张表）

- [ ] **Step 2: 逐章填充正文**

按骨架逐章写正文。公式用行内数学记号（如 `Upper = RangeHigh + K1 × Range`）；所有数值与 spec 完全一致，不得自行发挥；第 8 章指标公式从 vn.py `calculate_statistics` 口径摘录（总收益率、年化收益率、夏普 rf=2.5%、最大回撤、卡玛、索提诺）。中文书写，术语首次出现附英文。

- [ ] **Step 3: 与 spec 一致性自检**

逐条核对：默认参数 7 个值、止损公式、强平时间、验收门槛 6 项数值、三层风控内容、四阶段退出条件，与 spec 第 3/5/6 章一致。不一致处修正文档（spec 为准）。

- [ ] **Step 4: Commit**

```bash
git add docs/algorithm/dual-thrust-算法文档.md
git commit -m "docs: 编写 Dual Thrust 算法文档（第一交付物）

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 数据导入工具 import_data.py

**Files:**
- Create: `tools/import_data.py`
- Test: `tests/test_import_data.py`

**Interfaces:**
- Consumes: vnpy（`BarData`、`Exchange`、`Interval`）、pandas
- Produces（后续任务依赖的确切签名）:
  - `read_csv(path) -> pd.DataFrame`：校验必需列、解析时间戳、排序去重前保持原始
  - `validate(df, calendar=None) -> ValidationReport`：`ValidationReport` 含 `total_rows:int`、`errors:list[str]`、`warnings:list[str]`、`ok:bool`
  - `to_bar_data(df, symbol: str, exchange: Exchange) -> list[BarData]`
  - `write_sqlite(bars, db_path) -> int`、`load_sqlite(db_path, symbol, exchange, start, end) -> list[BarData]`
  - CLI：`python tools/import_data.py --csv X --symbol ru2601 --db Y [--dry-run]`

- [ ] **Step 1: 写失败测试 tests/test_import_data.py**

```python
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
    body = rows(n=2) + "\n" + rows(n=1)[0] + "\n"
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
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_import_data.py`
Expected: 全部 FAIL（`ModuleNotFoundError: No module named 'import_data'`）

- [ ] **Step 3: 写 tools/import_data.py（完整实现）**

先用 `python -c "from vnpy_sqlite.sqlite_database import SqliteDatabase; import inspect; print(inspect.signature(SqliteDatabase.__init__))"` 核对数据库构造参数，若参数名与下面不同（如 `filename` 而非 `path`），按实际签名改写 `write_sqlite`/`load_sqlite` 中的 `SqliteDatabase(...)` 调用：

```python
"""RU 分钟数据导入工具：CSV → 校验 → vnpy BarData → SQLite。

CSV 格式（UTC+8 本地时间）：
    datetime,open,high,low,close,volume,open_interest
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData

REQUIRED_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]
# 交易时段（小时）：夜盘 21-22 点，日盘 9-11、13-14 点
SESSION_HOURS = {21, 22, 9, 10, 11, 13, 14}


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

    bad = (df["high"] < df["low"]) | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    if bad.any():
        report.errors.append(f"{int(bad.sum())} 行价格非法（high<low 或非正值）")

    dt = df["datetime"]
    gap_min = (dt.diff().dt.total_seconds() / 60.0).dropna()
    in_session = dt.dt.hour.isin(SESSION_HOURS)
    big_gap = gap_min[(gap_min > 1.5) & in_session.iloc[1:].to_numpy()]
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


def write_sqlite(bars: list[BarData], db_path: str | Path) -> int:
    """写入 vnpy sqlite 数据库，返回写入条数。"""
    from vnpy_sqlite.sqlite_database import SqliteDatabase
    db = SqliteDatabase(str(db_path))
    db.save_bar_data(bars)
    return len(bars)


def load_sqlite(db_path, symbol, exchange, start, end) -> list[BarData]:
    from vnpy_sqlite.sqlite_database import SqliteDatabase
    db = SqliteDatabase(str(db_path))
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
```

- [ ] **Step 4: 运行确认全部通过**

Run: `.venv/Scripts/python -m pytest tests/test_import_data.py -v`
Expected: 10 passed

- [ ] **Step 5: CLI 冒烟**

```bash
printf "datetime,open,high,low,close,volume,open_interest\n2026-01-05 21:00:00,105,110,100,105,1000,0\n2026-01-05 21:01:00,106,111,101,106,1000,0\n" > /tmp/smoke.csv
.venv/Scripts/python tools/import_data.py --csv /tmp/smoke.csv --dry-run
```

Expected: 输出校验摘要，`校验通过（--dry-run，未写库）`，退出码 0

- [ ] **Step 6: Commit**

```bash
git add tools/import_data.py tests/test_import_data.py
git commit -m "feat: 数据导入工具（CSV 校验、BarData 转换、SQLite 写入）

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 策略核心 DualThrustCore（纯算法状态机）

**Files:**
- Create: `strategies/dual_thrust_core.py`
- Test: `tests/test_dual_thrust_core.py`

**Interfaces:**
- Produces（Task 5 胶水依赖的确切签名）:
  - `Bar(datetime, open, high, low, close, volume=0.0)`（dataclass，属性 `.time`）
  - `DualThrustParams`（dataclass，字段：`window_minutes=15, k1=0.5, k2=0.5, atr_length=30, stop_atr_mult=2.0, min_stop_range_fraction=0.5, force_close_time=time(14,55), session_start=time(21,0), collect_deadline=time(21,30)`）
  - `Signal(action: Action, price: float, reason: str)`；`Action` 枚举：`BUY/SELL/SHORT/COVER`
  - `DayState` 枚举：`COLLECTING/ARMED/LONG/SHORT/STOPPED/CLOSED/ABORTED`
  - `DualThrustCore(params=None)`；`.on_bar(bar: Bar) -> list[Signal]`；公开属性：`state, upper, lower, range_high, range_low, range_size, entry_price, stop_price, long_today, short_today`

- [ ] **Step 1: 写失败测试 tests/test_dual_thrust_core.py**

```python
"""DualThrustCore 状态机与轨道计算测试。"""
from datetime import datetime, time

from dual_thrust_core import (
    Action, Bar, DayState, DualThrustCore, DualThrustParams, Signal,
)


def make_bar(day, hh, mm, o, h, l, c, v=0):
    return Bar(datetime(2026, 1, day, hh, mm), o, h, l, c, v)


def session_bars(day, n=15, high=110.0, low=100.0, close=105.0):
    """21:00 起 n 根 1 分钟 bar，区间 [low, high]。"""
    bars = []
    for i in range(n):
        bars.append(make_bar(day, 21 + i // 60, i % 60, close, high, low, close))
    return bars


def feed(core, bars):
    signals = []
    for b in bars:
        signals += core.on_bar(b)
    return signals


def test_range_calculation_exact():
    core = DualThrustCore()
    feed(core, session_bars(5))
    assert core.state is DayState.ARMED
    assert core.range_high == 110.0 and core.range_low == 100.0 and core.range_size == 10.0
    assert core.upper == 115.0   # 110 + 0.5*10
    assert core.lower == 95.0    # 100 - 0.5*10


def test_collecting_no_signal():
    core = DualThrustCore()
    signals = feed(core, session_bars(5)[:14])
    assert signals == []
    assert core.state is DayState.COLLECTING


def test_long_entry_on_upper_break():
    core = DualThrustCore()
    feed(core, session_bars(5))
    sig = feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])
    assert sig == [Signal(Action.BUY, 116.0, "UPPER_BREAK")]
    assert core.state is DayState.LONG
    assert core.long_today and not core.short_today


def test_stop_loss_with_atr():
    # bar 恒 TR=10 → ATR=10；止损距离 = max(10*2, 0.5*10) = 20
    core = DualThrustCore()
    feed(core, session_bars(5))
    feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])
    assert core.stop_price == 96.0  # 116 - 20
    # 跌破止损（close 95.5 < stop 96）：以 min(stop, close) 离场
    sig = feed(core, [make_bar(5, 21, 16, 96, 96, 95, 95.5)])
    assert sig == [Signal(Action.SELL, 95.5, "STOP_LOSS")]
    assert core.state is DayState.STOPPED


def test_stop_loss_dip_recover_fills_at_stop():
    core = DualThrustCore()
    feed(core, session_bars(5))
    feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])
    # 低点 95.5 击穿止损但收盘回到 100：成交按止损价 96
    sig = feed(core, [make_bar(5, 21, 16, 96, 100, 95.5, 100)])
    assert sig[0].price == 96.0


def test_no_entry_after_stop():
    core = DualThrustCore()
    feed(core, session_bars(5))
    feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])
    feed(core, [make_bar(5, 21, 16, 96, 96, 95, 95.5)])   # 止损
    sig = feed(core, [make_bar(5, 21, 17, 94, 95, 93, 94)])  # 跌破下轨 95
    assert sig == []  # STOPPED 状态当日不再开仓
    assert core.state is DayState.STOPPED


def test_reverse_position():
    core = DualThrustCore()
    feed(core, session_bars(5))
    feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])  # 开多
    sig = feed(core, [make_bar(5, 21, 20, 94, 95, 93, 94)])  # 跌破下轨 → 反手
    assert sig == [Signal(Action.SELL, 94.0, "REVERSE_EXIT"),
                   Signal(Action.SHORT, 94.0, "LOWER_BREAK")]
    assert core.state is DayState.SHORT
    assert core.short_today and core.long_today
    # 再突破上轨：long_today 已 True，不再开多
    sig = feed(core, [make_bar(5, 21, 25, 116, 117, 115, 116)])
    assert sig == []


def test_force_close():
    core = DualThrustCore()
    feed(core, session_bars(5))
    feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])
    sig = feed(core, [make_bar(5, 14, 55, 112, 113, 111, 112)])
    assert sig == [Signal(Action.SELL, 112.0, "FORCE_CLOSE")]
    assert core.state is DayState.CLOSED


def test_force_close_has_priority_over_stop():
    core = DualThrustCore()
    feed(core, session_bars(5))
    feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])
    sig = feed(core, [make_bar(5, 14, 55, 90, 95, 89, 90)])  # 既过强平时间又破止损
    assert sig == [Signal(Action.SELL, 90.0, "FORCE_CLOSE")]


def test_new_session_resets():
    core = DualThrustCore()
    feed(core, session_bars(5))
    feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])
    feed(core, [make_bar(5, 14, 55, 112, 113, 111, 112)])
    assert core.state is DayState.CLOSED
    # 次日 21:00 → 新会话重置
    feed(core, [make_bar(6, 21, 0, 105, 106, 104, 105)])
    assert core.state is DayState.COLLECTING
    assert not core.long_today and not core.short_today
    assert core.upper == 0.0


def test_zero_width_range_aborts():
    core = DualThrustCore()
    feed(core, session_bars(5, high=100.0, low=100.0, close=100.0))
    assert core.state is DayState.ABORTED
    sig = feed(core, [make_bar(5, 21, 15, 101, 102, 100, 101)])
    assert sig == []


def test_collect_deadline_aborts():
    core = DualThrustCore()
    feed(core, session_bars(5)[:10])          # 只有 10 根
    sig = feed(core, [make_bar(5, 21, 30, 105, 106, 104, 105)])  # 21:30 仍未凑齐
    assert core.state is DayState.ABORTED
    assert sig == []


def test_first_bar_after_midnight_session():
    # 首个 bar 为 22:00（夜盘开盘数据缺失）→ 当日放弃
    core = DualThrustCore()
    feed(core, [make_bar(5, 22, 0, 105, 106, 104, 105)])
    assert core.state is DayState.ABORTED
    # 次日 21:00 正常开启新会话
    feed(core, [make_bar(6, 21, 0, 105, 106, 104, 105)])
    assert core.state is DayState.COLLECTING


def test_first_bar_day_session_waits_for_night():
    # 首个 bar 是日盘 9:00（无夜盘历史）→ 保持等待，直到 21:00
    core = DualThrustCore()
    sig = feed(core, [make_bar(5, 9, 0, 105, 106, 104, 105)])
    assert sig == [] and core.state is DayState.CLOSED
    feed(core, [make_bar(5, 21, 0, 105, 106, 104, 105)])
    assert core.state is DayState.COLLECTING


def test_no_stop_check_on_entry_bar():
    core = DualThrustCore()
    feed(core, session_bars(5))
    # 入场 bar 本身低点远低于止损价：入场 bar 不检查止损
    sig = feed(core, [make_bar(5, 21, 15, 116, 117, 80, 116)])
    assert sig == [Signal(Action.BUY, 116.0, "UPPER_BREAK")]
    assert core.state is DayState.LONG


def test_short_entry_and_stop():
    core = DualThrustCore()
    feed(core, session_bars(5))
    sig = feed(core, [make_bar(5, 21, 15, 94, 95, 93, 94)])
    assert sig == [Signal(Action.SHORT, 94.0, "LOWER_BREAK")]
    assert core.stop_price == 114.0  # 94 + 20
    sig = feed(core, [make_bar(5, 21, 16, 114.5, 115, 113, 114.5)])
    assert sig == [Signal(Action.COVER, 114.0, "STOP_LOSS")]  # max(stop, close)=114


def test_stop_floor_uses_half_range_when_atr_small():
    params = DualThrustParams(stop_atr_mult=0.3)  # atr_stop=3 < 0.5*range=5
    core = DualThrustCore(params)
    feed(core, session_bars(5))
    feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])
    assert core.stop_price == 111.0  # 116 - 5
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_dual_thrust_core.py`
Expected: 全部 FAIL（`ModuleNotFoundError: No module named 'dual_thrust_core'`）

- [ ] **Step 3: 写 strategies/dual_thrust_core.py（完整实现）**

```python
"""Dual Thrust 策略核心：纯算法逻辑，不依赖 vn.py。

回测与实盘共用本模块，保证信号逻辑无漂移。
输入为 1 分钟 bar（UTC+8 本地时间，含夜盘）；交易日定义：21:00 开盘 → 次日 15:00 收盘。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum


class DayState(str, Enum):
    COLLECTING = "COLLECTING"   # 收集开盘区间 bar（21:00–21:15，不交易）
    ARMED = "ARMED"             # 轨道已激活，监控突破
    LONG = "LONG"               # 持有多头
    SHORT = "SHORT"             # 持有空头
    STOPPED = "STOPPED"         # 止损离场，当日不再开仓
    CLOSED = "CLOSED"           # 强平离场，等待下一交易日
    ABORTED = "ABORTED"         # 当日异常放弃（数据缺失/零宽度区间）


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    SHORT = "SHORT"
    COVER = "COVER"


@dataclass
class Bar:
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def time(self) -> time:
        return self.datetime.time()


@dataclass
class DualThrustParams:
    window_minutes: int = 15
    k1: float = 0.5
    k2: float = 0.5
    atr_length: int = 30
    stop_atr_mult: float = 2.0
    min_stop_range_fraction: float = 0.5
    force_close_time: time = time(14, 55)
    session_start: time = time(21, 0)
    collect_deadline: time = time(21, 30)


@dataclass
class Signal:
    action: Action
    price: float
    reason: str = ""


class DualThrustCore:
    """日内状态机 + 轨道/止损计算，纯逻辑、可单测。"""

    def __init__(self, params: DualThrustParams | None = None):
        self.params = params or DualThrustParams()
        self.state = DayState.CLOSED
        self.upper = 0.0
        self.lower = 0.0
        self.range_high = 0.0
        self.range_low = 0.0
        self.range_size = 0.0
        self.entry_price = 0.0
        self.stop_price = 0.0
        self.long_today = False
        self.short_today = False
        self._session_date = None
        self._range_bars: list[Bar] = []
        self._atr = 0.0
        self._atr_count = 0
        self._prev_close: float | None = None

    # ---------- 公开接口 ----------
    def on_bar(self, bar: Bar) -> list[Signal]:
        """处理一根 1 分钟 bar，返回需按序执行的信号列表。"""
        self._update_atr(bar)

        if bar.time == self.params.session_start:
            self._start_session(bar)
            return []

        if self._session_date is None:
            if bar.time > self.params.session_start:
                self.state = DayState.ABORTED  # 夜盘开盘 bar 缺失，当日放弃
            return []

        if self.state is DayState.ABORTED:
            return []

        signals: list[Signal] = []
        prev_state = self.state

        if self.state is DayState.COLLECTING:
            signals.extend(self._on_collecting(bar))
        elif self.state is DayState.ARMED:
            signals.extend(self._on_armed(bar))

        # 入场 bar 不检查持有逻辑（止损线在入场时刚建立）
        if self.state in (DayState.LONG, DayState.SHORT) and self.state == prev_state:
            signals.extend(self._on_holding(bar))

        return signals

    # ---------- 状态机各阶段 ----------
    def _on_collecting(self, bar: Bar) -> list[Signal]:
        self._range_bars.append(bar)
        if len(self._range_bars) >= self.params.window_minutes:
            self._activate_range()
        elif bar.time >= self.params.collect_deadline:
            self.state = DayState.ABORTED
        return []

    def _activate_range(self) -> None:
        highs = [b.high for b in self._range_bars]
        lows = [b.low for b in self._range_bars]
        self.range_high = max(highs)
        self.range_low = min(lows)
        self.range_size = self.range_high - self.range_low
        if self.range_size <= 0:
            self.state = DayState.ABORTED
            return
        self.upper = self.range_high + self.params.k1 * self.range_size
        self.lower = self.range_low - self.params.k2 * self.range_size
        self.state = DayState.ARMED

    def _on_armed(self, bar: Bar) -> list[Signal]:
        signals: list[Signal] = []
        if bar.close > self.upper and not self.long_today:
            self._enter_long(bar.close)
            signals.append(Signal(Action.BUY, bar.close, "UPPER_BREAK"))
        elif bar.close < self.lower and not self.short_today:
            self._enter_short(bar.close)
            signals.append(Signal(Action.SHORT, bar.close, "LOWER_BREAK"))
        return signals

    def _on_holding(self, bar: Bar) -> list[Signal]:
        signals: list[Signal] = []

        # 强平优先
        if bar.time >= self.params.force_close_time:
            signals.append(self._close_position(bar.close, "FORCE_CLOSE"))
            return signals

        # 止损：跳空穿过止损时按收盘价（更差者）成交
        if self.state is DayState.LONG and bar.low <= self.stop_price:
            exit_price = min(self.stop_price, bar.close)
            signals.append(self._close_position(exit_price, "STOP_LOSS"))
            return signals
        if self.state is DayState.SHORT and bar.high >= self.stop_price:
            exit_price = max(self.stop_price, bar.close)
            signals.append(self._close_position(exit_price, "STOP_LOSS"))
            return signals

        # 反手：先平仓再反向开仓
        if self.state is DayState.LONG and bar.close < self.lower and not self.short_today:
            signals.append(Signal(Action.SELL, bar.close, "REVERSE_EXIT"))
            self._enter_short(bar.close)
            signals.append(Signal(Action.SHORT, bar.close, "LOWER_BREAK"))
        elif self.state is DayState.SHORT and bar.close > self.upper and not self.long_today:
            signals.append(Signal(Action.COVER, bar.close, "REVERSE_EXIT"))
            self._enter_long(bar.close)
            signals.append(Signal(Action.BUY, bar.close, "UPPER_BREAK"))

        return signals

    # ---------- 会话与仓位 ----------
    def _start_session(self, bar: Bar) -> None:
        self._session_date = bar.datetime.date()
        self.state = DayState.COLLECTING
        self._range_bars = [bar]
        self.long_today = False
        self.short_today = False
        self.upper = self.lower = 0.0
        self.range_high = self.range_low = self.range_size = 0.0
        self.entry_price = self.stop_price = 0.0

    def _stop_distance(self) -> float:
        atr_stop = self._atr * self.params.stop_atr_mult if self._atr > 0 else 0.0
        return max(atr_stop, self.params.min_stop_range_fraction * self.range_size)

    def _enter_long(self, price: float) -> None:
        self.long_today = True
        self.entry_price = price
        self.stop_price = price - self._stop_distance()
        self.state = DayState.LONG

    def _enter_short(self, price: float) -> None:
        self.short_today = True
        self.entry_price = price
        self.stop_price = price + self._stop_distance()
        self.state = DayState.SHORT

    def _close_position(self, price: float, reason: str) -> Signal:
        action = Action.SELL if self.state is DayState.LONG else Action.COVER
        self.entry_price = self.stop_price = 0.0
        self.state = DayState.CLOSED if reason == "FORCE_CLOSE" else DayState.STOPPED
        return Signal(action, price, reason)

    # ---------- ATR（Wilder 平滑，跨会话连续） ----------
    def _update_atr(self, bar: Bar) -> None:
        if self._prev_close is None:
            self._prev_close = bar.close
            return
        tr = max(
            bar.high - bar.low,
            abs(bar.high - self._prev_close),
            abs(bar.low - self._prev_close),
        )
        self._atr_count += 1
        n = self.params.atr_length
        if self._atr_count == 1:
            self._atr = tr
        else:
            self._atr = (self._atr * (n - 1) + tr) / n
        self._prev_close = bar.close
```

- [ ] **Step 4: 运行确认全部通过**

Run: `.venv/Scripts/python -m pytest tests/test_dual_thrust_core.py -v`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add strategies/dual_thrust_core.py tests/test_dual_thrust_core.py
git commit -m "feat: DualThrustCore 策略核心（状态机、轨道计算、止损）

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 告警通知 Notifier + 交易日历 TradingCalendar

**Files:**
- Create: `strategies/notifier.py`
- Create: `strategies/trading_calendar.py`
- Test: `tests/test_notifier.py`、`tests/test_trading_calendar.py`

**Interfaces:**
- Produces（Task 5 依赖）:
  - `Notifier(dingtalk_webhook: str = "", smtp_config: dict | None = None, enabled: bool = True)`；方法 `.info(title, text="")`、`.warn(...)`、`.critical(...)`、`.send(title, text, level)`
  - `TradingCalendar(holidays: list[str] | None = None)`；`.is_trading_day(d: date|datetime) -> bool`、`.next_trading_day(d: date) -> date`；类方法 `.from_json(path)`、`.to_json(path)`

- [ ] **Step 1: 写失败测试 tests/test_notifier.py**

```python
"""Notifier：钉钉 webhook 载荷、静默模式、邮件走通性。"""
import json
import smtplib

from notifier import Notifier


class FakeResp:
    def read(self):
        return json.dumps({"errcode": 0}).encode("utf-8")


def test_disabled_is_silent(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)

    monkeypatch.setattr("notifier.urllib.request.urlopen", fake_urlopen)
    Notifier(enabled=False).send("t", "x")
    assert calls == []


def test_dingtalk_payload(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["data"] = json.loads(req.data.decode("utf-8"))
        captured["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr("notifier.urllib.request.urlopen", fake_urlopen)
    n = Notifier(dingtalk_webhook="https://oapi.dingtalk.com/robot/send?access_token=abc")
    n.critical("持仓不一致", "核心 LONG 仓位 0")
    assert captured["url"].startswith("https://oapi.dingtalk.com")
    md = captured["data"]["markdown"]
    assert md["title"].startswith("[CRITICAL]")
    assert "持仓不一致" in md["text"]


def test_dingtalk_error_raises(monkeypatch):
    class BadResp:
        def read(self):
            return json.dumps({"errcode": 310000}).encode("utf-8")

    monkeypatch.setattr("notifier.urllib.request.urlopen", lambda req, timeout=None: BadResp())
    import pytest
    n = Notifier(dingtalk_webhook="https://example.com/robot")
    with pytest.raises(RuntimeError, match="钉钉推送失败"):
        n.send("t", "x")


def test_email_sent(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host, self.port = host, port
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def login(self, u, p):
            sent["login"] = (u, p)
        def sendmail(self, frm, to, msg):
            sent["mail"] = (frm, to, msg)

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    cfg = {"host": "smtp.example.com", "port": 465, "username": "u",
           "password": "p", "from_addr": "a@x.com", "to_addr": "b@x.com"}
    Notifier(smtp_config=cfg).warn("强平预警", "14:50 仍持仓")
    assert sent["login"] == ("u", "p")
    assert "[WARN]" in sent["mail"][2]
```

- [ ] **Step 2: 写失败测试 tests/test_trading_calendar.py**

```python
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
```

- [ ] **Step 3: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_notifier.py tests/test_trading_calendar.py`
Expected: 全部 FAIL（模块不存在）

- [ ] **Step 4: 写 strategies/notifier.py**

```python
"""告警推送：钉钉机器人 + 可选 SMTP 邮件。webhook 未配置时静默（开发/回测模式）。"""
from __future__ import annotations

import json
import smtplib
import urllib.request
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from typing import Optional


class Notifier:
    def __init__(self, dingtalk_webhook: str = "", smtp_config: Optional[dict] = None,
                 enabled: bool = True):
        self.dingtalk_webhook = dingtalk_webhook
        self.smtp_config = smtp_config or {}
        self.enabled = enabled

    def info(self, title: str, text: str = "") -> None:
        self.send(title, text, "INFO")

    def warn(self, title: str, text: str = "") -> None:
        self.send(title, text, "WARN")

    def critical(self, title: str, text: str = "") -> None:
        self.send(title, text, "CRITICAL")

    def send(self, title: str, text: str = "", level: str = "INFO") -> None:
        if not self.enabled:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.dingtalk_webhook:
            self._send_dingtalk(ts, title, text, level)
        if self.smtp_config.get("host"):
            self._send_email(ts, title, text, level)

    def _send_dingtalk(self, ts: str, title: str, text: str, level: str) -> None:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"[{level}] {title}",
                "text": f"### [{level}] {title}\n\n{text}\n\n> {ts}",
            },
        }
        req = urllib.request.Request(
            self.dingtalk_webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("errcode") != 0:
                raise RuntimeError(f"钉钉推送失败: {result}")

    def _send_email(self, ts: str, title: str, text: str, level: str) -> None:
        cfg = self.smtp_config
        msg = MIMEText(f"[{level}] {title}\n\n{text}\n\n{ts}", "plain", "utf-8")
        msg["Subject"] = Header(f"[DualThrust][{level}] {title}", "utf-8")
        msg["From"] = cfg["from_addr"]
        msg["To"] = cfg["to_addr"]
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port", 465), timeout=10) as server:
            server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["from_addr"], [cfg["to_addr"]], msg.as_string())
```

- [ ] **Step 5: 写 strategies/trading_calendar.py**

```python
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
```

- [ ] **Step 6: 运行确认全部通过**

Run: `.venv/Scripts/python -m pytest tests/test_notifier.py tests/test_trading_calendar.py -v`
Expected: 9 passed

- [ ] **Step 7: Commit**

```bash
git add strategies/notifier.py strategies/trading_calendar.py tests/test_notifier.py tests/test_trading_calendar.py
git commit -m "feat: 钉钉/邮件告警通知与 SHFE 交易日历

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: vn.py 策略胶水 DualThrustStrategy（含风控接线）

**Files:**
- Create: `strategies/dual_thrust.py`
- Test: `tests/test_dual_thrust_strategy.py`

**Interfaces:**
- Consumes: Task 3 核心（`DualThrustCore/Bar/Signal/Action/DayState/DualThrustParams`）、Task 4（`Notifier/TradingCalendar`）、vnpy_ctastrategy（`CtaTemplate`）、vnpy（`BarData/OrderData/TradeData/Interval/Status`、`EVENT_GATEWAY`）
- Produces（Task 6 依赖）: `DualThrustStrategy` 类；可调参数 `window_minutes/k1/k2/atr_length/stop_atr_mult/fixed_size/force_close_minute/warmup_days/market_stale_seconds/prewarn_minute`；variables `state/upper/lower/pos/entry_price/stop_price`

- [ ] **Step 1: 写失败测试 tests/test_dual_thrust_strategy.py**

先核对 vn.py API（按 Global Constraints 约定）：

Run: `.venv/Scripts/python -c "from vnpy.trader.event import EVENT_GATEWAY; from vnpy_ctastrategy import CtaTemplate; import inspect; print(EVENT_GATEWAY); print(inspect.getsource(CtaTemplate.__init__))"`

Expected: 看到 `EVENT_GATEWAY` 常量与 `CtaTemplate.__init__` 源码。据此确认 `self.event_engine`、`self.get_gateway_name()`、`self.load_bar()` 均存在；若名称不同，按实际 API 调整测试与实现。

```python
"""策略胶水冒烟测试：用假引擎实例化，验证信号执行与风控门控。"""
from datetime import datetime

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData

from dual_thrust import DualThrustStrategy


class FakeEngine:
    """CtaTemplate.__init__ 所需的最小引擎接口。

    注意：若安装的 vnpy 版本 CtaTemplate.__init__ 引用更多引擎属性
    （如 callback_queue），按 Step 1 的源码核对结果补全本类。
    """

    def __init__(self):
        import queue
        from vnpy.event import EventEngine
        self.event_engine = EventEngine()
        self.callback_queue = queue.Queue()
        self.sent: list[dict] = []

    def write_log(self, msg: str) -> None:
        pass

    def send_order(self, strategy, direction, offset, price, volume, stop, lock, net):
        self.sent.append({"direction": direction, "offset": offset,
                          "price": price, "volume": volume})

    def get_gateway_name(self, strategy):
        return "CTP"

    def load_bar(self, days, interval, callback, use_database):
        pass  # 测试不预热历史

    def cancel_all(self, strategy):
        pass


def make_vn_bar(day, hh, mm, o, h, l, c, limit_up=0.0, limit_down=0.0):
    return BarData(
        gateway_name="CTP", symbol="ru2601", exchange=Exchange.SHFE,
        datetime=datetime(2026, 1, day, hh, mm), interval=Interval.MINUTE,
        open_price=o, high_price=h, low_price=l, close_price=c, volume=1.0,
        limit_up=limit_up, limit_down=limit_down,
    )


def make_strategy():
    engine = FakeEngine()
    s = DualThrustStrategy(engine, "dt", "ru2601.SHFE", {})
    return engine, s


def test_init_builds_core():
    engine, s = make_strategy()
    s.on_init()
    assert s.core is not None


def test_warmup_does_not_send_orders():
    engine, s = make_strategy()
    s.on_init()
    s.trading = False  # 预热阶段
    bars = [make_vn_bar(5, 21, i % 60, 105, 110, 100, 105) for i in range(15)]
    for b in bars:
        s.on_bar(b)
    s.on_bar(make_vn_bar(5, 21, 15, 116, 117, 114, 116))  # 突破上轨
    assert engine.sent == []  # 预热不执行信号


def test_live_entry_sends_order():
    engine, s = make_strategy()
    s.on_init()
    s.trading = True
    for i in range(15):
        s.on_bar(make_vn_bar(5, 21, i % 60, 105, 110, 100, 105))
    s.on_bar(make_vn_bar(5, 21, 15, 116, 117, 114, 116))
    assert len(engine.sent) == 1
    assert engine.sent[0]["price"] == 116.0 and engine.sent[0]["volume"] == 1


def test_market_stale_blocks_entry_but_allows_exit():
    engine, s = make_strategy()
    s.on_init()
    s.trading = True
    for i in range(15):
        s.on_bar(make_vn_bar(5, 21, i % 60, 105, 110, 100, 105))
    s.market_stale = True  # 行情中断
    s.on_bar(make_vn_bar(5, 21, 15, 116, 117, 114, 116))  # 突破上轨
    assert engine.sent == []  # 开仓被阻止


def test_price_limit_blocks_entry():
    engine, s = make_strategy()
    s.on_init()
    s.trading = True
    for i in range(15):
        s.on_bar(make_vn_bar(5, 21, i % 60, 105, 110, 100, 105))
    # 收盘 116 恰触及涨停 116 → 不追多
    s.on_bar(make_vn_bar(5, 21, 15, 116, 117, 114, 116, limit_up=116.0))
    assert engine.sent == []
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_dual_thrust_strategy.py`
Expected: FAIL（`ModuleNotFoundError: No module named 'dual_thrust'`）

- [ ] **Step 3: 写 strategies/dual_thrust.py（完整实现）**

```python
"""Dual Thrust vn.py 策略胶水：CtaTemplate 子类，全部决策委托给 DualThrustCore。

部署：本文件 + dual_thrust_core.py + notifier.py + trading_calendar.py
平铺复制到 vn.py 的 strategies 目录即可加载。
"""
from datetime import datetime, time

from vnpy.event import Event
from vnpy.trader.constant import Status
from vnpy.trader.event import EVENT_GATEWAY
from vnpy.trader.object import BarData, OrderData, TradeData
from vnpy_ctastrategy import CtaTemplate, Interval

from dual_thrust_core import Action, Bar, DayState, DualThrustCore, DualThrustParams, Signal
from notifier import Notifier
from trading_calendar import TradingCalendar


class DualThrustStrategy(CtaTemplate):
    author = "dualT"

    # 可调参数（GUI 参数面板可见）
    window_minutes = 15
    k1 = 0.5
    k2 = 0.5
    atr_length = 30
    stop_atr_mult = 2.0
    fixed_size = 1
    force_close_minute = 55       # 14:55 强平（分钟数）
    warmup_days = 10
    market_stale_seconds = 300    # 行情中断判定（默认 5 分钟）
    prewarn_minute = 50           # 14:50 持仓预警

    # 扩展参数（配置文件注入，非 GUI）
    dingtalk_webhook = ""
    calendar_path = ""

    parameters = [
        "window_minutes", "k1", "k2", "atr_length", "stop_atr_mult",
        "fixed_size", "force_close_minute", "warmup_days",
        "market_stale_seconds", "prewarn_minute",
    ]
    variables = ["state", "upper", "lower", "pos", "entry_price", "stop_price"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.core: DualThrustCore | None = None
        self.notifier = Notifier()
        self.calendar: TradingCalendar | None = None
        self.halted = False          # 持仓不一致等致命异常 → 停机
        self.market_stale = False    # 行情中断 → 禁止开仓
        self.entry_blocked = False   # 废单 → 当日禁止开仓
        self.last_bar_time: datetime | None = None
        self._prewarned_today = False
        self._state = ""
        self.entry_price = 0.0
        self.stop_price = 0.0

    def on_init(self) -> None:
        params = DualThrustParams(
            window_minutes=self.window_minutes,
            k1=self.k1,
            k2=self.k2,
            atr_length=self.atr_length,
            stop_atr_mult=self.stop_atr_mult,
            force_close_time=time(14, self.force_close_minute),
        )
        self.core = DualThrustCore(params)
        self.notifier = Notifier(dingtalk_webhook=self.dingtalk_webhook)
        if self.calendar_path:
            self.calendar = TradingCalendar.from_json(self.calendar_path)
        self.event_engine.register(EVENT_GATEWAY, self._on_gateway_event)
        self.write_log(f"初始化完成，加载 {self.warmup_days} 天历史 bar 预热")
        self.load_bar(self.warmup_days, Interval.MINUTE, use_database=True)

    def on_start(self) -> None:
        self.halted = False
        self.market_stale = False
        self.entry_blocked = False
        self.write_log("策略启动")

    def on_stop(self) -> None:
        self.write_log("策略停止")

    def on_bar(self, bar: BarData) -> None:
        if self.core is None or self.halted:
            return
        prev_time = self.last_bar_time
        self.last_bar_time = bar.datetime

        core_bar = Bar(bar.datetime, bar.open_price, bar.high_price,
                       bar.low_price, bar.close_price, bar.volume)
        signals = self.core.on_bar(core_bar)
        self._sync_variables()

        if bar.datetime.time() == time(21, 0):
            self._prewarned_today = False  # 新交易日重置预警标记

        if not self.trading:
            return  # 预热阶段：只更新核心状态，不执行信号

        self._check_market_stale(prev_time, bar.datetime)
        self._prewarn_check(bar)
        for sig in signals:
            self._execute(sig, bar)
        if not signals:
            self._check_consistency()  # 仅在本 bar 无信号时校验（有信号时订单未成交，仓位尚未同步）

    # ---------- 信号执行 ----------
    def _execute(self, sig: Signal, bar: BarData) -> None:
        if self.market_stale or self.entry_blocked:
            if sig.action in (Action.BUY, Action.SHORT):
                self.write_log(f"开仓信号被阻止: {sig.action.value} {sig.reason}")
                return
        # 涨跌停保护：临近涨跌停不追单（limit_up/limit_down 为 0 表示无该字段）
        if sig.action is Action.BUY and bar.limit_up and sig.price >= bar.limit_up:
            self.write_log(f"接近涨停，放弃开多: {sig.price} >= {bar.limit_up}")
            return
        if sig.action is Action.SHORT and bar.limit_down and sig.price <= bar.limit_down:
            self.write_log(f"接近跌停，放弃开空: {sig.price} <= {bar.limit_down}")
            return
        if sig.action is Action.BUY:
            self.buy(sig.price, self.fixed_size)
            self.notifier.info("开多", f"价格 {sig.price:.1f} 触发 {sig.reason}")
        elif sig.action is Action.SHORT:
            self.short(sig.price, self.fixed_size)
            self.notifier.info("开空", f"价格 {sig.price:.1f} 触发 {sig.reason}")
        elif sig.action is Action.SELL:
            self.sell(sig.price, abs(self.pos))
            self.notifier.warn("平多", f"价格 {sig.price:.1f} 触发 {sig.reason}")
        elif sig.action is Action.COVER:
            self.cover(sig.price, abs(self.pos))
            self.notifier.warn("平空", f"价格 {sig.price:.1f} 触发 {sig.reason}")

    # ---------- 风控与监控 ----------
    def _check_market_stale(self, prev_time, now) -> None:
        if prev_time is None:
            return
        if (now - prev_time).total_seconds() > self.market_stale_seconds:
            if not self.market_stale:
                self.market_stale = True
                self.notifier.critical(
                    "行情中断", f"已 {self.market_stale_seconds} 秒无新 bar，停止开仓")
        else:
            self.market_stale = False

    def _check_consistency(self) -> None:
        if self.active_orders:
            return  # 有待成交委托时不校验
        expected = self.fixed_size if self.core.state in (DayState.LONG, DayState.SHORT) else 0
        if self.pos != expected:
            self.halted = True
            msg = f"核心状态 {self.core.state.value}，实际仓位 {self.pos} → 策略停机，需人工核对"
            self.notifier.critical("持仓不一致", msg)
            self.write_log("持仓不一致，策略停机")

    def _prewarn_check(self, bar: BarData) -> None:
        if (self.core.state in (DayState.LONG, DayState.SHORT)
                and bar.datetime.time().minute >= self.prewarn_minute
                and bar.datetime.time().hour == 14
                and not self._prewarned_today):
            self._prewarned_today = True
            self.notifier.warn("强平预警", f"14:50 仍持仓 {self.pos} 手，14:55 将强平")

    def _on_gateway_event(self, event: Event) -> None:
        data = event.data
        if data.gateway_name != self.get_gateway_name():
            return
        if data.status:
            self.notifier.info("网关连接", f"{data.gateway_name} 已连接")
        else:
            self.market_stale = True  # 断线即禁止开仓
            self.notifier.critical("网关断开", f"{data.gateway_name} 连接断开")

    def on_trade(self, trade: TradeData) -> None:
        self.notifier.info(
            "成交回报",
            f"{trade.direction.value} {trade.offset.value} {trade.volume} 手 @ {trade.price}")
        self._sync_variables()

    def on_order(self, order: OrderData) -> None:
        if order.status == Status.REJECTED:
            self.entry_blocked = True
            self.notifier.critical(
                "委托被拒",
                f"{order.symbol} {order.direction.value} {order.volume} 手：{order.reject_reason}")

    # ---------- 状态同步 ----------
    def _sync_variables(self) -> None:
        if self.core is None:
            return
        self._state = self.core.state.value
        self.entry_price = self.core.entry_price
        self.stop_price = self.core.stop_price
```

- [ ] **Step 4: 运行确认全部通过**

Run: `.venv/Scripts/python -m pytest tests/test_dual_thrust_strategy.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add strategies/dual_thrust.py tests/test_dual_thrust_strategy.py
git commit -m "feat: vn.py 策略胶水（信号执行、持仓一致性、行情中断、网关告警）

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 批量回测与参数寻优脚本 run_backtest.py + 端到端验证

**Files:**
- Create: `tools/run_backtest.py`
- Test: `tests/test_backtest_integration.py`

**Interfaces:**
- Consumes: Task 2（`read_csv/to_bar_data`）、Task 5（`DualThrustStrategy`）、`vnpy_ctastrategy.backtesting.BacktestingEngine/OptimizationSetting`
- Produces:
  - `build_engine(args, setting) -> BacktestingEngine`
  - `run_single(args, setting, output_dir: Path) -> dict`（返回 vn.py 统计字典；产出 `equity_curve.png`、`daily_stats.csv`、`yearly_pnl.csv`、`monthly_pnl.csv`）
  - `run_optimization(args, output_dir)`（网格寻优，产出 `optimization.csv`）
  - `run_sensitivity(args, output_dir)`（参数 ±0.1 微扰稳定性检验，产出 `sensitivity.csv`）
  - CLI：`--csv/--symbol/--exchange/--start/--end/--params(JSON)/--optimize/--sensitivity/--output`

- [ ] **Step 1: 写失败测试 tests/test_backtest_integration.py**

```python
"""端到端：合成 30 天 1 分钟数据 → CSV → 回测全流程 → 产出文件齐全。

合成数据含周末（无日历过滤），只验证管线走通与产物生成。
"""
import random
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from run_backtest import run_single

DAY_SESSION = [(9, 0), (10, 30)]      # 简化：9:00–14:59 连续
NIGHT_SESSION = [(21, 0), (22, 59)]


def make_1min_data(days=30, start_price=15000.0, seed=42):
    rng = random.Random(seed)
    price = start_price
    rows = []
    d0 = datetime(2026, 1, 5)
    for i in range(days):
        d = d0 + timedelta(days=i)
        for (h0, m0), (h1, m1) in (NIGHT_SESSION, DAY_SESSION):
            t = datetime(d.year, d.month, d.day, h0, m0)
            end = datetime(d.year, d.month, d.day, h1, m1)
            while t <= end:
                o = price
                h = o + rng.uniform(0, 30)
                l = o - rng.uniform(0, 30)
                c = rng.uniform(l, h)
                rows.append((t.strftime("%Y-%m-%d %H:%M:%S"), o, h, l, c, 100))
                price = c
                t += timedelta(minutes=1)
    return pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])


def test_end_to_end_backtest(tmp_path):
    csv_path = tmp_path / "ru_1min.csv"
    make_1min_data().to_csv(csv_path, index=False)

    args = SimpleNamespace(
        csv=str(csv_path), symbol="ru2601", exchange="SHFE",
        start="2026-01-05", end="2026-02-03", params="",
    )
    out = tmp_path / "out"
    stats = run_single(args, {}, out)

    assert stats["total_return"] is not None
    assert stats["sharpe_ratio"] is not None
    assert (out / "equity_curve.png").exists()
    assert (out / "daily_stats.csv").exists()
    assert (out / "yearly_pnl.csv").exists()
    assert (out / "monthly_pnl.csv").exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_backtest_integration.py`
Expected: FAIL（`ModuleNotFoundError: No module named 'run_backtest'`）

- [ ] **Step 3: 核对 BacktestingEngine 注入方式**

Run: `.venv/Scripts/python -c "from vnpy_ctastrategy.backtesting import BacktestingEngine; import inspect; src=inspect.getsource(BacktestingEngine.run_backtesting); print('history_data' in src); print(inspect.signature(BacktestingEngine.add_strategy)); print(inspect.signature(BacktestingEngine.calculate_statistics))"`

Expected: `run_backtesting` 源码引用 `self.history_data`（直接注入可用）；`add_strategy(strategy_class, setting)` 接受类对象；`calculate_statistics(output=None)`。若 `run_backtesting` 内自行调用 `load_data()`，则 `build_engine` 改为先用 Task 2 的 `write_sqlite` 写临时库并 monkeypatch `get_database`（见下方注释）。

- [ ] **Step 4: 写 tools/run_backtest.py（完整实现）**

```python
"""Dual Thrust 批量回测与参数寻优脚本。

用法:
  .venv/Scripts/python tools/run_backtest.py --csv data/ru_1min.csv --symbol ru2601 \\
      --start 2023-01-01 --end 2025-12-31
  .venv/Scripts/python tools/run_backtest.py --csv ... --optimize     # 网格寻优
  .venv/Scripts/python tools/run_backtest.py --csv ... --sensitivity  # 参数微扰检验
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from vnpy.trader.constant import Exchange, Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine, OptimizationSetting

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "strategies"))
sys.path.insert(0, str(ROOT / "tools"))

from dual_thrust import DualThrustStrategy      # noqa: E402
from import_data import read_csv, to_bar_data   # noqa: E402

DEFAULTS = dict(
    capital=100_000,   # 起始资金（元）
    rate=0.00002,      # 手续费率 ≈ 3 元/手 @ 15000 元/吨（按成交额比例）
    slippage=5.0,      # 滑点 1 tick = 5 元/吨 = 50 元/手
    size=10,           # 合约乘数 10 吨/手
    pricetick=5.0,     # 最小变动价位 5 元/吨
)


def build_engine(args, setting: dict) -> BacktestingEngine:
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=f"{args.symbol}.{args.exchange}",
        interval=Interval.MINUTE,
        start=datetime.strptime(args.start, "%Y-%m-%d"),
        end=datetime.strptime(args.end, "%Y-%m-%d"),
        rate=DEFAULTS["rate"],
        slippage=DEFAULTS["slippage"],
        size=DEFAULTS["size"],
        pricetick=DEFAULTS["pricetick"],
        capital=DEFAULTS["capital"],
    )
    df = read_csv(args.csv)
    bars = to_bar_data(df, args.symbol, getattr(Exchange, args.exchange))
    engine.history_data = [b for b in bars if engine.start <= b.datetime <= engine.end]
    # 注：vn.py 回测引擎不建模保证金占用（盈亏按余额计），起始资金 10 万已覆盖 1 手保证金需求（spec 6.1）
    engine.add_strategy(DualThrustStrategy, setting)
    return engine


def run_single(args, setting: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = build_engine(args, setting)
    engine.run_backtesting()

    df: pd.DataFrame = engine.calculate_result()
    stats: dict = engine.calculate_statistics(output=str(output_dir / "daily_stats.csv"))

    df["balance"].plot(title=f"DualThrust {args.symbol} 权益曲线")
    plt.savefig(output_dir / "equity_curve.png", dpi=120)
    plt.close()

    daily = pd.read_csv(output_dir / "daily_stats.csv")
    yearly = daily.groupby(daily["date"].str[:4])["net_pnl"].sum()
    monthly = daily.groupby(daily["date"].str[:7])["net_pnl"].sum()
    yearly.to_csv(output_dir / "yearly_pnl.csv")
    monthly.to_csv(output_dir / "monthly_pnl.csv")

    # 基准对比：同期买入持有收益（spec 6.3）
    bars = engine.history_data
    if bars:
        buy_hold = (bars[-1].close_price - bars[0].close_price) / bars[0].close_price
        print(f"基准（同期买入持有）收益率: {buy_hold:.2%}")
    return stats


def run_optimization(args, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = build_engine(args, {})
    setting = OptimizationSetting()
    setting.set_target("sharpe_ratio")
    setting.add_parameter("window_minutes", 10, 30, 10)
    setting.add_parameter("k1", 0.2, 0.9, 0.1)
    setting.add_parameter("k2", 0.2, 0.9, 0.1)
    setting.add_parameter("stop_atr_mult", 1.5, 2.5, 0.5)
    results = engine.run_optimization(setting, output=str(output_dir / "optimization.csv"))
    print(f"共 {len(results)} 组参数，最优 5 组：")
    for params, target, stats in sorted(results, key=lambda x: x[1], reverse=True)[:5]:
        print(f"  {params}  sharpe={target:.2f}")


def run_sensitivity(args, output_dir: Path) -> None:
    """参数微扰稳定性：k1/k2/stop_atr_mult 各 ±0.1，夏普变化 ≤ 25% 视为稳定。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    base = json.loads(args.params) if args.params else {}
    rows = []
    for param in ("k1", "k2", "stop_atr_mult"):
        for delta in (-0.1, 0.1):
            setting = dict(base)
            setting[param] = round(setting.get(param, 0.5) + delta, 2)
            stats = run_single(args, setting, output_dir / f"sens_{param}_{delta:+.1f}")
            rows.append({"param": param, "delta": delta,
                         "sharpe": stats["sharpe_ratio"]})
    df = pd.DataFrame(rows)
    df.to_csv(output_dir / "sensitivity.csv", index=False)
    print(df.to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description="Dual Thrust 批量回测")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--exchange", default="SHFE")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--params", default="", help='策略参数 JSON，如 {"k1":0.6,"k2":0.4}')
    parser.add_argument("--optimize", action="store_true")
    parser.add_argument("--sensitivity", action="store_true")
    parser.add_argument("--output", default="output/backtest")
    args = parser.parse_args()

    output_dir = Path(args.output)
    setting = json.loads(args.params) if args.params else {}
    if args.optimize:
        run_optimization(args, output_dir)
    elif args.sensitivity:
        run_sensitivity(args, output_dir)
    else:
        stats = run_single(args, setting, output_dir)
        keys = ("total_return", "annual_return", "sharpe_ratio",
                "max_drawdown", "total_trade_count", "daily_win_rate")
        print(json.dumps({k: stats.get(k) for k in keys}, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行确认测试通过**

Run: `.venv/Scripts/python -m pytest tests/test_backtest_integration.py -v`
Expected: 1 passed（回测约 1 万根 bar，几秒内完成）

- [ ] **Step 6: CLI 冒烟（同合成数据）**

```bash
.venv/Scripts/python -c "
import sys; sys.path.insert(0, 'tests')
from test_backtest_integration import make_1min_data
make_1min_data().to_csv('/tmp/ru_smoke.csv', index=False)
"
.venv/Scripts/python tools/run_backtest.py --csv /tmp/ru_smoke.csv --symbol ru2601 --start 2026-01-05 --end 2026-02-03 --output /tmp/bt_out
```

Expected: 打印统计 JSON（total_return/sharpe_ratio 等），`/tmp/bt_out/` 下 4 个产物文件齐全

- [ ] **Step 7: Commit**

```bash
git add tools/run_backtest.py tests/test_backtest_integration.py
git commit -m "feat: 批量回测/参数寻优脚本与端到端集成测试

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: 实盘配置与上线检查清单

**Files:**
- Create: `config/vt_setting.json`
- Create: `config/dual_thrust_config.json`
- Create: `config/trading_calendar.json`
- Create: `docs/deployment-checklist.md`

**Interfaces:**
- Consumes: 无代码依赖；`config/trading_calendar.json` 被 Task 4 的 `TradingCalendar.from_json` 读取（格式 `{"holidays": ["YYYY-MM-DD", ...]}`）
- Produces: 实盘部署与上线依据；Phase 1（SimNow）与 Phase 2（实盘）的启动与检查材料

- [ ] **Step 1: 写 config/vt_setting.json**

```json
{
  "font.family": "微软雅黑",
  "font.size": 12,
  "log.active": true,
  "log.level": 50,
  "log.console": true,
  "log.file": true,
  "database.database": "sqlite",
  "database.name": "C:\\Users\\liubo\\.vntrader\\database.db",
  "database.host": "localhost",
  "database.port": 3306,
  "database.user": "root",
  "database.password": "",
  "datafeed.name": ""
}
```

（`database.name` 按本机实际用户名调整；此文件复制到 `~/.vntrader/vt_setting.json` 供 vn.py 全局使用。）

- [ ] **Step 2: 写 config/dual_thrust_config.json**

```json
{
  "strategy": {
    "window_minutes": 15,
    "k1": 0.5,
    "k2": 0.5,
    "atr_length": 30,
    "stop_atr_mult": 2.0,
    "fixed_size": 1,
    "force_close_minute": 55,
    "prewarn_minute": 50,
    "warmup_days": 10,
    "market_stale_seconds": 300
  },
  "risk": {
    "max_daily_loss_pct": 2.0,
    "max_drawdown_pct": 20.0,
    "risk_manager": {
      "active": true,
      "order_flow_limit": 5,
      "order_flow_clear": 1,
      "order_size_limit": 5,
      "trade_limit": 100,
      "active_order_limit": 10
    }
  },
  "alert": {
    "dingtalk_webhook": "",
    "enabled": false
  },
  "calendar": "config/trading_calendar.json"
}
```

（`dingtalk_webhook` 留空=告警静默；上线前填入机器人 webhook 并把 `enabled` 置 true。风控阈值对应 spec 5.1 第三层：日亏 2% 熔断、回撤 20% 全面停策略，每日盘前由交易员复核。）

- [ ] **Step 3: 写 config/trading_calendar.json（2026 年节假日）**

先 WebSearch「上期所 2026年 节假日 休市安排」核对官方公告日期，按公告填入（格式示例，日期以官方公告为准）：

```json
{
  "holidays": [
    "2026-01-01", "2026-01-02",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    "2026-04-06",
    "2026-05-01", "2026-05-04", "2026-05-05",
    "2026-06-19",
    "2026-09-25",
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"
  ],
  "note": "以上期所年度公告为准，每年初更新"
}
```

- [ ] **Step 4: 写 docs/deployment-checklist.md**

内容（每条为勾选清单项，共四部分）：

1. **Phase 0 回测确认**：验收门槛 6 项（夏普≥1.0、回撤≤20%、样本外/内≥60%、成本占比≤30%、正收益年份≥60%、微扰≤25%）逐项勾选；真实数据导入与校验（`import_data.py --dry-run` 无错误）；**成本占比核对**（daily_stats 中 commission+slippage 列合计 ÷ 毛利润 ≤ 30%）；**日线版对照**（用 vn.py 自带 DualThrust 样例策略以 DAILY 区间回测同一区间，记录对比结论，证明分钟级改造的增量价值）；**基准对比**（回测脚本打印的同期买入持有收益率）
2. **Phase 1 SimNow 仿真启动步骤**：① 安装 vnpy_ctp 与 SimNow 仿真账号；② `~/.vntrader/vt_setting.json` 就位；③ 把 `dual_thrust.py` 等 4 个策略文件平铺复制到 vnpy `strategies/` 目录；④ 用 `import_data.py` 把 RU 主力连续分钟数据导入 sqlite（实盘 warmup 依赖）；⑤ 启动 vn_trader → 连接 CTP（SimNow 前置）→ CtaStrategyPro 添加策略（参数照 `dual_thrust_config.json`）→ 启动；⑥ 开通钉钉告警 webhook 并验证收到"网关连接"推送。退出条件勾选：状态机零异常/**信号一致性回放**（取同一交易日分钟数据在 CtaBacktester 重放，与实盘日志信号逐一比对，一致率 100%）/断线重连与 14:55 强平实测通过
3. **Phase 2 实盘试运行**：换成实盘 CTP 账号；首日 1 手；每日盘后核对项——当日成交与核心状态日志一致、手续费滑点 vs 回测假设偏差、日亏损是否触及 2% 熔断线；连续 2 周正常后进入 Phase 3 加仓
4. **应急处理卡**：持仓不一致（策略自动停机→人工核对柜台仓位→手动平齐后重启）；行情中断（自动禁开仓，观察是否 5 分钟内恢复）；废单（当日禁开仓，查 reject_reason）；进程崩溃（Windows 任务计划/服务守护，重启后按第 2 条流程恢复）；换月（交割月前切换到新主力合约并重新导入新合约数据）

- [ ] **Step 5: 验证 JSON 与日历格式**

```bash
.venv/Scripts/python -c "
import json, sys
sys.path.insert(0, 'strategies')
from trading_calendar import TradingCalendar
for p in ('config/vt_setting.json', 'config/dual_thrust_config.json'):
    json.load(open(p, encoding='utf-8')); print(p, 'OK')
cal = TradingCalendar.from_json('config/trading_calendar.json')
assert not cal.is_trading_day('2026-10-01')
assert cal.is_trading_day('2026-01-05')
print('calendar OK', len(cal.holidays), 'holidays')
"
```

Expected: 三个文件均 OK

- [ ] **Step 6: Commit**

```bash
git add config/vt_setting.json config/dual_thrust_config.json config/trading_calendar.json docs/deployment-checklist.md
git commit -m "feat: 实盘配置（vn.py/风控/日历）与上线检查清单

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 完成标准（全部任务验收）

- [ ] `pytest` 全量通过（Task 2–6 共约 43 个用例）
- [ ] `docs/algorithm/dual-thrust-算法文档.md` 与 spec 逐条一致
- [ ] 合成数据端到端回测产出权益曲线图 + 日/月/年绩效 CSV
- [ ] 交付物清单（spec 第 8 章 6 项）全部落盘并已提交 `feat/dual-thrust` 分支
- [ ] 真实 RU 数据到位后：跑通 `import_data.py` → `run_backtest.py`（样本内/外分区间各跑一次），对照 spec 6.3 验收门槛决定是否进入 Phase 1
