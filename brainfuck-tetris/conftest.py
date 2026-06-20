import os
import sys

# Make `src` importable as a top-level package and the repo root importable so
# that `from src.oracle import run_bf` works regardless of the pytest rootdir.
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
