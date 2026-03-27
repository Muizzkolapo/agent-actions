"""
Select the best performing model from parallel training results.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def select_champion_model(data: dict[str, Any]) -> dict[str, Any]:
    """
    Select champion model from multiple trained models.

    Pattern: Loop consumption with merge pattern
    Returns: Dict with champion selection (passthrough handles upstream fields)
    """
    content = data.get("content", data)

    # Collect all model evaluations from loop iterations
    models = []
    for key, value in content.items():
        if key.startswith("evaluate_model_") and isinstance(value, dict):
            models.append(
                {
                    "source": key,
                    "model_id": value.get("model_id", "unknown"),
                    "algorithm": value.get("algorithm", "unknown"),
                    "metrics": value.get("validation_metrics", {}),
                    "feature_importance": value.get("feature_importance", {}),
                }
            )

    if not models:
        return {
            "champion_model": None,
            "champion_algorithm": None,
            "champion_metrics": {},
            "selection_reasoning": "No models to evaluate",
            "model_comparison": [],
        }

    # Define selection criteria (weighted scoring)
    METRIC_WEIGHTS = {
        "f1_score": 0.3,
        "auc_roc": 0.25,
        "precision": 0.2,
        "recall": 0.15,
        "accuracy": 0.1,
    }

    # Score each model
    scored_models = []
    for model in models:
        metrics = model["metrics"]
        score = 0.0
        for metric, weight in METRIC_WEIGHTS.items():
            metric_value = metrics.get(metric, 0.0)
            score += metric_value * weight

        scored_models.append({**model, "composite_score": round(score, 4)})

    # Sort by composite score
    scored_models.sort(key=lambda x: x["composite_score"], reverse=True)

    # Select champion
    champion = scored_models[0]

    # Generate comparison table
    model_comparison = [
        {
            "algorithm": m["algorithm"],
            "model_id": m["model_id"],
            "composite_score": m["composite_score"],
            "f1_score": m["metrics"].get("f1_score", 0.0),
            "auc_roc": m["metrics"].get("auc_roc", 0.0),
            "rank": i + 1,
        }
        for i, m in enumerate(scored_models)
    ]

    return {
        "champion_model": champion["model_id"],
        "champion_algorithm": champion["algorithm"],
        "champion_metrics": champion["metrics"],
        "champion_score": champion["composite_score"],
        "champion_feature_importance": champion["feature_importance"],
        "selection_reasoning": (
            f"Selected {champion['algorithm']} with composite score {champion['composite_score']:.4f}. "
            f"Scored highest across weighted metrics (F1: 30%, AUC-ROC: 25%, Precision: 20%, Recall: 15%, Accuracy: 10%)."
        ),
        "model_comparison": model_comparison,
        "runner_up": scored_models[1] if len(scored_models) > 1 else None,
    }
