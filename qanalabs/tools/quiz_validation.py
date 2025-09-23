"""
Quiz validation functions for TopicToQuizPipeline conditional reprocessing.

These functions validate different aspects of quiz content quality
to ensure educational standards are met.
"""

import json
import re
from typing import Dict, List, Any, Union

def validate_scenario_quality(content: Union[str, Dict[str, Any]]) -> bool:
    """
    Validate that quiz scenarios meet quality standards.
    
    Requirements:
    - Exactly 3 scenarios
    - Each scenario 150-200 words
    - Clear questions with 4 options (A, B, C, D)
    - Exactly one correct answer per scenario
    
    Args:
        content: Quiz scenario content to validate
        
    Returns:
        bool: True if scenarios meet quality standards
    """
    try:
        # Extract scenarios from content
        scenarios = _extract_scenarios(content)
        
        if not scenarios:
            return False
        
        # Must have exactly 3 scenarios
        if len(scenarios) != 3:
            return False
        
        # Validate each scenario
        for i, scenario in enumerate(scenarios):
            if not _validate_single_scenario(scenario, f"scenario_{i+1}"):
                return False
        
        return True
        
    except Exception as e:
        print(f"Error validating scenarios: {e}")
        return False


def validate_question_clarity(content: Union[str, Dict[str, Any]]) -> bool:
    """
    Validate that questions are clear and unambiguous.
    
    Requirements:
    - Clear, grammatically correct questions
    - No trick questions or ambiguous wording
    - Exactly 4 options per question
    - One definitively correct answer
    
    Args:
        content: Question content to validate
        
    Returns:
        bool: True if questions meet clarity standards
    """
    try:
        questions = _extract_questions(content)
        
        if not questions:
            return False
        
        for question in questions:
            # Check question clarity
            if not _is_question_clear(question):
                return False
            
            # Check options format
            if not _has_valid_options(question):
                return False
            
            # Check for ambiguity
            if _has_ambiguous_wording(question):
                return False
        
        return True
        
    except Exception as e:
        print(f"Error validating question clarity: {e}")
        return False


def validate_distractors(content: Union[str, Dict[str, Any]]) -> bool:
    """
    Validate that incorrect answer choices (distractors) are high quality.
    
    Requirements:
    - Distractors are plausible but clearly incorrect
    - No distractors too similar to correct answer
    - Distractors are realistic and educational
    - No obvious "joke" or implausible answers
    
    Args:
        content: Content with questions and distractors
        
    Returns:
        bool: True if distractors meet quality standards
    """
    try:
        questions = _extract_questions(content)
        
        if not questions:
            return False
        
        for question in questions:
            if not _validate_question_distractors(question):
                return False
        
        return True
        
    except Exception as e:
        print(f"Error validating distractors: {e}")
        return False


def validate_comprehensive_quiz_quality(content: Union[str, Dict[str, Any]]) -> bool:
    """
    Comprehensive validation combining all quality checks.
    
    This function runs all validation checks and requires all to pass.
    """
    return (validate_scenario_quality(content) and 
            validate_question_clarity(content) and
            validate_distractors(content))


# Helper functions

