import json
from typing import Any, Dict, List, Optional, Set, Tuple, TypedDict, Union
from agent_actions import udf_tool


def parse_correct_answer_indices(answer_str: str) -> Set[int]:
    """
    Parse answer string into set of correct indices.
    Examples: 'A' -> {0}, 'ACE' or 'A,C,E' -> {0, 2, 4}, 'BD' or 'B,D' -> {1, 3}
    """
    if not answer_str:
        raise ValueError("Answer string cannot be empty")

    # Handle both comma-separated (A,C,E) and non-comma (ACE) formats
    if "," in answer_str:
        letters = [letter.strip().upper() for letter in answer_str.split(",")]
    else:
        letters = [ch.upper() for ch in answer_str if ch.strip()]

    indices = set()

    for letter in letters:
        if not letter or not letter.isalpha() or len(letter) != 1:
            raise ValueError(f"Invalid answer letter: {letter}")
        indices.add(ord(letter) - ord("A"))

    return indices


def update_answer_string_for_new_options(original_answer: str, correct_indices: Set[int]) -> str:
    """
    Generate new answer string based on correct indices.
    This handles cases where we might add new options.
    """
    letters = [chr(ord("A") + idx) for idx in sorted(correct_indices)]
    return ",".join(letters)


class TargetWordCounts(TypedDict, total=False):
    """Word count targets for distractors."""

    correct_answer_words: int
    distractor_1: str
    distractor_2: str
    distractor_3: str


class ApplyEditedDistractorsInput(TypedDict, total=False):
    """Input schema for apply_edited_distractors function.

    Source: node_11_reconstruct_options output (after distractor generation)
    Destination: Reconstructed options list with correct answer(s) and distractors

    This function takes the generated distractors and reconstructs the full
    options list, placing the correct answer(s) at the specified position(s)
    and filling remaining slots with distractors.
    """

    # Core question fields
    question: str
    options: List[str]
    answer: str
    answer_explanation: str
    answer_text: List[str]  # Always a list (single item for SA, multiple for MA)

    # Question metadata
    question_type: str

    # Generated distractors (from distractor generation nodes)
    distractor_1: str
    distractor_2: str
    distractor_3: str

    # Distractor explanations
    explanation_why_it_is_incorrect_1: str
    explanation_why_it_is_incorrect_2: str
    explanation_why_it_is_incorrect_3: str

    # LLM reasoning process
    thinking_process_1: str
    thinking_process_2: str
    thinking_process_3: str

    # Word count targets from suggest_distractor_counts
    target_word_counts: TargetWordCounts


