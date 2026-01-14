from typing import Any, List, TypedDict, Union
from agent_actions import udf_tool


class AddAnswerTextInput(TypedDict, total=False):
    """Input schema for add_answer_text function.

    Source: node_6_suggest_distractor_counts output
    Destination: node_7_add_answer_text output (adds answer_text field)

    This function takes the question data with suggested distractor counts
    and extracts the actual answer text(s) from the options list based on
    the answer letter(s).
    """

    # Core question fields (from node_6_suggest_distractor_counts)
    question: str
    options: List[str]
    answer: str
    answer_explanation: str

    # Distractor generation metadata (mixed types: correct_answer_words is int, distractor_N is str like "equal_to"/"greater_than")
    target_word_counts: dict


class AddAnswerTextOutput(TypedDict, total=False):
    """Output schema - same as input but with answer_text added."""

    question: str
    options: List[str]
    answer: str
    answer_explanation: str
    target_word_counts: dict
    answer_text: List[str]  # Always a list, even for SA (single item list)


@udf_tool(input_type=AddAnswerTextInput, output_type=AddAnswerTextOutput)
def add_answer_text(question_data: dict) -> dict:
    """
    Takes a question JSON, finds the correct answer index/indices,
    extracts the corresponding option texts, and adds them as 'answer_text'.

    Supports both single-answer (e.g., 'A') and multiple-answer (e.g., 'AD') cases.
    Always replaces existing answer_text to prevent duplicates.
    """
    answer = question_data.get("answer", "").strip()
    options = question_data.get("options", [])

    if not answer or not options:
        question_data["answer_text"] = []
        return question_data

    # Handle comma-separated format (e.g., "A, B" or "A,B")
    if "," in answer:
        answer_letters = [a.strip().upper() for a in answer.split(",")]
    else:
        # Handle concatenated format (e.g., "AB") - split into individual letters
        answer_letters = [a.upper() for a in answer if a.isalpha()]

    # Map answer letters to indices (A=0, B=1, etc.)
    indices = [ord(letter) - ord("A") for letter in answer_letters]

    # Extract texts for valid indices, removing duplicates while preserving order
    seen = set()
    answer_texts = []
    for i in indices:
        if 0 <= i < len(options) and i not in seen:
            seen.add(i)
            answer_texts.append(options[i])

    # Always return as list for consistency (even SA is a single-item list)
    question_data["answer_text"] = answer_texts

    return question_data
