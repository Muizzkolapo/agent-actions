# Lessons Learned

## 2026-02-15 - Packaging regressions can bypass test suites

- Failure mode: Console-script entrypoints (`agac-lsp`) can break even when unit/integration tests pass.
- Detection signal: Installed script fails immediately with `ModuleNotFoundError` on `--help`.
- Prevention rule: In CI/release pipelines, install the built wheel and smoke-test all declared `project.scripts` commands.

## 2026-02-15 - Avoid environment-dependent failure assumptions in tests

- Failure mode: Tests relied on external environment behavior (network availability for tiktoken downloads, privileged port binding failure on port 80), causing false negatives in CI/containerized runs.
- Detection signal: Full test suite failures in metadata token-count tests with `ProxyError` and HITL startup failure test timing out when port 80 bind succeeded.
- Prevention rule: Mock network/tokenizer calls in unit tests and force server startup errors with deterministic monkeypatching instead of privileged-port assumptions.
