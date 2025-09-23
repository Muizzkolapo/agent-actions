import string
import random
import re
import json
from typing import List, Dict, Any
import json
import random
import string
import uuid
import os

#-------------------------------------------------------------------------------------------------------------------------------------------
def flatten_testable_insights(data):
    """
    Transforms the input data into a list of dictionaries where each 'key_ideas'
    entry is placed under a separate 'key_ideas' key.

    Parameters:
        data (str): JSON string containing the original list of dictionaries.

    Returns:
        str: JSON string containing the transformed list of dictionaries.
    """
    returned_data = [
        {"key_ideas": test}
        for test in data["key_ideas"]
    ]
    return json.dumps(returned_data)

#-------------------------------------------------------------------------------------------------------------------------------------------



def transform_quiz_data(input_data):
    """
    Transform quiz data by removing distractor options and keeping only the correct answer option.

    Args:
        input_data (dict): The input quiz data with multiple options

    Returns:
        str: Transformed quiz data as a JSON string with only the correct option
    """
    output_data = input_data.copy()

    answer_letter = input_data.get("answer", "")
    options = input_data.get("options", [])

    # Ensure answer_letter is a single character A-Z
    if isinstance(answer_letter, str) and len(answer_letter.strip()) == 1 and answer_letter.strip().isalpha():
        answer_letter = answer_letter.strip().upper()
        answer_index = ord(answer_letter) - ord('A')

        if 0 <= answer_index < len(options):
            # Keep only the correct option
            options_answer = [options[answer_index]]
            output_data["options_answer"] = options_answer[0]

        # Remove original options list
        output_data.pop("options", None)

    

    return json.dumps([output_data], indent=2)

#-------------------------------------------------------------------------------------------------------------------------------------------




#---------------------------------------------------------------
# --- transform_quiz_data function ---
#---------------------------------------------------------------
# --- Constants for Thresholds (remain the same) ---
PERCENTAGE_THRESHOLD_FOR_BEING_LONGEST_WORDS = 8
PERCENTAGE_THRESHOLD_FOR_BEING_LONGEST_CHARS = 8
SIGNIFICANT_PERCENTAGE_DIFFERENCE_WORDS = 8
MINIMUM_ABSOLUTE_WORD_DIFFERENCE = 2
SIGNIFICANT_PERCENTAGE_DIFFERENCE_CHARS = 3
MINIMUM_ABSOLUTE_CHAR_DIFFERENCE = 4

# --- Helper Functions (remain the same) ---

def _get_option_stats(option_text: str) -> dict:
    """Calculates word count and character length for a single option."""
    words = option_text.split()
    return {"words": len(words), "chars": len(option_text)}

def _calculate_percentage_difference(value1: float, value2: float, base_for_percentage: float) -> float:
    """
    Calculates the percentage difference: (abs(value1 - value2) / base_for_percentage) * 100.
    Handles cases where base_for_percentage is 0.
    """
    if base_for_percentage == 0:
        return 100.0 if abs(value1 - value2) > 1e-9 else 0.0
    return (abs(value1 - value2) / base_for_percentage) * 100

# --- Main Function (Modified) ---

