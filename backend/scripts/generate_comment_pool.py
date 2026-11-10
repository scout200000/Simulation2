"""生成初始评论池。

用法::

    python backend/scripts/generate_comment_pool.py --count 60 --out var/state/comment_pool.json
"""

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.comments.pool_generator import main  # noqa: E402


if __name__ == "__main__":
    main()