def _extract_scenarios(content: Union[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract scenarios from content in various formats."""
    scenarios = []
    
    if isinstance(content, str):
        try:
            # Try to parse as JSON
            parsed = json.loads(content)
            scenarios = _extract_scenarios(parsed)
        except json.JSONDecodeError:
            # Try to parse as text with scenario markers
            scenarios = _parse_text_scenarios(content)
    
    elif isinstance(content, dict):
        # Look for common scenario fields
        for key in ['scenarios', 'quiz_scenarios', 'content', 'questions']:
            if key in content:
                value = content[key]
                if isinstance(value, list):
                    scenarios.extend(value)
                elif isinstance(value, dict):
                    scenarios.append(value)
    
    elif isinstance(content, list):
        scenarios = content
    
    return scenarios


def _extract_questions(content: Union[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract questions from content in various formats."""
    questions = []
    
    # First try to get scenarios and extract questions from them
    scenarios = _extract_scenarios(content)
    for scenario in scenarios:
        if isinstance(scenario, dict):
            # Look for question fields
            for key in ['question', 'quiz_question', 'q', 'prompt']:
                if key in scenario:
                    questions.append(scenario)
                    break
    
    # If no questions found in scenarios, try direct extraction
    if not questions:
        if isinstance(content, dict):
            for key in ['questions', 'quiz_questions', 'refined_questions']:
                if key in content and isinstance(content[key], list):
                    questions.extend(content[key])
        elif isinstance(content, list):
            questions = content
    
    return questions


def _validate_single_scenario(scenario: Dict[str, Any], scenario_id: str) -> bool:
    """Validate a single scenario meets requirements."""
    
    # Check word count (150-200 words)
    text = _extract_text_from_scenario(scenario)
    if not text:
        return False
    
    word_count = len(text.split())
    if not (150 <= word_count <= 200):
        return False
    
    # Check for question and options
    if not _has_valid_question_structure(scenario):
        return False
    
    # Check for exactly one correct answer
    if not _has_single_correct_answer(scenario):
        return False
    
    return True


def _extract_text_from_scenario(scenario: Dict[str, Any]) -> str:
    """Extract all text content from a scenario for word counting."""
    text_parts = []
    
    # Common text fields to include in word count
    text_fields = ['scenario', 'context', 'description', 'question', 'prompt']
    
    for field in text_fields:
        if field in scenario and isinstance(scenario[field], str):
            text_parts.append(scenario[field])
    
    return ' '.join(text_parts)


def _has_valid_question_structure(scenario: Dict[str, Any]) -> bool:
    """Check if scenario has valid question structure with 4 options."""
    
    # Look for question
    has_question = any(key in scenario for key in ['question', 'quiz_question', 'q', 'prompt'])
    if not has_question:
        return False
    
    # Look for options (A, B, C, D)
    options = _extract_options(scenario)
    return len(options) == 4


def _extract_options(scenario: Dict[str, Any]) -> List[str]:
    """Extract answer options from scenario."""
    options = []
    
    # Look for options in various formats
    if 'options' in scenario and isinstance(scenario['options'], dict):
        option_dict = scenario['options']
        for key in ['A', 'B', 'C', 'D']:
            if key in option_dict:
                options.append(option_dict[key])
    
    elif 'choices' in scenario and isinstance(scenario['choices'], list):
        options = scenario['choices'][:4]  # Take first 4
    
    elif 'answers' in scenario and isinstance(scenario['answers'], dict):
        answer_dict = scenario['answers']
        for key in ['A', 'B', 'C', 'D']:
            if key in answer_dict:
                options.append(answer_dict[key])
    
    return options


def _has_single_correct_answer(scenario: Dict[str, Any]) -> bool:
    """Check if scenario has exactly one correct answer designated."""
    
    correct_answer_fields = ['correct_answer', 'answer', 'correct', 'solution']
    
    correct_count = 0
    for field in correct_answer_fields:
        if field in scenario:
            correct_count += 1
    
    # Should have exactly one way to indicate correct answer
    return correct_count == 1


def _is_question_clear(question: Dict[str, Any]) -> bool:
    """Check if question is clear and well-formed."""
    
    # Extract question text
    question_text = ""
    for field in ['question', 'quiz_question', 'q', 'prompt']:
        if field in question and isinstance(question[field], str):
            question_text = question[field]
            break
    
    if not question_text:
        return False
    
    # Basic clarity checks
    if len(question_text.strip()) < 10:  # Too short
        return False
    
    if not question_text.strip().endswith('?'):  # Should end with question mark
        return False
    
    # Check for clear grammar (basic checks)
    if question_text.count('?') > 1:  # Multiple question marks suggests confusion
        return False
    
    return True


def _has_valid_options(question: Dict[str, Any]) -> bool:
    """Check if question has exactly 4 valid options."""
    options = _extract_options(question)
    
    if len(options) != 4:
        return False
    
    # Each option should be substantive (not just single characters or empty)
    for option in options:
        if not isinstance(option, str) or len(option.strip()) < 2:
            return False
    
    return True


def _has_ambiguous_wording(question: Dict[str, Any]) -> bool:
    """Check for ambiguous or trick question wording."""
    
    question_text = ""
    for field in ['question', 'quiz_question', 'q', 'prompt']:
        if field in question and isinstance(question[field], str):
            question_text = question[field].lower()
            break
    
    # Check for problematic phrases that suggest ambiguity
    ambiguous_phrases = [
        'which of the following is not',
        'all of the above except',
        'which is the best',
        'which is the most appropriate',
        'select the incorrect',
        'choose the wrong'
    ]
    
    for phrase in ambiguous_phrases:
        if phrase in question_text:
            return True  # Found ambiguous wording
    
    return False  # No ambiguous wording found


def _validate_question_distractors(question: Dict[str, Any]) -> bool:
    """Validate that distractors are high quality."""
    
    options = _extract_options(question)
    if len(options) != 4:
        return False
    
    # Basic distractor quality checks
    for option in options:
        # Each distractor should be substantive
        if len(option.split()) < 2:  # Too short/simple
            return False
        
        # Should not contain obvious joke answers
        if _is_joke_answer(option):
            return False
        
        # Should not be identical or near-identical to other options
        for other_option in options:
            if option != other_option and _are_too_similar(option, other_option):
                return False
    
    return True


def _is_joke_answer(option: str) -> bool:
    """Check if an option appears to be a joke answer."""
    option_lower = option.lower()
    
    joke_indicators = [
        'none of the above',
        'all of the above', 
        'i don\'t know',
        'who cares',
        'it doesn\'t matter',
        'your mom',
        '42',  # Hitchhiker's Guide reference
        'magic',
        'because reasons'
    ]
    
    return any(indicator in option_lower for indicator in joke_indicators)


def _are_too_similar(option1: str, option2: str) -> bool:
    """Check if two options are too similar to each other."""
    # Simple similarity check based on word overlap
    words1 = set(option1.lower().split())
    words2 = set(option2.lower().split())
    
    if not words1 or not words2:
        return False
    
    # If more than 80% of words overlap, they're too similar
    overlap = len(words1.intersection(words2))
    min_length = min(len(words1), len(words2))
    
    if min_length == 0:
        return False
    
    similarity = overlap / min_length
    return similarity > 0.8


def _parse_text_scenarios(text: str) -> List[Dict[str, Any]]:
    """Parse scenarios from plain text format."""
    scenarios = []
    
    # Look for numbered scenarios or question patterns
    scenario_pattern = r'(?:Scenario|Question)\s*(\d+)[:.]?\s*(.*?)(?=(?:Scenario|Question)\s*\d+|$)'
    matches = re.findall(scenario_pattern, text, re.DOTALL | re.IGNORECASE)
    
    for match in matches:
        scenario_num, scenario_text = match
        scenarios.append({
            'scenario_number': int(scenario_num),
            'content': scenario_text.strip(),
            'text': scenario_text.strip()
        })
    
    return scenarios


def get_quiz_quality_info(content: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get detailed information about quiz quality for debugging.
    
    Args:
        content: Quiz content to analyze
        
    Returns:
        Dict with detailed quality analysis
    """
    info = {
        'scenarios_found': 0,
        'questions_found': 0,
        'scenario_word_counts': [],
        'validation_results': {},
        'issues_found': []
    }
    
    try:
        scenarios = _extract_scenarios(content)
        questions = _extract_questions(content)
        
        info['scenarios_found'] = len(scenarios)
        info['questions_found'] = len(questions)
        
        # Analyze word counts
        for i, scenario in enumerate(scenarios):
            text = _extract_text_from_scenario(scenario)
            word_count = len(text.split()) if text else 0
            info['scenario_word_counts'].append({
                f'scenario_{i+1}': word_count,
                'meets_range': 150 <= word_count <= 200
            })
        
        # Run validation checks
        info['validation_results'] = {
            'scenario_quality': validate_scenario_quality(content),
            'question_clarity': validate_question_clarity(content), 
            'distractor_quality': validate_distractors(content),
            'comprehensive_quality': validate_comprehensive_quiz_quality(content)
        }
        
        # Identify specific issues
        if not info['validation_results']['scenario_quality']:
            if len(scenarios) != 3:
                info['issues_found'].append(f"Expected 3 scenarios, found {len(scenarios)}")
            
            for i, wc_info in enumerate(info['scenario_word_counts']):
                if not wc_info['meets_range']:
                    scenario_key = f'scenario_{i+1}'
                    word_count = wc_info[scenario_key]
                    info['issues_found'].append(f"Scenario {i+1}: {word_count} words (need 150-200)")
        
    except Exception as e:
        info['error'] = str(e)
        info['issues_found'].append(f"Analysis error: {e}")
    
    return info