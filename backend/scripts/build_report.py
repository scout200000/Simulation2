"""根据实验批次生成报告数据。

用法::

    python backend/scripts/build_report.py \
        --experiment event_gaoyang_assault_001_20261020_141414_286129 \
        --out var/reports/report-gaoyang-rule.json
"""

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.evaluation.build_report_data import main  # noqa: E402


if __name__ == "__main__":
    main()
