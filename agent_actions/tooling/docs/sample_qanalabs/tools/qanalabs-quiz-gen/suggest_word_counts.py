import random
from typing import Any, Dict, List
from agent_actions import udf_tool


def _word_count(text: str) -> int:
    return len(text.split()) if isinstance(text, str) else 0


def _generate_targets(correct_len: int, count: int = 3, variance: float = 0.2) -> List[int]:
    if correct_len <= 0:
        return [0 for _ in range(count)]
    min_words = max(1, int(correct_len * (1 - variance)))
    max_words = max(min_words, int(correct_len * (1 + variance)))
    targets = []
    for _ in range(count):
        target = int(round(random.uniform(min_words, max_words)))
        targets.append(target)
    random.shuffle(targets)
    return targets


@udf_tool()
def suggest_word_counts(question_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Suggest relative word count targets for three distractors based on the correct answer length.
    Returns target_word_counts dict AND forwards question fields.
    """
    if not isinstance(question_obj, dict):
        return {}

    # Handle content wrapper
    if 'content' in question_obj:
        content = question_obj['content']
    else:
        content = question_obj

    options = content.get("options")
    answer_key = content.get("answer", "")
    if not isinstance(options, list) or not options or not isinstance(answer_key, str):
        return {}

    # Map letters to option indices
    letter_to_idx = {chr(65 + i): i for i in range(len(options))}

    # Try direct text match
    answer_by_text = None
    for i, opt in enumerate(options):
        if isinstance(opt, str) and opt.strip().lower() == answer_key.strip().lower():
            answer_by_text = i
            break

    if answer_by_text is not None:
        correct_indices = [answer_by_text]
    else:
        # Parse letters
        if "," in answer_key:
            letters = [a.strip().upper() for a in answer_key.split(",") if a.strip()]
        elif len(answer_key) > 1 and answer_key.isalpha() and answer_key.isupper():
            letters = list(answer_key)
        elif len(answer_key) == 1 and answer_key.isalpha():
            letters = [answer_key.upper()]
        else:
            return {}

        correct_indices = [letter_to_idx[l] for l in letters if l in letter_to_idx]

    if not correct_indices:
        return {}

    reference_idx = random.choice(correct_indices)
    correct_len = _word_count(options[reference_idx])
    targets = _generate_targets(correct_len, count=3)

    result = {"target_word_counts": {"correct_answer_words": correct_len}}
    for i, target in enumerate(targets, start=1):
        if target > correct_len:
            rel = "greater_than"
        elif target < correct_len:
            rel = "lesser_than"
        else:
            rel = "equal_to"
        result["target_word_counts"][f"distractor_{i}"] = rel

    # Forward question fields explicitly
    result["question"] = content.get("question")
    result["options"] = content.get("options")
    result["answer"] = content.get("answer")
    result["answer_explanation"] = content.get("answer_explanation")
    result["question_type"] = content.get("question_type")

    return [result]