def add_answer_length_flag(input_data: dict) -> dict:
    """
    Analyzes if the correct answer option is problematically long based on defined criteria
    and adds a flag to the input data dictionary.

    The flag 'is_correct_answer_flagged_long' is True if the correct answer is:
    1. Among the longest options overall (close to the absolute longest).
    AND
    2. Significantly longer (in words or chars) than the next longest option.

    Parameters:
    - data (dict): Dictionary containing:
        - 'options' (list of str): The text of the answer choices.
        - 'answer' (str): The key of the correct answer (e.g., 'A', 'B').

    Returns:
    - dict: The modified input data dictionary with an added
            'is_correct_answer_flagged_long' key (boolean) and potentially
            an 'answer_length_analysis_error' key if validation fails.
    """
    data = input_data.copy()
    # --- 1. Initial Data Validation ---
    if not isinstance(data, dict):
        # If data itself isn't a dict, we can't reliably add keys.
        # Return a new dict with an error, or raise an exception.
        # For this example, returning a new dict with error.
        return {"answer_length_analysis_error": "Input data is not a dictionary.", "original_data_preview": str(data)[:100]}

    # Initialize new keys to ensure they exist, even if errors occur later
    data['is_correct_answer_flagged_long'] = None 
    data.pop('answer_length_analysis_error', None) # Remove pre-existing error key if any

    if "options" not in data or "answer" not in data:
        data['answer_length_analysis_error'] = "Invalid data structure. 'options' or 'answer' key missing."
        return data

    options = data["options"]
    answer_key = data["answer"]

    if not isinstance(options, list) or not options:
        data['answer_length_analysis_error'] = "'options' must be a non-empty list."
        return data
    if not all(isinstance(opt, str) for opt in options):
        data['answer_length_analysis_error'] = "All items in 'options' must be strings."
        return data
    if not isinstance(answer_key, str):
        data['answer_length_analysis_error'] = "'answer' key (e.g., 'A') must be a string."
        return data

    # Handle both letter format (A, B, C, D) and full text format
    if len(answer_key) == 1 and answer_key.isalpha() and answer_key.isupper():
        # Letter format - use directly
        try:
            correct_answer_index = ord(answer_key) - ord('A')
        except TypeError:
            data['answer_length_analysis_error'] = f"Could not process answer key '{answer_key}'."
            return data
    else:
        # Full text format - find matching option
        try:
            correct_answer_index = options.index(answer_key)
        except ValueError:
            data['answer_length_analysis_error'] = f"Answer text '{answer_key}' not found in options list."
            return data

    if not (0 <= correct_answer_index < len(options)):
        data['answer_length_analysis_error'] = f"Answer key '{answer_key}' is out of range for the {len(options)} options provided."
        return data

    # --- 2. Calculate Statistics for All Options ---
    all_options_stats = [_get_option_stats(opt) for opt in options]
    correct_answer_stats = all_options_stats[correct_answer_index]
    correct_word_count = correct_answer_stats["words"]
    correct_char_length = correct_answer_stats["chars"]

    # --- 3. Check 1: Is the correct answer among the longest options overall? ---
    max_word_count_overall = max(stat["words"] for stat in all_options_stats) if all_options_stats else 0
    max_char_length_overall = max(stat["chars"] for stat in all_options_stats) if all_options_stats else 0

    diff_from_overall_longest_words_perc = _calculate_percentage_difference(
        max_word_count_overall, correct_word_count, max_word_count_overall
    )
    diff_from_overall_longest_chars_perc = _calculate_percentage_difference(
        max_char_length_overall, correct_char_length, max_char_length_overall
    )
    
    is_one_of_the_longest_words = diff_from_overall_longest_words_perc <= PERCENTAGE_THRESHOLD_FOR_BEING_LONGEST_WORDS
    is_one_of_the_longest_chars = diff_from_overall_longest_chars_perc <= PERCENTAGE_THRESHOLD_FOR_BEING_LONGEST_CHARS
    correct_answer_is_among_longest = is_one_of_the_longest_words or is_one_of_the_longest_chars

    # --- 4. Check 2: Is the correct answer significantly longer than the NEXT longest option? ---
    other_options_stats = [
        stat for i, stat in enumerate(all_options_stats) if i != correct_answer_index
    ]

    correct_answer_is_significantly_longer_than_others = False
    if other_options_stats:
        next_longest_word_count = max(stat["words"] for stat in other_options_stats)
        next_longest_char_length = max(stat["chars"] for stat in other_options_stats)

        word_diff_from_next = correct_word_count - next_longest_word_count
        char_diff_from_next = correct_char_length - next_longest_char_length

        perc_longer_words_vs_next = _calculate_percentage_difference(
            correct_word_count, next_longest_word_count, next_longest_word_count
        )
        perc_longer_chars_vs_next = _calculate_percentage_difference(
            correct_char_length, next_longest_char_length, next_longest_char_length
        )

        is_significantly_longer_words_vs_next = (
            word_diff_from_next > 0 and
            perc_longer_words_vs_next > SIGNIFICANT_PERCENTAGE_DIFFERENCE_WORDS and
            word_diff_from_next >= MINIMUM_ABSOLUTE_WORD_DIFFERENCE
        )
        is_significantly_longer_chars_vs_next = (
            char_diff_from_next > 0 and
            perc_longer_chars_vs_next > SIGNIFICANT_PERCENTAGE_DIFFERENCE_CHARS and
            char_diff_from_next >= MINIMUM_ABSOLUTE_CHAR_DIFFERENCE
        )
        correct_answer_is_significantly_longer_than_others = (
            is_significantly_longer_words_vs_next or is_significantly_longer_chars_vs_next
        )

    # --- 5. Final Decision & Add Flag ---
    # The flag is True if the answer is considered problematically long by the criteria.
    is_flagged_as_long = correct_answer_is_among_longest and correct_answer_is_significantly_longer_than_others
    data['is_correct_answer_flagged_long'] = is_flagged_as_long

    data = [data]
    return json.dumps(data, indent=2)

#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------

def reconstruct_options_from_answer(data):
    """
    This function modifies the input data by removing 'options_answer' and
    reconstructing 'answer' and 'options'. It assumes 'options_answer' is
    a list with a single correct answer string.

    Args:
        data (dict): The input data containing 'options_answer' and 'question'.

    Returns:
        str: A JSON string representation of the modified data.
    """
    correct_letter = data.get("answer")
    correct_index = string.ascii_uppercase.index(correct_letter)
    options_answer = data.get("options_answer")
    options = data.get("options", [])
    options[correct_index] =  options_answer
    

    return json.dumps([data], indent=4)
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------

def reconstruct_options_from_answer(data):
    """
    This function modifies the input data by removing 'options_answer' and
    reconstructing 'answer' and 'options'. It assumes 'options_answer' is
    a list with a single correct answer string.

    Args:
        data (dict): The input data containing 'options_answer' and 'question'.

    Returns:
        str: A JSON string representation of the modified data.
    """
    correct_letter = data.get("answer")
    correct_index = string.ascii_uppercase.index(correct_letter)
    options_answer = data.get("options_answer")
    options = data.get("options", [])
    options[correct_index] =  options_answer
    

    return json.dumps([data], indent=4)


def extract_question_structure(data):
    # Get the index of the correct answer based on the letter (A = 0, B = 1, etc.)
    correct_letter = data.get("answer")
    correct_index = string.ascii_uppercase.index(correct_letter)

    # Extract the correct answer text
    options = data.get("options", [])
    if correct_index >= len(options):
        raise ValueError("Answer index out of range of options list.")

    correct_answer_text = options[correct_index]

    # Extract distractors (all other options)
    distractors = [opt for i, opt in enumerate(options) if i != correct_index]

    # Build the transformed structure
    transformed = {
        "distractors": distractors,
        "id": data.get("id"),
        "url": data.get("url"),
        "key_ideas": data.get("key_ideas"),
        "explanation": data.get("explanation"),
        "code_sample": data.get("code_sample", ""),
        "yaml_code_sample": data.get("yaml_code_sample", ""),
        "question": data.get("question"),
        "options_answer": correct_answer_text,
        "answer_explanation": data.get("answer_explanation"),
        "is_correct_answer_flagged_long": data.get("is_correct_answer_flagged_long")
    }

    return json.dumps([transformed], indent=2) 

