"""兼容入口 —— 回归已迁至 tests/harness.py,运行时代码不依赖本文件。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.harness import run_suite

if __name__ == "__main__":
    raise SystemExit(run_suite())
