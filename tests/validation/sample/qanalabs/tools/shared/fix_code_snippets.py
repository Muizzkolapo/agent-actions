"""
Tool to fix double-escaped code snippets in any programming language
"""

import re
import codecs
from typing import Any, List, TypedDict
from agent_actions import udf_tool


def detect_language_simple(code):
    """Simple pattern-based language detection"""
    patterns = {
        "python": [r"\bdef\b", r"\bimport\b", r"\bclass\b", r"print\("],
        "javascript": [r"\bfunction\b", r"\bconst\b", r"\blet\b", r"=>", r"\.then\("],
        "json": [r"^\s*[{\[]", r'"jsonrpc"', r'"method"', r'"id"\s*:\s*\d'],
        "bash": [r"^#!/bin/bash", r"\bexport\b", r"\bcurl\b", r"\bchmod\b"],
        "yaml": [r"^---", r":\s*$", r"apiVersion:"],
        "sql": [r"\bSELECT\b", r"\bINSERT\b", r"\bFROM\b"],
        "typescript": [r"\binterface\b", r"\btype\b", r":\s*string", r":\s*number"],
    }

    for lang, regexes in patterns.items():
        if any(re.search(pattern, code, re.MULTILINE | re.IGNORECASE) for pattern in regexes):
            return lang

    return "text"


def fix_unicode_escapes(snippet):
    """Fix Unicode escape sequences using codecs"""
    # Check if there are Unicode escapes
    if r"\u" in snippet:
        try:
            # Decode Unicode escapes
            snippet = codecs.decode(snippet, "unicode_escape")
        except:
            pass  # If decoding fails, return as-is

    # First, handle quote patterns (sequence-based replacements)
    # Pattern: \u001c\u201c ... \u001d\u001d represents quoted text
    snippet = snippet.replace("\u001c\u201c", '"')  # Opening quote sequence
    snippet = snippet.replace("\u001d\u001d", '"')  # Closing quote sequence

    # Then handle remaining individual characters
    unicode_char_map = {
        "\u001c": "",  # Information Separator Four (remove if not part of pattern)
        "\u001d": "",  # Information Separator Three (remove if not part of pattern)
        "\u001e": "",  # Information Separator Two (remove)
        "\u001f": "",  # Information Separator One (remove)
        "\u201c": '"',  # Left double quotation mark
        "\u201d": '"',  # Right double quotation mark
        "\u2018": "'",  # Left single quotation mark
        "\u2019": "'",  # Right single quotation mark
        "\u2013": "-",  # En dash
        "\u2014": "--",  # Em dash
        "\u00a0": " ",  # Non-breaking space
    }

    # Replace special Unicode characters with readable equivalents
    for char, replacement in unicode_char_map.items():
        snippet = snippet.replace(char, replacement)

    return snippet


def unescape_snippet(snippet):
    """Unescape double-escaped content and Unicode escapes"""
    # Remove outer quotes if the entire snippet is wrapped
    if snippet.startswith('"') and snippet.endswith('"') and snippet.count('"') > 2:
        snippet = snippet[1:-1]

    # Fix Unicode escape sequences first
    snippet = fix_unicode_escapes(snippet)

    # Unescape in specific order to avoid conflicts
    snippet = snippet.replace("\\\\", "\x00")  # Temporary marker for \\
    snippet = snippet.replace("\\n", "\n")
    snippet = snippet.replace("\\t", "\t")
    snippet = snippet.replace('\\"', '"')
    snippet = snippet.replace("\\'", "'")
    snippet = snippet.replace("\\r", "\r")
    snippet = snippet.replace("\x00", "\\")  # Restore single backslash

    return snippet


def is_double_escaped(snippet):
    """Check if snippet has double-escaping issues"""
    has_escaped_newlines = "\\n" in snippet
    has_escaped_quotes = '\\"' in snippet
    has_outer_wrapper = snippet.startswith('"') and snippet.endswith('"') and snippet.count('"') > 2
    has_unicode_escapes = r"\u" in snippet  # Check for Unicode escape sequences

    return has_escaped_newlines or has_escaped_quotes or has_outer_wrapper or has_unicode_escapes


def is_well_formatted(snippet):
    """Check if snippet is already well-formatted"""
    has_markdown = any(
        marker in snippet for marker in ["* `", "+ `", "- `", "\n  +", "\n  *", "\n* "]
    )
    has_code_fence = "```" in snippet

    return (has_markdown or has_code_fence) and not is_double_escaped(snippet)


