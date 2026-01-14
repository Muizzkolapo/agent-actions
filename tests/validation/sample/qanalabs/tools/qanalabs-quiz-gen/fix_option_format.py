import json
from typing import Any, Dict, List, TypedDict
from agent_actions import udf_tool

import json
import ast
from typing import Any, Dict, List, TypedDict


import json
import re
from typing import Any, Dict, List, TypedDict


def fix_options_string(broken_str: str):
    """
    Fix a malformed JSON-style string that contains escaped lists like:
    'options': "[\"a\", \"b\", \"c\"]"

    Returns a Python list of strings.
    """
    # Extract the portion after "options":
    match = re.search(r'"options"\s*:\s*"(.*)"', broken_str)
    if not match:
        raise ValueError("No 'options' key found in the string.")

    inner = match.group(1)

    # Unescape the quotes and parse as JSON
    try:
        fixed = json.loads(inner)
    except json.JSONDecodeError:
        # Try cleaning up stray escape characters
        cleaned = inner.replace('\\"', '"').strip()
        fixed = json.loads(cleaned)

    return fixed


class FixOptionsFormattingInput(TypedDict, total=False):
    """Input schema for fixoptionsformatting function."""

    options: List[str]
    question: str
    answer: str
    answer_explanation: str
    question_type: str


@udf_tool(input_type=FixOptionsFormattingInput)
def fix_options_formatting(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fix the formatting of the 'options' field in the question data.

    Converts the options from a JSON string to a properly formatted list.
    Does not modify any other fields in the data.

    Args:
        data: Dictionary containing question data with 'options' field

    Returns:
        Dictionary with properly formatted options (only options field modified)
        None if record is missing required fields (filters it out)
    """
    # Validate required fields - filter out malformed records
    required_fields = ["question", "options", "answer"]
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        print(f"⚠️ Filtering malformed question - missing: {missing}")
        return None

    # Make a copy to avoid modifying the original
    formatted_data = data.copy()

    # Check if options field exists and is a string
    if "options" in formatted_data and isinstance(formatted_data["options"], str):
        options_str = formatted_data["options"]

        print(f"📝 Attempting to parse options string (length: {len(options_str)})")
        print(f"📝 First 150 chars: {options_str[:150]}")

        try:
            # Method 1: Try parsing as JSON directly (most common case)
            options_list = json.loads(options_str)
            if isinstance(options_list, list):
                formatted_data["options"] = options_list
                print(f"✅ Parsed successfully using json.loads() - {len(options_list)} options")
                return formatted_data
            else:
                print(f"⚠️ json.loads() returned {type(options_list)}, not a list")

        except json.JSONDecodeError as e:
            print(f"⚠️ json.loads() failed: {e}")

            # Method 2: Try to extract array content with regex
            try:
                match = re.search(r"\[(.*)\]", options_str, re.DOTALL)
                if match:
                    array_content = "[" + match.group(1) + "]"
                    options_list = json.loads(array_content)
                    formatted_data["options"] = options_list
                    print(f"✅ Parsed using regex extraction - {len(options_list)} options")
                    return formatted_data
            except (json.JSONDecodeError, AttributeError) as regex_err:
                print(f"⚠️ Regex extraction failed: {regex_err}")

            # Method 3: Try ast.literal_eval (safer than eval)
            try:
                import ast

                # Replace escaped quotes for ast parsing
                cleaned = options_str.replace('\\"', '"').replace("\\'", "'")
                options_list = ast.literal_eval(cleaned)
                if isinstance(options_list, list):
                    formatted_data["options"] = options_list
                    print(f"✅ Parsed using ast.literal_eval() - {len(options_list)} options")
                    return formatted_data
            except (ValueError, SyntaxError) as ast_err:
                print(f"⚠️ ast.literal_eval() failed: {ast_err}")

            # Method 4: Manual string splitting as last resort
            try:
                # Extract content between brackets and split by quoted strings
                match = re.findall(r'"([^"]*)"', options_str)
                if match and len(match) >= 2:
                    # Filter out empty strings
                    options_list = [opt.strip() for opt in match if opt.strip()]
                    formatted_data["options"] = options_list
                    print(f"✅ Parsed using manual regex split - {len(options_list)} options")
                    return formatted_data
            except Exception as manual_err:
                print(f"⚠️ Manual parsing failed: {manual_err}")

            # All methods failed
            print(f"❌ All parsing methods failed. Keeping original string value.")
            print(f"   Options value: {options_str[:200]}")

    elif "options" in formatted_data and isinstance(formatted_data["options"], list):
        print(f"✅ Options already in list format with {len(formatted_data['options'])} items")
    else:
        print(
            f"⚠️ No 'options' field found or unexpected type: {type(formatted_data.get('options'))}"
        )

    return formatted_data


# Example usage
if __name__ == "__main__":
    # Sample data matching the document structure
    sample_data = {
        "question_context_based": True,
        "question": "A data science team is developing an automated text classification pipeline for sports league content.",
        "options": '["Create a text classification job using CSV data with labels formatted as comma-separated plain text strings", "Use a text classification job with labels defined as Python lists enclosed in quotes", "Configure the job to manually parse and convert label formats during preprocessing", "Submit the job without specifying label formatting, relying on AutoML\'s default parsing"]',
        "answer": "B",
        "answer_explanation": "For multi-label text classification in Azure AutoML...",
    }

    # Fix the formatting
    fixed_data = fix_options_formatting(sample_data)

    # Display the result
    print(json.dumps(fixed_data, indent=4))
