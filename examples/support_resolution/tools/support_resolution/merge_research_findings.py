"""
Merge research findings from parallel researchers.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def merge_research_findings(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Merge and deduplicate research from all three strategies.

    Combines findings from:
    - research_1 (codebase_search)
    - research_2 (documentation_search)
    - research_3 (similar_issues)

    Returns synthesized findings with confidence scores.
    """
    content = data.get("content", data)

    # Collect findings from all research versions
    all_findings = []
    all_files = set()
    all_causes = []
    all_solutions = []
    all_related = []

    # Extract from each research version
    for i in range(1, 4):
        version_key = f"research_{i}"
        research_data = content.get(version_key, {})

        if not research_data:
            continue

        strategy = research_data.get("research_strategy", f"strategy_{i}")
        confidence = research_data.get("confidence_score", 0.5)

        # Collect findings with source attribution
        for finding in research_data.get("findings", []):
            finding["strategy"] = strategy
            finding["strategy_confidence"] = confidence
            all_findings.append(finding)

        # Collect relevant files
        for f in research_data.get("relevant_files", []):
            all_files.add(f)

        # Collect potential causes with dedup
        for cause in research_data.get("potential_causes", []):
            if cause not in all_causes:
                all_causes.append(cause)

        # Collect solutions
        for solution in research_data.get("suggested_solutions", []):
            solution["from_strategy"] = strategy
            all_solutions.append(solution)

        # Collect related issues
        all_related.extend(research_data.get("related_issues", []))

    # Sort findings by relevance
    all_findings.sort(
        key=lambda x: {"high": 3, "medium": 2, "low": 1}.get(x.get("relevance", "low"), 0),
        reverse=True,
    )

    # Sort solutions by confidence
    all_solutions.sort(key=lambda x: x.get("confidence", 0), reverse=True)

    # Deduplicate related issues by ID
    seen_issues = set()
    unique_related = []
    for issue in all_related:
        issue_id = issue.get("id", "")
        if issue_id and issue_id not in seen_issues:
            seen_issues.add(issue_id)
            unique_related.append(issue)

    # Calculate overall confidence
    confidences = [content.get(f"research_{i}", {}).get("confidence_score", 0) for i in range(1, 4)]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0

    # Generate solution summary
    solution_summary = "No clear solution identified."
    if all_solutions:
        top_solution = all_solutions[0]
        solution_summary = f"{top_solution.get('solution', 'Unknown')} (confidence: {top_solution.get('confidence', 0):.0%})"

    # Build result
    result = {
        "synthesis_complete": True,
        "total_findings": len(all_findings),
        "findings_by_relevance": {
            "high": len([f for f in all_findings if f.get("relevance") == "high"]),
            "medium": len([f for f in all_findings if f.get("relevance") == "medium"]),
            "low": len([f for f in all_findings if f.get("relevance") == "low"]),
        },
        "top_findings": all_findings[:5],
        "affected_files": list(all_files),
        "root_causes": all_causes,
        "recommended_solutions": all_solutions[:3],
        "solution_summary": solution_summary,
        "related_issues": unique_related[:5],
        "overall_confidence": avg_confidence,
        "research_coverage": {
            "codebase": bool(content.get("research_1")),
            "documentation": bool(content.get("research_2")),
            "similar_issues": bool(content.get("research_3")),
        },
    }

    # Pass through analyze_issue data
    if "analyze_issue" in content:
        for key, value in content["analyze_issue"].items():
            result[f"issue_{key}"] = value

    return [result]
