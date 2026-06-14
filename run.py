#!/usr/bin/env python3
"""Entry point for Lifeboard menu bar app.

Automatically activates the project's .venv if it exists, so users can run
this with any Python and still get the correct dependencies.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(HERE, ".venv")
VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python")

# If a .venv exists but we're not running from it, re-exec with the venv Python.
# We check VIRTUAL_ENV rather than comparing executable paths, because venv
# symlinks resolve to the same binary and path comparison fails.
if os.path.isfile(VENV_PYTHON) and os.environ.get("VIRTUAL_ENV") != VENV_DIR:
    os.environ["VIRTUAL_ENV"] = VENV_DIR
    os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)

sys.path.insert(0, HERE)

from lifeboard.app import main

if __name__ == "__main__":
    main()
