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
    """Read a ``.py`` file the way the import machinery would (PEP 263 cookie, BOM).

    Raises only ``OSError``, ``ValueError`` or ``SyntaxError``. ``LookupError``
    is normalised to ``ValueError`` because ``detect_encoding`` accepts non-text
    codecs that ``TextIOWrapper`` then rejects, and uncaught it would abort a
    whole directory sweep over one file.
    """
    try:
        with tokenize.open(path) as handle:
            return handle.read()
    except LookupError as e:
        raise ValueError(f"{path}: {e}") from e
