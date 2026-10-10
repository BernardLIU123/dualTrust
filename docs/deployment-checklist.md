# Dual Thrust 实盘部署与上线检查清单

> 本清单是 Phase 0 → 3 四阶段上线的操作与验收依据。
> 参数取值来源：`config/dual_thrust_config.json`（策略/风控/告警）与 `config/trading_calendar.json`（2026 交易日历）；
> vn.py 全局配置来源：`config/vt_setting.json`（复制到 `~/.vntrader/vt_setting.json`）。
> 每条均为勾选项，全部勾选后才能进入下一阶段。**本机环境：Python 3.14.3 + vnpy 4.0.0 + vnpy_ctastrategy 1.4.1。**

---

## Phase 0：回测确认（进入 Phase 1 的硬门槛）

真实 RU 主力连续分钟数据到位后，跑通 `tools/import_data.py` → `tools/run_backtest.py`（样本内/样本外分区间各跑一次），对照 spec 6.3 验收门槛逐项勾选：

### 0.1 验收门槛（6 项，全部达标才放行）

- [ ] **夏普比率 ≥ 1.0**：`run_backtest.py` 控制台统计 `sharpe_ratio`（样本内与样本外均看）
- [ ] **最大回撤 ≤ 20%**：控制台统计 `max_drawdown`
- [ ] **样本外/样本内绩效比 ≥ 60%**：样本外收益（或夏普）÷ 样本内对应值
- [ ] **成本占比 ≤ 30%**：见 0.3 的成本占比核对步骤
- [ ] **正收益年份 ≥ 60%**：`output/backtest/yearly_pnl.csv` 中 net_pnl > 0 的年份占比
- [ ] **参数微扰 ≤ 25%**：`run_backtest.py --sensitivity` 输出（k1/k2/窗口/ATR 微扰后绩效相对基准的偏移幅度）

### 0.2 真实数据导入与校验

- [ ] `tools/import_data.py --csv <真实RU分钟CSV> --dry-run` 校验通过（无 [错误] 项）
- [ ] 段内真实缺口 warning 逐条核对完毕（见"已知限制与验证项"第 4 条：时段间隔类 warning 可忽略）
- [ ] 正式导入 sqlite：`tools/import_data.py --csv ... --symbol ruXXXX --calendar config/trading_calendar.json`（无 `--dry-run`）

### 0.3 成本占比核对

- [ ] 读取 `output/backtest/daily_stats.csv`：`(commission + slippage 两列合计) ÷ 毛利（trading_pnl 或 net_pnl + commission + slippage）≤ 30%`
- [ ] 记录算式与结果，成本占比超标则先优化参数/过滤低质量信号，不得进入 Phase 1

### 0.4 日线版对照（证明分钟级改造的增量价值）

- [ ] 用 vn.py 自带 DualThrust 样例策略，以 **DAILY** 区间回测同一合约同一时间段
- [ ] 记录两个版本的核心指标（收益、夏普、回撤、成本占比）对比结论
- [ ] 结论须明确：分钟级版本相较日线版是否有增量价值（收益更高或回撤更小且成本可控），否则退回重新评估

### 0.5 基准对比

- [ ] 记录 `run_backtest.py` 打印的"基准（同期买入持有）收益率"
- [ ] 确认策略收益 ≥ 买入持有基准（显著跑输基准则退回评估）

### 0.6 决策门

- [ ] 以上全部勾选 → 书面记录回测结论与参数（k1/k2/window/ATR/止损倍数）→ 进入 Phase 1
- [ ] 任一门槛未达 → 不进入 Phase 1，回到参数寻优（`run_backtest.py --optimize`）

---

## Phase 1：SimNow 仿真

### 1.1 准备（按序执行）

- [ ] **① CTP 网关与 Python 3.14 兼容性**（本机 3.14.3 无 vnpy_ctp wheel，见"已知限制与验证项"第 1 条）：
  - [ ] 方案 A（推荐，立即可用）：另建 Python 3.11/3.12 环境（如 `py -3.12 -m venv ~/.venv-live` → 激活 → `pip install vnpy vnpy_ctastrategy vnpy_ctp`）
  - [ ] 或方案 B：等待 vnpy_ctp 官方 cp314 wheel 发布后直接 `pip install vnpy_ctp` 到本机 3.14 环境
  - [ ] 装好后验证：`python -c "import vnpy_ctp; print('OK')"`
