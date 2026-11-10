"""运行单个 Agent 的认知决策调试脚本。

用法::

    python backend/scripts/decide_agent.py
"""

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.decision_service import main  # noqa: E402


if __name__ == "__main__":
    main()
