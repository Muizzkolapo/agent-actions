def mark_answer(question_object):
    """
    Compares user's answer with the correct answer and adds marking result.
    
    Args:
        question_object (dict): Dictionary containing question data with 'my_answer_key' and 'answer' keys
        
    Returns:
        dict: Original object with added 'is_correct' and 'marking_details' keys
    """
    # Extract the user's answer and the correct answer
    user_answer = question_object.get('my_answer_key', '')
    correct_answer = question_object.get('answer', '')
    
    def normalize_answer(answer):
        """Normalize answer by splitting, trimming, and sorting"""
        if not answer or not isinstance(answer, str):
            return []
        return sorted([item.strip().upper() for item in answer.split(',') if item.strip()])
    
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

def mark_and_attach(question_data):
    """
    Mark a list of questions and return a summary.
    
    Args:
        questions_list (list): List of question dictionaries
        
    Returns:
        tuple: List of marked questions and summary statistics
    """
    marked_result = mark_answer(question_data)
    if marked_result['is_correct'] == True:
        correctness = "Correct"
    else:
        correctness = "Incorrect"
    question_data["marked_result_is_correct"] = correctness
    
    return question_data
# Example usage with your data
if __name__ == "__main__":
    question_data = {
        "my_answer_key": "A,B",
        "my_answer_text": "Develop a custom Python function to query the company's product inventory database and integrate a third-party API for real-time shipping status tracking.",
        "my_reasoning": "The question asks for approaches to extend the Azure AI Foundry Agent's capabilities to handle complex customer inquiries requiring specialized data retrieval and real-time processing. Option A—developing a custom Python function to query the product inventory database—enables specialized data retrieval directly from the company's systems, supporting complex inquiry handling. Option B—integrating a third-party API for real-time shipping status tracking—adds real-time processing and up-to-date information that customers often need. Options C, D, and E, while potentially useful, do not directly support complex or real-time data retrieval relevant to customer inquiries in the same way. Therefore, A and B best meet the advanced requirements.",
        "my_confidence_level": "high",
        "id": "80e1e3a0-73aa-4cb0-96f2-0369450a24ec",
        "url": "https://learn.microsoft.com/en-us/training/modules/build-agent-with-custom-tools/1-introduction",
        "fact": "Foundry Agent Service allows integration of custom tools based on user code or APIs to extend agent functionality.",
        "quote": "To accomplish these actions, you can provide your agent a custom tool based on your own code or a third-party service or API.",
        "technical_level": "integration",
        "questionable": "High Value",
        "distractor_3": "Develop a customer sentiment analysis feature to prioritize service response times dynamically",
        "explanation_why_it_is_incorrect_3": "Sentiment analysis enhances prioritization but does not extend the agent's ability to perform specialized data retrieval or real-time processing, which is essential for handling complex inquiries as achieved by custom tools and APIs.",
        "distractor_2": "Implement predictive analytics to forecast long-term sales trends",
        "explanation_why_it_is_incorrect_2": "Predictive analytics forecasting sales trends does not directly enable real-time or specialized data retrieval needed for complex inquiries, unlike integrating custom query functions or APIs that extend agent capabilities in real time.",
        "distractor_1": "Train a custom language model solely on product descriptions for query understanding",
        "explanation_why_it_is_incorrect_1": "Training a custom language model on product descriptions doesn't provide real-time or specialized data retrieval capabilities, whereas integrating custom tools or APIs directly extends the agent to handle complex, real-time inquiries effectively.",
        "answer": "A,B",
        "answer_explanation": "By integrating custom tools like database query functions and third-party APIs, the Foundry Agent Service can extend its capabilities beyond generic AI models. These custom tools enable the agent to perform specialized tasks such as retrieving real-time inventory information and tracking shipping statuses, which are crucial for providing comprehensive and accurate customer support. The ability to supplement built-in agent capabilities with external services allows for more tailored and efficient solution design.",
        "question_type": "MA",
        "options": [
            "Develop a custom Python function to query the company's product inventory database",
            "Integrate a third-party API for real-time shipping status tracking",
            "Train a custom language model solely on product descriptions for query understanding",
            "Implement predictive analytics to forecast long-term sales trends",
            "Develop a customer sentiment analysis feature to prioritize service response times dynamically"
        ],
        "question": "You are designing an enterprise customer support solution using Azure AI Foundry Agent Service for a multinational retail company. The solution needs to handle complex customer inquiries that require specialized data retrieval and real-time processing.\n\nWhich two approaches would best extend the agent's capabilities to meet these advanced requirements?\n\nSelect all answers that apply."
    }
    
    # Test the function
    marked_result = mark_and_attach(question_data)
    print(marked_result)