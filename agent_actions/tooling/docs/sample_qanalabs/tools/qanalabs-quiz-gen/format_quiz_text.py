import json
import re
from typing import Any, Dict, List, Union
from agent_actions import udf_tool


def add_html_formatting(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    if "<p>" in text or "<br>" in text:
        return text
    if text.strip().startswith("#"):
        return text

    sentence_pattern = r"(?<=[.!?])\s+(?=[A-Z])"
    sentences = re.split(sentence_pattern, text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= 1:
        return f"<p>{text}</p>"

    formatted_parts: List[str] = []
    current: List[str] = []

    for i, sentence in enumerate(sentences):
        should_break = False
        if i > 0 and "?" in sentence:
            should_break = True
        if i > 0 and re.match(r"^(Which|What|When|Where|How|Why|Who|Do|Does|Can|Should|Is|Are)\s", sentence):
            should_break = True
        if i > 0 and current:
            if re.match(r"^(You\s|Your\s|The system\s|The service\s|Users\s|Operators\s)", sentence):
                if len(" ".join(current)) > 60:
                    should_break = True
        if current and len(" ".join(current)) > 200:
            should_break = True

        if should_break and current:
            paragraph_text = " ".join(current)
            formatted_parts.append(f"<p>{paragraph_text}</p>")
            current = [sentence]
        else:
            current.append(sentence)

    if current:
        paragraph_text = " ".join(current)
        formatted_parts.append(f"<p>{paragraph_text}</p>")

    return "\n".join(formatted_parts)


def add_line_breaks_to_long_text(text: str) -> str:
    if not text or len(text) < 300:
        return text

    if ";" in text:
        parts = text.split(";", 1)
        return f"{parts[0]};<br>{parts[1].strip()}"

    if len(text) > 400:
        mid = len(text) // 2
        for pattern in [r",\s+and\s+", r",\s+or\s+", r",\s+but\s+"]:
            matches = list(re.finditer(pattern, text))
            if matches:
                best = min(matches, key=lambda m: abs(m.start() - mid))
                if abs(best.start() - mid) < 100:
                    return text[:best.start()] + ",<br>" + text[best.start() + 1:].lstrip()

    return text


def format_option_text(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    if "<p>" in text or "<br>" in text:
        return text

    if len(text) > 200:
        if ";" in text:
            parts = text.split(";", 1)
            return f"<p>{parts[0]};<br>{parts[1].strip()}</p>"
        for phrase in ["instead of", "rather than", "as opposed to"]:
            if phrase in text.lower():
                idx = text.lower().index(phrase)
                return f"<p>{text[:idx].rstrip()}<br>{text[idx:]}</p>"

    return f"<p>{text}</p>"


@udf_tool()
def format_quiz_object(quiz_obj: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(quiz_obj, str):
        quiz_obj = json.loads(quiz_obj)

    if not isinstance(quiz_obj, dict):
        return quiz_obj

    # Handle content wrapper
    if 'content' in quiz_obj:
        content = quiz_obj['content']
    else:
        content = quiz_obj

    formatted = content.copy()

    if "question" in formatted:
        formatted["question"] = add_html_formatting(formatted["question"])

    if "options" in formatted and isinstance(formatted["options"], list):
        formatted["options"] = [format_option_text(opt) if isinstance(opt, str) else opt for opt in formatted["options"]]

    if "options_combined" in formatted and isinstance(formatted["options_combined"], list):
        for item in formatted["options_combined"]:
            if isinstance(item, dict):
                if "option" in item:
                    item["option"] = format_option_text(item["option"])
                if "explanation_why_it_is_correct_or_incorrect" in item:
                    exp = item["explanation_why_it_is_correct_or_incorrect"]
                    exp_fmt = add_html_formatting(exp)
                    if len(exp) > 300 and "<br>" not in exp_fmt:
                        exp_fmt = add_line_breaks_to_long_text(exp_fmt)
                    item["explanation_why_it_is_correct_or_incorrect"] = exp_fmt

    if "question_explanation" in formatted and "answer_reasoning" in formatted:
        q_exp = add_html_formatting(formatted["question_explanation"])
        if len(formatted["question_explanation"]) > 300 and "<br>" not in q_exp:
            q_exp = add_line_breaks_to_long_text(q_exp)
        a_exp = add_html_formatting(formatted["answer_reasoning"])
        if len(formatted["answer_reasoning"]) > 300 and "<br>" not in a_exp:
            a_exp = add_line_breaks_to_long_text(a_exp)
        formatted["feynman_explanation_collapsible"] = f"<details><summary>Simple Explanation</summary>{q_exp}\n\n{a_exp}</details>"

    if "concept_explanation" in formatted:
        content = formatted["concept_explanation"]
        formatted_content = add_html_formatting(content)
        if len(content) > 300 and "<br>" not in formatted_content:
            formatted_content = add_line_breaks_to_long_text(formatted_content)
        formatted["concept_explanation_collapsible"] = f"<details><summary>Concept Explanation</summary>{formatted_content}</details>"

    if "answer_explanation" in formatted:
        exp = formatted["answer_explanation"]
        exp_fmt = add_html_formatting(exp)
        if len(exp) > 300 and "<br>" not in exp_fmt:
            exp_fmt = add_line_breaks_to_long_text(exp_fmt)
        formatted["answer_explanation"] = exp_fmt

    return formatted
