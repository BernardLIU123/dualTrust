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
