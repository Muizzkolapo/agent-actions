import json
from typing import Dict, Any, List, Set, Union

def parse_answer_letters(answer_str: str) -> List[str]:
    """Parse answer string into list of letters"""
    if not answer_str:
        return []
    return [letter.strip().upper() for letter in answer_str.split(',') if letter.strip()]

def get_answer_indices(answer_letters: List[str]) -> List[int]:
    """Convert answer letters to indices (A=0, B=1, etc.)"""
    return [ord(letter) - ord('A') for letter in answer_letters]

def extract_explanations(data: Dict[str, Any]) -> Dict[str, str]:
    """Extract all explanation fields from the data"""
    explanations = {}
    
    # Get answer explanation
    explanations['answer'] = data.get('answer_explanation', '')
    
    # Get distractor explanations
    for i in range(1, 20):  # Support many distractors
        exp_key = f'explanation_why_it_is_incorrect_{i}'
        if exp_key in data:
            explanations[f'distractor_{i}'] = data[exp_key]
    
    return explanations

def create_combined_explanation(correct_answers: List[Dict], distractors: List[Dict], question_type: str) -> str:
    """
    Create a formatted combined explanation showing correct answers and distractors
    For MA questions, avoid repeating the same explanation for each correct answer
    """
    explanation_parts = []
    
    # Correct Answer(s) Section
    if question_type == 'MA' and len(correct_answers) > 1:
        explanation_parts.append("## Correct Answers:")
        
        # List all correct options first
        for i, correct in enumerate(correct_answers, 1):
            explanation_parts.append(f"**Option {i}:** {correct['option']}")
        
        explanation_parts.append("")
        
        # Add the shared explanation once (avoid repetition)
        if correct_answers and correct_answers[0]['explanation_why_it_is_correct']:
            explanation_parts.append(correct_answers[0]['explanation_why_it_is_correct'])
            explanation_parts.append("")
            
    else:
        explanation_parts.append("## Correct Answer:")
        if correct_answers:
            explanation_parts.append(f"**Option:** {correct_answers[0]['option']}")
            explanation_parts.append("")
            explanation_parts.append(correct_answers[0]['explanation_why_it_is_correct'])
            explanation_parts.append("")
    
    # Incorrect Options Section
    if distractors:
        explanation_parts.append("## Incorrect Options:")
        explanation_parts.append("")
        
        for i, distractor in enumerate(distractors, 1):
            explanation_parts.append(f"### Distractor {i}:")
            explanation_parts.append(f"{distractor['option']}")
            explanation_parts.append("")
            if distractor['explanation_why_it_is_incorrect']:
                explanation_parts.append(distractor['explanation_why_it_is_incorrect'])
                explanation_parts.append("")
    
    return "\n".join(explanation_parts).strip()


