"""Entry point for the doc audit test suite.

Usage:
    python -m tests.manual.doc_audit                   # run all audits
    python -m tests.manual.doc_audit retry_reprompt     # run one by name
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from tests.manual.doc_audit.harness import DocAudit, aggregate_summary

_PKG_DIR = Path(__file__).resolve().parent


def _discover_modules() -> list[str]:
    """Return module stems for every test_*.py in this package."""
    return sorted(p.stem for p in _PKG_DIR.glob("test_*.py") if p.stem != "__init__")


def _run_module(stem: str) -> DocAudit:
    """Import ``tests.manual.doc_audit.<stem>`` and call its ``run_audit()``."""
    mod = importlib.import_module(f"tests.manual.doc_audit.{stem}")
    if not hasattr(mod, "run_audit"):
        print(f"  SKIP  {stem} (no run_audit function)")
        return DocAudit(name=stem)
    return mod.run_audit()


def main() -> int:
    filter_name = sys.argv[1] if len(sys.argv) > 1 else None

    modules = _discover_modules()
    if filter_name:
        target = f"test_{filter_name}" if not filter_name.startswith("test_") else filter_name
        modules = [m for m in modules if m == target]
        if not modules:
            print(f"No audit module matching '{filter_name}'. Available:")
            for m in _discover_modules():
                print(f"  {m.removeprefix('test_')}")
            return 1

    if len(modules) == 1:
        return _run_module(modules[0]).summary()

    results: list[tuple[str, DocAudit]] = []
    for stem in modules:
        audit = _run_module(stem)
        results.append((stem.removeprefix("test_"), audit))

    return aggregate_summary(results)


if __name__ == "__main__":
    sys.exit(main())
