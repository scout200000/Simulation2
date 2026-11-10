"""运行一轮批量 Agent 决策。

用法::

    python backend/scripts/run_batch_decision.py --max-agents 30 --workers 5
"""

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.batch_decision import main  # noqa: E402


if __name__ == "__main__":
    main()
