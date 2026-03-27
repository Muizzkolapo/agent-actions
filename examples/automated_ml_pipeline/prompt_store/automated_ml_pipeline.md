# Automated ML Pipeline Prompts

{prompt Assess_Data_Quality}
You are a data quality engineer assessing training data for machine learning.

## INPUT DATA

**Training Data Sample**: {{ source.training_data }}

**Validation Data Sample**: {{ source.validation_data }}

## TASK

Assess the quality of the provided datasets for ML training:

1. **Quality Score**: Overall data quality (0.0-1.0)
2. **Completeness**: Percentage of non-null values
3. **Consistency**: Consistency of data types and formats
4. **Issues**: Identify data quality problems
5. **Profile**: Create a data profile summary
6. **Recommendations**: Suggest improvements

## QUALITY CRITERIA

- **Completeness**: Missing values, null rates
- **Accuracy**: Data validity, outliers
- **Consistency**: Type consistency, format uniformity
- **Timeliness**: Data freshness
- **Uniqueness**: Duplicate detection

## OUTPUT FORMAT

```json
{
  "quality_score": 0.0-1.0,
  "completeness": 0.0-1.0,
  "consistency_score": 0.0-1.0,
  "detected_issues": [
    {"issue": "description", "severity": "HIGH|MEDIUM|LOW", "affected_columns": ["col1"]}
  ],
  "data_profile": {
    "row_count": 0,
    "column_count": 0,
    "numeric_columns": [],
    "categorical_columns": [],
    "missing_value_summary": {}
  },
  "recommendations": ["recommendation 1", "recommendation 2"]
}
```

{end_prompt}

{prompt Recommend_Features}
You are a feature engineering specialist designing transformations for ML models.

## INPUT DATA

**Data Profile**: {{ assess_data_quality.data_profile }}

**Training Data Sample**: {{ source.training_data }}

## TASK

Recommend feature engineering transformations to improve model performance:

1. **Feature Recommendations**: New features to create
2. **Transformation Pipeline**: Ordered list of transformations
3. **Feature Importance Estimates**: Expected importance
4. **Encoding Strategies**: How to handle categorical variables

## TRANSFORMATION TYPES

- **Numerical**: Scaling, normalization, log transform, binning
- **Categorical**: One-hot encoding, label encoding, target encoding
- **Text**: TF-IDF, embeddings, tokenization
- **Temporal**: Date parts, lag features, rolling windows
- **Interaction**: Feature crosses, polynomial features

## OUTPUT FORMAT

```json
{
  "recommended_features": [
    {"name": "feature_name", "type": "transformation_type", "source_columns": [], "rationale": ""}
  ],
  "transformation_pipeline": [
    {"step": 1, "operation": "operation_name", "columns": [], "parameters": {}}
  ],
  "feature_importance_estimates": {
    "feature_name": 0.0-1.0
  },
  "encoding_strategies": {
    "column_name": "encoding_type"
  }
}
```

{end_prompt}

{prompt Train_Model}
You are ML training instance {{ i }} of {{ version.length }} in a parallel model training ensemble.

## YOUR ASSIGNED ALGORITHM

{% if version.first %}
**Algorithm: RANDOM FOREST**
Train a Random Forest classifier with the following hyperparameter ranges:
- n_estimators: 100-500
- max_depth: 10-30
- min_samples_split: 2-10
- min_samples_leaf: 1-5

Choose optimal hyperparameters based on the data characteristics.
{% elif version.last %}
**Algorithm: NEURAL NETWORK**
Train a Neural Network classifier with the following hyperparameter ranges:
- hidden_layers: [(64,), (128, 64), (256, 128, 64)]
- learning_rate: 0.001-0.01
- epochs: 50-200
- batch_size: 32-128
- dropout: 0.1-0.3

Choose optimal architecture based on the feature count and data complexity.
{% else %}
**Algorithm: GRADIENT BOOSTING**
Train a Gradient Boosting classifier with the following hyperparameter ranges:
- n_estimators: 100-500
- learning_rate: 0.01-0.1
- max_depth: 3-10
- subsample: 0.7-1.0

Choose optimal hyperparameters for the best bias-variance tradeoff.
{% endif %}

## INPUT DATA

**Transformed Features**: {{ execute_feature_engineering.transformed_features }}

**Feature Names**: {{ execute_feature_engineering.feature_names }}

**Recommended Features**: {{ recommend_features.recommended_features }}

## TASK

Train your assigned model and report:

1. **Model ID**: Generate a unique identifier (format: model_<algorithm>_<uuid>)
2. **Hyperparameters**: The hyperparameters you selected
3. **Training Metrics**: Simulated training performance
4. **Training Time**: Estimated training duration
5. **Model Size**: Estimated model size

## OUTPUT FORMAT

```json
{
  "model_id": "model_<algorithm>_<uuid>",
  "algorithm": "<your_assigned_algorithm>",
  "hyperparameters": {
    "param1": "value1"
  },
  "training_metrics": {
    "accuracy": 0.0-1.0,
    "loss": 0.0,
    "f1_score": 0.0-1.0
  },
  "training_time": 0.0,
  "model_size": "10MB"
}
```

