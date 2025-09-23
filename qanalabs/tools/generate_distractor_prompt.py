import json, random
from typing import Dict, Any, List, Tuple, Set

def _norm_cmp(s: str) -> str:
    """Normalize string for comparison"""
    return " ".join(str(s).lower().split())

def _count_words(s: str) -> int:
    """Count words in a string"""
    return len([w for w in str(s).split() if w.strip()])

def _parse_correct_answers(answer_str: str) -> Set[int]:
    """Parse answer string (e.g., 'A,C,E' or 'B') into set of indices"""
    if not answer_str:
        return set()
    
    letters = [letter.strip().upper() for letter in answer_str.split(',')]
    return {ord(letter) - ord('A') for letter in letters if letter and letter.isalpha()}

def _get_incorrect_options(options: List[str], correct_indices: Set[int]) -> List[Tuple[int, str, str]]:
    """Get list of incorrect options with their indices and letters"""
    distractors = [
        (i, chr(ord("A") + i), text)
        for i, text in enumerate(options)
        if i not in correct_indices
    ]
    return sorted(distractors, key=lambda x: x[1])

def generate_distractor_prompt(data: Dict[str, Any]) -> str:
    """Generate prompt for creating distractors based on question type"""
    
    if isinstance(data, str):
        data = json.loads(data)

    # Extract basic info
    question = data.get("question", "").strip()
    options = data["options"]
    answer_str = str(data["answer"]).upper()
    question_type = data.get("question_type", "SA")
    
    # Parse correct answers
    correct_indices = _parse_correct_answers(answer_str)
    if not correct_indices:
        raise ValueError(f"Invalid answer format: {answer_str}")
    
    # Get incorrect options (potential distractors)
    available_distractors = _get_incorrect_options(options, correct_indices)
    
    if not available_distractors:
        raise ValueError("No incorrect options available for distractor generation")
    
    # Skip already-used distractors
    used_texts = []
    if isinstance(data.get("distractor_1"), str):
        used_texts.append(data["distractor_1"])
    if isinstance(data.get("used_distractors"), list):
        used_texts.extend([t for t in data["used_distractors"] if isinstance(t, str)])
    used_norm = {_norm_cmp(t) for t in used_texts if t}
    
    # Select distractor to edit
    selected_index, selected_letter, selected_text = available_distractors[0]
    for i, letter, text in available_distractors:
        if _norm_cmp(text) not in used_norm:
            selected_index, selected_letter, selected_text = i, letter, text
            break
    
    # Calculate target length relative to correct answers
    correct_texts = [options[i] for i in correct_indices]
    avg_correct_length = sum(_count_words(text) for text in correct_texts) / len(correct_texts)
    
    # Length variation
    die = random.choice([-1, 0, 1])
    delta = random.randint(0, 3)
    relation = {-1: "SHORTER", 0: "THE SAME LENGTH AS", 1: "LONGER"}[die]
    target_word_count = max(5, int(avg_correct_length + die * delta))
    
    # Extract context information
    fact = data.get("fact", "")
    quote = data.get("quote", "")
    fact_explanation = data.get("fact_explanation", "")
    
    # Determine schema based on question type
    if question_type == "MA":
        schema_str = '{"distractor_1": "string", "explanation_why_it_is_incorrect_1": "string"}'
        context_note = "This is a multiple-answer question where multiple options can be correct."
    else:
        schema_str = '{"distractor_1": "string", "explanation_why_it_is_incorrect_1": "string"}'
        context_note = "This is a single-answer question where only one option is correct."
    
    # Build correct answers description
    correct_letters = sorted([chr(ord("A") + i) for i in correct_indices])
    if len(correct_letters) == 1:
        correct_desc = f"Option {correct_letters[0]}"
    else:
        correct_desc = f"Options {', '.join(correct_letters)}"
    
    prompt = f"""You are writing ONE multiple-choice distractor and explaining why it is wrong.

{context_note}

You will see:
- QUESTION and OPTIONS
- CORRECT ANSWER(S)
- FACT (key concept summary)
- QUOTE (direct source reference)
- FACT_EXPLANATION (detailed context)

Grounding instructions (very important):
- Use the FACT to understand the core concept being tested.
- Use the QUOTE for specific technical details and exact terminology.
- Use the FACT_EXPLANATION for comprehensive context and reasoning.
- Base the distractor's flaw on concepts supported by these sources.
- Do NOT quote or directly reference these source materials in your response.

Your job:
1) Write a distractor that is plausible but incorrect, informed by the provided context.
2) Explain why the distractor is wrong compared to the correct answer(s).
   - Focus on the specific technical or conceptual flaw.
   - The explanation must be self-contained and clear.

STRICT length rule for the distractor:
- Make it approximately {target_word_count} words long.
- This should be {relation} the correct answer(s), which average {int(avg_correct_length)} words.
- Maintain natural, professional language.

Style & content rules for the distractor:
- Mirror the tone and technical level of the correct answer(s).
- Avoid obvious negatives like "not", "never", "without", "isn't", "can't".
- No typos or deliberately confusing wording.
- Avoid hedge words: "although", "though", "while", "whereas", "however", "but", "yet", "nevertheless", "nonetheless", "despite", "in spite of".

Rules for the explanation:
- 1-3 sentences maximum.
- Focus on the technical/conceptual reason why it's incorrect.
- Compare directly to what makes the correct answer(s) better.
- Avoid the same hedge words listed above.

QUESTION:
{question}

OPTIONS:
{json.dumps(options, ensure_ascii=False, indent=2)}

CORRECT ANSWER(S):
{answer_str} ({correct_desc})

FACT:
{fact}

QUOTE:
{quote}

FACT_EXPLANATION:
{fact_explanation}

TARGET DISTRACTOR TO IMPROVE:
Option {selected_letter}: {selected_text}

Return only valid JSON (schema {schema_str}):
{{"distractor_1": "...", "explanation_why_it_is_incorrect_1": "..."}}"""

    return prompt