- [ ] **② SimNow 仿真账号**：注册 SimNow（simnow.com.cn），获取仿真前置地址、账号、BrokerID、AppID、AuthCode（AppID/AuthCode 用于穿透式认证）
- [ ] **③ 全局配置就位**：把 `config/vt_setting.json` 复制到 `~/.vntrader/vt_setting.json`（`database.name` 已按本机用户名 `liubo` 填写）
- [ ] **④ 策略文件部署**：把 `strategies/` 下 **4 个文件**（`dual_thrust.py`、`dual_thrust_core.py`、`notifier.py`、`trading_calendar.py`）平铺复制到 vn_trader 启动工作目录的 `strategies/` 子目录（vn.py 按 cwd 加载）
- [ ] **⑤ 实盘 warmup 数据**：用 `tools/import_data.py` 把 RU 主力连续分钟数据导入 sqlite（策略 `on_init` 的 `load_bar(warmup_days)` 依赖该库；目标库与 `vt_setting.json` 的 `database.name` 一致）
- [ ] **⑥ 告警 webhook**：开通钉钉群机器人，把 webhook 填入 `config/dual_thrust_config.json` 的 `alert.dingtalk_webhook` 并把 `alert.enabled` 置 `true`（空 webhook = 告警静默）

### 1.2 启动步骤

- [ ] 启动 `vn_trader`
- [ ] 连接 CTP 网关（SimNow 前置地址 + 仿真账号 + AppID/AuthCode）
- [ ] CtaStrategyPro 面板添加 `DualThrustStrategy`，参数照 `config/dual_thrust_config.json` 的 `strategy` 段逐项填入（**`dingtalk_webhook` 与 `calendar_path` 已在 parameters 列表，可直接在参数面板或 setting dict 注入**，见"已知限制与验证项"第 5 条；`calendar_path` 填 `config/trading_calendar.json`）
- [ ] 风控参数照 `config/dual_thrust_config.json` 的 `risk` 段在风控模块配置（spec 5.1 第三层：日亏 2% 熔断、回撤 20% 全面停策略，**每日盘前由交易员复核**）
- [ ] 启动策略 → 观察初始化日志：历史 bar 预热成功、无异常
- [ ] 验证告警链路：确认能收到策略告警推送（注意 vnpy 4.0 无 EVENT_GATEWAY，"网关连接"推送已不可用，改用其他告警事件验证，见"已知限制与验证项"第 3 条）

### 1.3 仿真期每日核对

- [ ] 状态机当日无异常（日志无"持仓不一致停机"、无未预期 rollback）
- [ ] 下单/撤单/成交回报与日志一致
- [ ] 14:50 持仓预警与 14:55 强平按预期触发

### 1.4 退出条件（全部勾选才进入 Phase 2）

- [ ] **状态机零异常**：仿真期间核心状态机（ARMED→LONG/SHORT→平仓）无一次异常迁移或停机死链
- [ ] **信号一致性回放**：取同一交易日分钟数据在 CtaBacktester 重放，与实盘（仿真）日志信号逐一比对，**一致率 100%**
- [ ] **断线重连实测**：断网/重启网关后策略恢复正常交易（无残留禁开仓状态、无状态失配）
- [ ] **14:55 强平实测**：持隔夜仓到收盘，强平委托按时发出且成交
- [ ] **涨跌停保护核实**（必做，见"已知限制与验证项"第 2 条）：确认 CTP 网关 4.0 是否给 BarData 附加 `limit_up`/`limit_down`；**若不附加，必须先落实替代方案（如 tick 级涨跌停检查）才能进 Phase 2**
- [ ] **行情中断兜底时效实测**：模拟行情中断（如断开行情源），验证 5 分钟无 bar 检测的告警与禁开仓时效，记录实测延迟
- [ ] 告警推送（钉钉）在以上实测场景中均正常触达

---

## Phase 2：实盘试运行（小规模）

- [ ] 换成实盘 CTP 账号（真实前置地址 + 穿透式认证信息）
- [ ] **首日仅 1 手**（`fixed_size = 1`）
- [ ] 每日盘后核对（逐项勾选）：
  - [ ] 当日成交与核心状态日志一致（手数、方向、价格）
  - [ ] 手续费 + 滑点 vs 回测假设（rate 0.00002、slippage 1 tick）的偏差在可接受范围，偏差大则更新回测假设重算成本占比
  - [ ] 日亏损是否触及 2% 熔断线（触及则当日停手并复盘）
