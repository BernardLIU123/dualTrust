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
