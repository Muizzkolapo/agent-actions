"""Validate BISAC classification codes against the official 2021 BISAC list (5,128 codes).

Loads the full BISAC code → description mapping from seed data and validates
that LLM-generated codes are real. Suggests corrections for invalid codes
by matching against the official list.
"""

import json
import os
from typing import Any

from agent_actions import udf_tool

# Load BISAC codes from seed data
_BISAC_CODES: dict[str, str] = {}
_BISAC_BY_PREFIX: dict[str, list[tuple[str, str]]] = {}


def _load_bisac_codes() -> None:
    """Load BISAC codes from seed data JSON."""
    global _BISAC_CODES, _BISAC_BY_PREFIX

    if _BISAC_CODES:
        return

    seed_path = os.path.join(
        os.path.dirname(__file__),
        "../../agent_workflow/book_catalog_enrichment/seed_data/bisac_codes.json",
    )
    seed_path = os.path.normpath(seed_path)

    if not os.path.exists(seed_path):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        seed_path = os.path.join(
            base_dir,
            "agent_workflow/book_catalog_enrichment/seed_data/bisac_codes.json",
        )

    if os.path.exists(seed_path):
        with open(seed_path, encoding="utf-8") as f:
            _BISAC_CODES.update(json.load(f))

        for code, desc in _BISAC_CODES.items():
            prefix = code[:3]
            _BISAC_BY_PREFIX.setdefault(prefix, []).append((code, desc))


def _find_closest_code(invalid_code: str) -> tuple[str, str]:
    """Find the closest valid BISAC code for an invalid one."""
    _load_bisac_codes()

    prefix = invalid_code[:3].upper() if len(invalid_code) >= 3 else ""

    # Try exact prefix match — return the general code (suffix 000000)
    if prefix in _BISAC_BY_PREFIX:
        general_code = f"{prefix}000000"
        if general_code in _BISAC_CODES:
            return general_code, _BISAC_CODES[general_code]
        # Return first code in that prefix
        return _BISAC_BY_PREFIX[prefix][0]

    return "", ""


@udf_tool()
def validate_bisac_codes(data: dict[str, Any]) -> dict[str, Any]:
    """Validate BISAC codes against the official 5,128-code list.

    Checks each code exists in the real BISAC standard. For invalid codes,
    suggests the closest valid alternative from the same prefix.
    """
    _load_bisac_codes()

    primary_code = data.get("primary_bisac_code", "")
    primary_name = data.get("primary_bisac_name", "")
    secondary_codes = data.get("secondary_bisac_codes", [])

    validation_notes = []
    all_codes = []
    all_names = []

    # Validate primary code
    if primary_code:
        code_upper = primary_code.upper().strip()

        if code_upper in _BISAC_CODES:
            all_codes.append(code_upper)
            # Use official name, not LLM-generated one
            all_names.append(_BISAC_CODES[code_upper])
        else:
            # Code not in official list — try to find closest
            suggested_code, suggested_name = _find_closest_code(code_upper)
            if suggested_code:
                validation_notes.append(
                    f"Primary code '{code_upper}' not in official BISAC list. "
                    f"Corrected to '{suggested_code}' ({suggested_name})"
                )
                all_codes.append(suggested_code)
                all_names.append(suggested_name)
            else:
                validation_notes.append(
                    f"Primary code '{code_upper}' not recognized and no close match found"
                )
                all_codes.append(code_upper)
                all_names.append(primary_name or "Unknown")

    # Validate secondary codes
    for code in secondary_codes:
        if not code:
            continue
        code_upper = code.upper().strip()
        if code_upper in all_codes:
            continue  # Skip duplicates

        if code_upper in _BISAC_CODES:
            all_codes.append(code_upper)
            all_names.append(_BISAC_CODES[code_upper])
        else:
            suggested_code, suggested_name = _find_closest_code(code_upper)
            if suggested_code and suggested_code not in all_codes:
                validation_notes.append(
                    f"Secondary code '{code_upper}' corrected to '{suggested_code}'"
                )
                all_codes.append(suggested_code)
                all_names.append(suggested_name)

    # Fallback if no valid codes
    if not all_codes:
        validation_notes.append("No valid BISAC codes provided")
        all_codes = ["COM000000"]
        all_names = [_BISAC_CODES.get("COM000000", "Computers / General")]
        validation_notes.append("Defaulted to COM000000 (Computers / General)")

    return {
        "bisac_valid": len(validation_notes) == 0,
        "bisac_codes": all_codes,
        "bisac_names": all_names,
        "validation_notes": "; ".join(validation_notes) if validation_notes else "All codes valid",
    }