- [ ] **连续 2 周正常**（无停机、无误单、风控未熔断）→ 进入 Phase 3 加仓
- [ ] 期间出现任一异常（持仓不一致/废单/熔断）→ 回到 Phase 2 首日流程重新累计观察期

---

## Phase 3：加仓放大

- [ ] 按风险预算分档加仓（如 1 → 2 → 5 手），每档至少观察 1 周且日亏熔断/回撤监控无告警后才加下一档
- [ ] 加仓过程中同步复查：单笔订单量是否触发风控模块 `order_size_limit`、`trade_limit` 等限流参数
- [ ] 达到目标仓位后转常规运营：每日盘前复核风控参数与告警配置，每季度复查回测假设（成本、滑点、流动性）

---

## 应急处理卡

- [ ] **持仓不一致**：策略自动停机 → 人工核对柜台实际仓位 → 手动平齐（柜台与策略一致）→ 按 Phase 2 流程重启策略
- [ ] **行情中断**：策略自动禁开仓（观察是否 5 分钟内恢复）→ 恢复后策略自动解除禁开（仅缺口检测置位的场景）；外部置位需重启策略复位
- [ ] **废单（委托被拒）**：当日禁开仓（`entry_blocked`）→ 查日志中 `reject_reason` 定位原因（保证金/权限/价格越界等）→ 修复后次日恢复
- [ ] **进程崩溃**：Windows 任务计划程序/服务守护 vn_trader 自动拉起 → 重启后按"持仓不一致"条目对账恢复（策略 `on_start` 自带启动对账回退）
- [ ] **换月**：交割月前切换到新主力合约 → 用 `tools/import_data.py` 导入新合约分钟数据 → 更新 `vt_symbol` 与 warmup 数据 → 验证信号正常后切换

---

## 已知限制与验证项（来自各任务审查裁定，上线必读）

1. **vnpy_ctp 与 Python 3.14**：本机 Python 3.14.3 无 vnpy_ctp wheel（无 C++ 编译器无法源码构建）。Phase 1 前二选一：
   - 方案 A：另建 Python 3.11/3.12 venv（`py -3.12 -m venv ~/.venv-live` → 激活 → `pip install vnpy vnpy_ctastrategy vnpy_ctp`），复用本仓库代码（策略 4 文件复制即可，无环境耦合）；
   - 方案 B：等官方 cp314 wheel 发布。
   - 注意：回测/测试仍用本仓库 `.venv`（3.14），实盘网关环境与回测环境分离不影响结果一致性。
2. **涨跌停保护在 vnpy 4.0 惰性**：BarData 无 `limit_up`/`limit_down` 字段（本地已核实 vnpy 4.0.0：BarData 字段无此二项，**TickData 仍带 `limit_up`/`limit_down`**），保护依赖上游动态附加，默认 0 = 不拦截。Phase 1 必须核实：CTP 网关 4.0 是否给 BarData 附加该字段（以 TickData 仍带该字段为线索，在网关生成 bar 的路径上检查）；**若不附加，Phase 2 实盘前必须另找方案（如 tick 级涨跌停检查）**。此条已列为 Phase 1 退出条件的显式检查项。
3. **网关断线告警在 vnpy 4.0 不可用**（EVENT_GATEWAY 事件已移除，策略 `on_init` 会写日志提示）：断线由"行情中断（5 分钟无 bar）"检测兜底（`market_stale_seconds = 300`）。Phase 1 需实测验证兜底时效（从断线到告警/禁开仓的延迟）。
4. **数据导入缺口告警的已知误报**：`import_data.py` 的缺 bar 检测会把合法的时段间隔（夜盘→日盘、午休、10:15 小节休息、收盘→夜盘开盘）算作 warning。导入真实数据时这些 warning 可忽略，但**段内真实缺口 warning 要认真核对**（缺失分钟数较多会影响策略信号）。
5. **告警推送 webhook 配置方式**：`dingtalk_webhook` 与 `calendar_path` 已加入策略 `parameters` 列表（Task 5 审查裁定落地），可通过 CtaStrategyPro 的参数面板或 setting dict 注入；`config/dual_thrust_config.json` 的 `alert` 段作为取值来源，**启动时人工填入参数面板**（`enabled: true` 时才发送；webhook 留空 = 静默）。
