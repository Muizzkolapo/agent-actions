import re
import json
from typing import Any, Dict, List, TypedDict, Union
from agent_actions import udf_tool


def add_html_formatting(text: str) -> str:
    """
    Add <p> and <br> tags to text based on rules for better readability.
    Respects sentence boundaries and natural break points.
    """
    if not text or not isinstance(text, str):
        return text

    # Skip if already has HTML tags
    if "<p>" in text or "<br>" in text:
        return text

    # Skip markdown headers
    if text.strip().startswith("#"):
        return text

    # Split text into sentences (but keep the delimiter)
    sentence_pattern = r"(?<=[.!?])\s+(?=[A-Z])"
    sentences = re.split(sentence_pattern, text)

    # Clean up sentences
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= 1:
        # Single sentence or short text - just wrap it
        return f"<p>{text}</p>"

    formatted_parts = []
    current_paragraph = []

    for i, sentence in enumerate(sentences):
        # Check if this sentence should start a new paragraph
        should_break_paragraph = False

        # Rule 1: Question sentences after initial context get their own paragraph
        if i > 0 and "?" in sentence:
            should_break_paragraph = True

        # Rule 2: Sentences starting with question words after first sentence
        if i > 0 and re.match(
            r"^(Which|What|When|Where|How|Why|Who|Do|Does|Can|Should|Is|Are)\s", sentence
        ):
            should_break_paragraph = True

        # Rule 3: New scenario or context shift
        if i > 0 and current_paragraph:
            # Check for scenario markers
            if re.match(
                r"^(You\s|Your\s|The system\s|The service\s|Users\s|Operators\s)", sentence
            ):
                # Only break if we have accumulated some content
                if len(" ".join(current_paragraph)) > 60:
                    should_break_paragraph = True

        # Rule 4: Very long accumulated paragraphs (but complete the sentence)
        if current_paragraph and len(" ".join(current_paragraph)) > 200:
            should_break_paragraph = True

        if should_break_paragraph and current_paragraph:
            # Join current paragraph and wrap in <p> tags
            paragraph_text = " ".join(current_paragraph)
            formatted_parts.append(f"<p>{paragraph_text}</p>")
            current_paragraph = [sentence]
        else:
            current_paragraph.append(sentence)

    # Add remaining paragraph
    if current_paragraph:
        paragraph_text = " ".join(current_paragraph)
        formatted_parts.append(f"<p>{paragraph_text}</p>")

    return "\n".join(formatted_parts)


def add_line_breaks_to_long_text(text: str) -> str:
    """
    Add <br> tags to very long continuous text at natural break points.
    Only for texts that are unusually long without natural paragraph breaks.
    """
    if not text or len(text) < 300:  # Only for very long text
        return text

    # Find natural break points in order of preference
    # 1. After complete sentences (. ! ?)
    # 2. After semicolons
    # 3. Before conjunctions (and, or, but) in long sentences

    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)

    if len(sentences) > 2:
        # Multiple sentences - add a break in the middle
        mid = len(sentences) // 2
        first_half = " ".join(sentences[:mid])
        second_half = " ".join(sentences[mid:])
        return f"{first_half}<br>{second_half}"

    # Single long sentence - look for semicolons
    if ";" in text:
        parts = text.split(";", 1)
        return f"{parts[0]};<br>{parts[1]}"

    # Look for conjunctions in the middle
    if len(text) > 400:
        # Find a good break point near the middle
        mid_point = len(text) // 2
        # Look for ", and" or ", or" or ", but" near the middle
        for pattern in [r",\s+and\s+", r",\s+or\s+", r",\s+but\s+"]:
            matches = list(re.finditer(pattern, text))
            if matches:
                # Find the match closest to the middle
                best_match = min(matches, key=lambda m: abs(m.start() - mid_point))
                if abs(best_match.start() - mid_point) < 100:  # Within reasonable range
                    return (
                        text[: best_match.start()]
                        + ",<br>"
                        + text[best_match.start() + 1 :].lstrip()
                    )

    return text


def format_option_text(text: str) -> str:
    """
    Special formatting for option text.
    Options get wrapped in <p> tags but rarely need internal breaks.
    """
    if not text or not isinstance(text, str):
        return text

    # Skip if already has HTML tags
    if "<p>" in text or "<br>" in text:
        return text

    # For very long options (>200 chars), check if we should add a break
    if len(text) > 200:
        # Only add line break if there's a natural break point
        # Look for semicolons first
        if ";" in text:
            parts = text.split(";", 1)
            return f"<p>{parts[0]};<br>{parts[1].strip()}</p>"

        # Look for "instead of" or "rather than" phrases
        for phrase in ["instead of", "rather than", "as opposed to"]:
            if phrase in text.lower():
                parts = text.lower().split(phrase, 1)
                if len(parts) == 2:
                    # Find the actual position in original text
                    idx = text.lower().index(phrase)
                    return f"<p>{text[:idx].rstrip()}<br>{text[idx:]}</p>"

    # Default: just wrap in <p> tags without breaks
    return f"<p>{text}</p>"


