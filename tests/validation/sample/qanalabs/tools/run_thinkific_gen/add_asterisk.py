from typing import List, TypedDict
from agent_actions import udf_tool


class AddAsteriskToCorrectAnswerInput(TypedDict, total=False):
    """Input schema for add_asterisk_to_correct_answer function.

    This is STEP 6 (FINAL) in the Thinkific quiz generation pipeline.
    Receives prettified data and adds asterisks to mark correct answers.

    Input source: node_4_prettify_html_formatting output (7 fields)
    Output destination: Final quiz output for Thinkific loader

    Input/Output fields (7 total - same structure, asterisks added to options):
    - answer_indices: List[int] - Indices of correct answers (used for marking)
    - answer_letter: str - Letter(s) of correct answer(s)
    - batch_name: str - Quiz batch identifier
    - explanation: str - HTML explanation (passthrough)
    - options: List[str] - HTML options (asterisks prepended to correct ones)
    - question: str - HTML question (passthrough)
    - question_type: str - 'SA' or 'MA'
    """

    # -------------------------------------------------------------------------
    # Core quiz fields (7 fields from prettify_html_formatting)
    # -------------------------------------------------------------------------
    question: str  # HTML question text (passthrough)
    options: List[str]  # HTML options (asterisks added to correct)
    explanation: str  # HTML explanation (passthrough)
    answer_letter: str  # e.g., 'A' or 'A,B,C' for MA (passthrough)
    answer_indices: List[int]  # Indices of correct answers (used for marking)
    question_type: str  # 'SA' or 'MA' (passthrough)
    batch_name: str  # Quiz batch identifier (passthrough)


@udf_tool(input_type=AddAsteriskToCorrectAnswerInput)
def add_asterisk_to_correct_answer(data: dict) -> dict:
    """
    Adds asterisk as the very first character to correct answer options.
    Simple and direct - just prepends * to whatever is in the field.
    Prioritizes 'options_thinkific_loader', falls back to 'options'.

    Args:
        data: Full record with 'content' dict, or just the content dict itself

    Returns:
        List containing the updated dictionary with asterisks added.
    """
    # Handle both full record and content-only formats
    if "content" in data:
        content = data["content"]
    else:
        content = data

    answer_indices = content.get("answer_indices", [])

    # Use the standard options field
    options_key = "options"
    options = content.get(options_key, [])

    if not options or not answer_indices:
        print("Warning: Missing options or answer_indices")
        return [data]

    # Add asterisk to each correct answer option
    for index in answer_indices:
        if 0 <= index < len(options):
            # Simply prepend asterisk as the very first character
            if not options[index].startswith("*"):
                options[index] = "*" + options[index]
                letter = chr(ord("A") + index)
                print(f"Added asterisk to option {letter}")

    # Update the content with modified options
    content[options_key] = options

    return [data]


# Test with your exact data
def test_asterisk():
    test_data = {
        "answer_indices": [0, 2, 3],
        "options": [
            "<html><body><div>Option A</div></body></html>",
            "<html><body><div>Option B</div></body></html>",
            "<html><body><div>Option C</div></body></html>",
            "<html><body><div>Option D</div></body></html>",
        ],
    }

    print("Before:")
    for i, opt in enumerate(test_data["options"]):
        print(f"{chr(ord('A') + i)}: {opt[:30]}...")

    result = add_asterisk_to_correct_answer(test_data)

    print("\nAfter:")
    for i, opt in enumerate(result[0]["options"]):
        letter = chr(ord("A") + i)
        has_asterisk = "✓" if opt.startswith("*") else "❌"
        print(f"{letter}: {has_asterisk} {opt[:30]}...")


if __name__ == "__main__":
    test_asterisk()
