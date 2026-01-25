import json
from typing import Any, Dict, List, Union
from agent_actions import udf_tool


@udf_tool()
def flatten_questions(data: Union[str, Dict[str, Any], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Flatten questions data by including shared keys alongside each question.
    Accepts JSON string, dict, or list of dicts.
    Returns original data if there's nothing to flatten.
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
            shared_from_record = {k: v for k, v in rec.items() if k != "content"}
            shared_from_content = {k: v for k, v in content.items() if k != "questions"}
            shared_keys = {**shared_from_record, **shared_from_content}
            questions = content.get("questions", [])
        else:
            # Treat the record itself as the container
            shared_keys = {k: v for k, v in rec.items() if k != "questions"}
            questions = rec.get("questions", [])

        # Ensure questions is iterable
        if isinstance(questions, dict):
            questions = [questions]
        elif not isinstance(questions, list):
            questions = []

        # Check if there are actually questions to flatten
        if questions:
            has_questions_to_flatten = True

        for q in questions:
            if isinstance(q, dict):
                flattened.append({**shared_keys, **q})
            else:
                # If a question item is a primitive, wrap it
                flattened.append({**shared_keys, "question": q})

    # Return original data if there's nothing to flatten
    if not has_questions_to_flatten:
        return records

    # Validate flattened records - support both full question schema and raw Q&A schema
    # Full schema: question, options, answer (for scenario-based questions)
    # Raw schema: question_text, answer_text (for extracted Q&A pairs)
    # Note: difficulty_reason is optional in raw schema
    full_required = ['question', 'options', 'answer']
    raw_required = ['question_text', 'answer_text']

    validated = []
    for item in flattened:
        # Check if it matches full schema
        full_missing = [f for f in full_required if not item.get(f)]
        # Check if it matches raw schema
        raw_missing = [f for f in raw_required if not item.get(f)]

        # Accept if it matches EITHER schema
        if not full_missing or not raw_missing:
            validated.append(item)
        else:
            print(f"⚠️ Skipping malformed question - missing fields")
            print(f"   Full schema missing: {full_missing}")
            print(f"   Raw schema missing: {raw_missing}")
            print(f"   Item keys: {list(item.keys())}")
            continue

    if len(validated) < len(flattened):
        print(f"📊 Filtered {len(flattened) - len(validated)} malformed questions, keeping {len(validated)}")

    return validated
