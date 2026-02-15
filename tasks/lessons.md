# Lessons Learned

## 2026-02-15 - Packaging regressions can bypass test suites

- Failure mode: Console-script entrypoints (`agac-lsp`) can break even when unit/integration tests pass.
- Detection signal: Installed script fails immediately with `ModuleNotFoundError` on `--help`.
- Prevention rule: In CI/release pipelines, install the built wheel and smoke-test all declared `project.scripts` commands.
