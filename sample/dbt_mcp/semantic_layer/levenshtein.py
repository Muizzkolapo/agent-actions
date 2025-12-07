from dataclasses import dataclass


@dataclass
class Misspelling:
    word: str
    similar_words: list[str]


def levenshtein(s1: str, s2: str) -> int:
    len_s1, len_s2 = len(s1), len(s2)
    dp = [[0] * (len_s2 + 1) for _ in range(len_s1 + 1)]

    for i in range(len_s1 + 1):
        dp[i][0] = i
    for j in range(len_s2 + 1):
        dp[0][j] = j

    for i in range(1, len_s1 + 1):
        for j in range(1, len_s2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,  # Deletion
                dp[i][j - 1] + 1,  # Insertion
                dp[i - 1][j - 1] + cost,  # Substitution
            )
    return dp[len_s1][len_s2]


def get_closest_words(
    target: str,
    words: list[str],
    top_k: int | None = None,
    threshold: int | None = None,
) -> list[str]:
    distances = [(word, levenshtein(target, word)) for word in words]

    # Filter by threshold if provided
    if threshold is not None:
        distances = [(word, dist) for word, dist in distances if dist <= threshold]

    # Sort by distance
    distances.sort(key=lambda x: x[1])

    # Limit by top_k if provided
    if top_k is not None:
        distances = distances[:top_k]

    return [word for word, _ in distances]


def get_misspellings(
    targets: list[str],
    words: list[str],
    top_k: int | None = None,
) -> list[Misspelling]:
    misspellings = []
    for target in targets:
        if target not in words:
            misspellings.append(
                Misspelling(
                    word=target,
                    similar_words=get_closest_words(
                        target=target,
                        words=words,
                        top_k=top_k,
                        threshold=max(1, len(target) // 2),
                    ),
                )
            )
    return misspellings
