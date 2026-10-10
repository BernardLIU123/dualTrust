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
        signals: list[Signal] = []

        if bar.time == self.params.session_start:
            self._start_session(bar)
        elif self._session_date is None:
            if bar.time > self.params.session_start:
                self.state = DayState.ABORTED  # 夜盘开盘 bar 缺失，当日放弃
        elif self.state is DayState.ABORTED:
            pass
        else:
            prev_state = self.state

            if self.state is DayState.COLLECTING:
                signals.extend(self._on_collecting(bar))
            elif self.state is DayState.ARMED:
                signals.extend(self._on_armed(bar))

            # 入场 bar 不检查持有逻辑（止损线在入场时刚建立）
            if self.state in (DayState.LONG, DayState.SHORT) and self.state == prev_state:
                signals.extend(self._on_holding(bar))

        # ATR 在 bar 处理结束后更新：入场/止损价基于入场前的 ATR
        self._update_atr(bar)
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

        # 强平优先（14:55 属日盘时段；夜盘 bar（>= session_start）不受影响）
        if bar.time < self.params.session_start and bar.time >= self.params.force_close_time:
            signals.append(self._close_position(bar.close, "FORCE_CLOSE"))
            return signals

        # 反手优先于止损：close 突破反向轨道时以收盘信号为准
        # （反手 bar 即新仓位入场 bar，不判止损；当日已反向交易过则落止损判定）
        if self.state is DayState.LONG and bar.close < self.lower:
            if not self.short_today:
                signals.append(Signal(Action.SELL, bar.close, "REVERSE_EXIT"))
                self._enter_short(bar.close)
                signals.append(Signal(Action.SHORT, bar.close, "LOWER_BREAK"))
                return signals
        elif self.state is DayState.SHORT and bar.close > self.upper:
            if not self.long_today:
                signals.append(Signal(Action.COVER, bar.close, "REVERSE_EXIT"))
                self._enter_long(bar.close)
                signals.append(Signal(Action.BUY, bar.close, "UPPER_BREAK"))
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
