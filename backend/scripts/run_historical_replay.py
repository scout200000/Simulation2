"""运行历史舆情趋势复现。

用法::

    python backend/scripts/run_historical_replay.py --list-events
    python backend/scripts/run_historical_replay.py --event-id event_huxinyu_2022_001
"""

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.historical_replay.main import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
