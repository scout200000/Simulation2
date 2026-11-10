"""生成一轮增量评论。

用法::

    python backend/scripts/generate_incremental_comments.py --count 20
"""

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.comments.incremental_generator import main  # noqa: E402


if __name__ == "__main__":
    main()
