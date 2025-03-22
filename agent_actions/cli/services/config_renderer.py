

"""
Configuration rendering service.
"""

import yaml
from pathlib import Path
from typing import Dict, Any
from agent_actions.workflow.render_workflow import render_pipeline_with_templates


class ConfigRenderer:
    """Handles configuration rendering operations."""
    
    @staticmethod
    def render_and_load_config(
        agent_name: str,
        config_path: Path,
        template_dir: Path,
        output_dir: Path
    ) -> Dict[str, Any]:
        """
        Render templates and load configuration data.

        Args:
            agent_name: Name of the agent.
            config_path: Path to the agent configuration file.
            template_dir: Path to the template directory.
            output_dir: Path to the output directory.

        Returns:
            Parsed configuration data as a dictionary.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{agent_name}.yml"

        config_data_str = render_pipeline_with_templates(str(config_path), str(template_dir), str(output_path))
        return yaml.safe_load(config_data_str)
