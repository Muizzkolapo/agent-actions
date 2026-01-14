"""
Tool to prettify and clean up HTML formatting in quiz objects
Makes HTML more readable by adding proper indentation and line breaks
"""

from bs4 import BeautifulSoup
from typing import Any, Dict, List, TypedDict
from agent_actions import udf_tool


def prettify_html(html_string: str, indent_size: int = 2) -> str:
    """
    Prettify HTML string with proper indentation

    Args:
        html_string: Raw HTML string
        indent_size: Number of spaces for indentation

    Returns:
        Prettified HTML string
    """
    if not html_string or not isinstance(html_string, str):
        return html_string

    # Skip if not HTML
    if "<" not in html_string or ">" not in html_string:
        return html_string

    try:
        # Parse HTML
        soup = BeautifulSoup(html_string, "html.parser")

        # Prettify with specified indentation
        prettified = soup.prettify(formatter="html")

        # Optionally: adjust indentation size (BeautifulSoup uses 1 space by default)
        if indent_size != 1:
            lines = prettified.split("\n")
            adjusted_lines = []
            for line in lines:
                # Count leading spaces
                stripped = line.lstrip(" ")
                if line != stripped:
                    spaces = len(line) - len(stripped)
                    # Multiply spaces by indent_size
                    new_spaces = " " * (spaces * indent_size)
                    adjusted_lines.append(new_spaces + stripped)
                else:
                    adjusted_lines.append(line)
            prettified = "\n".join(adjusted_lines)

        return prettified

    except Exception as e:
        # If parsing fails, return original
        return html_string


class PrettifyHtmlFormattingInput(TypedDict, total=False):
    """Input schema for prettify_html_formatting function.

    This is STEP 5 in the Thinkific quiz generation pipeline.
    Receives readability-improved data and prettifies HTML indentation.

    Input source: node_3_improve_text_readability output (7 fields)
    Output destination: node_5_add_asterisk

    Input/Output fields (7 total - same structure, prettified HTML):
    - answer_indices: List[int] - Indices of correct answers
    - answer_letter: str - Letter(s) of correct answer(s)
    - batch_name: str - Quiz batch identifier
    - explanation: str - HTML explanation (prettified)
    - options: List[str] - HTML options (prettified)
    - question: str - HTML question (prettified)
    - question_type: str - 'SA' or 'MA'
    """

    # -------------------------------------------------------------------------
    # Core quiz fields (7 fields from improve_text_readability)
    # -------------------------------------------------------------------------
    question: str  # HTML question text (will be prettified)
    options: List[Any]  # HTML answer options (will be prettified)
    explanation: str  # HTML explanation (will be prettified)
    answer_letter: str  # e.g., 'A' or 'A,B,C' for MA (passthrough)
    answer_indices: List[int]  # Indices of correct answers (passthrough)
    question_type: str  # 'SA' or 'MA' (passthrough)
    batch_name: str  # Quiz batch identifier (passthrough)


@udf_tool(input_type=PrettifyHtmlFormattingInput)
def prettify_html_formatting(quiz_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prettify HTML in all text fields of a quiz object for better readability

    Processes:
    - question
    - options (array of HTML strings)
    - explanation
    - Any other HTML fields

    Args:
        quiz_obj: Quiz object with HTML content

    Returns:
        Quiz object with prettified HTML
    """
    formatted = quiz_obj.copy()

    # Prettify question
    if "question" in formatted:
        formatted["question"] = prettify_html(formatted["question"])

    # Prettify options array
    if "options" in formatted and isinstance(formatted["options"], list):
        formatted["options"] = [
            prettify_html(opt) if isinstance(opt, str) else opt for opt in formatted["options"]
        ]

    # Prettify explanation
    if "explanation" in formatted:
        formatted["explanation"] = prettify_html(formatted["explanation"])

    # Prettify answer_explanation
    if "answer_explanation" in formatted:
        formatted["answer_explanation"] = prettify_html(formatted["answer_explanation"])

    # Prettify combined_explanation
    if "combined_explanation" in formatted:
        formatted["combined_explanation"] = prettify_html(formatted["combined_explanation"])

    # Prettify collapsible sections
    if "feynman_explanation_collapsible" in formatted:
        formatted["feynman_explanation_collapsible"] = prettify_html(
            formatted["feynman_explanation_collapsible"]
        )

    if "concept_explanation_collapsible" in formatted:
        formatted["concept_explanation_collapsible"] = prettify_html(
            formatted["concept_explanation_collapsible"]
        )

    return formatted


if __name__ == "__main__":
    # Test with a sample
    sample_html = "<html><body><p>Your Mcp client library must select a single hint.</p><p>What should you implement?</p></body></html>"

    print("Original:")
    print(sample_html)
    print("\nPrettified:")
    print(prettify_html(sample_html))
