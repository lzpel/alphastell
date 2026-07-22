#!/usr/bin/env python3
"""stellarator (rust, pyo3) の hello() を python から呼ぶ最小例 (issue #5)。

リポジトリルートで:

    uv run examples/hello.py
"""

from stellarator import hello

hello()
