"""Validate BISAC classification codes."""

from agent_actions import udf_tool

# Valid BISAC code prefixes for technical/computing books
VALID_BISAC_PREFIXES = [
    "COM",  # Computers
    "BUS",  # Business
    "TEC",  # Technology
    "SCI",  # Science
    "MAT",  # Mathematics
    "EDU",  # Education
]


@udf_tool()
def validate_bisac_codes(data: dict) -> dict:
    """Validate BISAC codes and normalize format."""
    primary_code = data.get("primary_bisac_code", "")
    primary_name = data.get("primary_bisac_name", "")
    secondary_codes = data.get("secondary_bisac_codes", [])

    validation_notes = []
    all_codes = []
    all_names = []

    # Validate primary code format
    if primary_code:
        # BISAC codes are typically 9 characters: 3 letters + 6 digits
        code_upper = primary_code.upper().strip()
        prefix = code_upper[:3] if len(code_upper) >= 3 else ""

        if prefix in VALID_BISAC_PREFIXES:
            all_codes.append(code_upper)
            all_names.append(primary_name)
        else:
            validation_notes.append(f"Primary code '{primary_code}' has unusual prefix")
            # Still include it but flag it
            all_codes.append(code_upper)
            all_names.append(primary_name)

    # Validate secondary codes
    for code in secondary_codes:
        if code:
            code_upper = code.upper().strip()
            if code_upper not in all_codes:
                all_codes.append(code_upper)

    # Check for minimum classification
    if not all_codes:
        validation_notes.append("No BISAC codes provided")
        # Default to general programming
        all_codes = ["COM051000"]
        all_names = ["Programming / General"]
        validation_notes.append("Defaulted to COM051000 (Programming / General)")

    return {
        "bisac_valid": len(validation_notes) == 0,
        "bisac_codes": all_codes,
        "bisac_names": all_names if all_names else [primary_name] if primary_name else ["Unknown"],
        "validation_notes": "; ".join(validation_notes) if validation_notes else "All codes valid",
    }
