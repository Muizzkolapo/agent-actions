 All CI Checks Pass

  | Check             | Result              |
  |-------------------|---------------------|
  | Unit Tests        | 60 passed           |
  | Integration Tests | 62 passed           |
  | Full Test Suite   | 1174 passed         |
  | Ruff Lint         | All checks passed   |
  | Ruff Format       | All files formatted |
  | Pylint            | 10.00/10            |

  Implementation Summary - Issue #629

  Files Created

  | File                             | Description                     |
  |----------------------------------|---------------------------------|
  | batch_retry_config.py            | RetryConfig model with presets  |
  | batch_retry_orchestrator.py      | Core retry orchestration logic  |
  | mock_batch_client.py             | Mock provider for testing retry |
  | test_batch_retry_config.py       | 24 unit tests                   |
  | test_batch_retry_orchestrator.py | 14 unit tests                   |

  Files Modified

  | File                      | Changes                                     |
  |---------------------------|---------------------------------------------|
  | batch_result_processor.py | Added _retry_metadata to output records     |
  | batch_service.py          | Wired orchestrator, added retry_batch_job() |
  | batch_job_manager.py      | Added chain query methods                   |
  | batch_cli.py              | Added retry and chain-status commands       |
  | batch_client_factory.py   | Registered mock client                      |
  | batch_client_resolver.py  | Allow mock without API key                  |
  | new_format_schema.py      | Added retry config validation               |

  Manual Testing

  # Test with mock provider (30% failure rate)
  export MOCK_BATCH_FAILURE_RATE=0.3
  agac run workflow.yaml --run-mode batch  # with model_vendor: mock

  # Or test specific failing IDs
  export MOCK_BATCH_FAILURE_IDS=record_1,record_5
  agac run workflow.yaml --run-mode batch
