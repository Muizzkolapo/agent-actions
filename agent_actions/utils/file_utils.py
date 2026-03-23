"""File I/O utilities for loading structured data files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def load_structured_file(path: Path) -> Any:
    """Load a JSON or YAML file based on its extension.

    Returns the parsed content.  Raises ``json.JSONDecodeError`` for
    malformed JSON and ``yaml.YAMLError`` for malformed YAML.
    """
    with open(path, encoding="utf-8") as f:
        if path.suffix == ".json":
            return json.load(f)
        return yaml.safe_load(f)
