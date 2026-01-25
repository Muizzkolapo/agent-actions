from agent_actions import udf_tool
def mark_answer(question_object):
    """
    Compares user's answer with the correct answer and adds marking result.
    
    Args:
        question_object (dict): Dictionary containing question data with 'my_answer_key' and 'answer' keys
        
    Returns:
        dict: Original object with added 'is_correct' and 'marking_details' keys
    """
    print(question_object)
    # Extract the user's answer and the correct answer
    # Support both 'my_answer_key' and 'my_answer_letter_key' field names
    user_answer = question_object.get('my_answer_key', '') or question_object.get('my_answer_letter_key', '')
    correct_answer = question_object.get('answer', '')
    
    def normalize_answer(answer):
        """Normalize answer by splitting, trimming, and sorting"""
        if not answer or not isinstance(answer, str):
            return []

        # If answer contains commas, split on commas (existing behavior)
        if ',' in answer:
            return sorted([item.strip().upper() for item in answer.split(',') if item.strip()])

        # If answer is multiple letters without commas, split each character
        if len(answer.strip()) > 1:
            return sorted([char.upper() for char in answer.strip() if char.isalpha()])

        # Single letter answer
        return [answer.strip().upper()] if answer.strip() else []
    
    # Normalize both answers
    user_answer_array = normalize_answer(user_answer)
    correct_answer_array = normalize_answer(correct_answer)
    
    # Compare arrays for exact match
    is_correct = user_answer_array == correct_answer_array
    
    # Create marking details
    marking_details = {
        'user_answer_normalized': user_answer_array,
        'correct_answer_normalized': correct_answer_array,
        'score': 1 if is_correct else 0,
        'feedback': (
            "Correct! Your answer matches the expected response." 
            if is_correct 
            else f"Incorrect. You answered: {', '.join(user_answer_array)}. Correct answer: {', '.join(correct_answer_array)}."
        )
    }
    
    # Create a new dictionary with the marking result
    marked_question = question_object.copy()
    marked_question['is_correct'] = is_correct
    marked_question['marking_details'] = marking_details
    
    return marked_question


def mark_multiple_answers(questions_list):
    """
    Mark multiple questions at once.
    
    Args:
        questions_list (list): List of question dictionaries
        
    Returns:
        list: List of marked question dictionaries
    """
    return [mark_answer(question) for question in questions_list]


def get_marking_summary(marked_questions):
    """
    Generate summary statistics for marked questions.
    
    Args:
        marked_questions (list): List of marked question dictionaries
        
    Returns:
        dict: Summary statistics
    """
    total = len(marked_questions)
    correct = sum(1 for q in marked_questions if q.get('is_correct', False))
    percentage = round((correct / total) * 100) if total > 0 else 0
    
    return {
        'total_questions': total,
        'correct_answers': correct,
        'incorrect_answers': total - correct,
        'percentage_score': percentage
    }

@udf_tool()
def mark_and_attach(data):
    """
    Mark a question and attach the result.

    Args:
        data: Dictionary containing question data

    Returns:
        List with marked question dictionary
    """
    # Handle content wrapper
    if 'content' in data:
        question_data = data['content'].copy()
    else:
        question_data = data.copy()

    marked_result = mark_answer(question_data)
    if marked_result['is_correct'] == True:
        correctness = "Correct"
    else:
        correctness = "Incorrect"
    question_data["marked_result_is_correct"] = correctness

    return [question_data]
# Example usage with your data
if __name__ == "__main__":
    # Test case 1: Original format (comma-separated)
    question_data_1 = {
        "my_answer_key": "A,B",
        "answer": "A,B"
    }

    # Test case 2: Concatenated format (should now work)
    question_data_2 = {
        "my_answer_letter_key": "ABC",
        "answer": "A,B,C"
    }

    # Test case 3: Single letter
    question_data_3 = {
        "my_answer_key": "A",
        "answer": "A"
    }

    # Test case 4: Mixed formats
    question_data_4 = {
        "my_answer_key": "ABC",
        "answer": "C,A,B"  # Different order should still match
    }

    print("Test 1 - Comma-separated (A,B vs A,B):")
    result1 = mark_answer(question_data_1)
    print(f"Result: {result1['is_correct']}")
    print(f"Details: {result1['marking_details']}")
    print()

    print("Test 2 - Concatenated (ABC vs A,B,C):")
    result2 = mark_answer(question_data_2)
    print(f"Result: {result2['is_correct']}")
    print(f"Details: {result2['marking_details']}")
    print()

    print("Test 3 - Single letter (A vs A):")
    result3 = mark_answer(question_data_3)
    print(f"Result: {result3['is_correct']}")
    print(f"Details: {result3['marking_details']}")
    print()

    print("Test 4 - Order independence (ABC vs C,A,B):")
    result4 = mark_answer(question_data_4)
    print(f"Result: {result4['is_correct']}")
    print(f"Details: {result4['marking_details']}")
    print()