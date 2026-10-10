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
    # 再突破上轨：long_today 已 True，不再反手开多；high 117 击穿止损 → 止损离场
    sig = feed(core, [make_bar(5, 21, 25, 116, 117, 115, 116)])
    assert sig == [Signal(Action.COVER, 116.0, "STOP_LOSS")]


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
    sig = feed(core, [make_bar(5, 21, 16, 114.5, 115, 113, 114.0)])
    assert sig == [Signal(Action.COVER, 114.0, "STOP_LOSS")]  # max(stop, close)=114


def test_stop_floor_uses_half_range_when_atr_small():
    params = DualThrustParams(stop_atr_mult=0.3)  # atr_stop=3 < 0.5*range=5
    core = DualThrustCore(params)
    feed(core, session_bars(5))
    feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])
    assert core.stop_price == 111.0  # 116 - 5


def test_rollback_entry_simple():
    """胶水阻止入场后回退：状态回 ARMED、方向标志恢复，突破可重新触发。"""
    core = DualThrustCore()
    feed(core, session_bars(5))
    sig = feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])
    assert sig == [Signal(Action.BUY, 116.0, "UPPER_BREAK")]
    core.rollback_entry()
    assert core.state is DayState.ARMED
    assert core.long_today is False
    assert core.entry_price == 0.0 and core.stop_price == 0.0
    # 再喂突破 bar → 重新触发 BUY
    sig = feed(core, [make_bar(5, 21, 16, 116, 117, 114, 116)])
    assert sig == [Signal(Action.BUY, 116.0, "UPPER_BREAK")]
    assert core.state is DayState.LONG


def test_rollback_entry_after_reverse_exit():
    """反手路径回退只撤销被阻止一侧：long_today 保持，short 可重触发，long 不再触发。"""
    core = DualThrustCore()
    feed(core, session_bars(5))
    feed(core, [make_bar(5, 21, 15, 116, 117, 114, 116)])  # 开多
    sig = feed(core, [make_bar(5, 21, 20, 94, 95, 93, 94)])  # 反手 SELL+SHORT
    assert sig == [Signal(Action.SELL, 94.0, "REVERSE_EXIT"),
                   Signal(Action.SHORT, 94.0, "LOWER_BREAK")]
    core.rollback_entry()
    assert core.state is DayState.ARMED
    assert core.long_today is True
    assert core.short_today is False
    # 再喂下破 bar → SHORT 重新触发
    sig = feed(core, [make_bar(5, 21, 25, 94, 95, 93, 94)])
    assert sig == [Signal(Action.SHORT, 94.0, "LOWER_BREAK")]
    # 再喂上破 bar → long_today 仍 True，无 BUY
    sig = feed(core, [make_bar(5, 21, 30, 116, 117, 114, 116)])
    assert not any(s.action is Action.BUY for s in sig)
