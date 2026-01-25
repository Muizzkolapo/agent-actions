import re
from typing import Any, Dict, List, Optional
from agent_actions import udf_tool


@udf_tool()
def aggregate_votes(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Aggregate votes from 3 voters for a single question.

    Vote aggregation logic:
    - If at least 2 voters say "keep", final decision is "keep"
    - Otherwise, decision is "filter"

    Expected input: Record with merged voter data from version_consumption pattern.
    Merged fields are prefixed like: filter_learning_quality_1_vote, filter_learning_quality_2_vote, etc.

    Returns ONLY computed fields: filter and vote_summary.
    Downstream actions get other fields (question_text, etc.) from original sources.
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # Extract votes from nested or flattened structures
    vote_decisions: List[str] = []
    vote_scores: List[float] = []

    def _normalize_vote(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        value = value.strip().lower()
        if value in {'keep', 'filter'}:
            return value
        return None

    # Try nested structure first (filter_learning_quality_1: {vote: ...})
    found_votes = False
    for i in [1, 2, 3]:
        key = f'filter_learning_quality_{i}'
        voter_data = content.get(key)
        if isinstance(voter_data, dict):
            vote_value = _normalize_vote(voter_data.get('vote'))
            if vote_value:
                found_votes = True
                vote_decisions.append(vote_value)
                score = voter_data.get('learning_quality_score', 0)
                try:
                    vote_scores.append(float(score))
                except (TypeError, ValueError):
                    vote_scores.append(0)

    # If no nested structure, try flattened fields (filter_learning_quality_1_vote)
    if not found_votes:
        flat_vote_re = re.compile(r'^filter_learning_quality_(\d+)_vote$')
        for key in content.keys():
            match = flat_vote_re.match(key)
            if not match:
                continue
            voter_id = int(match.group(1))

            vote_value = _normalize_vote(content.get(key))
            if not vote_value:
                continue

            score = content.get(f'filter_learning_quality_{voter_id}_learning_quality_score', 0)

            vote_decisions.append(vote_value)
            try:
                vote_scores.append(float(score))
            except (TypeError, ValueError):
                vote_scores.append(0)

    if not vote_decisions:
        print(f"⚠️ No votes found in record (keys={list(content.keys())})")
        return {'filter': 'filter', 'vote_summary': {'keep_count': 0, 'filter_count': 0, 'avg_score': 0}}

    # Calculate aggregation
    keep_count = vote_decisions.count('keep')
    filter_count = vote_decisions.count('filter')

    # Majority rule based on available votes
    majority_needed = (len(vote_decisions) // 2) + 1
    final_decision = 'keep' if keep_count >= majority_needed else 'filter'

    # Average score
    avg_score = sum(vote_scores) / len(vote_scores) if vote_scores else 0

    print(f"   Votes: {keep_count} keep, {filter_count} filter → {final_decision} (avg score: {avg_score:.2f})")

    # Return ONLY computed fields
    result = {
        'filter': final_decision,  # "keep" or "filter"
        'vote_summary': {
            'keep_count': keep_count,
            'filter_count': filter_count,
            'avg_score': round(avg_score, 2)
        }
    }

    return result