#-------------------------------------------------------------------------------------------------------------------------------------------



import json

def merge_correct_answer_with_distractors(mcq_dict):
    # Handle case where input is a JSON string
    if isinstance(mcq_dict, str):
        try:
            mcq_dict = json.loads(mcq_dict)
        except json.JSONDecodeError:
            raise ValueError("Input mcq_dict is a string but not valid JSON.")

    # Initialize the final options list
    options = []

    # Check and handle missing correct answer
    if not mcq_dict.get("options_answer"):
        mcq_dict["bad_message"] = True
    else:
        explanation = mcq_dict.get("explanation", "").strip()
        answer_explanation = mcq_dict.get("answer_explanation", "").strip()
        correct_expl = f"### Correct Answer Explanation:\n\n{answer_explanation}\n\n\n\n### Detailed Explanation:\n\n{explanation}"
        correct_option = {
            "option": mcq_dict["options_answer"],
            "answer_or_distractor": "answer",
            "explanation_why_it_is_correct_or_incorrect": correct_expl
        }
        options.append(correct_option)

    # Add each distractor from the original list
    for distractor in mcq_dict.get("distractors", []):
        options.append({
            "option": distractor.get("option", ""),
            "answer_or_distractor": "distractor",
            "explanation_why_it_is_correct_or_incorrect": distractor.get("explanation_why_it_is_incorrect", "")
        })

    mcq_dict["options_combined"] = options
    mcq_dict.pop("distractors", None)
    mcq_dict.pop("options_answer", None)
    mcq_dict.pop("answer_explanation", None)

    return json.dumps([mcq_dict], indent=2)


#-------------------------------------------------------------------------------------------------------------------------------------------


def transform_options_with_lengths(data):
    # Parse the JSON string into a dictionary
    data_dict = data
    
    options = data_dict.pop("options")  # Remove options list
    
    # Assign new keys (option_a, option_b, etc.) and calculate lengths
    for i, option in enumerate(options):
        option_key = f"option_{string.ascii_lowercase[i]}"
        length_key = f"{option_key}_len"
        
        data_dict[option_key] = option  # Add option
        data_dict[length_key] = len(option)  # Add option length

    return json.dumps([data_dict])  # IMPORTANT : Return a list of dictionaries

#-------------------------------------------------------------------------------------------------------------------------------------------


def get_answer_length_flag_value(processed_data: dict, **kwargs) -> bool:
    """
    Retrieves the boolean value of the 'is_correct_answer_flagged_long'
    flag from a processed data dictionary.

    Args:
        processed_data (dict): The dictionary that was processed by the
                               `add_answer_length_flag` function. It is
                               expected to potentially contain the
                               'is_correct_answer_flagged_long' key.

    Returns:
        bool: The boolean value of the 'is_correct_answer_flagged_long' key.
              Defaults to False if the key is not found, if the input is not
              a dictionary, or if the key's value was None (which might
              indicate an issue or incomplete analysis during the flagging step).
    """
    if not isinstance(processed_data, dict):
        # If the input isn't a dictionary, we can't find the flag.
        return False

    # .get() retrieves the value for the key.
    # If the key is missing, .get() returns None.
    # bool(None) is False.
    # bool(True) is True.
    # bool(False) is False.
    # This concisely handles all expected cases for the flag's value.
    flag_value = processed_data.get('is_correct_answer_flagged_long')
    return bool(flag_value)

#-------------------------------------------------------------------------------------------------------------------------------------------



def get_answer_length_flag_value_false(processed_data: dict, **kwargs) -> bool:
    """
    Retrieves the boolean value of the 'is_correct_answer_flagged_long'
    flag from a processed data dictionary.

    Args:
        processed_data (dict): The dictionary that was processed by the
                               `add_answer_length_flag` function. It is
                               expected to potentially contain the
                               'is_correct_answer_flagged_long' key.

    Returns:
        bool: The boolean value of the 'is_correct_answer_flagged_long' key.
              Defaults to False if the key is not found, if the input is not
              a dictionary, or if the key's value was None (which might
              indicate an issue or incomplete analysis during the flagging step).
    """
    if not isinstance(processed_data, dict):
        # If the input isn't a dictionary, we can't find the flag.
        return False

    # .get() retrieves the value for the key.
    # If the key is missing, .get() returns None.
    # bool(None) is False.
    # bool(True) is True.
    # bool(False) is False.
    # This concisely handles all expected cases for the flag's value.
    flag_value = processed_data.get('is_correct_answer_flagged_long')
    return not bool(flag_value)
#-------------------------------------------------------------------------------------------------------------------------------------------


