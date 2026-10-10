"""Dual Thrust 批量回测与参数寻优脚本。

用法:
  .venv/Scripts/python tools/run_backtest.py --csv data/ru_1min.csv --symbol ru2601 \\
      --start 2023-01-01 --end 2025-12-31
  .venv/Scripts/python tools/run_backtest.py --csv ... --optimize     # 网格寻优
  .venv/Scripts/python tools/run_backtest.py --csv ... --sensitivity  # 参数微扰检验

vnpy 4.0.0 / vnpy_ctastrategy 1.4.1 适配（相对计划假定 vnpy 3.x，全部最小改动）：
1. calculate_statistics 的 output 参数在 4.0 是 bool（仅控制台打印），不再接受
   路径写 CSV → 改为 output=True 取控制台统计，自行将日线 DataFrame 落盘
   daily_stats.csv（date 为索引，index=True 写出，读回后即 date 列）。
2. 4.0 统计字典无 daily_win_rate 键 → 由 profit_days / total_days 自行计算注入。
3. 4.0 的 run_optimization 用 ProcessPoolExecutor(spawn) 在子进程里新建引擎并
   调用 load_data() 读真实数据库，主进程注入的 history_data 与 monkeypatch 都
   无法跨进程生效 → 改为本进程内网格循环：OptimizationSetting.generate_settings()
   逐组 build_engine（与 run_single 同一注入路径）回测并自行写 optimization.csv。
4. 策略 on_init 的 load_bar 预热在 4.0 回测模式下会查一次真实数据库（结果为空，
   无害；首次可能创建 ~/.vntrader/database.db，属引擎既有行为）。
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


def _build_engine(args, setting: dict, bars: list) -> BacktestingEngine:
    """以已转换的 bars 构造引擎（history_data 直接注入，4.0 已验证 run_backtesting
    读 self.history_data 且会置 trading=True 并调用 on_start）。"""
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
    engine.history_data = [b for b in bars if engine.start <= b.datetime <= engine.end]
    # 注：vn.py 回测引擎不建模保证金占用（盈亏按余额计），起始资金 10 万已覆盖 1 手保证金需求（spec 6.1）
    engine.add_strategy(DualThrustStrategy, setting)
    return engine


def build_engine(args, setting: dict) -> BacktestingEngine:
    df = read_csv(args.csv)
    bars = to_bar_data(df, args.symbol, getattr(Exchange, args.exchange))
    return _build_engine(args, setting, bars)


def run_single(args, setting: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = build_engine(args, setting)
    engine.run_backtesting()

    df: pd.DataFrame = engine.calculate_result()
    # 4.0：output 为 bool 仅打印控制台统计；日线 CSV 自行落盘（date 为索引）
    stats: dict = engine.calculate_statistics(output=True)
    if df.empty:
        return stats
    df.to_csv(output_dir / "daily_stats.csv", index=True)
    if "daily_win_rate" not in stats and stats.get("total_days"):
        stats["daily_win_rate"] = stats["profit_days"] / stats["total_days"] * 100

    if "balance" in df.columns:
        # 英文标题：默认 DejaVu Sans 无 CJK 字形，中文标题会渲染为方框
        df["balance"].plot(title=f"DualThrust {args.symbol} Equity Curve")
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
    # 4.0：engine.run_optimization 在 spawn 子进程中经真实数据库 load_data，
    # 无法使用注入的 history_data → 改为本进程网格循环（见模块 docstring 适配 3）
    df = read_csv(args.csv)
    bars = to_bar_data(df, args.symbol, getattr(Exchange, args.exchange))

    setting = OptimizationSetting()
    setting.set_target("sharpe_ratio")
    setting.add_parameter("window_minutes", 10, 30, 10)
    setting.add_parameter("k1", 0.2, 0.9, 0.1)
    setting.add_parameter("k2", 0.2, 0.9, 0.1)
    setting.add_parameter("stop_atr_mult", 1.5, 2.5, 0.5)

    settings = setting.generate_settings()
    results = []
    for i, s in enumerate(settings, 1):
        engine = _build_engine(args, s, bars)
        engine.run_backtesting()
        engine.calculate_result()
        stats = engine.calculate_statistics(output=False)
        results.append((s, stats.get("sharpe_ratio", 0), stats))
        if i % 50 == 0:
            print(f"寻优进度: {i}/{len(settings)}")

    rows = []
    for params, target, stats in sorted(results, key=lambda x: x[1], reverse=True):
        rows.append({**params,
                     "sharpe_ratio": target,
                     "total_return": stats.get("total_return"),
                     "annual_return": stats.get("annual_return"),
                     "max_drawdown": stats.get("max_drawdown"),
                     "total_trade_count": stats.get("total_trade_count")})
    pd.DataFrame(rows).to_csv(output_dir / "optimization.csv", index=False)

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
                         "sharpe": stats.get("sharpe_ratio")})
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

        def _jsonable(v):
            # 4.0 统计值含 numpy 标量（如 total_trade_count 为 np.int64），
            # json.dumps 无法序列化 → 统一转原生类型
            import numpy as np
            if isinstance(v, np.integer):
                return int(v)
            if isinstance(v, np.floating):
                return float(v)
            return v

        print(json.dumps({k: _jsonable(stats.get(k)) for k in keys}, indent=2))


if __name__ == "__main__":
    main()