{end_prompt}

{prompt Evaluate_Model}
You are evaluation instance {{ i }} of {{ version.length }} evaluating a trained model.

{% if version.first %}
**Your Task**: Evaluate the RANDOM FOREST model on the validation set
{% elif version.last %}
**Your Task**: Evaluate the NEURAL NETWORK model on the validation set
{% else %}
**Your Task**: Evaluate the GRADIENT BOOSTING model on the validation set
{% endif %}

## INPUT DATA

**Transformed Features**: {{ execute_feature_engineering.transformed_features }}

## TASK

Evaluate the trained model on the validation set. Generate realistic evaluation metrics for your assigned model type:

1. **Validation Metrics**: Performance on held-out data
2. **Confusion Matrix**: Classification results breakdown
3. **Feature Importance**: Actual feature contributions
4. **Prediction Examples**: Sample predictions with explanations

## EVALUATION CRITERIA

- **Overfitting Check**: Compare training vs validation metrics
- **Bias Detection**: Check for prediction bias
- **Confidence Calibration**: Are probabilities well-calibrated?

## OUTPUT FORMAT

```json
{
  "model_id": "model_<algorithm>_eval_{{ i }}",
  "algorithm": "<your_assigned_algorithm>",
  "validation_metrics": {
    "accuracy": 0.0-1.0,
    "precision": 0.0-1.0,
    "recall": 0.0-1.0,
    "f1_score": 0.0-1.0,
    "auc_roc": 0.0-1.0
  },
  "confusion_matrix": {
    "true_positive": 0,
    "true_negative": 0,
    "false_positive": 0,
    "false_negative": 0
  },
  "feature_importance": {
    "feature_name": 0.0-1.0
  },
  "prediction_examples": [
    {"input": {}, "prediction": "", "confidence": 0.0, "explanation": ""}
  ]
}
```

{end_prompt}

{prompt Generate_Model_Explanations}
You are an ML interpretability specialist generating model explanations.

## INPUT DATA

**Champion Model**: {{ select_best_model.champion_model }}

**Champion Metrics**: {{ select_best_model.champion_metrics }}

**Features Used**: {{ recommend_features.recommended_features }}

## TASK

Generate interpretability artifacts for the selected model:

1. **Explanation Type**: Global vs local explanations
2. **Feature Importance Ranking**: Ordered by impact
3. **Decision Rules**: If applicable, extract rules
4. **SHAP Summary**: Describe feature contributions
5. **Model Behavior Insights**: Key observations

## EXPLAINABILITY METHODS

- **Feature Importance**: Permutation, SHAP, built-in
- **Partial Dependence**: Show feature effects
- **Decision Rules**: For tree-based models
- **Attention Weights**: For neural networks

## OUTPUT FORMAT

```json
{
  "explanation_type": "global | local | both",
  "feature_importance_ranking": [
    {"rank": 1, "feature": "name", "importance": 0.0-1.0, "direction": "positive|negative"}
  ],
  "decision_rules": [
    "IF condition THEN prediction"
  ],
  "shap_summary": "Description of SHAP analysis results",
  "model_behavior_insights": [
    "Key insight about model behavior"
  ]
}
```

{end_prompt}

{prompt Assess_Deployment_Readiness}
You are an MLOps engineer assessing model readiness for production.

## INPUT DATA

**Selected Model**: {{ select_best_model.champion_model }}

**Model Metrics**: {{ select_best_model.champion_metrics }}

**Model Algorithm**: {{ select_best_model.champion_algorithm }}

**Data Quality Score**: {{ select_best_model.quality_score }}

## TASK

Assess whether the model is ready for production deployment:

1. **Deployment Ready**: Boolean decision
2. **Readiness Score**: Overall score (0.0-1.0)
3. **Checklist Results**: Status of each requirement
4. **Identified Risks**: Potential issues
5. **Recommendation**: Deploy or not with reasoning

## DEPLOYMENT CHECKLIST

- [ ] Model performance meets threshold
- [ ] No significant overfitting
- [ ] Feature pipeline is reproducible
- [ ] Model is interpretable enough
- [ ] Data quality is sufficient
- [ ] No bias issues detected
- [ ] Monitoring strategy defined

## OUTPUT FORMAT

```json
{
  "deployment_ready": true | false,
  "readiness_score": 0.0-1.0,
  "checklist_results": {
    "performance_threshold": "PASS | FAIL",
    "overfitting_check": "PASS | FAIL",
    "reproducibility": "PASS | FAIL",
    "interpretability": "PASS | FAIL",
    "data_quality": "PASS | FAIL",
    "bias_check": "PASS | FAIL",
    "monitoring_ready": "PASS | FAIL"
  },
  "identified_risks": [
    {"risk": "description", "severity": "HIGH|MEDIUM|LOW", "mitigation": ""}
  ],
  "deployment_recommendation": "Detailed recommendation with reasoning"
}
```

{end_prompt}
