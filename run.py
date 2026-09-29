#!/usr/bin/env python3
"""Convenience launcher: python run.py [--show-window] [--debug]"""

import sys

from cursor_usage_app.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
