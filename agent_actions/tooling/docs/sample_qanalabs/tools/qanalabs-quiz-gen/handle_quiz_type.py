import random
from agent_actions import udf_tool


def get_scenario_opener(quiz_type: str = "general") -> dict:
    """Return a random, natural scenario opener phrase based on quiz type."""
    openers = {
        "individual": [
            "You are", "You are a solutions architect", "You are a cloud engineer",
            "You are a senior developer", "You are a DevOps engineer",
            "As a software engineer, you are", "As the technical lead, you are",
            "You have been assigned to", "You are responsible for", "You are implementing",
            "You need to"
        ],
        "team": [
            "Your team is", "Your development team is", "A cross-functional team is",
            "The engineering team is", "A team of developers is", "Your DevOps team is",
            "The platform team is", "A distributed team is"
        ],
        "colleague": [
            "A colleague is", "A team member is", "Another developer is",
            "A fellow engineer is", "Your manager has asked you to"
        ],
        "organization": [
            "Your organization is", "An enterprise organization is", "A startup company is",
            "Your company is", "A financial services company is", "A healthcare organization is",
            "The organization needs to"
        ],
        "project": [
            "A production system is", "An application is", "A new project requires",
            "An existing application needs to", "A legacy system is",
            "A customer-facing application is", "A microservices architecture is",
            "The current system is"
        ],
        "task": [
            "You have been asked to", "You are evaluating", "You are designing",
            "You are configuring", "You are migrating", "You are integrating",
            "You are setting up"
        ],
        "problem": [
            "A production system is experiencing", "Users are reporting",
            "An application has started", "Performance metrics indicate",
            "After a recent deployment,", "During monitoring, you notice",
            "The system is showing"
        ]
    }

    type_weights = {
        "analysis": ["problem", "project", "individual"],
        "design": ["individual", "team", "task"],
        "implementation": ["task", "team", "individual"],
        "troubleshooting": ["problem", "task"],
        "architecture": ["individual", "organization", "project"],
        "general": list(openers.keys())
    }

    categories = type_weights.get(quiz_type.lower(), list(openers.keys()))
    category = random.choice(categories)
    scenario_opener = random.choice(openers[category])
    return {"scenario_opener_type": scenario_opener}


APPLICATION_PROMPT = """
Generate a practical question testing configuration/workflow selection.

CRITICAL RULES:
- Use ONLY terms from the provided summary - do not invent terminology
- NO TELEGRAPHING: Don't hint at answer in scenario. Focus on GOAL/PROBLEM, not method/solution.
- NO FAKE COMPLEXITY: Depth from technical specificity, not complex grammar.

SCENARIO (2-3 sentences):
- Opener suggestion: "{SUGGESTED_OPENER}" (use if it fits, or choose another)
- Present PROBLEM/GOAL with context (scale, team, pain points)
- Keep requirements IMPLICIT (describe goal, not solution)

QUESTION STEM:
- Use: "What should you do?" / "Which service/configuration should you use?"

OPTIONS (4 options):
- No identifiers (A, B, C, D)
- 15-30 words each with SPECIFIC technical terms (exact service/parameter names)
- Correct option(s) precisely satisfy requirements from facts
- Incorrect options: plausible alternatives with one critical detail changed

ANSWER:
- question_type: "SA" (one correct) or "MA" (multiple)
- answer: uppercase letters only (e.g., "C" or "BD")
- answer_explanation: explain why correct answer works

OUTPUT: JSON only, professional tone, rich technical details from provided summary.
"""

UNDERSTANDING_PROMPT = """
Generate a conceptual question testing definition/purpose/characteristic comprehension.

CRITICAL RULES:
- Use ONLY terms from the provided summary - do not invent terminology
- NO TELEGRAPHING: Don't hint at answer in scenario. Focus on GOAL/PROBLEM, not method/solution.
- NO FAKE COMPLEXITY: Depth from technical specificity, not complex grammar.

SCENARIO (2-3 sentences):
- Opener suggestion: "{SUGGESTED_OPENER}" (use if it fits, or choose another)
- Present SITUATION requiring concept understanding (context, scale, pain points)
- Don't reveal which service/feature is the answer

QUESTION STEM:
- Use: "Which service should you use?" / "What is the primary purpose/benefit of [service]?" / "Which statement best describes [concept]?"

OPTIONS (4 options):
- No identifiers (A, B, C, D)
- 15-30 words each with SPECIFIC technical terminology
- Correct option(s): accurate definition/purpose from facts
- Incorrect options: plausible statements with one critical detail altered/omitted

ANSWER:
- question_type: "SA" or "MA"
- answer: uppercase letters only (e.g., "B" or "AC")
- answer_explanation: explain why correct answer is right

OUTPUT: JSON only, professional tone, rich technical details from provided summary.
"""

