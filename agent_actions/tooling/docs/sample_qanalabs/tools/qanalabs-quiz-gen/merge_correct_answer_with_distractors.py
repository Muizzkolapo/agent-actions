from typing import Any, Dict, List, Set, Union
from agent_actions import udf_tool
import json
import re


def parse_answer_letters(answer_str: Any) -> List[str]:
    if not answer_str:
        return []

    if isinstance(answer_str, list) and len(answer_str) == 2:
        answer_str = answer_str[1]

    if isinstance(answer_str, str):
        if "," in answer_str:
            return [letter.strip().upper() for letter in answer_str.split(",") if letter.strip()]
        return [char.upper() for char in answer_str if char.isalpha()]

    return []


def get_answer_indices(answer_letters: List[str]) -> List[int]:
    indices = []
    for letter in answer_letters:
        if len(letter) == 1 and letter.isalpha():
            indices.append(ord(letter.upper()) - ord("A"))
    return indices


def extract_explanations(data: Dict[str, Any]) -> Dict[str, str]:
    explanations: Dict[str, str] = {}
    explanations["answer"] = data.get("answer_explanation", "")
    for i in range(1, 20):
        key = f"explanation_why_it_is_incorrect_{i}"
        if key in data:
            explanations[f"distractor_{i}"] = data[key]
    return explanations


def create_combined_explanation(correct_answers: List[Dict[str, Any]], distractors: List[Dict[str, Any]], question_type: str, flagged_items: List[Dict[str, Any]] = None) -> str:
    parts: List[str] = []

    if question_type == "MA" and len(correct_answers) > 1:
        parts.append("## Correct Answers:")
        for i, correct in enumerate(correct_answers, 1):
            parts.append(f"**Option {i}:** {correct['option']}")
        parts.append("")
        if correct_answers and correct_answers[0].get("explanation_why_it_is_correct"):
            parts.append(correct_answers[0]["explanation_why_it_is_correct"])
            parts.append("")
    else:
        parts.append("## Correct Answer:")
        if correct_answers:
            parts.append(f"**Option:** {correct_answers[0]['option']}")
            parts.append("")
            parts.append(correct_answers[0].get("explanation_why_it_is_correct", ""))
            parts.append("")

    if flagged_items:
        parts.append("## Facts to Remember:")
        for item in flagged_items:
            if "fact" in item:
                parts.append(f"- {item['fact']}")
        parts.append("")

    if distractors:
        parts.append("## Incorrect Options:")
        parts.append("")
        for i, distractor in enumerate(distractors, 1):
            parts.append(f"### Distractor {i}:")
            parts.append(distractor["option"])
            parts.append("")
            if distractor.get("explanation_why_it_is_incorrect"):
                parts.append(distractor["explanation_why_it_is_incorrect"])
                parts.append("")

    return "\n".join(parts).strip()


def process_single_mcq(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Expected dictionary input")

    options = data.get("options", [])
    answer_str = data.get("answer", "")
    if not answer_str and data.get("my_answer_key"):
        answer_str = data.get("my_answer_key")

    if not options or not answer_str:
        raise ValueError("Missing required fields: options and answer")

    answer_letters = parse_answer_letters(answer_str)
    answer_indices = get_answer_indices(answer_letters)

    if not all(0 <= idx < len(options) for idx in answer_indices):
        raise ValueError("Answer indices out of range")

    explanations = extract_explanations(data)

    options_combined: List[Dict[str, Any]] = []
    correct_answer_texts: List[str] = []

    for i, option_text in enumerate(options):
        is_correct = i in answer_indices
        if is_correct:
            correct_answer_texts.append(option_text)
            options_combined.append({
                "option": option_text,
                "answer_or_distractor": "answer",
                "explanation_why_it_is_correct_or_incorrect": explanations.get("answer", "")
            })
        else:
            distractor_explanation = ""
            for exp_key, exp_text in explanations.items():
                if exp_key.startswith("distractor_"):
                    distractor_num = exp_key.split("_")[-1]
                    if data.get(f"distractor_{distractor_num}") == option_text:
                        distractor_explanation = exp_text
                        break
            options_combined.append({
                "option": option_text,
                "answer_or_distractor": "distractor",
                "explanation_why_it_is_correct_or_incorrect": distractor_explanation
            })

    result = data.copy()
    result["options_combined"] = options_combined
    result["answer"] = correct_answer_texts
    result["answer_indices"] = answer_indices
    result["correct_answers"] = [
        {"option": options[idx], "explanation_why_it_is_correct": explanations.get("answer", "")}
        for idx in answer_indices
    ]
    result["distractors"] = [
        {
            "option": options[i],
            "explanation_why_it_is_incorrect": next(
                (exp for exp_key, exp in explanations.items()
                 if exp_key.startswith("distractor_") and data.get(f"distractor_{exp_key.split('_')[-1]}") == options[i]),
                ""
            )
        }
        for i in range(len(options))
        if i not in answer_indices
    ]

    result["question_type"] = "MA" if len(answer_indices) > 1 else "SA"
    result["combined_explanation"] = create_combined_explanation(
        result["correct_answers"],
        result["distractors"],
        result["question_type"],
        data.get("flagged_items")
    )

    return result


def add_answer_count_hint(question_text: str, answer_count: int) -> str:
    if not question_text or answer_count <= 1:
        return question_text

    pattern = r"(select\s+all\s+that\s+apply\.?)(\s*</p>)?"

    def replacement(match):
        text_part = match.group(1)
        closing = match.group(2) or ""
        return f"<i>{text_part} (choose {answer_count})</i>{closing}"

    return re.sub(pattern, replacement, question_text, flags=re.IGNORECASE)


@udf_tool()
def merge_correct_answer_with_distractors(mcq_data: Union[str, Dict[str, Any], List[Dict[str, Any]]]) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    if isinstance(mcq_data, str):
        mcq_data = json.loads(mcq_data)

    if isinstance(mcq_data, list):
        processed: List[Dict[str, Any]] = []
        for item in mcq_data:
            processed_item = process_single_mcq(item)
            if processed_item.get("question_type") == "MA" and "question" in processed_item:
                answer_count = len(processed_item.get("answer_indices", []))
                processed_item["question"] = add_answer_count_hint(processed_item["question"], answer_count)
            processed.append(processed_item)
        return processed

    processed_item = process_single_mcq(mcq_data)
    if processed_item.get("question_type") == "MA" and "question" in processed_item:
        answer_count = len(processed_item.get("answer_indices", []))
        processed_item["question"] = add_answer_count_hint(processed_item["question"], answer_count)
    return processed_item