@udf_tool(input_type=ApplyEditedDistractorsInput)
def apply_edited_distractors(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Constructs options list from answer_text and distractors.

    For SA: answer_text is a string, placed at position specified by answer (e.g., "B")
    For MA: answer_text is a list of strings, placed at positions specified by answer (e.g., "A,D")
    Distractors fill remaining positions in order.

    Returns a single-item list: [data].
    """
    # Allow JSON string input
    if isinstance(data, str):
        data = json.loads(data)

    # Basic validations
    if not isinstance(data, dict):
        raise TypeError("Expected dict or JSON-encoded dict")

    answer_str = data.get("answer", "")
    answer_text = data.get("answer_text")
    question_type = data.get("question_type", "SA")

    # Handle records without answer/answer_text (e.g., filtered records from earlier steps)
    # Return original data unchanged rather than raising an error
    if not isinstance(answer_str, str) or not answer_str:
        return [data]
    if answer_text is None:
        return [data]

    # FIX: Detect and repair corrupted answer field (text instead of letters)
    # If answer contains spaces or is longer than expected letter format, it's corrupted
    if " " in answer_str or len(answer_str) > 10:
        # Corrupted: answer contains actual text instead of letter(s)
        # Default to "A" for single answer, or generate based on number of answer_text items
        if isinstance(answer_text, list):
            # MA question: generate "A,B,C..." based on number of correct answers
            num_answers = len(answer_text)
            answer_str = ",".join([chr(ord("A") + i) for i in range(num_answers)])
            question_type = "MA"
        else:
            # SA question: default to "A"
            answer_str = "A"
            question_type = "SA"

        # Update the data to fix it permanently
        data["answer"] = answer_str

    # Parse correct answer indices
    try:
        correct_indices = parse_correct_answer_indices(answer_str)
    except ValueError as e:
        raise ValueError(f"Invalid answer format '{answer_str}': {e}")

    # answer_text is always a list now
    if not isinstance(answer_text, list):
        raise ValueError("'answer_text' must be a list of strings")

    correct_answers = answer_text
    # SA = single answer, MA = multiple answers
    question_type = "SA" if len(correct_answers) == 1 else "MA"

    # Validate correct answers match indices
    if len(correct_answers) != len(correct_indices):
        raise ValueError(
            f"Mismatch: {len(correct_indices)} answer positions but {len(correct_answers)} answer texts"
        )

    # Collect distractors
    distractors = []
    for i in range(1, 10):  # Support up to distractor_9
        distractor_key = f"distractor_{i}"
        distractor_text = data.get(distractor_key)
        if distractor_text is not None and str(distractor_text).strip():
            distractors.append(str(distractor_text).strip())

    if not distractors:
        raise ValueError("At least one distractor is required")

    # Calculate total options needed
    max_correct_idx = max(correct_indices)
    total_options = max(max_correct_idx + 1, len(correct_indices) + len(distractors))

    # Build options list
    options = [None] * total_options

    # Place correct answers at specified positions
    sorted_correct_indices = sorted(correct_indices)
    for i, idx in enumerate(sorted_correct_indices):
        options[idx] = correct_answers[i]

    # Fill remaining positions with distractors
    distractor_idx = 0
    for i in range(total_options):
        if options[i] is None:
            if distractor_idx < len(distractors):
                options[i] = distractors[distractor_idx]
                distractor_idx += 1
            else:
                # Not enough distractors provided
                raise ValueError(f"Not enough distractors for {total_options} options")

    # Update data
    data["options"] = options
    data["question_type"] = question_type

    return [data]


def apply_edited_distractors_with_error_context(
    data: Dict[str, Any],
) -> Union[List[Dict[str, Any]], Tuple[str, Dict[str, Any]]]:
    """
    Constructs options list from answer_text and distractors.

    Returns:
        - On success: [data] (single-item list)
        - On error: ("ERROR", {"error_message": str, "problematic_data": dict, "error_location": str})
    """
    original_data = data.copy() if isinstance(data, dict) else data

    try:
        # Allow JSON string input
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                return (
                    "ERROR",
                    {
                        "error_message": f"Invalid JSON format: {e}",
                        "problematic_data": {"raw_input": original_data},
                        "error_location": "JSON parsing",
                    },
                )

        # Basic validations
        if not isinstance(data, dict):
            return (
                "ERROR",
                {
                    "error_message": "Expected dict or JSON-encoded dict",
                    "problematic_data": {"input_type": type(data).__name__, "input_value": data},
                    "error_location": "type validation",
                },
            )

        answer_str = data.get("answer", "")
        answer_text = data.get("answer_text")
        question_type = data.get("question_type", "SA")

        if not isinstance(answer_str, str) or not answer_str:
            return (
                "ERROR",
                {
                    "error_message": "'answer' must be a non-empty string",
                    "problematic_data": {
                        "answer": answer_str,
                        "answer_type": type(answer_str).__name__,
                        "full_data": data,
                    },
                    "error_location": "answer validation",
                },
            )

        if answer_text is None:
            return (
                "ERROR",
                {
                    "error_message": "'answer_text' is required",
                    "problematic_data": {
                        "answer_text": answer_text,
                        "available_keys": list(data.keys()),
                        "full_data": data,
                    },
                    "error_location": "answer_text validation",
                },
            )

        # Parse correct answer indices
        try:
            correct_indices = parse_correct_answer_indices(answer_str)
        except ValueError as e:
            return (
                "ERROR",
                {
                    "error_message": f"Invalid answer format '{answer_str}': {e}",
                    "problematic_data": {"answer": answer_str, "full_data": data},
                    "error_location": "answer parsing",
                },
            )
        except Exception as e:
            return (
                "ERROR",
                {
                    "error_message": f"Unexpected error parsing answer: {e}",
                    "problematic_data": {"answer": answer_str, "full_data": data},
                    "error_location": "answer parsing",
                },
            )

        # answer_text is always a list now
        if not isinstance(answer_text, list):
            return (
                "ERROR",
                {
                    "error_message": "'answer_text' must be a list of strings",
                    "problematic_data": {
                        "answer_text": answer_text,
                        "answer_text_type": type(answer_text).__name__,
                        "full_data": data,
                    },
                    "error_location": "answer_text type validation",
                },
            )

        correct_answers = answer_text
        # SA = single answer, MA = multiple answers
        question_type = "SA" if len(correct_answers) == 1 else "MA"

        # Validate correct answers match indices
        if len(correct_answers) != len(correct_indices):
            return (
                "ERROR",
                {
                    "error_message": f"Mismatch: {len(correct_indices)} answer positions but {len(correct_answers)} answer texts",
                    "problematic_data": {
                        "correct_indices": correct_indices,
                        "correct_answers": correct_answers,
                        "answer": answer_str,
                        "answer_text": answer_text,
                        "full_data": data,
                    },
                    "error_location": "answer count validation",
                },
            )

        # Collect distractors
        distractors = []
        distractor_data = {}
        for i in range(1, 10):  # Support up to distractor_9
            distractor_key = f"distractor_{i}"
            distractor_text = data.get(distractor_key)
            distractor_data[distractor_key] = distractor_text
            if distractor_text is not None and str(distractor_text).strip():
                distractors.append(str(distractor_text).strip())

        if not distractors:
            return (
                "ERROR",
                {
                    "error_message": "At least one distractor is required",
                    "problematic_data": {"distractor_fields": distractor_data, "full_data": data},
                    "error_location": "distractor validation",
                },
            )

        # Calculate total options needed
        max_correct_idx = max(correct_indices)
        total_options = max(max_correct_idx + 1, len(correct_indices) + len(distractors))

        # Build options list
        options = [None] * total_options

        # Place correct answers at specified positions
        sorted_correct_indices = sorted(correct_indices)
        for i, idx in enumerate(sorted_correct_indices):
            options[idx] = correct_answers[i]

        # Fill remaining positions with distractors
        distractor_idx = 0
        for i in range(total_options):
            if options[i] is None:
                if distractor_idx < len(distractors):
                    options[i] = distractors[distractor_idx]
                    distractor_idx += 1
                else:
                    return (
                        "ERROR",
                        {
                            "error_message": f"Not enough distractors for {total_options} options",
                            "problematic_data": {
                                "total_options_needed": total_options,
                                "distractors_available": len(distractors),
                                "distractors": distractors,
                                "correct_indices": correct_indices,
                                "max_correct_idx": max_correct_idx,
                                "distractor_fields": distractor_data,
                                "full_data": data,
                            },
                            "error_location": "distractor allocation",
                        },
                    )

        # Update data
        data["options"] = options
        data["question_type"] = question_type

        return [data]

    except Exception as e:
        # Catch any unexpected errors
        return (
            "ERROR",
            {
                "error_message": f"Unexpected error: {e}",
                "problematic_data": {"full_data": original_data},
                "error_location": "unknown",
                "exception_type": type(e).__name__,
            },
        )


def test_apply_edited_distractors():
    """Test the function with both SA and MA examples"""

    # Test Single Answer (SA) - answer_text is now always a list
    print("=== TESTING SINGLE ANSWER (SA) ===")
    sa_data = {
        "question": "Test SA question",
        "answer": "B",
        "answer_text": [
            "Add custom data to the Foundry workspace, create semantic indexes over the data, and integrate these indexes with a generative model."
        ],
        "question_type": "SA",
        "distractor_1": "New Option A",
        "distractor_2": "New Option C",
        "distractor_3": "New Option D",
    }

    result_sa = apply_edited_distractors(sa_data)
    print("Constructed options:", result_sa[0]["options"])
    print("Answer position B (index 1):", result_sa[0]["options"][1][:50] + "...")
    print("Verification:")
    print("  Position A (distractor):", result_sa[0]["options"][0] == sa_data["distractor_1"])
    print("  Position B (correct):", result_sa[0]["options"][1] == sa_data["answer_text"][0])
    print("  Position C (distractor):", result_sa[0]["options"][2] == sa_data["distractor_2"])
    print("  Position D (distractor):", result_sa[0]["options"][3] == sa_data["distractor_3"])

    # Test Multiple Answer (MA)
    print("\n=== TESTING MULTIPLE ANSWER (MA) ===")
    ma_data = {
        "question": "Which step ensures the correct configuration to build and refine the AI application?",
        "answer": "A,D",
        "answer_text": [
            "Pick and deploy a base model from the catalog, then fine-tune it for chat-completion tasks.",
            "Fine-tune a pre-deployed model and then use Prompt Flow to design and test prompt interactions.",
        ],
        "question_type": "MA",
        "distractor_1": "Deploy a pre-trained base model to production first, then use Prompt Flow to orchestrate prompts without fine-tuning.",
        "distractor_2": "Build with the Azure AI Foundry SDK and rely on few-shot prompting instead of fine-tuning.",
        "distractor_3": "Use Azure OpenAI hosted models and rely on system prompts instead of fine-tuning in Foundry.",
    }

    print("Answer positions: A, D")
    print("Number of distractors: 3")

    result_ma = apply_edited_distractors(ma_data)
    print(f"\nConstructed ({len(result_ma[0]['options'])} options):")
    for i, opt in enumerate(result_ma[0]["options"]):
        letter = chr(ord("A") + i)
        print(f"  {letter}: {opt[:60]}...")

    print("\nVerification:")
    print("  A (correct):", result_ma[0]["options"][0] == ma_data["answer_text"][0])
    print("  B (distractor):", result_ma[0]["options"][1] == ma_data["distractor_1"])
    print("  C (distractor):", result_ma[0]["options"][2] == ma_data["distractor_2"])
    print("  D (correct):", result_ma[0]["options"][3] == ma_data["answer_text"][1])
    print("  E (distractor):", result_ma[0]["options"][4] == ma_data["distractor_3"])
    print("  Total options:", len(result_ma[0]["options"]))

    # Test edge case: answer at position C with 2 distractors
    print("\n=== TESTING SA WITH ANSWER AT POSITION C ===")
    sa_c = {
        "answer": "C",
        "answer_text": ["Correct answer at C"],  # Now a list
        "distractor_1": "Distractor A",
        "distractor_2": "Distractor B",
    }

    result_c = apply_edited_distractors(sa_c)
    print("Constructed options:", result_c[0]["options"])
    print("Verification:")
    print("  Position A (distractor):", result_c[0]["options"][0] == "Distractor A")
    print("  Position B (distractor):", result_c[0]["options"][1] == "Distractor B")
    print("  Position C (correct):", result_c[0]["options"][2] == "Correct answer at C")

    # Test both answer formats: "BD" vs "B,D"
    print("\n=== TESTING ANSWER FORMAT PARSING ===")
    test_bd_no_comma = {
        "answer": "BD",  # No comma format
        "answer_text": ["First correct", "Second correct"],
        "distractor_1": "Distractor A",
        "distractor_2": "Distractor C",
    }

    test_bd_with_comma = {
        "answer": "B,D",  # Comma format
        "answer_text": ["First correct", "Second correct"],
        "distractor_1": "Distractor A",
        "distractor_2": "Distractor C",
    }

    result_no_comma = apply_edited_distractors(test_bd_no_comma)
    result_with_comma = apply_edited_distractors(test_bd_with_comma)

    print("BD format (no comma):", [opt[:20] + "..." for opt in result_no_comma[0]["options"]])
    print("B,D format (comma):", [opt[:20] + "..." for opt in result_with_comma[0]["options"]])
    print(
        "Both formats produce same result:",
        result_no_comma[0]["options"] == result_with_comma[0]["options"],
    )


if __name__ == "__main__":
    test_apply_edited_distractors()