def transform_question_block(question_block):
    try:
        option_entries = question_block["options_combined"]

        # Extract option strings
        original_options = [entry["option"] for entry in option_entries]

        # Identify correct answer string before shuffling
        correct_option_str = next(
            entry["option"] for entry in option_entries
            if entry["answer_or_distractor"] == "answer"
        )

        # Shuffle while preserving mapping to explanations
        zipped = list(zip(original_options, option_entries))
        random.shuffle(zipped)
        shuffled_options, shuffled_entries = zip(*zipped)

        # Find new correct answer index
        new_answer_index = shuffled_options.index(correct_option_str)
        answer_key = string.ascii_lowercase[new_answer_index]

        # Build markdown explanation
        correct_expl = ""
        distractors = []
        distractor_count = 1

        for entry in shuffled_entries:
            option_str = entry.get("option", "").strip()
            explanation = entry.get("explanation_why_it_is_correct_or_incorrect", "").strip()

            if entry["option"] == correct_option_str:
                correct_expl = f"**Option:** {option_str}\n\n{explanation}"
            else:
                distractors.append(f"### Distractor {distractor_count}:\n {option_str}\n\n{explanation}")
                distractor_count += 1

        combined_explanation = (
            "## Correct Answer:\n"
            f"{correct_expl}\n\n"
            "## Incorrect Options:\n\n" +
            "\n\n".join(distractors)
        )

        # Construct transformed question object
        transformed = {
            "question_guid": str(uuid.uuid4()),  
            "options": list(shuffled_options),
            "answer_index": new_answer_index,
            "answer": answer_key,
            "combined_explanation": combined_explanation
        }

        return json.dumps([transformed], indent=2)

    except Exception as e:
        question_block["bad_message"] = True
        print(f"Failed to transform question block: {e}")

        # Append to bad_questions.json
        guid = str(uuid.uuid4())

        # Create filename with GUID
        bad_file = f"bad_questions_{guid}.json"

        if os.path.exists(bad_file):
            with open(bad_file, "r", encoding="utf-8") as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError:
                    existing = []
        else:
            existing = []

        existing.append(question_block)

        with open(bad_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        return json.dumps([question_block], indent=2)
#-------------------------------------------------------------------------------------------------------------------------------------------

import uuid

def ensure_question_guid(data: dict) -> dict:
    if 'question_guid' not in data or not data['question_guid']:
        data['question_guid'] = str(uuid.uuid4())
    return json.dumps([data], indent=2)


import re

def extract_content_by_headings(data):

    content = data["page_content"]
    
    # Split content by H2 headings
    parts = re.split(r'\n## (.+)', content)
    section_dict = {}
    
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        text = parts[i + 1].strip()
        section_dict[heading] = text
    

    return json.dumps([section_dict], indent=2)




#----------------------------------------------------------------------------
def trans_data(data):
    return json.dumps([data], indent=2)



#----------------------------------------------------------------------------

def check_decision(data: dict) -> bool | None:
    """
    Checks the 'decision' field in the input dictionary.

    This function implements the logic to return False if the decision is 'Agree'
    and True if the decision is 'Disagree'. It provides a clear and inverted
    boolean representation based on the string value.

    Args:
        data: A dictionary expected to contain a 'decision' key.

    Returns:
        - False if the value of the 'decision' key is "Agree".
        - True if the value of the 'decision' key is "Disagree".
        - None if the 'decision' key is not present or has any other value.
    """
    # Use the .get() method to safely access the 'decision' key.
    # This prevents a KeyError if the key does not exist.
    decision_value = data.get("decision")

    if decision_value == "Agree":
        return False
    elif decision_value == "Disagree":
        return True
    else:
        # If the key is missing or the value is neither "Agree" nor "Disagree",
        # we return None to indicate an undefined outcome.
        return None
    






import json

def apply_edited_distractors(data):
    """
    If 'is_correct_answer_flagged_long' is True, replace distractors (all options except the correct one)
    with the revised ones in distractor_1/2/3. Otherwise return unchanged.
    Returns a single-item list: [data].
    """
    # Allow JSON string input
    if isinstance(data, str):
        data = json.loads(data)

    # Basic validations
    if not isinstance(data, dict):
        raise TypeError("Expected dict or JSON-encoded dict")

    options = data.get("options")
    answer_letter = data.get("answer")
    if not isinstance(options, list) or not options:
        raise ValueError("'options' must be a non-empty list")
    if not isinstance(answer_letter, str) or not answer_letter:
        raise ValueError("'answer' must be a non-empty string representing the correct option letter")

    correct_index = ord(answer_letter.upper()) - ord('A')
    if not (0 <= correct_index < len(options)):
        raise ValueError("Invalid answer index")

    # Only modify when flagged
    #if not data.get("is_correct_answer_flagged_long", False):
    #    return [data]

    # Collect edited distractors; if any are missing, skip editing instead of crashing
    d1 = data.get("distractor_1")
    d2 = data.get("distractor_2")
    d3 = data.get("distractor_3")
    new_distractors = [d1, d2, d3]

    # If any distractor text is missing/None/empty, do not attempt edit
    if any(d is None for d in new_distractors):
        # You could log here if your framework supports it
        return [data]

    # Determine which indices are distractors (everything except the correct index), sorted by letter
    distractor_indices = [(i, chr(ord('A') + i)) for i in range(len(options)) if i != correct_index]
    distractor_indices.sort(key=lambda x: x[1])  # alphabetical by A, B, C, ...

    # Rebuild options
    updated_options = options[:]
    for (idx, _), new_text in zip(distractor_indices, new_distractors):
        updated_options[idx] = new_text

    # Ensure correct answer text unchanged
    if updated_options[correct_index] != options[correct_index]:
        raise RuntimeError("Correct answer text was modified!")

    data["options"] = updated_options
    return [data]





#==============
from langchain_text_splitters import RecursiveCharacterTextSplitter

def split_markdown_content(md_content) -> list[str]:
    md_content = str(md_content)
    """
    Splits markdown content into a list of strings using RecursiveCharacterTextSplitter.

    Args:
        md_content: A string containing the markdown content.

    Returns:
        A list of strings, where each string is a chunk of the original text.
    """
#===start here===#
    # These are the default separators for markdown in LangChain
    markdown_separators = [
        "\n\n",
        "\n",
        " ",
        "",
    ]

    # Initialize the splitter with markdown-specific separators
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,  # The maximum size of a chunk (in characters)
        chunk_overlap=100, # The number of characters to overlap between chunks
        separators=markdown_separators
    )

    # Split the markdown content into documents (chunks)
    chunks = text_splitter.split_text(md_content)
    return chunks






import json
import uuid

