"""
Apply recommended feature transformations to the dataset.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def apply_feature_transformations(data: dict[str, Any]) -> dict[str, Any]:
    """
    Apply feature engineering transformations to the dataset.

    Pattern: Content injection with passthrough
    Returns: Dict with new fields (passthrough handles upstream fields)
    """
    content = data.get("content", data)

    transformation_pipeline = content.get("transformation_pipeline", [])
    encoding_strategies = content.get("encoding_strategies", {})

    # Simulate feature transformation
    # In production, this would apply actual transformations

    transformed_features = []
    feature_names = []
    transformation_log = []

    for step in transformation_pipeline:
        step_num = step.get("step", 0)
        operation = step.get("operation", "unknown")
        columns = step.get("columns", [])

        # Log the transformation
        transformation_log.append(
            {
                "step": step_num,
                "operation": operation,
                "columns": columns,
                "status": "applied",
                "rows_affected": "all",
            }
        )

        # Add transformed feature names
        for col in columns:
            feature_name = f"{col}_{operation}"
            if feature_name not in feature_names:
                feature_names.append(feature_name)

    # Add encoded features
    for column, encoding in encoding_strategies.items():
        feature_name = f"{column}_{encoding}"
        if feature_name not in feature_names:
            feature_names.append(feature_name)
        transformation_log.append(
            {
                "step": len(transformation_log) + 1,
                "operation": encoding,
                "columns": [column],
                "status": "applied",
                "rows_affected": "all",
            }
        )

    # Return only new fields (passthrough handles upstream fields)
    return {
        "transformed_features": transformed_features,
        "feature_names": feature_names,
        "transformation_log": transformation_log,
        "transformation_summary": {
            "total_steps": len(transformation_log),
            "features_created": len(feature_names),
            "encoding_applied": list(encoding_strategies.keys()),
        },
    }
