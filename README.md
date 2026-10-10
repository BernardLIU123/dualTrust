# Dual Thrust 橡胶期货日内突破策略

橡胶期货 RU 分钟级 Dual Thrust 日内突破策略，基于 Python + vn.py 实现。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `requirements.txt` | Python 依赖 |
| `pytest.ini` | pytest 配置 |
| `conftest.py` | pytest 路径注入与共享工具 |
| `strategies/` | CTA 策略（平级模块，可平铺复制到 vn.py） |
| `tools/` | 数据导入与回测工具 |
| `tests/` | 单元测试 |
| `docs/` | 设计文档 |

## 快速开始

1. 创建环境：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

2. 导入数据（见 `tools/import_data.py`）。

3. 回测（见 `tools/run_backtest.py`）。

## 文档

- 算法设计：`docs/algorithm/`
- 规格说明：`docs/superpowers/specs/`

## 风险提示

量化策略仅供研究使用，实盘风险自负。