def process_single_mcq(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a single MCQ item to create proper options_combined structure
    Works for both SA and MA question types
    """
    if not isinstance(data, dict):
        raise ValueError("Expected dictionary input")
    
    # Extract basic info
    options = data.get('options', [])
    answer_str = data.get('answer', '')
    question_type = data.get('question_type', 'SA')
    
    if not options or not answer_str:
        raise ValueError("Missing required fields: options and answer")
    
    # Parse answer information
    answer_letters = parse_answer_letters(answer_str)
    answer_indices = get_answer_indices(answer_letters)
    
    # Validate indices
    if not all(0 <= idx < len(options) for idx in answer_indices):
        raise ValueError(f"Answer indices {answer_indices} out of range for {len(options)} options")
    
    # Extract explanations
    explanations = extract_explanations(data)
    
    # Create options_combined array
    options_combined = []
    correct_answer_texts = []
    
    for i, option_text in enumerate(options):
        is_correct = i in answer_indices
        
        if is_correct:
            # This is a correct answer
            correct_answer_texts.append(option_text)
            options_combined.append({
                "option": option_text,
                "answer_or_distractor": "answer",
                "explanation_why_it_is_correct_or_incorrect": explanations.get('answer', '')
            })
        else:
            # This is a distractor - find matching explanation
            distractor_explanation = ""
            
            # Try to find explanation for this distractor
            # Match by checking which distractor_X has the same text as this option
            for exp_key, exp_text in explanations.items():
                if exp_key.startswith('distractor_'):
                    distractor_num = exp_key.split('_')[-1]
                    distractor_text_key = f'distractor_{distractor_num}'
                    
                    if data.get(distractor_text_key) == option_text:
                        distractor_explanation = exp_text
                        break
            
            options_combined.append({
                "option": option_text,
                "answer_or_distractor": "distractor", 
                "explanation_why_it_is_correct_or_incorrect": distractor_explanation
            })
    
    # Build result - SAME STRUCTURE for both MA and SA
    result = data.copy()  # Keep all original fields
    
    result['options_combined'] = options_combined
    
    # Universal structure (works for both SA and MA)
    result['answer'] = correct_answer_texts  # Always an array (even for SA)
    result['answer_indices'] = answer_indices  # Always an array (even for SA)
    
    # Grouped structure for easier processing
    result['correct_answers'] = [
        {
            "option": options[idx],
            "explanation_why_it_is_correct": explanations.get('answer', '')
        }
        for idx in answer_indices
    ]
    
    result['distractors'] = [
        {
            "option": options[i],
            "explanation_why_it_is_incorrect": next(
                (exp for exp_key, exp in explanations.items() 
                 if exp_key.startswith('distractor_') and 
                 data.get(f"distractor_{exp_key.split('_')[-1]}") == options[i]),
                ""
            )
        }
        for i in range(len(options))
        if i not in answer_indices
    ]
    
    # Set question type based on actual number of correct answers
    result['question_type'] = 'MA' if len(answer_indices) > 1 else 'SA'
    
    # Generate combined explanation
    result['combined_explanation'] = create_combined_explanation(
        result['correct_answers'], 
        result['distractors'], 
        result['question_type']
    )
    
    return result

def merge_correct_answer_with_distractors(mcq_data: Union[str, Dict, List]) -> str:
    """
    Ensure every MCQ item has proper options_combined structure.
    Handles SA and MA questions dynamically.
    """
    # Handle JSON strings
    if isinstance(mcq_data, str):
        try:
            mcq_data = json.loads(mcq_data)
        except json.JSONDecodeError:
            raise ValueError("Input mcq_data is a string but not valid JSON.")
    
    # Handle lists vs single items
    if isinstance(mcq_data, list):
        return json.dumps(
            [process_single_mcq(item) for item in mcq_data], 
            indent=2, 
            ensure_ascii=False
        )
    else:
        return json.dumps(
            [process_single_mcq(mcq_data)], 
            indent=2, 
            ensure_ascii=False
        )









import random
from typing import Dict, Any, List, Tuple

def process_file_content(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Process file content for both MA and SA questions with shuffling support
    Now handles multiple correct answers properly
    """
    content = data
    
    question = content['question']
    options = content['options']
    
    # Handle both old format (answer_index) and new format (answer_indices)
    if 'answer_indices' in content:
        # New format - use answer_indices array
        original_answer_indices = content['answer_indices']
    elif 'answer_index' in content:
        # Old format - convert single answer_index to array
        original_answer_indices = [content['answer_index']]
    else:
        # Fallback - try to parse from answer field
        answer_field = content.get('answer', 'A')
        
        if isinstance(answer_field, list) and len(answer_field) == 2:
            # Complex format: [["text1", "text2"], "A,B,C"]
            answer_texts, answer_letters = answer_field
            
            # Use the answer letters as the source of truth
            if isinstance(answer_letters, str):
                letters = [letter.strip().upper() for letter in answer_letters.split(',')]
                original_answer_indices = [ord(letter) - ord('A') for letter in letters if letter]
            else:
                # Fallback to finding text matches
                original_answer_indices = []
                if isinstance(answer_texts, list):
                    for answer_text in answer_texts:
                        try:
                            idx = options.index(answer_text)
                            original_answer_indices.append(idx)
                        except ValueError:
                            print(f"Warning: Could not find answer text '{answer_text}' in options")
                            
        elif isinstance(answer_field, list):
            # Array of answer texts - find their indices
            original_answer_indices = []
            for answer_text in answer_field:
                try:
                    idx = options.index(answer_text)
                    original_answer_indices.append(idx)
                except ValueError:
                    print(f"Warning: Could not find answer text '{answer_text}' in options")
        else:
            # Parse answer letters like "A" or "A,C,E"
            answer_letters = [letter.strip().upper() for letter in str(answer_field).split(',')]
            original_answer_indices = [ord(letter) - ord('A') for letter in answer_letters if letter]
    
    # Validate indices
    original_answer_indices = [idx for idx in original_answer_indices if 0 <= idx < len(options)]
    if not original_answer_indices:
        print("Warning: No valid answer indices found, defaulting to [0]")
        original_answer_indices = [0]
    
    # Create indexed options for shuffling
    indexed_options = [(option, i) for i, option in enumerate(options)]
    
    # Shuffle the options
    random.shuffle(indexed_options)
    
    # Get shuffled options and track new positions of correct answers
    shuffled_options = [option for option, _ in indexed_options]
    new_answer_indices = []
    
    # Find where each original correct answer ended up after shuffling
    for original_idx in original_answer_indices:
        for new_idx, (_, orig_idx) in enumerate(indexed_options):
            if orig_idx == original_idx:
                new_answer_indices.append(new_idx)
                break
    
    # Generate answer letters for the new positions
    if len(new_answer_indices) == 1:
        # Single answer - return just the letter
        answer_letter = chr(ord('A') + new_answer_indices[0])
    else:
        # Multiple answers - return comma-separated letters in SORTED ORDER by position
        # This ensures A,B,C corresponds to positions 0,1,2 regardless of original order
        sorted_indices = sorted(new_answer_indices)
        answer_letters = [chr(ord('A') + idx) for idx in sorted_indices]
        answer_letter = ','.join(answer_letters)
    
    # Handle options_combined shuffling
    options_combined = content.get('options_combined', [])
    shuffled_options_combined = []
    
    if options_combined:
        # Create mapping from option text to combined info
        option_to_combined = {opt['option']: opt for opt in options_combined}
        
        # Rebuild options_combined in the new shuffled order
        for option in shuffled_options:
            if option in option_to_combined:
                shuffled_options_combined.append(option_to_combined[option])
            else:
                # Fallback if option not found in combined
                shuffled_options_combined.append({
                    'option': option,
                    'answer_or_distractor': 'answer' if option in [options[i] for i in original_answer_indices] else 'distractor',
                    'explanation_why_it_is_correct_or_incorrect': ''
                })
    
    # Determine the primary answer index for thinkific (use first correct answer)
    primary_answer_index = new_answer_indices[0] if new_answer_indices else 0
    
    formatted_item = {
        'question': question,
        'options': shuffled_options,
        'answer_index': primary_answer_index,  # Primary answer for compatibility
        'answer_letter': answer_letter,  # "A" or "A,C,E"
        'answer_indices': new_answer_indices,  # All correct indices
        'options_combined': shuffled_options_combined,
        'url': content.get('link') or content.get('url', ''),
        'id': content.get('question_guid') or content.get('guid') or content.get('id', ''),
        'question_type': content.get('question_type', 'SA'),
        'original_answer_count': len(original_answer_indices),  # For debugging
        
        # Preserve other important fields
        'answer_explanation': content.get('answer_explanation', ''),
        'combined_explanation': content.get('combined_explanation', ''),
        'correct_answers': content.get('correct_answers', []),
        'distractors': content.get('distractors', [])
    }
    
    return [formatted_item]


def test_process_file_content():
    """Test the updated function with both SA and MA examples"""
    
    # Test SA question
    sa_data = {
        'question': 'What is the best approach for AI agents?',
        'options': [
            'Use custom tools with APIs',
            'Train on sensitive data', 
            'Store data internally',
            'Use static snapshots'
        ],
        'answer_indices': [0],  # New format
        'question_type': 'SA',
        'options_combined': [
            {
                'option': 'Use custom tools with APIs',
                'answer_or_distractor': 'answer',
                'explanation_why_it_is_correct_or_incorrect': 'This is correct because...'
            },
            {
                'option': 'Train on sensitive data',
                'answer_or_distractor': 'distractor', 
                'explanation_why_it_is_correct_or_incorrect': 'This is wrong because...'
            },
            {
                'option': 'Store data internally',
                'answer_or_distractor': 'distractor',
                'explanation_why_it_is_correct_or_incorrect': 'This is wrong because...'
            },
            {
                'option': 'Use static snapshots',
                'answer_or_distractor': 'distractor',
                'explanation_why_it_is_correct_or_incorrect': 'This is wrong because...'
            }
        ],
        'url': 'https://example.com'
    }
    
    # Test MA question  
    ma_data = {
        'question': 'Which security practices should you follow?',
        'options': [
            'Store keys in Azure Key Vault',
            'Embed keys in source code',
            'Rotate keys regularly', 
            'Share keys publicly',
            'Use RBAC restrictions'
        ],
        'answer_indices': [0, 2, 4],  # A, C, E
        'question_type': 'MA',
        'options_combined': [
            {'option': 'Store keys in Azure Key Vault', 'answer_or_distractor': 'answer', 'explanation_why_it_is_correct_or_incorrect': 'Secure storage is essential'},
            {'option': 'Embed keys in source code', 'answer_or_distractor': 'distractor', 'explanation_why_it_is_correct_or_incorrect': 'This exposes keys'},
            {'option': 'Rotate keys regularly', 'answer_or_distractor': 'answer', 'explanation_why_it_is_correct_or_incorrect': 'Regular rotation reduces risk'},
            {'option': 'Share keys publicly', 'answer_or_distractor': 'distractor', 'explanation_why_it_is_correct_or_incorrect': 'This defeats security'},
            {'option': 'Use RBAC restrictions', 'answer_or_distractor': 'answer', 'explanation_why_it_is_correct_or_incorrect': 'Access control is important'}
        ],
        'url': 'https://example.com'
    }
    
    # Test legacy format
    legacy_data = {
        'question': 'Legacy question?',
        'options': ['Option A', 'Option B', 'Option C'],
        'answer_index': 1,  # Old format
        'url': 'https://example.com'
    }
    
    print("=== TESTING SA QUESTION ===")
    result_sa = process_file_content(sa_data)
    sa_item = result_sa[0]
    print(f"Original answer indices: {sa_data['answer_indices']}")
    print(f"Shuffled answer indices: {sa_item['answer_indices']}")
    print(f"Answer letter: {sa_item['answer_letter']}")
    print(f"Primary answer index: {sa_item['answer_index']}")
    print(f"Question type: {sa_item['question_type']}")
    
    print("\n=== TESTING MA QUESTION ===")
    result_ma = process_file_content(ma_data)
    ma_item = result_ma[0]
    print(f"Original answer indices: {ma_data['answer_indices']}")
    print(f"Shuffled answer indices: {ma_item['answer_indices']}")
    print(f"Answer letter: {ma_item['answer_letter']}")
    print(f"Primary answer index: {ma_item['answer_index']}")
    print(f"Question type: {ma_item['question_type']}")
    
    print("\n=== TESTING LEGACY FORMAT ===")
    result_legacy = process_file_content(legacy_data)
    legacy_item = result_legacy[0]
    print(f"Original answer index: {legacy_data['answer_index']}")
    print(f"Converted to indices: {legacy_item['answer_indices']}")
    print(f"Answer letter: {legacy_item['answer_letter']}")
    print(f"Primary answer index: {legacy_item['answer_index']}")
    
    print("\n=== CHECKING SHUFFLED OPTIONS ===")
    print("SA shuffled options:", sa_item['options'])
    print("MA shuffled options:", ma_item['options'])
    print("Legacy shuffled options:", legacy_item['options'])


if __name__ == "__main__":
    test_process_file_content()


if __name__ == "__main__":
    test_process_file_content()
if __name__ == "__main__":
    test_process_file_content()