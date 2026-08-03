"""Make ``sandbox_widget`` importable from ``src/`` without an editable install.

Lets ``pytest test/`` work straight from a checkout (the ``pixi run test`` task,
CI) whether or not ``pixi run install-dev`` has been run. There is deliberately no
``__init__.py`` beside the tests: it would make pytest walk the parent tree to find
a package root, which is slow/unreliable on cloud-synced drives.
"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if os.path.isdir(SRC) and SRC not in sys.path:
    sys.path.insert(0, SRC)
