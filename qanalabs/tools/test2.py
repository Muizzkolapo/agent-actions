import json
from typing import Dict, Any, List, Set, Tuple

def parse_correct_answer_indices(answer_str: str) -> Set[int]:
    """
    Parse answer string into set of correct indices.
    Examples: 'A' -> {0}, 'A,C,E' -> {0, 2, 4}, 'B,D' -> {1, 3}
    """
    if not answer_str:
        raise ValueError("Answer string cannot be empty")
    
    letters = [letter.strip().upper() for letter in answer_str.split(',')]
    indices = set()
    
    for letter in letters:
        if not letter or not letter.isalpha() or len(letter) != 1:
            raise ValueError(f"Invalid answer letter: {letter}")
        indices.add(ord(letter) - ord('A'))
    
    return indices

def update_answer_string_for_new_options(original_answer: str, correct_indices: Set[int]) -> str:
    """
    Generate new answer string based on correct indices.
    This handles cases where we might add new options.
    """
    letters = [chr(ord('A') + idx) for idx in sorted(correct_indices)]
    return ','.join(letters)

def apply_edited_distractors(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    print(data)
    """
    For SA: Replace distractor options with new ones
    For MA: Keep correct answers, replace existing distractors, and add new distractors if needed
    
    Returns a single-item list: [data].
    """
    # Allow JSON string input
    if isinstance(data, str):
        data = json.loads(data)

    # Basic validations
    if not isinstance(data, dict):
        raise TypeError("Expected dict or JSON-encoded dict")

    options = data.get("options", [])
    answer_str = data.get("answer", "")
    question_type = data.get("question_type", "SA")
    
    if not isinstance(options, list) or not options:
        raise ValueError("'options' must be a non-empty list")
    if not isinstance(answer_str, str) or not answer_str:
        raise ValueError("'answer' must be a non-empty string")

    # Parse correct answer indices
    try:
        correct_indices = parse_correct_answer_indices(answer_str)
    except ValueError as e:
        raise ValueError(f"Invalid answer format '{answer_str}': {e}")

    # Validate indices are within range
    if not all(0 <= idx < len(options) for idx in correct_indices):
        raise ValueError(f"Answer indices {correct_indices} out of range for {len(options)} options")

    # Collect new distractors
    new_distractors = []
    for i in range(1, 10):  # Support up to distractor_9
        distractor_key = f"distractor_{i}"
        distractor_text = data.get(distractor_key)
        if distractor_text is not None and str(distractor_text).strip():
            new_distractors.append(str(distractor_text).strip())

    # If no valid distractors provided, return unchanged
    if not new_distractors:
        return [data]

    # Auto-detect MA vs SA based on answer format if question_type not specified
    if question_type is None or question_type == "":
        question_type = "MA" if "," in answer_str else "SA"
    
    # Debug output (can be removed in production)
    # print(f"DEBUG: Processing {question_type} question with {len(new_distractors)} distractors")
    # print(f"DEBUG: Correct indices: {correct_indices}")
    # print(f"DEBUG: New distractors: {new_distractors}")

    if question_type == "MA" or len(correct_indices) > 1:
        # Multiple Answer: Keep correct answers, replace/add distractors
        
        # Create new options list starting with correct answers preserved
        new_options = options[:]
        
        # Get existing distractor positions (non-correct indices)
        existing_distractor_indices = [i for i in range(len(options)) if i not in correct_indices]
        existing_distractor_indices.sort()  # Sort by position
        
        # Replace existing distractors first
        for i, distractor_idx in enumerate(existing_distractor_indices):
            if i < len(new_distractors):
                new_options[distractor_idx] = new_distractors[i]
        
        # Add additional distractors if we have more than existing positions
        remaining_distractors = new_distractors[len(existing_distractor_indices):]
        for additional_distractor in remaining_distractors:
            new_options.append(additional_distractor)
        
        # Update options
        data["options"] = new_options
        
        # Answer string stays the same since correct answer positions don't change
        # (A,C,E remains A,C,E even if we add more options)
        
    else:
        # Single Answer: Original behavior - replace distractors in existing positions
        existing_distractor_indices = [
            (i, chr(ord('A') + i)) 
            for i in range(len(options)) 
            if i not in correct_indices
        ]
        existing_distractor_indices.sort(key=lambda x: x[1])  # Sort alphabetically
        
        # Use only as many distractors as we have positions for
        distractors_to_use = new_distractors[:len(existing_distractor_indices)]
        
        # Create updated options
        updated_options = options[:]
        
        # Replace distractor options with new ones
        for i, (idx, letter) in enumerate(existing_distractor_indices):
            if i < len(distractors_to_use):
                updated_options[idx] = distractors_to_use[i]
        
        data["options"] = updated_options

    # Verify correct answers weren't modified
    for correct_idx in correct_indices:
        if data["options"][correct_idx] != options[correct_idx]:
            raise RuntimeError(f"Correct answer at index {correct_idx} was modified!")

    return [data]


def test_apply_edited_distractors():
    """Test the function with both SA and MA examples"""
    
    # Test Single Answer (SA) - Original behavior
    print("=== TESTING SINGLE ANSWER (SA) ===")
    sa_data = {
        "question": "Test SA question",
        "options": [
            "Option A (wrong)",
            "Option B (correct)", 
            "Option C (wrong)",
            "Option D (wrong)"
        ],
        "answer": "B",
        "question_type": "SA",
        "distractor_1": "New Option A",
        "distractor_2": "New Option C", 
        "distractor_3": "New Option D"
    }
    
    print("Original:", sa_data["options"])
    result_sa = apply_edited_distractors(sa_data)
    print("Updated: ", result_sa[0]["options"])
    print("Correct answer (B) preserved:", result_sa[0]["options"][1] == "Option B (correct)")
    
    # Test Multiple Answer (MA) - New behavior with expansion
    print("\n=== TESTING MULTIPLE ANSWER (MA) - Replace & Add ===")
    ma_data = {
        "question": "Test MA question with expansion", 
        "options": [
            "Store API keys in Azure Key Vault with restricted access.",  # A - correct
            "Embed the API keys directly in your application code.",      # B - distractor
            "Rotate API keys regularly to minimize risk of compromise.",   # C - correct
            "Share API keys publicly to allow easier access during development.",  # D - distractor  
            "Apply role-based access control and network restrictions to limit Azure Key Vault access."  # E - correct
        ],
        "answer": "A,C,E",
        "question_type": "MA",
        "distractor_1": "Store API keys in local configuration files for easy developer access.",
        "distractor_2": "Embed the API keys directly within frontend application source code.", 
        "distractor_3": "Commit API keys directly to public source code repositories for convenience."
    }
    
    print("Original (5 options):", ma_data["options"])
    print("Correct answers: A, C, E")
    print("Existing distractors: B, D")
    print("New distractors provided: 3")
    
    result_ma = apply_edited_distractors(ma_data)
    print(f"\nUpdated ({len(result_ma[0]['options'])} options):", result_ma[0]["options"])
    print("Answer string:", result_ma[0]["answer"])
    
    print("\nVerification:")
    print("  A (correct) preserved:", result_ma[0]["options"][0] == ma_data["options"][0])
    print("  B (distractor) replaced:", result_ma[0]["options"][1] == ma_data["distractor_1"])
    print("  C (correct) preserved:", result_ma[0]["options"][2] == ma_data["options"][2])
    print("  D (distractor) replaced:", result_ma[0]["options"][3] == ma_data["distractor_2"])
    print("  E (correct) preserved:", result_ma[0]["options"][4] == ma_data["options"][4])
    print("  F (new) added:", len(result_ma[0]["options"]) == 6 and result_ma[0]["options"][5] == ma_data["distractor_3"])
    
    # Test MA with fewer distractors than existing positions
    print("\n=== TESTING MA WITH FEWER NEW DISTRACTORS ===")
    ma_partial = {
        "options": ["A (correct)", "B (wrong)", "C (correct)", "D (wrong)", "E (wrong)"],
        "answer": "A,C",
        "question_type": "MA",
        "distractor_1": "New B",
        # Only 1 distractor provided for 3 distractor positions
    }
    
    print("Original:", ma_partial["options"])
    result_partial = apply_edited_distractors(ma_partial)
    print("Updated: ", result_partial[0]["options"])
    print("Only first distractor replaced, others unchanged")


if __name__ == "__main__":
    test_apply_edited_distractors()