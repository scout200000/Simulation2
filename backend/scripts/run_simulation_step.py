"""运行当前时间步的单轮仿真。

实验编排器也会通过 ``python -m workers.simulation_tasks.run_step`` 调用同一入口。

用法::

    python backend/scripts/run_simulation_step.py --max-agents 30 --workers 5
"""

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.simulation.runner import main  # noqa: E402


if __name__ == "__main__":
    main()
