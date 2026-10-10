"""Dual Thrust vn.py 策略胶水：CtaTemplate 子类，全部决策委托给 DualThrustCore。

部署：本文件 + dual_thrust_core.py + notifier.py + trading_calendar.py
平铺复制到 vn.py 的 strategies 目录即可加载。

vnpy 4.0.0 / vnpy_ctastrategy 1.4.1 适配（相对计划假定 vnpy 3.x，全部最小改动）：
1. EVENT_GATEWAY 事件与 GatewayData 在 vnpy 4.0 已整体移除（BaseGateway 无
   连接/断开事件）→ 导入守卫，注册跳过并写日志；_on_gateway_event 保留以兼容 3.x。
2. vnpy_ctastrategy 1.4.1 不再导出 Interval → 改从 vnpy.trader.constant 导入
   （CtaTemplate.load_bar 的 interval 参数即该枚举）。
3. CtaTemplate 4.0 不再持有 self.event_engine（3.x 由 __init__ 注入）→ 注册时
   从 self.cta_engine.event_engine 兜底获取。
4. CtaTemplate 4.0 无 active_orders（引擎内部以 strategy_orderid_map 跟踪，策略
   不可见）→ 胶水自维护 _pending_orders（on_order 按状态增删），一致性校验改为
   检查该字典，语义与 3.x 的 active_orders 相同。
5. BarData 4.0 为纯 dataclass，无 limit_up/limit_down 字段 → getattr 读取，
   上游（网关包装/测试）动态挂载时保护生效，否则默认 0 不拦截。
6. OrderData 4.0 无 reject_reason 字段 → getattr 兜底空串。
"""
from datetime import datetime, time

from vnpy.event import Event
from vnpy.trader.constant import Interval, Status
from vnpy.trader.object import BarData, OrderData, TradeData
from vnpy_ctastrategy import CtaTemplate

try:
    from vnpy.trader.event import EVENT_GATEWAY  # vnpy ≤3.x
except ImportError:
    EVENT_GATEWAY = None  # vnpy 4.0 已移除网关连接状态事件

from dual_thrust_core import Action, Bar, DayState, DualThrustCore, DualThrustParams, Signal
from notifier import Notifier
from trading_calendar import TradingCalendar

