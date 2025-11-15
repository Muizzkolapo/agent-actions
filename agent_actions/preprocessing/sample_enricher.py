"""Module for enriching prompts with few-shot samples."""
import json
import logging
from agent_actions.utilities.file_handler import FileHandler
from agent_actions.prompt_generation.prompt_handler import PromptLoader
logger = logging.getLogger(__name__)

class SampleEnricher:
    """Handles enriching prompts with few-shot samples."""

    @staticmethod
    def append_few_shot_samples(prompt_config, agent_config, agent_name):
        """Append few-shot samples to the prompt if configured.

        Parameters:
            prompt_config: The prompt string to enrich with samples
            agent_config: Configuration containing sample settings

        Returns:
            str: Enriched prompt string

        Raises:
            ValueError: If sample enrichment fails
        """
        try:
            agent_name = agent_name
            agent_type = agent_config.get('agent_type')
            few_shot_samples_path = None
            _, _, few_shot_samples_path = FileHandler.get_agent_paths(agent_name)
            sample_count = agent_config.get('few_shot', 0)
            try:
                sample_count = int(sample_count)
            except ValueError:
                sample_count = 0
            if sample_count > 0:
                if not few_shot_samples_path:
                    logger.warning(f"Few shot samples directory not found for agent '%s'. Skipping enrichment.", agent_name)
                    return prompt_config
                samples = PromptLoader.load_few_shot_samples(few_shot_samples_path, agent_type=agent_type or agent_name, sample_count=sample_count)
                samples_str = '\n\n'.join((json.dumps(sample, indent=2) for sample in samples))
                if isinstance(prompt_config, list):
                    prompt_config = [p + '\n\nfew shot samples:\n' + samples_str for p in prompt_config]
                else:
                    prompt_config = str(prompt_config) + '\n\nfew shot samples:\n' + samples_str
            return prompt_config
        except Exception as e:
            from agent_actions.shared.exceptions import ProcessingError
            raise ProcessingError(f'Failed to append few shot samples: {str(e)}', context={'agent_name': agent_config.get('agent_type', 'unknown'), 'operation': 'append_few_shot_samples'}, cause=e)