#===start here===#
def flatten_testable_keyideas(data):
    """
    Transforms the input data into a list of dictionaries where each 'key_ideas'
    entry is placed under a separate 'key_ideas' key and given a unique UUID.

    Parameters:
        data (dict): A dictionary containing a list of key ideas.

    Returns:
        str: JSON string containing the transformed list of dictionaries with UUIDs.
    """
    returned_data = [
        {"idea_id": str(uuid.uuid4()), "key_ideas": test}
        for test in data["key_ideas"]
    ]
    return json.dumps(returned_data)
#===end here===#



import json

def process_quiz_data(data):
    """
    Processes quiz data to extract questions and append top-level metadata.

    Accepts:
      - dict with 'questions' at root
      - dict with 'properties.questions' (list or {'items': [...]})
      - list of any of the above
      - JSON string of any of the above

    Returns:
      list of question dicts, each augmented with 'id' and 'url' from its source item.
      Returns [] on invalid input or no questions.
    """
    # Parse JSON strings first
    if isinstance(data, (str, bytes, bytearray)):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            print(f"Error: Input string is not valid JSON. Details: {e}")
            return []

    # Normalize to list of items
    if isinstance(data, dict):
        items_to_process = [data]
    elif isinstance(data, list):
        items_to_process = data
    else:
        print(f"Error: Input data must be a dictionary or a list of dictionaries, but got {type(data)}.")
        return []

    def _extract_question_list(item):
        """Return a list of questions for a single item, or [] if none."""
        if not isinstance(item, dict):
            return []

        # 1) Root: {"questions": [...]}
        q = item.get("questions")
        if isinstance(q, list):
            return q

        # 2) properties.questions (could be list)
        props = item.get("properties", {})
        q = props.get("questions")
        if isinstance(q, list):
            return q

        # 3) properties.questions.items (common "items" shape)
        if isinstance(q, dict):
            items = q.get("items")
            if isinstance(items, list):
                return items

        # 4) properties itself might directly contain items (rare)
        items = props.get("items")
        if isinstance(items, list):
            return items

        return []

    all_processed_questions = []

    for idx, item in enumerate(items_to_process):
        if not isinstance(item, dict):
            print("Warning: Skipping non-dictionary item in list.")
            continue

        source_id = item.get("id")
        source_url = item.get("url")

        questions = _extract_question_list(item)

        if not source_id or not source_url:
            print("Warning: Skipping an item due to missing 'id' or 'url'.")
            continue

        if not questions:
            print("Warning: Skipping an item because no questions were found.")
            continue

        for q in questions:
            if not isinstance(q, dict):
                print("Warning: Skipping a non-dictionary question entry.")
                continue
            updated = q.copy()

            # Merge scenario + old question text
            scenario_text = updated.get("scenario", "")
            question_text = updated.get("question", "")
            updated["question"] = f"{scenario_text} {question_text}".strip()

            updated["id"] = source_id
            updated["url"] = source_url
            all_processed_questions.append(updated)


    return all_processed_questions

    #===end here===#




def combine_to_explanation(data: dict) -> dict:
    """
    Combines selected fields into a single 'explanation' field with paragraph spacing,
    and removes the original fields from the dictionary.
    """
    explanation_keys = [
        "what_this_question_tests",
        "answer_deconstruction",
        "full_explanation"
    ]

    # Collect and remove the parts in order
    explanation_parts = []
    for key in explanation_keys:
        value = data.pop(key, "")
        if value.strip():
            explanation_parts.append(value.strip())

    # Join them with paragraph spacing
    data["explanation"] = "\n\n".join(explanation_parts)

    return [data]



#----------------------------------------------------------------------------

def flag_incorrect_answers(data):
    """
    Attaches 'flag_incorrect': True/False to each object in the input list,
    based on whether 'selected_answer_letter' matches 'answer'.
    Returns the modified list.
    """
    selected = data.get('selected_answer_letter')
    correct = data.get('answer')
    data['flag_incorrect'] = (selected != correct)
    return [data]







import re

def mentions_dbt_version(data):
    """
    Returns True if the question text mentions any version of dbt, regardless of the version number.

    Args:
        data (dict): A dictionary containing question data.

    Returns:
        bool: True if any version of dbt is mentioned, else False.
    """
    #data = data['content']
    question_text = data.get("question", "")
    
    # Match any variation of dbt + (core optional) + version or v + version number
    pattern = re.compile(r'\bdbt(?:\s+core)?\s+(?:v|version)\s*\d+(\.\d+)*\b', re.IGNORECASE)

    return bool(pattern.search(question_text))







def get_aligns(processed_data: dict, **kwargs) -> bool:
    #print(processed_data['content']['is_correct_answer_flagged_long'])
    """
    Retrieves the boolean value of the 'is_correct_answer_flagged_long'
    flag from a processed data dictionary.

    Args:
        processed_data (dict): The dictionary that was processed by the
                               `add_answer_length_flag` function. It is
                               expected to potentially contain the
                               'is_correct_answer_flagged_long' key.

    Returns:
        bool: The boolean value of the 'is_correct_answer_flagged_long' key.
              Defaults to False if the key is not found, if the input is not
              a dictionary, or if the key's value was None (which might
              indicate an issue or incomplete analysis during the flagging step).
    """
    # .get() retrieves the value for the key.
    # If the key is missing, .get() returns None.
    # bool(None) is False.
    # bool(True) is True.
    # bool(False) is False.
    # This concisely handles all expected cases for the flag's value.
    flag_value = processed_data['aligns']
    return bool(flag_value)


