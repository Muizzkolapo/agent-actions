#!/usr/bin/env python3
"""
Transform agent_actions to dbt-like structure.
This script reorganizes the codebase to follow dbt's architectural patterns.
"""

import os
import re
import shutil
from pathlib import Path
from typing import Dict, List, Tuple
import json


class DbtTransformer:
    def __init__(self, root_path: str = ".", dry_run: bool = True):
        self.root = Path(root_path)
        self.agent_actions = self.root / "agent_actions"
        self.dry_run = dry_run
        self.moved_files = []
        self.import_map = {}

        # Define the complete file mapping
        self.file_mappings = {
            # CORE MODULE
            "core/runtime/agent_runner.py": "core/agent_runner.py",
            "core/runtime/agent_strategies.py": "core/agent_strategies.py",
            "core/runtime/application_container.py": "core/application_container.py",

            "core/graph/agent_workflow.py": "workflow/agent_workflow.py",
            "core/graph/render_workflow.py": "workflow/render_workflow.py",
            "core/graph/dependency_injection.py": "core/dependency_injection.py",

            "core/parser/config_schema.py": "models/config_schema.py",
            "core/parser/config_types.py": "models/config_types.py",
            "core/parser/pipeline_config.py": "models/pipeline_config.py",
            "core/parser/processor_config.py": "models/processor_config.py",
            "core/parser/vendor_config.py": "models/vendor_config.py",
            "core/parser/schema_change.py": "models/schema_change.py",
            "core/parser/where_parser.py": "common/filters/where_parser.py",

            "core/context/context.py": "artifacts/context.py",
            "core/context/path_config.py": "core/path_config.py",
            "core/context/path_manager.py": "core/path_manager.py",
            "core/context/environment_config.py": "models/environment_config.py",

            "core/contracts/base.py": "artifacts/base.py",
            "core/contracts/interfaces.py": "common/interfaces/interfaces.py",
            "core/contracts/base_async_processor.py": "common/interfaces/base_async_processor.py",

            "core/exceptions.py": "core/exceptions.py",
            "core/utils.py": "core/utils.py",
            "core/tooling.py": "core/tooling.py",
            "core/constants.py": "constants.py",
            "core/config.py": "config.py",
            "core/init.py": "core/init.py",

            # AGENTS MODULE
            "agents/extractors/source_data_loader.py": "loaders/data_loaders/source_data_loader.py",
            "agents/extractors/json_loader.py": "loaders/data_loaders/json_loader.py",
            "agents/extractors/xml_loader.py": "loaders/data_loaders/xml_loader.py",
            "agents/extractors/tabular_loader.py": "loaders/data_loaders/tabular_loader.py",
            "agents/extractors/text_loader.py": "loaders/data_loaders/text_loader.py",

            "agents/transformers/data_processor.py": "processors/content/data_processor.py",
            "agents/transformers/prompt_formatter.py": "processors/prompt_processor/prompt_formatter.py",
            "agents/transformers/context_preprocessor.py": "processors/content/context_preprocessor.py",
            "agents/transformers/response_transformer.py": "processors/content/response_transformer.py",
            "agents/transformers/sample_enricher.py": "processors/content/sample_enricher.py",
            "agents/transformers/string_transformer.py": "common/transformers/string_transformer.py",
            "agents/transformers/data_transformer.py": "common/transformers/data_transformer.py",
            "agents/transformers/pure_transformers.py": "common/transformers/pure_transformers.py",
            "agents/transformers/prompt_utils.py": "processors/content/prompt_utils.py",

            # Also move prompt_processor versions
            "agents/transformers/pp_context_preprocessor.py": "processors/prompt_processor/context_preprocessor.py",
            "agents/transformers/pp_response_transformer.py": "processors/prompt_processor/response_transformer.py",
            "agents/transformers/pp_sample_enricher.py": "processors/prompt_processor/sample_enricher.py",

            "agents/generators/content_generator.py": "generators/content/content_generator.py",
            "agents/generators/data_generator.py": "generators/content/data_generator.py",
            "agents/generators/target_generator.py": "processors/target_processor/target_generator.py",
            "agents/generators/output_processor.py": "generators/output/output_processor.py",
            "agents/generators/directory_handler.py": "generators/output/directory_handler.py",
            "agents/generators/file_handler.py": "generators/output/file_handler.py",
            "agents/generators/target_data_generator.py": "processors/target_processor/data_generator.py",
            "agents/generators/target_data_processor.py": "processors/target_processor/data_processor.py",
            "agents/generators/target_content_processor.py": "processors/target_processor/target_content_processor.py",

            "agents/validators/validation_interceptor.py": "interceptors/validation_interceptor.py",
            "agents/validators/builtin_functions.py": "validators/builtin_functions.py",
            "agents/validators/functions.py": "validators/functions.py",
            "agents/validators/schema_validator.py": "cli/validators/schema_validator.py",
            "agents/validators/config_validator.py": "cli/validators/config_validator.py",
            "agents/validators/path_validator.py": "cli/validators/path_validator.py",
            "agents/validators/prompt_validator.py": "cli/validators/prompt_validator.py",

            "agents/handlers/agent_handlers.py": "handlers/agent_handlers.py",
            "agents/handlers/prompt_handler.py": "handlers/prompt_handler.py",
            "agents/handlers/file_handler.py": "handlers/file_handler.py",
            "agents/handlers/output_handler.py": "processors/target_processor/output_handler.py",
            "agents/handlers/config_handler.py": "handlers/config_handler.py",
            "agents/handlers/schema_handler.py": "handlers/schema_handler.py",
            "agents/handlers/file_reader.py": "handlers/file_reader.py",
            "agents/handlers/file_writer.py": "handlers/file_writer.py",
            "agents/handlers/cleaner.py": "handlers/cleaner.py",

            "agents/base/base_loader.py": "loaders/data_loaders/base_loader.py",
            "agents/base/base_validator.py": "cli/validators/base_validator.py",
            "agents/base/agent_builder.py": "models/agent_builder.py",

            # ARTIFACTS MODULE
            "artifacts/catalog.py": "artifacts/catalog.py",
            "artifacts/manifest.py": "artifacts/manifest.py",
            "artifacts/run_results.py": "artifacts/run_results.py",
            "artifacts/validation_results.py": "artifacts/validation_results.py",
            "artifacts/manager.py": "artifacts/manager.py",
            "artifacts/lineage/lineage_mixin.py": "common/utils/lineage_mixin.py",

            # TASKS MODULE
            "tasks/run.py": "cli/commands/run_command.py",
            "tasks/test.py": "cli/commands/clean_command.py",
            "tasks/compile.py": "cli/commands/render_command.py",
            "tasks/batch.py": "cli/commands/batch_command.py",
            "tasks/init.py": "cli/commands/init_command.py",
            "tasks/docs.py": "cli/commands/docs_command.py",
            "tasks/status.py": "cli/commands/status_command.py",
            "tasks/services/batch_service.py": "services/batch_service.py",
            "tasks/services/config_renderer.py": "cli/services/config_renderer.py",
            "tasks/services/project_paths_factory.py": "cli/services/project_paths_factory.py",

            # INTEGRATIONS MODULE
            "integrations/providers/anthropic/provider.py": "providers/anthropic_provider.py",
            "integrations/providers/anthropic/vendor.py": "vendors/anthropic_vendor.py",
            "integrations/providers/openai/provider.py": "providers/openai_provider.py",
            "integrations/providers/openai/vendor.py": "vendors/openai_vendor.py",
            "integrations/providers/gemini/provider.py": "providers/gemini_provider.py",
            "integrations/providers/gemini/vendor.py": "vendors/gemini_vendor.py",
            "integrations/providers/cohere/vendor.py": "vendors/cohere_vendor.py",
            "integrations/providers/mistral/vendor.py": "vendors/mistral_vendor.py",
            "integrations/providers/ollama/vendor.py": "vendors/ollama_vendor.py",
            "integrations/providers/deepseek/vendor.py": "vendors/deepseek_vendor.py",
            "integrations/providers/groq/vendor.py": "vendors/groq_llama.py",
            "integrations/providers/tools/vendor.py": "vendors/tools_vendor.py",
            "integrations/providers/base.py": "providers/base.py",
            "integrations/providers/factory.py": "providers/factory.py",
            "integrations/providers/vendor_base.py": "vendors/base_vendor.py",

            "integrations/loaders/batch_data_loader.py": "loaders/data_loaders/batch_data_loader.py",

            "integrations/interceptors/base.py": "interceptors/base.py",
            "integrations/interceptors/factory.py": "interceptors/factory.py",
            "integrations/interceptors/reprompt_interceptor.py": "interceptors/reprompt_interceptor.py",

            # CLI MODULE
            "cli/main.py": "cli/main.py",
            "cli/exceptions.py": "cli/exceptions.py",
            "cli/utils/error_handler.py": "cli/utils/error_handler.py",
            "cli/utils/service_logger.py": "cli/utils/service_logger.py",
            "cli/utils/error_wrap.py": "cli/validators/error_wrap.py",

            # INTERNAL UTILITIES
            "_internal/common/monitoring/logging.py": "common/monitoring/logging.py",
            "_internal/common/monitoring/metrics.py": "common/monitoring/metrics.py",
            "_internal/common/resilience/circuit_breaker.py": "common/resilience/circuit_breaker.py",
            "_internal/common/resilience/retry.py": "common/resilience/retry.py",
            "_internal/common/correlation/tracker.py": "common/correlation/tracker.py",
            "_internal/common/feature_flags/manager.py": "common/feature_flags/manager.py",

            "_internal/utils/processor_utils.py": "common/utils/processor_utils.py",
            "_internal/utils/processor_helpers.py": "common/utils/processor_helpers.py",
            "_internal/utils/error_handling.py": "common/utils/error_handling.py",
            "_internal/utils/field_chunking.py": "utils/field_chunking.py",
            "_internal/utils/path_utils.py": "utils/path_utils.py",

            "_internal/filters/ast_nodes.py": "common/filters/ast_nodes.py",
            "_internal/filters/operator_registry.py": "common/filters/operator_registry.py",
            "_internal/filters/parser.py": "common/filters/parser.py",
            "_internal/filters/secure_parser.py": "common/filters/secure_parser.py",
            "_internal/filters/where_filter.py": "common/filters/where_filter.py",

            "_internal/staging/staging_content.py": "processors/staging_processor/staging_content.py",
            "_internal/staging/staging_loader.py": "processors/staging_processor/staging_loader.py",
            "_internal/staging/staging_processor.py": "processors/staging_processor/staging_processor.py",
            "_internal/staging/source_path_manager.py": "processors/source_processor/source_path_manager.py",

            "_internal/bootstrap/bootstrap.py": "bootstrap.py",
            "_internal/bootstrap/di_configurator.py": "core/di_configurator.py",
            "_internal/bootstrap/startup_validator.py": "core/startup_validator.py",

            # DOCS MODULE
            "docs/app.py": "docs/app.py",
        }

        # Additional validators that weren't mapped
        self.additional_validators = [
            "cli/validators/batch_validator.py",
            "cli/validators/clean_validator.py",
            "cli/validators/directory_validator.py",
            "cli/validators/docs_validator.py",
            "cli/validators/init_validator.py",
            "cli/validators/project_validator.py",
            "cli/validators/render_validator.py",
            "cli/validators/run_validator.py",
            "cli/validators/status_validator.py",
        ]

    def create_directories(self):
        """Create the new directory structure."""
        directories = [
            "core/runtime", "core/graph", "core/parser", "core/context", "core/contracts",
            "agents/extractors", "agents/transformers", "agents/generators",
            "agents/validators", "agents/handlers", "agents/base",
            "artifacts/lineage",
            "tasks/services",
            "integrations/providers/anthropic", "integrations/providers/openai",
            "integrations/providers/gemini", "integrations/providers/cohere",
            "integrations/providers/mistral", "integrations/providers/ollama",
            "integrations/providers/deepseek", "integrations/providers/groq",
            "integrations/providers/tools",
            "integrations/loaders", "integrations/interceptors",
            "cli/utils",
            "_internal/common/monitoring", "_internal/common/resilience",
            "_internal/common/correlation", "_internal/common/feature_flags",
            "_internal/utils", "_internal/filters", "_internal/staging", "_internal/bootstrap",
            "projects/example_project/agents", "projects/example_project/prompts",
            "projects/example_project/data", "docs"
        ]

        for dir_path in directories:
            full_path = self.agent_actions / dir_path
            if self.dry_run:
                print(f"[DRY RUN] Would create: {full_path}")
            else:
                full_path.mkdir(parents=True, exist_ok=True)
                print(f"Created: {full_path}")

    def move_files(self):
        """Move files to their new locations."""
        for new_path, old_path in self.file_mappings.items():
            old_file = self.agent_actions / old_path
            new_file = self.agent_actions / new_path

            if old_file.exists():
                if self.dry_run:
                    print(f"[DRY RUN] Would move: {old_path} -> {new_path}")
                else:
                    new_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old_file), str(new_file))
                    print(f"Moved: {old_path} -> {new_path}")

                self.moved_files.append((old_path, new_path))

                # Track import changes
                old_module = old_path.replace("/", ".").replace(".py", "")
                new_module = new_path.replace("/", ".").replace(".py", "")
                self.import_map[f"agent_actions.{old_module}"] = f"agent_actions.{new_module}"

    def move_validators(self):
        """Move remaining validators to agents/validators."""
        for validator in self.additional_validators:
            old_file = self.agent_actions / validator
            new_path = f"agents/validators/{Path(validator).name}"
            new_file = self.agent_actions / new_path

            if old_file.exists():
                if self.dry_run:
                    print(f"[DRY RUN] Would move: {validator} -> {new_path}")
                else:
                    new_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old_file), str(new_file))
                    print(f"Moved: {validator} -> {new_path}")

    def update_imports(self):
        """Update all import statements in Python files."""
        if self.dry_run:
            print("[DRY RUN] Would update imports in all Python files")
            return

        # Get all Python files
        python_files = list(self.agent_actions.rglob("*.py"))

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                original = content

                # Apply import mappings
                for old_import, new_import in self.import_map.items():
                    # Handle "from X import Y" patterns
                    content = re.sub(
                        rf"from {re.escape(old_import)}([\s\.])",
                        rf"from {new_import}\1",
                        content
                    )
                    # Handle "import X" patterns
                    content = re.sub(
                        rf"import {re.escape(old_import)}([\s\.,])",
                        rf"import {new_import}\1",
                        content
                    )

                # Write back if changed
                if content != original:
                    with open(py_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"Updated imports in: {py_file.relative_to(self.agent_actions)}")

            except Exception as e:
                print(f"Error updating {py_file}: {e}")

    def create_example_project(self):
        """Create an example project structure."""
        example_files = {
            "projects/example_project/agent_actions.yml": """# Agent Actions Project Configuration
name: example_project
version: 1.0.0

# LLM Provider Configuration
providers:
  default: openai
  openai:
    model: gpt-4
    temperature: 0.7
  anthropic:
    model: claude-3-opus
    temperature: 0.5

# Agent Definitions
agents:
  - name: data_extractor
    type: extractor
    source: agents/extract_data.yml
  - name: text_transformer
    type: transformer
    source: agents/transform_text.yml
  - name: content_generator
    type: generator
    source: agents/generate_content.yml

# Workflow Configuration
workflow:
  steps:
    - agent: data_extractor
      input: data/input.json
    - agent: text_transformer
      depends_on: [data_extractor]
    - agent: content_generator
      depends_on: [text_transformer]
      output: data/output.json
""",
            "projects/example_project/agents/extract_data.yml": """# Data Extraction Agent
name: extract_data
type: extractor

config:
  loader: json
  schema:
    type: object
    properties:
      text:
        type: string
      metadata:
        type: object

prompt: |
  Extract structured data from the following input:
  {{ input }}
""",
            "projects/example_project/prompts/transform.txt": """Transform the following text:
{{ text }}

Requirements:
- Make it more concise
- Maintain key information
- Improve clarity
"""
        }

        for file_path, content in example_files.items():
            full_path = self.root / file_path
            if self.dry_run:
                print(f"[DRY RUN] Would create example file: {file_path}")
            else:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                with open(full_path, 'w') as f:
                    f.write(content)
                print(f"Created example file: {file_path}")

    def cleanup_empty_directories(self):
        """Remove empty directories after moving files."""
        if self.dry_run:
            print("[DRY RUN] Would clean up empty directories")
            return

        # Directories that should be removed if empty
        dirs_to_check = [
            "processors", "models", "vendors", "workflow", "generators",
            "loaders", "validators", "handlers", "interceptors", "services",
            "common", "bootstrap", "utils"
        ]

        for dir_name in dirs_to_check:
            dir_path = self.agent_actions / dir_name
            if dir_path.exists() and not any(dir_path.rglob("*")):
                shutil.rmtree(dir_path)
                print(f"Removed empty directory: {dir_name}")

    def create_version_file(self):
        """Create version file."""
        version_content = '"""Agent Actions version."""\n__version__ = "2.0.0"\n'
        version_file = self.agent_actions / "__version__.py"

        if self.dry_run:
            print("[DRY RUN] Would create __version__.py")
        else:
            with open(version_file, 'w') as f:
                f.write(version_content)
            print("Created __version__.py")

    def generate_report(self):
        """Generate transformation report."""
        report = {
            "moved_files": len(self.moved_files),
            "import_mappings": len(self.import_map),
            "dry_run": self.dry_run,
            "file_mappings": self.moved_files
        }

        report_file = self.root / "dbt_transformation_report.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\nGenerated report: {report_file}")
        return report

    def transform(self):
        """Execute the complete transformation."""
        print(f"🚀 Starting dbt-like transformation (dry_run={self.dry_run})")
        print(f"📁 Root: {self.root}\n")

        # Execute transformation steps
        print("1️⃣ Creating new directory structure...")
        self.create_directories()

        print("\n2️⃣ Moving files to new locations...")
        self.move_files()

        print("\n3️⃣ Moving additional validators...")
        self.move_validators()

        print("\n4️⃣ Updating import statements...")
        self.update_imports()

        print("\n5️⃣ Creating example project...")
        self.create_example_project()

        print("\n6️⃣ Creating version file...")
        self.create_version_file()

        print("\n7️⃣ Cleaning up empty directories...")
        self.cleanup_empty_directories()

        # Generate report
        report = self.generate_report()

        print("\n✨ Transformation complete!")
        print(f"📊 Summary: {report['moved_files']} files moved")

        if self.dry_run:
            print("\n💡 This was a DRY RUN. To execute:")
            print("   python dbt_transformer.py --execute")


if __name__ == "__main__":
    import sys

    dry_run = "--execute" not in sys.argv

    transformer = DbtTransformer(dry_run=dry_run)
    transformer.transform()