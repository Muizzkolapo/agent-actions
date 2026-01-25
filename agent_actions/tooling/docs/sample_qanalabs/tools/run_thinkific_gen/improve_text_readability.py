"""
Tool to improve text readability by breaking long paragraphs into shorter chunks
"""
import re
from typing import Any, Dict, List, TypedDict
from agent_actions import udf_tool
from bs4 import BeautifulSoup


def break_long_paragraph(text: str, max_length: int = 200) -> str:
    """
    Break a long paragraph into multiple shorter paragraphs at natural break points
    
    Args:
        text: The paragraph text
        max_length: Maximum character length before breaking
        
    Returns:
        Text broken into multiple paragraphs
    """
    if len(text) <= max_length:
        return text
    
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    paragraphs = []
    current_para = []
    current_length = 0
    
    for sentence in sentences:
        sentence_length = len(sentence)
        
        # If adding this sentence exceeds max_length and we have content, start new paragraph
        if current_length + sentence_length > max_length and current_para:
            paragraphs.append(' '.join(current_para))
            current_para = [sentence]
            current_length = sentence_length
        else:
            current_para.append(sentence)
            current_length += sentence_length + 1  # +1 for space
    
    # Add remaining sentences
    if current_para:
        paragraphs.append(' '.join(current_para))
    
    return '\n\n'.join(paragraphs)


def improve_html_readability(html_string: str) -> str:
    """
    Improve readability of HTML by breaking long paragraphs
    
    Args:
        html_string: HTML content
        
    Returns:
        HTML with improved readability
    """
    if not html_string or not isinstance(html_string, str):
        return html_string
    
    # Skip if not HTML
    if '<' not in html_string or '>' not in html_string:
        # Plain text - just break it up
        return break_long_paragraph(html_string)
    
    try:
        soup = BeautifulSoup(html_string, 'html.parser')
        
        # Find all <p> tags
        for p_tag in soup.find_all('p'):
            text = p_tag.get_text()
            
            # If paragraph is too long, break it up
            if len(text) > 200:
                # Get broken text
                broken_text = break_long_paragraph(text, max_length=200)
                
                # Split into new paragraphs
                new_paragraphs = broken_text.split('\n\n')
                
                if len(new_paragraphs) > 1:
                    # Create new <p> tags for each paragraph
                    parent = p_tag.parent
                    index = parent.contents.index(p_tag)
                    
                    # Remove original <p>
                    p_tag.extract()
                    
                    # Insert new <p> tags
                    for i, para_text in enumerate(new_paragraphs):
                        new_p = soup.new_tag('p')
                        new_p.string = para_text
                        parent.insert(index + i, new_p)
        
        return str(soup)
    
    except Exception as e:
        # If parsing fails, return original
        return html_string




class ImproveTextReadabilityInput(TypedDict, total=False):
    """Input schema for improve_text_readability function.

    This is STEP 4 in the Thinkific quiz generation pipeline.
    Receives HTML-formatted data from format_quiz_object and improves readability.

    Input source: node_2_format_quiz_object output (7 fields)
    Output destination: node_4_prettify_html_formatting

    Input/Output fields (7 total - same structure, improved content):
    - answer_indices: List[int] - Indices of correct answers
    - answer_letter: str - Letter(s) of correct answer(s)
    - batch_name: str - Quiz batch identifier
    - explanation: str - HTML explanation (readability improved)
    - options: List[str] - HTML options (readability improved)
    - question: str - HTML question (readability improved)
    - question_type: str - 'SA' or 'MA'
    """
    # -------------------------------------------------------------------------
    # Core quiz fields (7 fields from format_quiz_object)
    # -------------------------------------------------------------------------
    question: str                    # HTML question text (will be improved)
    options: List[Any]               # HTML answer options (will be improved)
    explanation: str                 # HTML explanation (will be improved)
    answer_letter: str               # e.g., 'A' or 'A,B,C' for MA (passthrough)
    answer_indices: List[int]        # Indices of correct answers (passthrough)
    question_type: str               # 'SA' or 'MA' (passthrough)
    batch_name: str                  # Quiz batch identifier (passthrough)


@udf_tool()
def improve_text_readability(quiz_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Improve text readability by breaking long paragraphs into shorter chunks
    
    Focuses on:
    - Breaking paragraphs > 200 characters
    - Natural sentence boundaries
    - Maintaining HTML structure
    
    Args:
        quiz_obj: Quiz object with content
        
    Returns:
        Quiz object with improved readability
    """
    formatted = quiz_obj.copy()
    
    # Improve question readability
    if 'question' in formatted:
        formatted['question'] = improve_html_readability(formatted['question'])
    
    # Improve options
    if 'options' in formatted and isinstance(formatted['options'], list):
        formatted['options'] = [
            improve_html_readability(opt) if isinstance(opt, str) else opt
            for opt in formatted['options']
        ]
    
    # Improve explanation
    if 'explanation' in formatted:
        formatted['explanation'] = improve_html_readability(formatted['explanation'])
    
    # Improve answer_explanation
    if 'answer_explanation' in formatted:
        formatted['answer_explanation'] = improve_html_readability(formatted['answer_explanation'])
    
    # Improve combined_explanation
    if 'combined_explanation' in formatted:
        formatted['combined_explanation'] = improve_html_readability(formatted['combined_explanation'])
    
    # Improve collapsible sections (MOST IMPORTANT for Concept Explanation)
    if 'feynman_explanation_collapsible' in formatted:
        formatted['feynman_explanation_collapsible'] = improve_html_readability(formatted['feynman_explanation_collapsible'])
    
    if 'concept_explanation_collapsible' in formatted:
        formatted['concept_explanation_collapsible'] = improve_html_readability(formatted['concept_explanation_collapsible'])
    
    return formatted


if __name__ == "__main__":
    # Test with a long paragraph
    long_text = """When a receiver obtains a cancellation notification that references an in-progress request, the receiver is expected to: stop processing the referenced request, free any resources associated with that request, and not send a response for that request. The instruction is expressed with the normative qualifier SHOULD, indicating this is the expected/recommended behavior rather than an absolute mandate. The provided material does not supply an explicit rationale beyond instructing these three actions. In practice, the directive applies specifically to the referenced in-progress request named in the cancellation notification, and the absence of a required (MUST) qualifier means implementations may have some discretion while the listed actions remain the recommended behavior."""
    
    print("Original:")
    print(long_text)
    print(f"\nLength: {len(long_text)} characters")
    
    print("\n" + "="*70)
    print("\nImproved:")
    improved = break_long_paragraph(long_text)
    print(improved)
