import random
import numpy as np
from typing import Any, Dict, List, TypedDict
from agent_actions import udf_tool


def get_word_count(text: str) -> int:
    """Get word count of text."""
    return len(text.split())


def generate_target_word_counts(
    correct_answer_length: int, num_options: int = 4, variance: float = 0.2
) -> List[int]:
    """
    Generate bell curve distributed word counts around the correct answer length.

    Args:
        correct_answer_length: Word count of the correct answer
        num_options: Total number of options including correct answer
        variance: How much variation (as percentage) from correct answer length

    Returns:
        List of target word counts for all options (including one for correct answer)
    """
    # Calculate range
    min_words = int(correct_answer_length * (1 - variance))
    max_words = int(correct_answer_length * (1 + variance))

    # Generate bell curve distribution
    mean = correct_answer_length
    std = (max_words - min_words) / 4  # 95% within range

    targets = []
    for _ in range(num_options):
        # Sample from normal distribution
        target = int(np.random.normal(mean, std))
        # Clip to range
        target = max(min_words, min(target, max_words))
        targets.append(target)

    # Shuffle so correct answer isn't always at mean
    random.shuffle(targets)

    return targets


class SuggestWordCountsInput(TypedDict, total=False):
    """Input schema for suggestwordcounts function."""

    options: List[Any]
    answer: str
    question: str
    answer_explanation: str
    question_type: str  # SA or MA
    aligned_skill_area: str
    objective_tested: str
    reasoning: str
    syllabus_alignment_score: int
    question_status: str
    status_reason: str


@udf_tool(input_type=SuggestWordCountsInput)
def suggest_word_counts(question_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Suggest target word counts for each option based on correct answer length.

    Args:
        question_obj: Quiz question with options and answer key

    Returns:
        Dictionary with suggested word counts for answer and distractors
    """
    if "options" not in question_obj or "answer" not in question_obj:
        return {}

    options = question_obj["options"]
    answer_key = question_obj["answer"]

    # Dynamic mapping based on number of options
    num_options = len(options)
    letter_to_idx = {chr(65 + i): i for i in range(num_options)}  # A=0, B=1, C=2, etc.

    # Handle multiple correct answers (e.g., "A,B,C" or "AD")
    correct_indices = []

    # First, try to find the answer by matching option text directly
    answer_by_text_match = None
    for i, option in enumerate(options):
        if option.strip().lower() == answer_key.strip().lower():
            answer_by_text_match = i
            break

    if answer_by_text_match is not None:
        # Direct text match found
        correct_indices = [answer_by_text_match]
    else:
        # Try letter-based parsing
        if "," in answer_key:
            # Multiple answers case with comma separator
            answer_letters = [ans.strip() for ans in answer_key.split(",")]
        elif len(answer_key) > 1 and all(c.isalpha() and c.isupper() for c in answer_key):
            # Multiple answers case without separator (e.g., "AD")
            answer_letters = list(answer_key)
        else:
            # Single answer case (if it's a single letter)
            if len(answer_key) == 1 and answer_key.isalpha():
                answer_letters = [answer_key]
            else:
                # Unrecognized format, return empty
                return {}

        # Convert all letters to indices
        for letter in answer_letters:
            if letter in letter_to_idx:
                correct_indices.append(letter_to_idx[letter])

    if not correct_indices:
        return {}

    # Randomly pick one correct answer to use as reference
    reference_idx = random.choice(correct_indices)

    # Validate indices
    for idx in correct_indices:
        if idx >= len(options):
            return {}

    # Get reference answer word count (from the randomly selected correct answer)
    correct_word_count = get_word_count(options[reference_idx])

    # Always generate 3 distractor targets (MA questions need 3 distractors too)
    num_distractors = 3
    targets = generate_target_word_counts(correct_word_count, num_distractors)

    # Build suggestions - always include all 3 distractors
    suggestions = {"target_word_counts": {"correct_answer_words": correct_word_count}}

    # Add relative suggestions for all 3 distractors
    for distractor_num in range(1, 4):
        target = targets[distractor_num - 1]
        if target > correct_word_count:
            suggestions["target_word_counts"][f"distractor_{distractor_num}"] = "greater_than"
        elif target < correct_word_count:
            suggestions["target_word_counts"][f"distractor_{distractor_num}"] = "lesser_than"
        else:
            suggestions["target_word_counts"][f"distractor_{distractor_num}"] = "equal_to"

    return suggestions


if __name__ == "__main__":
    sample_question = {
        "question": "You want CI for a pull request to run incremental models in incremental mode (not full-refresh) so tests run faster and CI behavior matches production. What should you run first in the CI pipeline for the PR?",
        "options": [
            "Run dbt clone as the first CI step, using a selector that targets modified models and their downstream incremental models (for example: dbt clone --select state:modified+,config.materialized:incremental,state:old).",
            "Run dbt build --full-refresh on the PR schema before running tests.",
            "Create empty placeholder tables in the PR schema for each incremental model and then run dbt build.",
            "Run dbt seed to load test data, then run dbt build --select state:modified+.",
        ],
        "answer": "A,B",
    }

    # Generate suggestions
    suggestions = suggest_word_counts(sample_question)
    print(suggestions)
