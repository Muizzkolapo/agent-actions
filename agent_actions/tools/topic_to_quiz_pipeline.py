from typing import List

def topic_to_quiz_pipeline(topic: str) -> str:
    """Return a very simple quiz for the given topic.

    This function is a stub used for demonstration. It generates three
    basic quiz questions based on the provided topic string.
    """
    if not isinstance(topic, str):
        topic = str(topic)
    questions: List[str] = [
        f"What is the main idea of {topic}?",
        f"Name one key concept related to {topic}.",
        f"Explain an important fact about {topic}.",
    ]
    return "\n".join(questions)