IMPLEMENTATION_PROMPT = """
Generate an implementation question testing command/parameter/configuration/step selection.

CRITICAL RULES:
- Use ONLY terms from the provided summary - do not invent terminology
- NO TELEGRAPHING: Don't hint at answer in scenario. Focus on GOAL/PROBLEM, not method/solution.
- NO FAKE COMPLEXITY: Depth from technical specificity, not complex grammar.

SCENARIO (2-3 sentences):
- Opener suggestion: "{SUGGESTED_OPENER}" (use if it fits, or choose another)
- Present IMPLEMENTATION CHALLENGE (environment, constraints, goal not method)
- Include context (performance, scale, integration requirements)

QUESTION STEM:
- Use: "What should you do?" / "Which command/configuration should you use?" / "What is the correct sequence?"

OPTIONS (4 options):
- No identifiers (A, B, C, D)
- 15-30 words each with SPECIFIC implementation details (exact command syntax, parameter names, SDK methods)
- Correct option(s): exact valid implementation from facts
- Incorrect options: plausible alternatives with one critical parameter/flag/setting changed

ANSWER:
- question_type: "SA" or "MA"
- answer: uppercase letters only
- answer_explanation: explain why correct answer works

OUTPUT: JSON only, professional tone, rich implementation details from provided summary.
"""

ANALYSIS_PROMPT = """
Generate a diagnostic question testing root cause identification from symptoms/logs/metrics.

CRITICAL RULES:
- Use ONLY terms from the provided summary - do not invent terminology
- NO TELEGRAPHING: Don't hint at answer in scenario. Focus on GOAL/PROBLEM, not method/solution.
- NO FAKE COMPLEXITY: Depth from technical specificity, not complex grammar.

SCENARIO (2-3 sentences):
- Opener suggestion: "{SUGGESTED_OPENER}" (use if it fits, or choose another)
- Include SPECIFIC symptoms (error messages, status codes, exact services/components)
- Include QUANTITATIVE details (metrics, error rates, timelines, scale, baselines vs actual)

QUESTION STEM:
- Use: "What is the most likely cause?" / "What should you do to resolve this?" / "Which factor explains the problem?"

OPTIONS (4 options):
- No identifiers (A, B, C, D)
- 15-30 words each with SPECIFIC diagnostic reasoning (root causes, remediation actions with measurable steps)
- Correct option(s): valid interpretation/solution addressing specific symptoms
- Incorrect options: plausible alternatives addressing similar symptoms or missing one critical detail

ANSWER:
- question_type: "SA" or "MA"
- answer: uppercase letters only
- answer_explanation: explain diagnostic reasoning

OUTPUT: JSON only, professional tone, rich diagnostic details from provided summary.
"""

PROMPTS = {
    "APPLICATION": APPLICATION_PROMPT,
    "UNDERSTANDING": UNDERSTANDING_PROMPT,
    "IMPLEMENTATION": IMPLEMENTATION_PROMPT,
    "ANALYSIS": ANALYSIS_PROMPT
}


def _normalize_quiz_type(content: dict) -> tuple[str, str]:
    quiz_type_raw = str(
        content.get("quiz_type")
        or content.get("question_type")
        or content.get("type")
        or ""
    ).strip()
    quiz_type_upper = quiz_type_raw.upper() if quiz_type_raw else "APPLICATION"
    quiz_type_lower = quiz_type_raw.lower() if quiz_type_raw else "general"
    if quiz_type_upper not in PROMPTS:
        quiz_type_upper = "APPLICATION"
    return quiz_type_upper, quiz_type_lower


@udf_tool()
def handle_quiz_type(data: dict) -> dict:
    """
    Returns the authoring prompt and metadata based on quiz_type.
    """
    if "content" in data and isinstance(data["content"], dict):
        content = data["content"]
    else:
        content = data

    quiz_type_upper, quiz_type_lower = _normalize_quiz_type(content)
    suggested_result = get_scenario_opener(quiz_type_lower)
    suggested_opener = suggested_result.get("scenario_opener_type", "You are")
    prompt_template = PROMPTS[quiz_type_upper]

    return {
        "authoring_prompt": prompt_template.replace("{SUGGESTED_OPENER}", suggested_opener),
        "quiz_type_used": quiz_type_upper,
        "suggested_opener": suggested_opener
    }