class FormatQuizObjectInput(TypedDict, total=False):
    """Input schema for format_quiz_object function.

    Source: node_16_OptionsCombiner output
    Destination: node_17_format_quiz_text output (adds HTML formatting and collapsible sections)

    This function applies HTML formatting to text fields and creates
    collapsible explanation sections for the final quiz output.
    """

    # Core question fields
    question: str
    options: List[str]
    answer: List[str]  # List of correct answer texts
    answer_text: List[str]  # Always a list
    answer_explanation: str
    question_type: str

    # Answer metadata (from OptionsCombiner)
    answer_indices: List[int]
    answer_reasoning: str

    # Generated distractors and explanations
    distractor_1: str
    distractor_2: str
    distractor_3: str
    explanation_why_it_is_incorrect_1: str
    explanation_why_it_is_incorrect_2: str
    explanation_why_it_is_incorrect_3: str

    # Combined options structure (from OptionsCombiner)
    options_combined: List[dict]
    correct_answers: List[dict]
    distractors: List[dict]
    combined_explanation: str

    # Feynman explanation fields
    question_explanation: str
    key_concept_analogy: str
    memorable_takeaway: str

    # Concept explanation
    concept_explanation: str


@udf_tool(input_type=FormatQuizObjectInput)
def format_quiz_object(quiz_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply HTML formatting to all text fields in a quiz object.
    Main function that processes the entire quiz structure.
    """
    formatted = quiz_obj.copy()

    # Format main question
    if "question" in formatted:
        formatted["question"] = add_html_formatting(formatted["question"])

    # Format options array
    if "options" in formatted and isinstance(formatted["options"], list):
        formatted["options"] = [
            format_option_text(opt) if isinstance(opt, str) else opt for opt in formatted["options"]
        ]

    # Format options_combined array
    if "options_combined" in formatted and isinstance(formatted["options_combined"], list):
        for item in formatted["options_combined"]:
            if isinstance(item, dict):
                if "option" in item:
                    item["option"] = format_option_text(item["option"])
                if "explanation_why_it_is_correct_or_incorrect" in item:
                    # Explanations might be longer and benefit from line breaks
                    explanation = item["explanation_why_it_is_correct_or_incorrect"]
                    formatted_explanation = add_html_formatting(explanation)
                    # Check if very long explanation needs internal breaks
                    if len(explanation) > 300 and "<br>" not in formatted_explanation:
                        formatted_explanation = add_line_breaks_to_long_text(formatted_explanation)
                    item["explanation_why_it_is_correct_or_incorrect"] = formatted_explanation

    # NEW SECTION - Create collapsible explanation sections (but keep answer_explanation unchanged)
    if "question_explanation" in formatted and "answer_reasoning" in formatted:
        # Format both Feynman explanations
        question_exp = add_html_formatting(formatted["question_explanation"])
        if len(formatted["question_explanation"]) > 300 and "<br>" not in question_exp:
            question_exp = add_line_breaks_to_long_text(question_exp)

        answer_exp = add_html_formatting(formatted["answer_reasoning"])
        if len(formatted["answer_reasoning"]) > 300 and "<br>" not in answer_exp:
            answer_exp = add_line_breaks_to_long_text(answer_exp)

        # Create combined Feynman explanation
        combined_feynman = f"{question_exp}\n\n{answer_exp}"
        formatted["feynman_explanation_collapsible"] = (
            f"<details><summary>🧠 Simple Explanation</summary>{combined_feynman}</details>"
        )

    # Create collapsible concept explanation from summary
    if "summary" in formatted:
        content = formatted["summary"]
        formatted_content = add_html_formatting(content)
        if len(content) > 300 and "<br>" not in formatted_content:
            formatted_content = add_line_breaks_to_long_text(formatted_content)
        formatted["concept_explanation_collapsible"] = (
            f"<details><summary>📖 Concept Explanation</summary>{formatted_content}</details>"
        )

    # Format answer_explanation (keep unchanged - no collapsible wrapper)
    if "answer_explanation" in formatted:
        explanation = formatted["answer_explanation"]
        formatted_explanation = add_html_formatting(explanation)
        # Check if very long explanation needs internal breaks
        if len(explanation) > 300 and "<br>" not in formatted_explanation:
            formatted_explanation = add_line_breaks_to_long_text(formatted_explanation)
        formatted["answer_explanation"] = formatted_explanation

    # Format combined_explanation - handle markdown headers specially
    if "combined_explanation" in formatted:
        # Split by markdown headers to preserve them
        parts = re.split(r"(##[^\n]+)", formatted["combined_explanation"])
        formatted_parts = []

        for part in parts:
            if part.startswith("##"):
                formatted_parts.append(part)  # Keep headers as-is
            elif part.strip():
                # Format non-header content
                formatted_text = add_html_formatting(part.strip())
                # Check if needs internal breaks
                if len(part.strip()) > 300 and "<br>" not in formatted_text:
                    formatted_text = add_line_breaks_to_long_text(formatted_text)
                formatted_parts.append(formatted_text)

        formatted["combined_explanation"] = "\n".join(formatted_parts)

    # Format correct_answers array
    if "correct_answers" in formatted and isinstance(formatted["correct_answers"], list):
        for item in formatted["correct_answers"]:
            if isinstance(item, dict):
                if "option" in item:
                    item["option"] = format_option_text(item["option"])
                if "explanation_why_it_is_correct" in item:
                    explanation = item["explanation_why_it_is_correct"]
                    formatted_explanation = add_html_formatting(explanation)
                    if len(explanation) > 300 and "<br>" not in formatted_explanation:
                        formatted_explanation = add_line_breaks_to_long_text(formatted_explanation)
                    item["explanation_why_it_is_correct"] = formatted_explanation

    # Format distractors array
    if "distractors" in formatted and isinstance(formatted["distractors"], list):
        for item in formatted["distractors"]:
            if isinstance(item, dict):
                if "option" in item:
                    item["option"] = format_option_text(item["option"])
                if "explanation_why_it_is_incorrect" in item:
                    explanation = item["explanation_why_it_is_incorrect"]
                    formatted_explanation = add_html_formatting(explanation)
                    if len(explanation) > 300 and "<br>" not in formatted_explanation:
                        formatted_explanation = add_line_breaks_to_long_text(formatted_explanation)
                    item["explanation_why_it_is_incorrect"] = formatted_explanation

    return formatted


def process_quiz_file(input_file: str, output_file: str = None):
    """
    Process a JSON file containing quiz objects and add HTML formatting.
    """
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Handle single object or array of objects
    if isinstance(data, list):
        formatted_data = []
        for item in data:
            if "content" in item:
                # Handle wrapped format
                formatted_item = item.copy()
                formatted_item["content"] = format_quiz_object(item["content"])
                formatted_data.append(formatted_item)
            else:
                # Handle direct format
                formatted_data.append(format_quiz_object(item))
    elif isinstance(data, dict):
        if "content" in data:
            formatted_data = data.copy()
            formatted_data["content"] = format_quiz_object(data["content"])
        else:
            formatted_data = format_quiz_object(data)
    else:
        formatted_data = data

    # Write to output file
    if output_file is None:
        output_file = input_file.replace(".json", "_formatted.json")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(formatted_data, f, indent=2, ensure_ascii=False)

    print(f"Formatted quiz saved to: {output_file}")
    return formatted_data


# Example usage
if __name__ == "__main__":
    # Test with a sample quiz object
    sample_quiz = {
        "question": "You are integrating an Azure AI Foundry agent with external services using Azure Functions. You want the agent to invoke a function in response to an external request and exchange data with Azure Blob Storage without writing manual integration code inside the function. Which approach best satisfies these requirements?",
        "options": [
            "Configure the Azure Function with an Event Grid trigger that runs whenever blobs are created or updated, and use input/output Blob bindings so the function processes blob events; have the agent create or update blobs to cause the function to run.",
            "Configure the Azure Function with an HTTP trigger so the agent can invoke it on request, and add input/output bindings for Azure Blob Storage to let the function read/write blobs without custom SDK code.",
        ],
        "answer_explanation": "The correct approach is to use a trigger that represents the external event (an HTTP trigger for incoming requests from the agent) combined with input/output bindings configured for Azure Blob Storage. Triggers determine when the function runs, and bindings provide preconfigured connections to read/write data without requiring manual SDK integration code inside the function.",
    }

    formatted = format_quiz_object(sample_quiz)
    print(json.dumps(formatted, indent=2))
