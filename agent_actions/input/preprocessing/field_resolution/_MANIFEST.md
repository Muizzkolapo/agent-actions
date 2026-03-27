# Field Resolution Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | All field-resolution utilities live directly under this package. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Exposes the resolver/validator/context helpers plus public exceptions for downstream guards, prompts, and validation helpers. | `preprocessing`, `filtering`, `cli` |
| `context_provider.py` | Module | `EvaluationContextProvider`/`EvaluationContext` build rich guard/filter contexts that include upstream action outputs, workflow metadata, source data, and version info. | `filtering`, `preprocessing`, `validation` |
| `exceptions.py` | Module | Custom exceptions (`FieldResolutionError`, `InvalidReferenceError`, `ReferenceNotFoundError`, etc.) used by the resolver and validator to surface reference problems. | `validation`, `filtering` |
| `reference_parser.py` | Module | `ReferenceParser` plus `ParsedReference`/`ReferenceFormat` that understand selector, template, and Jinja reference syntaxes. | `preprocessing`, `prompt_generation` |
| `resolver.py` | Module | `FieldReferenceResolver` and `ResolvedReference` that parse, resolve, and substitute field references with strict/fallback modes. | `filtering`, `validation`, `services` |
| `schema_field_validator.py` | Module | `SchemaFieldValidator` and `SchemaFieldValidationResult` ensure referenced fields exist in action JSON schemas, enabling UDF output validation. | `validation`, `configuration` |
| `validator.py` | Module | `ReferenceValidator`, dependency/special-namespace helpers, and convenience methods that validate guard references and schema usage before runtime. | `configuration`, `filtering`, `preprocessing` |
