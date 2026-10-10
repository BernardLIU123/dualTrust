"""策略胶水冒烟测试：用假引擎实例化，验证信号执行与风控门控。"""
from datetime import datetime

from vnpy.trader.constant import Direction, Exchange, Interval, Offset, Status
from vnpy.trader.object import BarData, OrderData

from dual_thrust import DualThrustStrategy
from dual_thrust_core import DayState


class FakeEngine:
    """CtaTemplate 所需的最小引擎接口（按安装的 vnpy 4.0.0 / vnpy_ctastrategy 1.4.1 核对）。

    vnpy 4.x 适配（相对计划假定 vnpy 3.x）：
    - CtaTemplate.write_log 调用 engine.write_log(msg, strategy) → 需第二参数；
    - CtaTemplate.load_bar 调用 engine.load_bar(vt_symbol, days, interval, callback,
      use_database) 并迭代其返回值 → 需首参 vt_symbol 且返回空列表。
    """

    def __init__(self):
        import queue
        from vnpy.event import EventEngine
        self.event_engine = EventEngine()
        self.callback_queue = queue.Queue()
        self.sent: list[dict] = []

    def write_log(self, msg: str, strategy=None) -> None:
        pass

    def send_order(self, strategy, direction, offset, price, volume, stop, lock, net):
        self.sent.append({"direction": direction, "offset": offset,
                          "price": price, "volume": volume})
        return ["fake-1"]  # 模拟真实引擎：返回 vt_orderid 列表（vnpy 4.0 与 3.x 一致）

    def get_gateway_name(self, strategy):
        return "CTP"

    def load_bar(self, vt_symbol, days, interval, callback, use_database):
        return []  # 测试不预热历史

    def cancel_all(self, strategy):
        pass


def make_vn_bar(day, hh, mm, o, h, l, c, limit_up=0.0, limit_down=0.0):
    # vnpy 4.0 的 BarData 为纯 dataclass，无 limit_up/limit_down 字段（3.x 有）
    # → 构造后动态挂载，策略侧以 getattr 读取
    bar = BarData(
        gateway_name="CTP", symbol="ru2601", exchange=Exchange.SHFE,
        datetime=datetime(2026, 1, day, hh, mm), interval=Interval.MINUTE,
        open_price=o, high_price=h, low_price=l, close_price=c, volume=1.0,
    )
    bar.limit_up = limit_up
    bar.limit_down = limit_down
    return bar


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


def test_blocked_entry_rolls_back_and_rearms():
    engine, s = make_strategy()
    s.on_init()
    s.trading = True
    for i in range(15):
        s.on_bar(make_vn_bar(5, 21, i % 60, 105, 110, 100, 105))
    s.market_stale = True
    s.on_bar(make_vn_bar(5, 21, 15, 116, 117, 114, 116))  # 阻止 + 回退
    assert engine.sent == []
    assert s.core.state is DayState.ARMED
    s.market_stale = False
    s.on_bar(make_vn_bar(5, 21, 16, 116, 117, 114, 116))  # 恢复后再次突破 → 正常入场
    assert len(engine.sent) == 1
    assert not s.halted


def test_segment_break_not_stale():
    engine, s = make_strategy()
    s.on_init()
    s.trading = True
    for i in range(15):
        s.on_bar(make_vn_bar(5, 21, i % 60, 105, 110, 100, 105))
    # 夜盘连续收盘（21:15–22:59 无缺口）
    for i in range(15, 120):
        s.on_bar(make_vn_bar(5, 21 + i // 60, i % 60, 105, 110, 100, 105))
    s.on_bar(make_vn_bar(5, 23, 0, 105, 110, 100, 105))   # 夜盘收盘
    s.on_bar(make_vn_bar(6, 9, 0, 106, 111, 101, 106))   # 次日日盘开盘（合法时段间隔）
    assert s.market_stale is False


def test_within_segment_gap_is_stale():
    engine, s = make_strategy()
    s.on_init()
    s.trading = True
    for i in range(15):
        s.on_bar(make_vn_bar(5, 21, i % 60, 105, 110, 100, 105))
    s.on_bar(make_vn_bar(6, 9, 0, 105, 110, 100, 105))    # 时段开盘（合法间隔）
    s.on_bar(make_vn_bar(6, 9, 5, 105, 110, 100, 105))    # 正常
    # 段内 9:05→9:20 缺口 15 分钟 → 判中断，开仓被阻止并回退
    s.on_bar(make_vn_bar(6, 9, 20, 116, 117, 114, 116))
    assert s.market_stale is True
    assert engine.sent == []
    assert s.core.state is DayState.ARMED


def test_exit_uses_fixed_size_when_stale():
    engine, s = make_strategy()
    s.on_init()
    s.trading = True
    for i in range(15):
        s.on_bar(make_vn_bar(5, 21, i % 60, 105, 110, 100, 105))
    s.on_bar(make_vn_bar(5, 21, 15, 116, 117, 114, 116))  # 正常入场 LONG
    s.pos = 1  # 模拟成交同步
    s.market_stale = True
    s.on_bar(make_vn_bar(5, 21, 16, 95, 96, 90, 95))  # 击穿止损 → SELL
    exits = [o for o in engine.sent
             if o["direction"] == Direction.SHORT and o["offset"] == Offset.CLOSE]
    assert exits
    assert exits[-1]["volume"] == s.fixed_size


def test_rejected_entry_rolls_back():
    engine, s = make_strategy()
    s.on_init()
    s.trading = True
    for i in range(15):
        s.on_bar(make_vn_bar(5, 21, i % 60, 105, 110, 100, 105))
    s.on_bar(make_vn_bar(5, 21, 15, 116, 117, 114, 116))  # 入场 BUY（FakeEngine 返回 "fake-1"）
    assert len(engine.sent) == 1
    order = OrderData(gateway_name="fake", symbol="ru2601", exchange=Exchange.SHFE,
                      orderid="1", direction=Direction.LONG, offset=Offset.OPEN,
                      status=Status.REJECTED)
    order.vt_orderid = "fake-1"  # 与 FakeEngine 返回的假 orderid 对齐
    s.on_order(order)
    assert s.core.state is DayState.ARMED  # 异步拒单 → 回退待命
    assert s.halted is False
    # 拒单后当日禁止开仓：再喂突破 bar 不再发单
    s.on_bar(make_vn_bar(5, 21, 16, 116, 117, 114, 116))
    assert len(engine.sent) == 1
    # 再喂一根无信号 bar：一致性校验不触发停机死链
    s.on_bar(make_vn_bar(5, 21, 17, 105, 110, 100, 105))
    assert s.halted is False