# Test function
def test_with_sample_data():
    """Test the function with the provided sample data"""
    
    # Multiple Answer Example
    ma_data = {
        "question": "You are developing an application that integrates Azure AI Speech services. To ensure the security of your API keys, you decide to follow best practices.\n\nWhich of the following actions should you take to securely manage your Azure AI Speech API keys?\n\nSelect all that apply.",
        "options": [
            "Store API keys in Azure Key Vault with restricted access.",
            "Embed the API keys directly in your application code.",
            "Rotate API keys regularly to minimize risk of compromise.",
            "Share API keys publicly to allow easier access during development.",
            "Apply role-based access control and network restrictions to limit Azure Key Vault access."
        ],
        "answer": "A,C,E",
        "question_type": "MA",
        "fact": "API keys for Azure AI Speech should be stored securely in Azure Key Vault with regular rotation and restricted access.",
        "quote": "Use API keys with caution. Don't include the API key directly in your code, and never post it publicly. If using API keys, store them securely in Azure Key Vault, rotate the keys regularly, and restrict access to Azure Key Vault using role based access control and network access restrictions.",
        "fact_explanation": "API keys used for authenticating Azure AI Speech services must be managed securely to prevent unauthorized access. This involves storing keys in Azure Key Vault, a service that securely stores secrets, and applying strict role-based access control and network restrictions to limit who can access these keys. Additionally, regularly rotating API keys minimizes the risk of compromised credentials. Embedding API keys directly in code or exposing them publicly is strongly discouraged, as it undermines security."
    }
    
    # Single Answer Example  
    sa_data = {
        "question": "You are developing a real-time speech transcription application using the Azure Speech SDK. You want to capture audio input directly from a user's microphone and convert the speech to text as it is spoken.\n\nWhich approach should you use to configure the audio input for your SpeechRecognizer in this scenario?\n\nSelect only one answer.",
        "options": [
            "Use AudioConfig.FromWavFileInput with a prerecorded WAV file.",
            "Create an AudioConfig by specifying the microphone device with AudioConfig.FromDefaultMicrophoneInput.",
            "Configure AudioConfig to read from a network audio stream.",
            "Use a blank AudioConfig to enable automatic microphone detection."
        ],
        "answer": "B",
        "question_type": "SA",
        "fact": "To recognize speech from a microphone, use AudioConfig.FromDefaultMicrophoneInput with SpeechRecognizer in the Speech SDK.",
        "quote": "using var audioConfig = AudioConfig.FromDefaultMicrophoneInput(); using var speechRecognizer = new SpeechRecognizer(speechConfig, audioConfig);",
        "fact_explanation": "In the Azure Speech SDK, real-time speech recognition from a microphone is achieved by creating an AudioConfig object configured with the default microphone input using AudioConfig.FromDefaultMicrophoneInput. This audio configuration is then paired with a SpeechRecognizer instance, which handles capturing audio from the microphone and transcribing spoken words into text. This approach supports processing live audio input directly, distinguishing it from recognizing speech from audio files where different AudioConfig setups are used."
    }
    
    print("=== MULTIPLE ANSWER EXAMPLE ===")
    print(generate_distractor_prompt(ma_data))
    print("\n" + "="*50 + "\n")
    print("=== SINGLE ANSWER EXAMPLE ===")
    print(generate_distractor_prompt(sa_data))


if __name__ == "__main__":
    test_with_sample_data()