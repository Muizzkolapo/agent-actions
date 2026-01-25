import json
from typing import Any, Dict, List, Union
from agent_actions import udf_tool


@udf_tool()
def flatten_canonical_questions(data: Union[str, Dict[str, Any], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Flatten canonical_questions from nested structure to flat array.
    Each question inherits metadata from parent record.
    Accepts JSON string, dict, or list of dicts.
    """
    # 1) If a JSON string was passed, parse it
    if isinstance(data, str):
        parsed_data = json.loads(data)
    else:
        parsed_data = data

    # 2) Normalize to a list of records
    if isinstance(parsed_data, dict):
        records = [parsed_data]
    elif isinstance(parsed_data, list):
        records = parsed_data
    else:
        raise TypeError("data must be a JSON string, dict, or list of dicts")

    flattened: List[Dict[str, Any]] = []
    has_questions_to_flatten = False

    for rec in records:
        # Skip records that aren't dicts
        if not isinstance(rec, dict):
            # try to parse if it's a JSON string; otherwise skip
            if isinstance(rec, str):
                try:
                    rec = json.loads(rec)
                except Exception:
                    continue
            else:
                continue

        content = rec.get("content")

        if isinstance(content, dict):
            # Extract shared keys from the parent record (excluding 'content')
            shared_keys = {k: v for k, v in rec.items() if k != "content"}

            # Get the canonical_questions array
            canonical_questions = content.get("canonical_questions", [])
        else:
            # Treat the record itself as the container
            shared_keys = {k: v for k, v in rec.items() if k != "canonical_questions"}
            canonical_questions = rec.get("canonical_questions", [])

        # Ensure canonical_questions is iterable
        if isinstance(canonical_questions, dict):
            canonical_questions = [canonical_questions]
        elif not isinstance(canonical_questions, list):
            canonical_questions = []

        # Check if there are actually questions to flatten
        if canonical_questions:
            has_questions_to_flatten = True

        # Flatten each question with shared keys
        for question in canonical_questions:
            if isinstance(question, dict):
                flattened.append({**shared_keys, **question})
            else:
                # If a question item is a primitive, wrap it
                flattened.append({**shared_keys, "question": question})

    # Return original data if there's nothing to flatten
    if not has_questions_to_flatten:
        return records

    # Validate flattened records - canonical questions should have question_text and answer_text
    canonical_required = ['question_text', 'answer_text']

    validated = []
    for item in flattened:
        # Check if it matches canonical schema
        missing = [f for f in canonical_required if not item.get(f)]

        if not missing:
            validated.append(item)
        else:
            print(f"⚠️ Skipping malformed canonical question - missing fields: {missing}")
            print(f"   Item keys: {list(item.keys())}")
            continue

    if len(validated) < len(flattened):
        print(f"📊 Filtered {len(flattened) - len(validated)} malformed questions, keeping {len(validated)}")

    return validated
