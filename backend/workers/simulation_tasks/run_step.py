"""单轮仿真子进程入口（供实验编排器调用）。"""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.simulation.runner import main  # noqa: E402


if __name__ == "__main__":
    main()