# 各交易时段开盘时间：时段间的合法间隔（如 15:00→21:00、23:00→9:00）不判行情中断
SEGMENT_OPEN_TIMES = {time(9, 0), time(10, 30), time(13, 30), time(21, 0)}


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

    dingtalk_webhook = ""
    calendar_path = ""

    parameters = [
        "window_minutes", "k1", "k2", "atr_length", "stop_atr_mult",
        "fixed_size", "force_close_minute", "warmup_days",
        "market_stale_seconds", "prewarn_minute",
        "dingtalk_webhook", "calendar_path",
    ]
    variables = ["state", "upper", "lower", "pos", "entry_price", "stop_price"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.core: DualThrustCore | None = None
        self.notifier = Notifier()
        self.calendar: TradingCalendar | None = None
        self.halted = False          # 持仓不一致等致命异常 → 停机
        self.market_stale = False    # 行情中断 → 禁止开仓
        self._stale_by_gap = False   # market_stale 是否由本策略的缺口检测置位（决定能否自动清除）
        self.entry_blocked = False   # 废单 → 当日禁止开仓
        self.last_bar_time: datetime | None = None
        self._prewarned_today = False
        # 待成交委托（vnpy 4.0 无 active_orders，胶水自维护；3.x 语义等价）
        self._pending_orders: dict[str, OrderData] = {}
        # 本策略发出的入场委托 orderid 集合：异步拒单时据此回退核心入场状态
        self._entry_orderids: set = set()
        # variables 列表声明的属性必须在实例上存在（引擎 put_strategy_event 会 getattr）
        self.state = ""
        self.upper = 0.0
        self.lower = 0.0
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
        if EVENT_GATEWAY is not None:
            engine = getattr(self, "event_engine", None) or getattr(self.cta_engine, "event_engine", None)
            if engine is not None:
                engine.register(EVENT_GATEWAY, self._on_gateway_event)
        else:
            self.write_log("当前 vnpy 版本无 EVENT_GATEWAY，网关断线监控不可用（由行情中断检测兜底）")
        self.write_log(f"初始化完成，加载 {self.warmup_days} 天历史 bar 预热")
        self.load_bar(self.warmup_days, Interval.MINUTE, use_database=True)

    def on_start(self) -> None:
        self.halted = False
        self.market_stale = False
        self._stale_by_gap = False
        self.entry_blocked = False
        self._pending_orders.clear()
        self._entry_orderids.clear()
        if self.core is not None and self.core.state in (DayState.LONG, DayState.SHORT) and self.pos == 0:
            self.core.rollback_entry()
            self.write_log("启动对账：核心持仓状态无实际仓位，回退入场")
        self.write_log("策略启动")

    def on_stop(self) -> None:
        self.write_log("策略停止")

    def on_bar(self, bar: BarData) -> None:
        # 时间戳先行更新（重启后首根 bar 不误报行情中断）
        prev_time = self.last_bar_time
        self.last_bar_time = bar.datetime
        if self.core is None or self.halted:
            return

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

    # ---------- 告警封装 ----------
    def _notify(self, level: str, title: str, text: str = "") -> None:
        """告警一律经此封装：网络/回调异常绝不打断交易循环与下单路径。"""
        try:
            {"info": self.notifier.info, "warn": self.notifier.warn,
             "critical": self.notifier.critical}[level](title, text)
        except Exception:
            self.write_log(f"告警发送失败({level}: {title})")

    # ---------- 信号执行 ----------
    def _execute(self, sig: Signal, bar: BarData) -> None:
        if self.market_stale or self.entry_blocked:
            if sig.action in (Action.BUY, Action.SHORT):
                self.write_log(f"开仓信号被阻止: {sig.action.value} {sig.reason}")
                self.core.rollback_entry()  # 核心已入场但委托被阻止 → 回退，避免状态失配停机
                return
        # 涨跌停保护：临近涨跌停不追单（vnpy 4.0 BarData 无该字段，getattr 兜底 0 = 不拦截）
        limit_up = getattr(bar, "limit_up", 0)
        limit_down = getattr(bar, "limit_down", 0)
        if sig.action is Action.BUY and limit_up and sig.price >= limit_up:
            self.write_log(f"接近涨停，放弃开多: {sig.price} >= {limit_up}")
            self.core.rollback_entry()
            return
        if sig.action is Action.SHORT and limit_down and sig.price <= limit_down:
            self.write_log(f"接近跌停，放弃开空: {sig.price} <= {limit_down}")
            self.core.rollback_entry()
            return
        if sig.action is Action.BUY:
            orderids = self.buy(sig.price, self.fixed_size) or []
            self._entry_orderids.update(orderids)  # 记录入场委托，异步拒单时回退核心状态
            self._notify("info", "开多", f"价格 {sig.price:.1f} 触发 {sig.reason}")
        elif sig.action is Action.SHORT:
            orderids = self.short(sig.price, self.fixed_size) or []
            self._entry_orderids.update(orderids)
            self._notify("info", "开空", f"价格 {sig.price:.1f} 触发 {sig.reason}")
        elif sig.action is Action.SELL:
            self.sell(sig.price, self.fixed_size)  # 平仓量恒用 fixed_size（异常路径下 pos 可能未同步为 0）
            self._notify("warn", "平多", f"价格 {sig.price:.1f} 触发 {sig.reason}")
        elif sig.action is Action.COVER:
            self.cover(sig.price, self.fixed_size)
            self._notify("warn", "平空", f"价格 {sig.price:.1f} 触发 {sig.reason}")

    # ---------- 风控与监控 ----------
    def _check_market_stale(self, prev_time, now) -> None:
        if now.time() in SEGMENT_OPEN_TIMES:
            return  # 时段间合法间隔（收盘→下一时段开盘），不判中断
        if prev_time is None:
            return
        if (now - prev_time).total_seconds() > self.market_stale_seconds:
            if not self.market_stale:
                self.market_stale = True
                self._stale_by_gap = True
                self._notify(
                    "critical", "行情中断", f"已 {self.market_stale_seconds} 秒无新 bar，停止开仓")
        elif self._stale_by_gap:
            # 仅自动清除由缺口检测自身置位的标志（bar 恢复正常间隔后自动恢复交易）；
            # 外部置位（网关断开/人工）保持粘性，直到 on_start 复位。
            self.market_stale = False
            self._stale_by_gap = False

    def _check_consistency(self) -> None:
        if self._pending_orders:
            return  # 有待成交委托时不校验
        # vnpy pos 为净持仓：多头为正、空头为负（SHORT 持仓 pos = -fixed_size）
        if self.core.state is DayState.LONG:
            expected = self.fixed_size
        elif self.core.state is DayState.SHORT:
            expected = -self.fixed_size
        else:
            expected = 0
        if self.pos != expected:
            self.halted = True
            msg = f"核心状态 {self.core.state.value}，实际仓位 {self.pos} → 策略停机，需人工核对"
            self._notify("critical", "持仓不一致", msg)
            self.write_log("持仓不一致，策略停机")

    def _prewarn_check(self, bar: BarData) -> None:
        if (self.core.state in (DayState.LONG, DayState.SHORT)
                and bar.datetime.time().minute >= self.prewarn_minute
                and bar.datetime.time().hour == 14
                and not self._prewarned_today):
            self._prewarned_today = True
            self._notify("warn", "强平预警", f"14:50 仍持仓 {abs(self.pos)} 手，14:55 将强平")

    def _on_gateway_event(self, event: Event) -> None:
        # 仅 vnpy ≤3.x 存在 EVENT_GATEWAY；4.0 中本方法不会被注册。
        data = event.data
        get_gateway_name = getattr(self, "get_gateway_name", None)
        if get_gateway_name is not None and data.gateway_name != get_gateway_name():
            return
        if data.status:
            self._notify("info", "网关连接", f"{data.gateway_name} 已连接")
        else:
            self.market_stale = True  # 断线即禁止开仓
            self._notify("critical", "网关断开", f"{data.gateway_name} 连接断开")

    def on_trade(self, trade: TradeData) -> None:
        self._notify(
            "info", "成交回报",
            f"{trade.direction.value} {trade.offset.value} {trade.volume} 手 @ {trade.price}")
        self._sync_variables()

    def on_order(self, order: OrderData) -> None:
        if order.status in (Status.SUBMITTING, Status.NOTTRADED, Status.PARTTRADED):
            self._pending_orders[order.vt_orderid] = order
        else:
            self._pending_orders.pop(order.vt_orderid, None)
            if order.vt_orderid in self._entry_orderids:
                self._entry_orderids.discard(order.vt_orderid)
                if order.status == Status.REJECTED:
                    # 异步拒单（非胶水主动阻止）：核心已入场但无实际仓位 → 回退待命，
                    # 避免下一根无信号 bar 的一致性校验触发永久停机
                    if self.core is not None:
                        self.core.rollback_entry()
                    self.write_log("入场委托被拒，回退待命")
        if order.status == Status.REJECTED:
            self.entry_blocked = True
            self._notify(
                "critical", "委托被拒",
                f"{order.symbol} {order.direction.value} {order.volume} 手："
                f"{getattr(order, 'reject_reason', '')}")

    # ---------- 状态同步 ----------
    def _sync_variables(self) -> None:
        if self.core is None:
            return
        self.state = self.core.state.value
        self.upper = self.core.upper
        self.lower = self.core.lower
        self.entry_price = self.core.entry_price
        self.stop_price = self.core.stop_price