def return_data(processed_data: dict, **kwargs) -> bool:
    #print(processed_data['content']['is_correct_answer_flagged_long'])
    """
    Retrieves the boolean value of the 'is_correct_answer_flagged_long'
    flag from a processed data dictionary.

    Args:
        processed_data (dict): The dictionary that was processed by the
                               `add_answer_length_flag` function. It is
                               expected to potentially contain the
                               'is_correct_answer_flagged_long' key.

    Returns:
        bool: The boolean value of the 'is_correct_answer_flagged_long' key.
              Defaults to False if the key is not found, if the input is not
              a dictionary, or if the key's value was None (which might
              indicate an issue or incomplete analysis during the flagging step).
    """
    # .get() retrieves the value for the key.
    # If the key is missing, .get() returns None.
    # bool(None) is False.
    # bool(True) is True.
    # bool(False) is False.
    # This concisely handles all expected cases for the flag's value.
    return [processed_data]





import ast
import re

def is_options_valid(data):
    """
    Returns True if 'options' is a proper list of strings.
    Returns False if it's malformed (e.g., a list with one stringified list).
    """
    options = data.get("options")
    print(f"Options: {options}")

    # Must be a list
    if not isinstance(options, list):
        return False

    # If it's a list of strings
    if all(isinstance(opt, str) for opt in options):
        if len(options) == 1:
            # Check if the single string is a list in string form
            option = options[0].strip()
            if option.startswith("[") and option.endswith("]"):
                try:
                    parsed = ast.literal_eval(option)
                    if isinstance(parsed, list):
                        return False  # Definitely a stringified list — invalid
                except:
                    return False  # Failed to parse, but smells like a stringified list
        return True

    return False







def rewriteneeded(processed_data: dict, **kwargs) -> bool:
    """
    Retrieves the boolean value of the 'is_correct_answer_flagged_long'
    flag from a processed data dictionary.

    Args:
        processed_data (dict): The dictionary that was processed by the
                               `add_answer_length_flag` function. It is
                               expected to potentially contain the
                               'is_correct_answer_flagged_long' key.

    Returns:
        bool: The boolean value of the 'is_correct_answer_flagged_long' key.
              Defaults to False if the key is not found, if the input is not
              a dictionary, or if the key's value was None (which might
              indicate an issue or incomplete analysis during the flagging step).
    """
    
    if not isinstance(processed_data, dict):
        # If the input isn't a dictionary, we can't find the flag.
        return False

    # .get() retrieves the value for the key.
    # If the key is missing, .get() returns None.
    # bool(None) is False.
    # bool(True) is True.
    # bool(False) is False.
    # This concisely handles all expected cases for the flag's value.
    flag_value = processed_data.get('needs_rewrite')
    return bool(flag_value)


