"""Aggregate validation votes from multiple AI validators."""

from typing import Any, Dict, List
from agent_actions import udf_tool


@udf_tool()
def aggregate_validation_votes(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Aggregate votes from 5 validators to check if answer is grounded in source.

    Args:
        data: Dict containing validator predictions and correct answer

    Returns:
        List with single dict containing aggregation results
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # Extract correct answer
    correct_answer = content.get('answer', '')

    # Extract predictions from all 5 validators (nested structure after merge)
    predictions = []
    reasonings = []

    for i in range(1, 6):
        validator_key = f'validate_answer_from_source_{i}'
        validator_data = content.get(validator_key, {})

        if isinstance(validator_data, dict):
            pred = validator_data.get('predicted_answer')
            reasoning = validator_data.get('reasoning')

            if pred:
                predictions.append(pred.strip().upper())
                reasonings.append({
                    f'validator_{i}': {
                        'predicted': pred.strip().upper(),
                        'reasoning': reasoning or ''
                    }
                })

    # Count votes for each option
    vote_counts = {}
    for pred in predictions:
        vote_counts[pred] = vote_counts.get(pred, 0) + 1

    # Find majority answer
    if vote_counts:
        majority_answer = max(vote_counts.items(), key=lambda x: x[1])[0]
        majority_count = vote_counts[majority_answer]
    else:
        majority_answer = None
        majority_count = 0

    # Get correct answer letter (answer field is already a letter like "A")
    correct_answer_letter = correct_answer.strip().upper() if correct_answer else None

    # Determine if validation passed (3 or more validators agree with correct answer)
    validation_passed = (
        majority_count >= 3 and
        correct_answer_letter and
        majority_answer == correct_answer_letter
    )

    # Calculate confidence
    confidence = (majority_count / len(predictions)) if predictions else 0

    # Build result
    result = content.copy()
    result.update({
        'validation_passed': validation_passed,
        'majority_answer': majority_answer,
        'correct_answer_letter': correct_answer_letter,
        'vote_counts': vote_counts,
        'majority_count': majority_count,
        'total_validators': len(predictions),
        'confidence': confidence,
        'validator_reasonings': reasonings,
        'validation_status': 'PASS' if validation_passed else 'FAIL'
    })

    return [result]
