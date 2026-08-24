# -*- coding: utf-8 -*-
"""python -m epubforge 入口。"""
import os
import sys

_DEPS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".deps")
if os.path.isdir(_DEPS) and _DEPS not in sys.path:
    sys.path.insert(0, _DEPS)

from .gui import main  # noqa: E402

if __name__ == "__main__":
    main()
