"""Canonicalizing dict keys for hashing must not collapse distinct keys into one identity.

Stringifying keys to make them sortable is lossy if two keys stringify to the same string
(a numeric spreadsheet header ``2024`` vs a text header ``"2024"``; a ragged csv row's ``None``
restkey vs a literal ``"None"`` column). Collapsing them gives two structurally distinct rows
the same ``source_guid`` — a silent dedup collision. These pin that the encoding is injective.
"""

from agent_actions.utils.id_generation import IDGenerator


def test_numeric_and_string_same_name_keys_are_distinct():
    # int 2024 and str "2024" are different keys; hashing must not merge them
    both = IDGenerator.derive_source_guid({2024: "a", "2024": "b"})
    only_str = IDGenerator.derive_source_guid({"2024": "b"})
    assert both != only_str, "a non-string key collapsed into a same-looking string key"


def test_none_restkey_does_not_collapse_into_none_named_column():
    # a ragged row: literal "None" column carries "2"; the None restkey carries ["3"]
    ragged = IDGenerator.derive_source_guid({"a": "1", "None": "2", None: ["3"]})
    # a genuinely different row where the "None" column itself holds ["3"]
    other = IDGenerator.derive_source_guid({"a": "1", "None": ["3"]})
    assert ragged != other, "None restkey overwrote the 'None' column — identity collision"


def test_golden_identity_unchanged():
    # the encoding must remain a strict no-op for normal string-keyed payloads
    assert (
        IDGenerator.derive_source_guid(
            {"content": "The mitochondria is the powerhouse of the cell."}
        )
        == "865e85c1-c292-5537-a9dc-aed6618263eb"
    )
