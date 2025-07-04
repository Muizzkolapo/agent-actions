# Batch Processing with Agent Actions

This document explains how to use the batch processing feature of the Agent Actions CLI.

## Overview

The batch processing feature allows you to run agent actions on a large dataset asynchronously. This is useful for tasks such as data enrichment, content generation, and sentiment analysis.

The batch processing workflow is seamlessly integrated into the main `run` command. When you run a workflow that contains an agent configured for batch processing, the CLI will automatically submit a batch job and continue with the workflow.

## Configuration

To use the batch processing feature, you need to configure your agent to run in `batch` mode.

Here is an example of an agent configuration in your `config.yml` file:

```yaml
my_batch_agent:
  - agent_type: my_agent
    run_mode: batch
    model_name: "gpt-4.1-mini"
```

## Usage

### Running a Workflow with a Batch Agent

To run a workflow that contains a batch agent, use the `run` command as you normally would:

```bash
agent-actions run -a my_workflow
```

When the workflow encounters an agent with `run_mode: batch`, it will:

1.  Prepare the batch tasks based on the data from the previous agent.
2.  Create a `batch_input.jsonl` file in the `batch` directory.
3.  Submit the batch job to the OpenAI Batch API.
4.  Save the batch job ID to a file named `.last_batch_id` in the `batch` directory.
5.  Continue to the next agent in the workflow.

### Managing Batch Jobs

You can use the `batch` command to manage the lifecycle of your batch jobs.

#### Check the Status of a Batch Job

To check the status of a batch job, use the `status` command:

```bash
agent-actions batch status
```

This command will use the batch job ID from the `.last_batch_id` file to check the status of the last submitted job. You can also provide a specific batch job ID using the `--batch-id` option:

```bash
agent-actions batch status --batch-id <your_batch_id>
```

#### Retrieve the Results of a Batch Job

To retrieve the results of a completed batch job, use the `retrieve` command:

```bash
agent-actions batch retrieve
```

This command will use the batch job ID from the `.last_batch_id` file to retrieve the results of the last submitted job. You can also provide a specific batch job ID using the `--batch-id` option:

```bash
agent-actions batch retrieve --batch-id <your_batch_id>
```

The results will be saved to a JSONL file in the current directory. You can specify a different output directory using the `--output-dir` option:

```bash
agent-actions batch retrieve --output-dir path/to/your/output/directory
```