def fix_snippet(snippet):
    """Fix a single code snippet"""
    if not isinstance(snippet, str):
        return snippet

    # Already well-formatted
    if is_well_formatted(snippet):
        return snippet

    # Fix double-escaped
    if is_double_escaped(snippet):
        unescaped = unescape_snippet(snippet)
        language = detect_language_simple(unescaped)

        # Wrap in fence if code, not markdown
        if language != "text" and not unescaped.strip().startswith("*"):
            return f"```{language}\n{unescaped.strip()}\n```"
        else:
            return unescaped

    return snippet


class FixCodeSnippetsInput(TypedDict, total=False):
    """Input schema for fix_code_snippets function.

    This is the FIRST step in the Thinkific quiz generation pipeline.
    Receives raw quiz data from upstream workflow and fixes code snippets.

    Input source: Raw quiz generation workflow output
    Output destination: node_1_combine_quiz_fields

    After processing, outputs 13 fields:
    - answer, answer_indices, combined_explanation, concept_explanation,
    - correct_answers, distractors, key_concept_analogy, memorable_takeaway,
    - options, options_combined, question, question_explanation, question_type
    """

    # -------------------------------------------------------------------------
    # Core quiz content fields
    # -------------------------------------------------------------------------
    question: str  # The quiz question text
    options: List[Any]  # Answer options (list of strings)
    answer: List[Any]  # Correct answer(s)
    answer_indices: List[int]  # Indices of correct answers in options
    question_type: str  # 'SA' (single answer) or 'MA' (multiple answer)

    # -------------------------------------------------------------------------
    # Explanation fields (Feynman-style learning)
    # -------------------------------------------------------------------------
    question_explanation: str  # Detailed explanation of the question
    concept_explanation: str  # Educational explanation of the concept
    key_concept_analogy: str  # Analogy to help understand the concept
    memorable_takeaway: str  # Key point to remember
    combined_explanation: str  # Full combined explanation text

    # -------------------------------------------------------------------------
    # Answer/Distractor data structures
    # -------------------------------------------------------------------------
    correct_answers: List[dict]  # [{option, explanation_why_it_is_correct}, ...]
    distractors: List[dict]  # [{option, explanation_why_it_is_incorrect}, ...]
    options_combined: List[dict]  # All options with answer_or_distractor flag

    # -------------------------------------------------------------------------
    # Fields that will be dropped after processing
    # -------------------------------------------------------------------------
    content: dict  # Wrapper field (legacy)
    code_snippets: List[Any]  # Code snippets to fix (dropped after fix)
    answer_text: List[str]  # Dropped - redundant with answer (always list)
    answer_explanation: str  # Dropped - merged into combined_explanation
    answer_reasoning: str  # Dropped - internal reasoning
    question_status: str  # Dropped - workflow status
    status_reason: str  # Dropped - workflow status reason
    concept_explanation_collapsible: str  # Dropped - generated later
    feynman_explanation_collapsible: str  # Dropped - generated later
    distractor_1: str  # Dropped - merged into distractors
    distractor_2: str  # Dropped - merged into distractors
    distractor_3: str  # Dropped - merged into distractors
    explanation_why_it_is_incorrect_1: str  # Dropped - merged into distractors
    explanation_why_it_is_incorrect_2: str  # Dropped - merged into distractors
    explanation_why_it_is_incorrect_3: str  # Dropped - merged into distractors
    thinking_process_1: str  # Dropped - internal reasoning


@udf_tool(input_type=FixCodeSnippetsInput)
def fix_code_snippets(record):
    """
    Tool function: Fix code_snippets in content field

    Returns: Same record with fixed code_snippets and unused fields dropped
    """
    # Fields to drop that downstream tools don't need
    fields_to_drop = [
        "answer_explanation",
        "answer_text",
        "answer_reasoning",
        "question_status",
        "status_reason",
        "code_snippets",
        "concept_explanation_collapsible",
        "feynman_explanation_collapsible",
        "distractor_1",
        "distractor_2",
        "distractor_3",
        "explanation_why_it_is_incorrect_1",
        "explanation_why_it_is_incorrect_2",
        "explanation_why_it_is_incorrect_3",
        "thinking_process_1",
    ]

    # Handle both wrapped (content) and unwrapped data structures
    if "content" in record and isinstance(record["content"], dict):
        content = record["content"]
        if "code_snippets" in content and isinstance(content["code_snippets"], list):
            content["code_snippets"] = [fix_snippet(s) for s in content["code_snippets"]]
        for field in fields_to_drop:
            content.pop(field, None)
    else:
        # Data is at record level
        if "code_snippets" in record and isinstance(record["code_snippets"], list):
            record["code_snippets"] = [fix_snippet(s) for s in record["code_snippets"]]
        for field in fields_to_drop:
            record.pop(field, None)

    return record
