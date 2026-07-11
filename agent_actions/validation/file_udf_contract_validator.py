"""Flag FILE-granularity UDFs whose return annotation is not FileUDFResult."""

from __future__ import annotations

from typing import Any

from agent_actions.config.types import Granularity
from agent_actions.utils.udf_management.registry import FileUDFResult


def _returns_fileudfresult(annotation: Any) -> bool:
    # Coarse name check by design: class identity, or the name text mentions
    # FileUDFResult (covers string forward-refs). It reads only what is already
    # recorded — never imports or resolves the annotation, which could fail.
    if annotation is FileUDFResult:
        return True
    name = getattr(annotation, "__name__", None) or (
        annotation if isinstance(annotation, str) else ""
    )
    return "FileUDFResult" in str(name)


def find_file_udf_contract_warnings(
    registry: dict[str, dict], referenced: set[str] | None = None
) -> list[str]:
    """Return one warning per FILE-mode UDF whose return annotation is not FileUDFResult.

    When *referenced* is given, only UDFs named in it are checked — the warning
    predicts a runtime crash, which can only happen for UDFs the workflow calls.
    """
    refs_lower = {r.lower() for r in referenced} if referenced is not None else None
    warnings: list[str] = []
    for meta in registry.values():
        if meta.get("granularity") is not Granularity.FILE:
            continue
        if refs_lower is not None and meta["name"].lower() not in refs_lower:
            continue
        annotation = meta["signature"].return_annotation
        if _returns_fileudfresult(annotation):
            continue
        warnings.append(
            f"FILE-mode UDF '{meta['name']}' returns {annotation!r}, not FileUDFResult. "
            f"If it constructs new dicts, wrap them in FileUDFResult(outputs=[{{source_index, data}}]); "
            f"if it round-trips input items unchanged (filter mode), this is safe to ignore."
        )
    return warnings
