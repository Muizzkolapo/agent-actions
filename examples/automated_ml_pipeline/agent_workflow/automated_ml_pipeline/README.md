# Automated ML Pipeline Workflow

End-to-end automated machine learning pipeline from data assessment to model deployment with quality gates and monitoring.

## Overview

This workflow demonstrates a Dataiku-inspired AutoML pipeline that handles data quality assessment, feature engineering, parallel model training, evaluation, selection, and conditional deployment.

## Workflow Diagram

```
                    ┌─────────────────────────┐
                    │   assess_data_quality   │
                    │        (LLM)            │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │   data_quality_check    │
                    │        (Tool)           │
                    │  [GUARD: score >= 0.7]  │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │    recommend_features   │
                    │        (LLM)            │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │execute_feature_engineering│
                    │        (Tool)           │
                    └───────────┬─────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
    ┌─────────┴───────┐ ┌───────┴───────┐ ┌──────┴──────┐
    │   train_model   │ │  train_model  │ │ train_model │
    │ random_forest   │ │gradient_boost │ │neural_network│
    │     (LLM)       │ │    (LLM)      │ │    (LLM)    │
    └─────────┬───────┘ └───────┬───────┘ └──────┬──────┘
              │                 │                 │
    ┌─────────┴───────┐ ┌───────┴───────┐ ┌──────┴──────┐
    │ evaluate_model  │ │ evaluate_model│ │evaluate_model│
    │ random_forest   │ │gradient_boost │ │neural_network│
    │     (LLM)       │ │    (LLM)      │ │    (LLM)    │
    └─────────┬───────┘ └───────┬───────┘ └──────┬──────┘
              │                 │                 │
              └─────────────────┼─────────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │   select_best_model     │
                    │        (Tool)           │
                    │  [version_consumption]  │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │generate_model_explanations│
                    │        (LLM)            │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │assess_deployment_readiness│
                    │        (LLM)            │
                    └───────────┬─────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                                   │
    ┌─────────┴───────────┐           ┌──────────┴──────────┐
    │    deploy_model     │           │generate_pipeline_report│
    │       (Tool)        │           │        (Tool)        │
    │[GUARD: ready & 0.8] │           └─────────────────────┘
    └─────────────────────┘
```

## Key Patterns Demonstrated

### 1. Quality Gate with Guard
Data must pass quality threshold before proceeding:
```yaml
guard:
  condition: 'quality_score >= 0.7'
  on_false: "filter"
```

### 2. Parallel Model Training
Train multiple algorithms simultaneously:
```yaml
versions:
  range: ["random_forest", "gradient_boosting", "neural_network"]
  mode: parallel
```

### 3. Model Selection via Version Consumption
Aggregate parallel results for champion selection:
```yaml
version_consumption:
  source: evaluate_model
  pattern: merge
```

### 4. Conditional Deployment
Only deploy if readiness criteria met:
```yaml
guard:
  condition: 'deployment_ready == true and readiness_score >= 0.8'
  on_false: "filter"
```

### 5. Passthrough for Data Lineage
Preserve upstream data through tool actions:
```yaml
context_scope:
  observe:
    - recommend_features.transformation_pipeline
  passthrough:
    - assess_data_quality.*
    - recommend_features.*
```

## Data Flow

```
agent_io/
├── staging/          # Place ML dataset JSON here
│   └── ml_dataset.json
├── source/           # Auto-generated with metadata
└── target/           # Output from each action
    ├── assess_data_quality/
    ├── data_quality_check/
    ├── recommend_features/
    ├── execute_feature_engineering/
    ├── train_model_random_forest/
    ├── train_model_gradient_boosting/
    ├── train_model_neural_network/
    ├── evaluate_model_random_forest/
    ├── evaluate_model_gradient_boosting/
    ├── evaluate_model_neural_network/
    ├── select_best_model/
    ├── generate_model_explanations/
    ├── assess_deployment_readiness/
    ├── deploy_model/
    └── generate_pipeline_report/
```

## Input Format

Place dataset metadata in `agent_io/staging/`:

```json
[
  {
    "training_data": {
      "dataset_name": "customer_churn_prediction",
      "row_count": 7043,
      "features": [
        {"name": "tenure", "type": "numeric", "min": 0, "max": 72},
        {"name": "Contract", "type": "categorical", "values": ["Month-to-month", "One year", "Two year"]}
      ],
      "target": {
        "name": "Churn",
        "type": "binary",
        "distribution": {"Yes": 1869, "No": 5174}
      },
      "sample_records": [...],
      "quality_indicators": {
        "missing_values": {"TotalCharges": 11},
        "class_imbalance_ratio": 2.77
      }
    },
    "validation_data": {
      "row_count": 1409,
      "split_ratio": 0.2
    }
  }
]
```

## Output

The pipeline produces:

1. **Model Selection Results**
```json
{
  "champion_model": "model_gradient_boosting_abc123",
  "champion_algorithm": "gradient_boosting",
  "champion_metrics": {"f1_score": 0.82, "auc_roc": 0.88},
  "model_comparison": [...]
}
```

2. **Deployment Status**
```json
{
  "deployment_id": "deploy_xyz789",
  "deployment_status": "SUCCESS",
  "endpoint_url": "https://ml-api.example.com/v1/models/.../predict"
}
```

3. **Pipeline Report**
```json
{
  "pipeline_summary": {"status": "COMPLETED", "stages_passed": 6},
  "key_metrics": {"data_quality_score": 0.85, "champion_model_score": 0.78},
  "recommendations": [...]
}
```

## Seed Data

Reference data in `seed_data/`:
- `feature_definitions.json` - Reusable feature transformations
- `model_registry.json` - Production model baselines
- `deployment_config.json` - Deployment requirements and targets

## Running the Workflow

```bash
# Run the pipeline
agac run -a automated_ml_pipeline

```

## Tools

| Tool | Purpose |
|------|---------|
| `validate_data_quality_threshold` | Quality gate validation |
| `apply_feature_transformations` | Execute feature engineering |
| `select_champion_model` | Weighted model selection |
| `deploy_model_to_production` | Production deployment |
| `format_ml_pipeline_report` | Generate pipeline report |

## Customization

- **Quality thresholds**: Modify constants in `validate_data_quality_threshold.py`
- **Model selection weights**: Update `METRIC_WEIGHTS` in `select_champion_model.py`
- **Deployment checks**: Adjust guard conditions in workflow YAML
- **Add algorithms**: Extend the `versions.range` array with new algorithm names

## Recommended Datasets

For testing, use datasets from:
- [UCI Machine Learning Repository](https://archive.ics.uci.edu/)
- [Kaggle Datasets](https://www.kaggle.com/datasets)
- Sample data included: Telco Customer Churn, German Credit Risk
