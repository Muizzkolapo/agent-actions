#!/usr/bin/env python3
"""Generate fake run data for testing the docs site."""

import json
import random
from datetime import datetime, timedelta

# Sample action names for the workflow
ACTION_NAMES = [
    "review_borderline_summaries",
    "filter_low_quality_summaries",
    "generate_scenarios",
    "flatten_questions",
    "fix_options_format",
    "score_question_quality",
    "filter_low_quality_questions",
    "suggest_distractor_counts",
    "add_answer_text",
    "generate_distractor_1",
    "generate_distractor_2",
    "generate_distractor_3",
    "reconstruct_options",
    "generate_feynman_explanation",
    "OptionsCombiner",
    "format_quiz_text"
]

LLM_ACTIONS = [
    "review_borderline_summaries",
    "generate_scenarios",
    "score_question_quality",
    "generate_distractor_1",
    "generate_distractor_2",
    "generate_distractor_3",
    "generate_feynman_explanation"
]

TOOL_ACTIONS = [
    "filter_low_quality_summaries",
    "flatten_questions",
    "fix_options_format",
    "filter_low_quality_questions",
    "suggest_distractor_counts",
    "add_answer_text",
    "reconstruct_options",
    "OptionsCombiner",
    "format_quiz_text"
]

MODELS = {
    "llm": [
        {"vendor": "openai", "model": "gpt-4o-mini"},
        {"vendor": "openai", "model": "gpt-4o"},
        {"vendor": "anthropic", "model": "claude-haiku-4-5-20251001"},
        {"vendor": "anthropic", "model": "claude-sonnet-4-5-20250929"}
    ],
    "tool": [
        {"impl": "filter_questions_by_score"},
        {"impl": "flatten_questions"},
        {"impl": "fix_options_formatting"},
        {"impl": "apply_quality_filter"},
        {"impl": "suggest_word_counts"},
        {"impl": "add_answer_text"},
        {"impl": "apply_edited_distractors"},
        {"impl": "merge_correct_answer_with_distractors"},
        {"impl": "format_quiz_object"}
    ]
}

def generate_action_data(action_name, start_time):
    """Generate data for a single action."""
    is_llm = action_name in LLM_ACTIONS
    action_type = "llm" if is_llm else "tool"

    # Random duration based on type
    if is_llm:
        duration = random.uniform(5.0, 120.0)  # LLM actions take longer
    else:
        duration = random.uniform(0.05, 2.0)  # Tool actions are faster

    end_time = start_time + timedelta(seconds=duration)

    # Random success/failure (90% success rate)
    status = "success" if random.random() < 0.9 else "failed"

    action_data = {
        "status": status,
        "started_at": start_time.isoformat(),
        "ended_at": end_time.isoformat(),
        "duration_seconds": round(duration, 6),
        "type": action_type
    }

    if is_llm:
        model_info = random.choice(MODELS["llm"])
        action_data.update(model_info)

        # Generate token counts
        input_tokens = random.randint(1000, 8000)
        output_tokens = random.randint(100, 1000)
        action_data["tokens"] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens
        }
    else:
        impl_info = random.choice(MODELS["tool"])
        action_data.update(impl_info)

        # Tools still have token info (from previous action)
        input_tokens = random.randint(1000, 8000)
        output_tokens = random.randint(100, 1000)
        action_data["tokens"] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens
        }

    if status == "failed":
        action_data["error"] = f"Error generating target: Failed to process content for {action_name}"

    return action_data, end_time

def generate_run(run_number, base_time):
    """Generate a complete run."""
    run_id = f"run_qanalabs_quiz_gen_{run_number:03d}"

    # Random number of actions that actually ran (between 0 and all)
    num_actions_to_run = random.randint(0, len(ACTION_NAMES))
    actions_to_run = random.sample(ACTION_NAMES, num_actions_to_run)

    # Start time for this run
    start_time = base_time - timedelta(hours=random.randint(0, 720))  # Up to 30 days ago
    current_time = start_time

    actions = {}
    successful = 0
    failed = 0
    total_tokens = 0

    for action_name in actions_to_run:
        action_data, current_time = generate_action_data(action_name, current_time)
        actions[action_name] = action_data

        if action_data["status"] == "success":
            successful += 1
        else:
            failed += 1

        total_tokens += action_data["tokens"]["total_tokens"]

    # Determine overall run status
    if failed > 0:
        status = "FAILED"
        error_message = f"Error generating target: Failed to process content [Context: workflow run {run_id}]"
    elif successful == 0:
        status = "FAILED"
        error_message = "No actions executed successfully"
    else:
        status = "SUCCESS"
        error_message = None

    duration = (current_time - start_time).total_seconds()

    run = {
        "id": run_id,
        "workflow_id": "qanalabs_quiz_gen",
        "workflow_name": "qanalabs_quiz_gen",
        "status": status,
        "started_at": start_time.isoformat(),
        "ended_at": current_time.isoformat(),
        "duration_seconds": round(duration, 6),
        "total_actions": len(ACTION_NAMES),
        "successful_actions": successful,
        "failed_actions": failed,
        "skipped_actions": 0,
        "total_tokens": total_tokens,
        "error_message": error_message,
        "actions": actions
    }

    return run

def generate_runs_file(num_runs=20, output_file=None):
    """Generate a complete runs.json file with fake data."""
    base_time = datetime.now()

    executions = []
    for i in range(num_runs, 0, -1):  # Reverse so newest is first
        run = generate_run(i, base_time)
        executions.append(run)

    # Calculate workflow metrics
    total_runs = len(executions)
    successful_runs = sum(1 for r in executions if r["status"] == "SUCCESS")
    failed_runs = total_runs - successful_runs
    total_tokens = sum(r["total_tokens"] for r in executions)
    avg_duration = sum(r["duration_seconds"] for r in executions) / total_runs if total_runs > 0 else 0
    success_rate = successful_runs / total_runs if total_runs > 0 else 0

    runs_data = {
        "metadata": {
            "generated_at": base_time.isoformat(),
            "total_runs": total_runs
        },
        "executions": executions,
        "workflow_metrics": {
            "qanalabs_quiz_gen": {
                "total_runs": total_runs,
                "successful_runs": successful_runs,
                "failed_runs": failed_runs,
                "total_tokens": total_tokens,
                "success_rate": success_rate,
                "avg_duration_seconds": avg_duration
            }
        }
    }

    # Write to file
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(runs_data, f, indent=2)
        print(f"✅ Generated {num_runs} fake runs → {output_file}")
        print(f"   - Successful: {successful_runs}")
        print(f"   - Failed: {failed_runs}")
        print(f"   - Total tokens: {total_tokens:,}")
    else:
        print(json.dumps(runs_data, indent=2))

    return runs_data

if __name__ == "__main__":
    import sys

    output_file = "/Users/muizz/Documents/codeshop/qanalabs/qanalabs-actions/qanalabs/artefact/runs.json"
    num_runs = 20

    if len(sys.argv) > 1:
        num_runs = int(sys.argv[1])

    generate_runs_file(num_runs=num_runs, output_file=output_file)
