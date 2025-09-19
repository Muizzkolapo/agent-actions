import os
import sys
from pathlib import Path


def pytest_configure():
    # Ensure project root is on sys.path for imports during tests.
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

