"""File I/O utilities for loading structured data files."""

from __future__ import annotations

import json
import tokenize
from pathlib import Path
from typing import Any

import yaml


def load_structured_file(path: Path) -> Any:
    """Load a JSON or YAML file based on its extension.

    Returns the parsed content.  Raises ``json.JSONDecodeError`` for
    malformed JSON, ``yaml.YAMLError`` for malformed YAML, and
    ``ValueError`` for empty files.
    """
    with open(path, encoding="utf-8") as f:
        if path.suffix == ".json":
            return json.load(f)
        result = yaml.safe_load(f)
        if result is None:
            raise ValueError(f"Empty or null YAML file: {path}")
        return result


def read_python_source(path: Path) -> str:
    """Read a ``.py`` file the way the import machinery would.

    Honours the PEP 263 encoding cookie and a UTF-8 BOM. Reading user tool
    files as plain UTF-8 silently drops any that declare another encoding —
    ``UnicodeDecodeError`` is a ``ValueError``, so a broad handler swallows it
    and the file disappears from discovery or analysis.

    Raises ``SyntaxError`` when the encoding declaration is bad or missing for
    non-UTF-8 bytes; callers must handle it alongside ``OSError``/``ValueError``.
    """
    with tokenize.open(path) as handle:
        return handle.read()