def fix_answer_key_assignment(data):
    """
    Fixes answer key assignment by finding the answer text in options and assigning the correct letter.
    
    Args:
        data (dict): Quiz data containing 'options' and 'answer' (answer text)
        
    Returns:
        str: JSON string with corrected answer key assignment
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return json.dumps([{"error": "Invalid JSON input"}], indent=2)
    
    if not isinstance(data, dict):
        return json.dumps([{"error": "Input must be a dictionary"}], indent=2)
    
    options = data.get("options", [])
    answer_text = data.get("answer", "")
    
    if not options:
        return json.dumps([{"error": "No options found"}], indent=2)
    
    if not answer_text:
        return json.dumps([{"error": "No answer text provided"}], indent=2)
    
    # Find the answer text in the options array
    try:
        answer_index = options.index(answer_text)
        # Convert index to letter: 0=A, 1=B, 2=C, 3=D, etc.
        answer_letter = string.ascii_uppercase[answer_index]
        data["answer"] = answer_letter
        data["options_answer"] = answer_text
    except ValueError:
        data["error"] = f"Answer text '{answer_text}' not found in options"
        return json.dumps([data], indent=2)
    except IndexError:
        data["error"] = f"Answer index {answer_index} out of range for alphabet"
        return json.dumps([data], indent=2)
    
    return json.dumps([data], indent=2)


def append_flag_and_context(payload,
                            flag_key="excerpt_is_in_page_content",
                            context_key="excerpt_context",
                            pre_sentences=1,
                            post_sentences=1):
    import copy, re, unicodedata

    def clean(s: str) -> str:
        if s is None:
            return ""
        s = unicodedata.normalize("NFKC", s)
        s = re.sub(r"[\u200B-\u200F\uFEFF]", "", s)  # remove zero-width
        return s

    def build_pattern_whitespace_flexible(excerpt_text: str):
        text = clean(excerpt_text or "").strip()
        if not text:
            return None
        parts = re.split(r"\s+", text)
        escaped = [re.escape(p) for p in parts if p]
        if not escaped:
            return None
        pat = r"\s+".join(escaped)
        return re.compile(pat, re.IGNORECASE)

    def sentence_spans(text: str):
        # Simple deterministic splitter
        return [(m.start(), m.end()) for m in re.finditer(r"[^.!?]+(?:[.!?]+|$)", text)]

    out = copy.deepcopy(payload)
    page_raw = out.get("page_content", "")
    page_for_search = clean(page_raw)
    spans = sentence_spans(page_for_search)

    items = out.get("excerpt", [])
    if not isinstance(items, list):
        return out

    for idx, item in enumerate(list(items)):
        if isinstance(item, dict):
            ex_text_raw = item.get("excerpts")
            if ex_text_raw is None:
                ex_text_raw = item.get("excerpt")
        else:
            ex_text_raw = str(item)

        pat = build_pattern_whitespace_flexible(ex_text_raw)
        m = pat.search(page_for_search) if pat else None
        is_in = m is not None

        context = None
        if is_in:
            match_start, match_end = m.start(), m.end()

            # Find sentence containing match start
            sent_idx = None
            for si, (s, e) in enumerate(spans):
                if s <= match_start < e:
                    sent_idx = si
                    break
            if sent_idx is None and spans:
                sent_idx = len(spans) - 1

            if sent_idx is not None:
                start_i = max(0, sent_idx - pre_sentences)
                end_i = min(len(spans) - 1, sent_idx + post_sentences)
                ctx_start = spans[start_i][0]
                ctx_end = spans[end_i][1]

                # Ensure FULL excerpt is included
                if match_start < ctx_start:
                    ctx_start = match_start
                if match_end > ctx_end:
                    ctx_end = match_end

                # >>> Minimal addition: include ONE FULL SENTENCE AFTER the excerpt, if present
                # Find the sentence that contains the *end* of the match
                end_locator = max(0, match_end - 1)
                end_sent_idx = None
                for si, (s, e) in enumerate(spans):
                    if s <= end_locator < e:
                        end_sent_idx = si
                        break
                if end_sent_idx is not None and end_sent_idx < len(spans) - 1:
                    # Extend to the end of the next sentence
                    ctx_end = max(ctx_end, spans[end_sent_idx + 1][1])
                # <<< end minimal addition

                context = page_for_search[ctx_start:ctx_end].strip()

        if isinstance(item, dict):
            item[flag_key] = bool(is_in)
            item[context_key] = context
        else:
            items[idx] = {"excerpts": ex_text_raw, flag_key: bool(is_in), context_key: context}

    return out





def add_distractors(question_data):
    """
    Takes question data and adds a 'distractors' key with formatted distractor information.
    
    Args:
        question_data (dict): Dictionary containing question data with distractor fields
        
    Returns:
        dict: Enhanced question data with 'distractors' array added
    """
    # Create a copy of the original data to avoid mutation
    result = question_data.copy()
    
    # Initialize distractors list
    distractors = []
    
    # Find the correct answer (convert letter to index)
    correct_answer_index = ord(question_data['answer']) - ord('A')  # A=0, B=1, C=2, etc.
    
    # Process each option
    for index, option in enumerate(question_data['options']):
        # Skip the correct answer
        if index == correct_answer_index:
            continue
        
        # Find the corresponding distractor number for this option
        distractor_num = None
        explanation = None
        
        # Check which distractor matches this option
        for i in range(1, 11):  # Check up to 10 distractors
            distractor_key = f"distractor_{i}"
            explanation_key = f"explanation_why_it_is_incorrect_{i}"
            
            if question_data.get(distractor_key) == option:
                distractor_num = i
                explanation = question_data.get(explanation_key)
                break
        
        # If we found a matching distractor, add it to the list
        if distractor_num and explanation:
            distractors.append({
                "option": option,
                "distractor": "distractor",
                "explanation_why_it_is_incorrect": explanation
            })
    
    # Add the distractors list as a new key to the question data
    result['distractors'] = distractors
    
    return result


def process_question_data(question_data):
    """
    Process question data and return the complete enhanced dictionary.
    
    Args:
        question_data (dict): Original question data
        
    Returns:
        dict: Complete question data with distractors key added
    """
    return add_distractors(question_data)





import string
import random
import re
import json
from typing import List, Dict, Any
import json
import random
import string
import uuid
import os


import json
import os
import uuid

def merge_correct_answer_with_distractors(mcq_data):
    """
    Ensure every MCQ item has:
      • options_combined   – list of {option, answer_or_distractor, explanation…}
      • answer            – the correct option text
      • answer_index      – (optional) its position in options_combined
    Handles a single MCQ dict or a list / JSON‑string of them.
    """
    # ---------------------------------------------------------------
    # 1. Accept JSON strings, lists, or single dicts
    # ---------------------------------------------------------------
    if isinstance(mcq_data, str):
        try:
            mcq_data = json.loads(mcq_data)
        except json.JSONDecodeError:
            raise ValueError("Input mcq_data is a string but not valid JSON.")

    if isinstance(mcq_data, list):
        return json.dumps(
            [process_single_mcq(item) for item in mcq_data], indent=2, ensure_ascii=False
        )
    else:
        return json.dumps(
            [process_single_mcq(mcq_data)], indent=2, ensure_ascii=False
        )


# -------------------------------------------------------------------
# Helper: handle one MCQ item
# -------------------------------------------------------------------
def process_single_mcq(mcq_item):
    # -- unwrap any nesting under .content[.content]
    if isinstance(mcq_item.get("content"), dict):
        inner = mcq_item["content"]
        mcq_dict = inner.get("content", inner)
    else:
        mcq_dict = mcq_item

    # ----------------------------------------------------------------
    # Build the combined explanation for the correct answer
    # ----------------------------------------------------------------
    expl_long  = mcq_dict.get("explanation", "").strip()
    expl_short = mcq_dict.get("answer_explanation", "").strip()
    combined_expl = (
        "### Correct Answer Explanation:\n\n"
        f"{expl_short}\n\n"
    )

    options_combined = []

    # ---------------------------------------------------------------
    # Either update existing options_combined …
    # ---------------------------------------------------------------
    existing = mcq_dict.get("options_combined", [])
    if existing:
        for opt in existing:
            new_opt = opt.copy()
            if opt.get("answer_or_distractor") == "answer":
                new_opt["explanation_why_it_is_correct_or_incorrect"] = combined_expl
            options_combined.append(new_opt)
    else:
        # -----------------------------------------------------------
        # … or build from scratch
        # -----------------------------------------------------------
        correct_text = mcq_dict.get("options_answer", "")

        # Correct option first
        options_combined.append(
            {
                "option": correct_text,
                "answer_or_distractor": "answer",
                "explanation_why_it_is_correct_or_incorrect": combined_expl,
            }
        )

        # Distractors – try .distractors first, else fall back to .options
        distractor_sources = (
            mcq_dict.get("distractors")
            or [
                {"option": o}
                for o in mcq_dict.get("options", [])
                if o != correct_text
            ]
        )
        for d in distractor_sources:
            options_combined.append(
                {
                    "option": d.get("option", ""),
                    "answer_or_distractor": "distractor",
                    "explanation_why_it_is_correct_or_incorrect": d.get(
                        "explanation_why_it_is_incorrect", ""
                    ),
                }
            )

    # ----------------------------------------------------------------
    # Add answer fields
    # ----------------------------------------------------------------
    try:
        correct_entry = next(
            o for o in options_combined if o["answer_or_distractor"] == "answer"
        )
        answer_text  = correct_entry["option"]
        answer_index = options_combined.index(correct_entry)
    except StopIteration:
        # Fallback if something went wrong
        answer_text  = ""
        answer_index = None

    # ----------------------------------------------------------------
    # Assemble the final record (copy to avoid overwriting caller data)
    # ----------------------------------------------------------------
    result = mcq_dict.copy()
    result["options_combined"] = options_combined
    result["answer"] = answer_text          # <-- NEW explicit answer field
    result["answer_index"] = answer_index   # <-- helpful, but drop if not needed

    # ----------------------------------------------------------------
    # Re‑wrap if the source item had nesting
    # ----------------------------------------------------------------
    if "content" in mcq_item:
        wrapped = mcq_item.copy()
        if isinstance(mcq_item["content"], dict) and "content" in mcq_item["content"]:
            wrapped["content"] = mcq_item["content"].copy()
            wrapped["content"]["content"] = result
        else:
            wrapped["content"] = result
        return wrapped
    else:
        return result

import uuid
import random
import string
import json
import os


def transform_question_block(question_block):
    option_entries = question_block["options_combined"]

    # Extract option strings
    original_options = [entry["option"] for entry in option_entries]

    # Identify correct answer string before shuffling
    correct_option_str = next(
        entry["option"] for entry in option_entries
        if entry["answer_or_distractor"] == "answer"
    )

    # Shuffle while preserving mapping to explanations
    zipped = list(zip(original_options, option_entries))
    random.shuffle(zipped)
    shuffled_options, shuffled_entries = zip(*zipped)

    # Find new correct answer index
    new_answer_index = shuffled_options.index(correct_option_str)
    answer_key = string.ascii_lowercase[new_answer_index]

    # Build markdown explanation
    correct_expl = ""
    distractors = []
    distractor_count = 1

    for entry in shuffled_entries:
        option_str = entry.get("option", "").strip()
        explanation = entry.get("explanation_why_it_is_correct_or_incorrect", "").strip()

        if entry["option"] == correct_option_str:
            correct_expl = f"**Option:** {option_str}\n\n{explanation}"
        else:
            distractors.append(f"### Distractor {distractor_count}:\n {option_str}\n\n{explanation}")
            distractor_count += 1

    combined_explanation = (
        "## Correct Answer:\n"
        f"{correct_expl}\n\n"
        "## Incorrect Options:\n\n" +
        "\n\n".join(distractors)
    )

    # Construct transformed question object
    transformed = {
        "question_guid": str(uuid.uuid4()),  
        "options": list(shuffled_options),
        "answer_index": new_answer_index,
        "answer": answer_key,
        "combined_explanation": combined_explanation
    }

    return json.dumps([transformed], indent=2)










def process_file_content(data):
    content = data
    
    question = content['question']
    options = content['options']
    original_answer_index = content.get('answer_index', 0)
    
    indexed_options = [(option, i) for i, option in enumerate(options)]
    
    random.shuffle(indexed_options)
    
    shuffled_options = [option for option, _ in indexed_options]
    new_answer_index = None
    
    for new_idx, (_, original_idx) in enumerate(indexed_options):
        if original_idx == original_answer_index:
            new_answer_index = new_idx
            break
    
    answer_letter = chr(ord('A') + new_answer_index) if new_answer_index is not None else 'A'
    
    options_combined = content.get('options_combined', [])
    if options_combined:
        option_to_combined = {opt['option']: opt for opt in options_combined}
        
        shuffled_options_combined = []
        for option in shuffled_options:
            if option in option_to_combined:
                shuffled_options_combined.append(option_to_combined[option])
    else:
        shuffled_options_combined = options_combined
    
    formatted_item = {
        'question_thinkific_loader': question,
        'options_thinkific_loader': shuffled_options,
        'answer_thinkific_loader': new_answer_index,
        'options_combined_thinkific_loader': shuffled_options_combined,
        'link_thinkific_loader': content.get('link') or content.get('url', ''),
        'question_guid': content.get('question_guid') or content.get('guid', ''),
    }
    
    
    return [formatted_item]







def attach_answer_text(data):
    """
    Adds 'answer_text' to the question dict based on the 'answer' letter(s).
    Handles both single and multiple answers like 'A' or 'AC'.
    """
    # Map letters A, B, C, ... to their respective indices
    letter_to_index = {chr(ord('A') + i): i for i in range(len(data["options"]))}
    
    # Collect matching option texts
    answer_letters = data["answer"].strip().upper()
    answer_texts = []
    
    for letter in answer_letters:
        idx = letter_to_index.get(letter)
        if idx is None or idx >= len(data["options"]):
            raise ValueError(f"Invalid answer letter: {letter}")
        answer_texts.append(data["options"][idx])
    
    # If multiple answers, store as list; if single, store as string
    data["options_answer"] = answer_texts if len(answer_texts) > 1 else answer_texts[0]
    
    return [data]
