"""运行一次完整仿真实验（生成评论池 + 全部回应策略对照）。

用法::

    python backend/scripts/run_simulation.py
"""

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main.cli import run_complete_simulation  # noqa: E402


if __name__ == "__main__":
    run_complete_simulation()
