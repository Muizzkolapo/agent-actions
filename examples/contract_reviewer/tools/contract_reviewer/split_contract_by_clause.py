"""
Split a contract's full_text into individual numbered clauses.

This is the MAP step of the Map-Reduce pattern: one contract record in,
N clause records out. Each output record contains a single clause ready
for independent risk analysis.
"""

import re
from typing import Any

from agent_actions import udf_tool


# Pattern matches common clause heading formats:
#   "1. DEFINITIONS"
#   "2. SCOPE OF WORK"
#   "Section 1: Definitions"
#   "ARTICLE 1 - DEFINITIONS"
CLAUSE_PATTERN = re.compile(
    r"(?:^|\n)"                         # Start of text or newline
    r"(?:"
    r"(\d+)\.\s+"                       # "1. " style numbering
    r"|Section\s+(\d+)[:\s]+"           # "Section 1:" style
    r"|ARTICLE\s+(\d+)\s*[-:]\s*"       # "ARTICLE 1 -" style
    r")"
    r"([A-Z][A-Z\s&,]+)"               # Title in ALL CAPS
    r"(?:\n|$)",
    re.MULTILINE,
)


@udf_tool()
def split_contract_by_clause(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Split contract full_text into individual clauses using numbered heading patterns.

    Pattern: Map step — one record in, many records out.
    Returns: List[Dict] with one entry per clause.

    Each output dict contains:
      - clause_number: int
      - clause_title: str (e.g., "DEFINITIONS")
      - clause_text: str (full clause body including sub-sections)
    """
    content = data.get("content", data)
    full_text = content.get("full_text", "")

    if not full_text:
        return [
            {
                "clause_number": 0,
                "clause_title": "EMPTY",
                "clause_text": "",
            }
        ]

    # Find all clause headings and their positions
    matches = list(CLAUSE_PATTERN.finditer(full_text))

    if not matches:
        # No numbered clauses found — return entire text as a single clause
        return [
            {
                "clause_number": 1,
                "clause_title": "FULL CONTRACT",
                "clause_text": full_text.strip(),
            }
        ]

    clauses: list[dict[str, Any]] = []

    for i, match in enumerate(matches):
        # Extract clause number from whichever capture group matched
        clause_num = int(
            match.group(1) or match.group(2) or match.group(3) or str(i + 1)
        )
        clause_title = match.group(4).strip()

        # Clause body runs from this heading to the next heading (or end of text)
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        clause_body = full_text[body_start:body_end].strip()

        clauses.append(
            {
                "clause_number": clause_num,
                "clause_title": clause_title,
                "clause_text": clause_body,
            }
        )

    return clauses
