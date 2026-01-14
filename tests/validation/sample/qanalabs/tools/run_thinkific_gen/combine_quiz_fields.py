"""
Combine Quiz Fields Tool

Takes all input fields from upstream workflow and combines them into
the 7 core quiz fields (without HTML formatting).

This is Step 1 of the quiz formatting pipeline:
1. combine_quiz_fields - Combine raw data into 7 fields
2. apply_html_formatting - Add HTML to those 7 fields
"""

import random
from typing import Any, Dict, List, TypedDict
from agent_actions import udf_tool


def validate_and_clean_answers(content: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and clean answer data."""
    if "answer_indices" in content:
        indices = content["answer_indices"]
        if isinstance(indices, list):
            content["answer_indices"] = [int(i) for i in indices if isinstance(i, (int, float))]
    return content


def randomize_quiz_options(
    content: Dict[str, Any], enable_randomization: bool = True
) -> Dict[str, Any]:
    """Randomize option order and update answer indices accordingly."""
    if not enable_randomization:
        return content

    options = content.get("options", [])
    answer_indices = content.get("answer_indices", [])

    if not options or not answer_indices:
        return content

    # Create index mapping
    indices = list(range(len(options)))
    random.shuffle(indices)

    # Reorder options
    new_options = [options[i] for i in indices]

    # Update answer indices
    index_map = {old: new for new, old in enumerate(indices)}
    new_answer_indices = [index_map[i] for i in answer_indices if i in index_map]

    # Update answer letter
    new_answer_letter = ",".join([chr(ord("A") + i) for i in new_answer_indices])

    content["options"] = new_options
    content["answer_indices"] = new_answer_indices
    content["answer_letter"] = new_answer_letter

    return content


def build_explanation_text(content: Dict[str, Any]) -> str:
    """
    Build the explanation text from correct_answers, distractors, and other fields.
    Returns plain text (no HTML).
    """
    parts = []

    # Add question context
    question_text = content.get("question", "")
    if question_text:
        parts.append(f"Question: {question_text}")
        parts.append("")

    # Add correct answer(s)
    correct_answers = content.get("correct_answers", [])
    if correct_answers:
        if len(correct_answers) == 1:
            parts.append("Correct Answer:")
            answer = correct_answers[0]
            parts.append(f"  {answer.get('option', '')}")
            if answer.get("explanation_why_it_is_correct"):
                parts.append(f"  Explanation: {answer['explanation_why_it_is_correct']}")
        else:
            parts.append("Correct Answers:")
            for answer in correct_answers:
                parts.append(f"  • {answer.get('option', '')}")
            if correct_answers[0].get("explanation_why_it_is_correct"):
                parts.append(
                    f"  Explanation: {correct_answers[0]['explanation_why_it_is_correct']}"
                )
        parts.append("")

    # Add memorable takeaway
    if content.get("memorable_takeaway"):
        parts.append(f"Memorable Takeaway: {content['memorable_takeaway']}")
        parts.append("")

    # Add key concepts
    if content.get("key_concepts"):
        parts.append("Key Concepts:")
        for concept in content["key_concepts"]:
            parts.append(f"  • {concept}")
        parts.append("")

    # Add concept explanation (prefer 'concept_explanation', fall back to 'summary'/'summary_content')
    concept_text = (
        content.get("concept_explanation")
        or content.get("summary")
        or content.get("summary_content")
    )
    if concept_text:
        parts.append(f"Concept Explanation: {concept_text}")
        parts.append("")

    # Add incorrect options (distractors)
    distractors = content.get("distractors", [])
    if distractors:
        parts.append("Incorrect Options:")
        for distractor in distractors:
            parts.append(f"  ✗ {distractor.get('option', '')}")
            if distractor.get("explanation_why_it_is_incorrect"):
                parts.append(f"    Why incorrect: {distractor['explanation_why_it_is_incorrect']}")
        parts.append("")

    # Add references
    url_list = content.get("url_list", [])
    if not url_list:
        single_url = content.get("url", "")
        if single_url:
            url_list = [single_url]

    if url_list:
        parts.append("References:")
        for url in url_list:
            parts.append(f"  • {url}")

    return "\n".join(parts)


def add_ma_instruction(question_text: str, question_type: str, num_correct: int) -> str:
    """Add instruction for MA questions about how many options to select."""
    if question_type != "MA" or num_correct <= 1:
        return question_text

    instruction = f"(Select {num_correct} options)"

    # Add instruction at the end if not already present
    if instruction not in question_text:
        question_text = f"{question_text}\n\n{instruction}"

    return question_text


class CombineQuizFieldsInput(TypedDict, total=False):
    """Input schema for combine_quiz_fields function.

    This is STEP 2 in the Thinkific quiz generation pipeline.
    Receives cleaned data from fix_code_snippets and combines into core fields.

    Input source: node_0_fix_code_snippets output (13 fields)
    Output destination: node_2_format_quiz_object

    Input fields from fix_code_snippets:
    - answer, answer_indices, combined_explanation, concept_explanation,
    - correct_answers, distractors, key_concept_analogy, memorable_takeaway,
    - options, options_combined, question, question_explanation, question_type

    Output fields (16 total):
    - answer_indices, answer_letter, batch_name, concept_explanation,
    - correct_answers, distractors, explanation, key_concept_analogy,
    - key_concepts, memorable_takeaway, options, question, question_explanation,
    - question_type, summary_content, url_list
    """

    # -------------------------------------------------------------------------
    # Core quiz content fields (from fix_code_snippets)
    # -------------------------------------------------------------------------
    question: str  # The quiz question text
    options: List[Any]  # Answer options (list of strings)
    answer: List[Any]  # Correct answer(s) - used to derive answer_indices
    answer_indices: List[int]  # Indices of correct answers in options
    question_type: str  # 'SA' (single answer) or 'MA' (multiple answer)

    # -------------------------------------------------------------------------
    # Explanation fields (from fix_code_snippets)
    # -------------------------------------------------------------------------
    question_explanation: str  # Detailed explanation of the question
    concept_explanation: str  # Educational explanation of the concept
    key_concept_analogy: str  # Analogy to help understand the concept
    memorable_takeaway: str  # Key point to remember
    combined_explanation: str  # Full combined explanation text

    # -------------------------------------------------------------------------
    # Answer/Distractor data structures (from fix_code_snippets)
    # -------------------------------------------------------------------------
    correct_answers: List[dict]  # [{option, explanation_why_it_is_correct}, ...]
    distractors: List[dict]  # [{option, explanation_why_it_is_incorrect}, ...]
    options_combined: List[dict]  # All options with answer_or_distractor flag


@udf_tool(input_type=CombineQuizFieldsInput)
def combine_quiz_fields(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Combine all input fields into the 7 core quiz fields.

    Input: Many fields from upstream workflow
    Output: 7 core fields (question, options, explanation, answer_letter,
            answer_indices, question_type, batch_name)

    No HTML formatting is applied - that's done in the next step.
    """
    # Handle content wrapper if present
    if "content" in obj:
        content = obj["content"]
    else:
        content = obj

    # Validate and clean the data
    content = validate_and_clean_answers(content)

    # Convert answer to answer_indices if needed
    if not content.get("answer_indices") or len(content.get("answer_indices", [])) == 0:
        answer_str = content.get("answer", "")
        if answer_str:
            indices = []
            if "," in str(answer_str):
                letters = [
                    letter.strip().upper()
                    for letter in str(answer_str).split(",")
                    if letter.strip()
                ]
            else:
                letters = [char.upper() for char in str(answer_str) if char.isalpha()]

            for letter in letters:
                indices.append(ord(letter.upper()) - ord("A"))

            content["answer_indices"] = indices
            content["answer_letter"] = ",".join(letters)
        else:
            content["answer_indices"] = []
            content["answer_letter"] = ""

    # Apply randomization
    content = randomize_quiz_options(content, enable_randomization=True)

    # Get question text and add MA instruction if needed
    question_text = content.get("question", "")
    question_type = content.get("question_type", "SA")
    batch_name = content.get("batch_name", "")

    if question_type == "MA":
        num_correct = len(content.get("answer_indices", []))
        question_text = add_ma_instruction(question_text, question_type, num_correct)

    # Get options
    options = content.get("options", [])

    # Build explanation text
    explanation = build_explanation_text(content)

    # If combined_explanation exists and is not empty, prefer it
    if content.get("combined_explanation"):
        explanation = content["combined_explanation"]

    # Build the 7-field output
    # Get concept explanation (prefer 'concept_explanation', fall back to 'summary'/'summary_content')
    concept_value = (
        content.get("concept_explanation")
        or content.get("summary")
        or content.get("summary_content", "")
    )

    result = {
        "question": question_text,
        "options": options,
        "explanation": explanation,
        "answer_letter": content.get("answer_letter", ""),
        "answer_indices": content.get("answer_indices", []),
        "question_type": question_type,
        "batch_name": batch_name,
        # Pass through data needed for HTML formatting
        "correct_answers": content.get("correct_answers", []),
        "distractors": content.get("distractors", []),
        # Feynman explanation fields
        "question_explanation": content.get("question_explanation", ""),
        "key_concept_analogy": content.get("key_concept_analogy", ""),
        "memorable_takeaway": content.get("memorable_takeaway", ""),
        "key_concepts": content.get("key_concepts", []),
        # Concept explanation
        "concept_explanation": concept_value,  # New primary field
        "summary_content": concept_value,  # Keep for downstream compatibility
        "url_list": content.get("url_list", [])
        or ([content.get("url")] if content.get("url") else []),
    }

    return result
