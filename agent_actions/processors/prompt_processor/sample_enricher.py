"""Module for enriching context with few-shot samples."""
import json
import logging
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.handlers.prompt_handler import PromptLoader

logger = logging.getLogger(__name__)


class SampleEnricher:
    """Handles enriching context with few-shot samples (Single Responsibility)."""
    
    @staticmethod
    def append_few_shot_samples(context_data, agent_name, agent_config):
        """
        Append few shot samples to the input documentation if configured.
        
        Parameters:
            context_data: Data to enrich with samples
            agent_name: Name of the agent
            agent_config: Configuration containing sample settings
            
        Returns:
            Enriched context data
        
        Raises:
            ValueError: If sample enrichment fails
        """
        try:
            _, _, few_shot_samples_path = FileHandler.get_agent_paths(agent_name)
            sample_count = agent_config.get("use_few_shot_samples", 0)
            try:
                sample_count = int(sample_count)
            except ValueError:
                sample_count = 0

            if sample_count > 0:
                if not few_shot_samples_path:
                    logger.warning(
                        "Few shot samples directory not found for agent '%s'. Skipping enrichment.",
                        agent_name,
                    )
                    return context_data

                samples = PromptLoader.load_few_shot_samples(
                    few_shot_samples_path,
                    agent_type=agent_config['agent_type'],
                    sample_count=sample_count
                )
                samples_str = "\n\n".join(
                    json.dumps(sample, indent=2) for sample in samples
                )

                if isinstance(context_data, dict):
                    context_data = json.dumps(context_data, indent=2)
                context_data += "\n\nfew shot samples:\n" + samples_str

            return context_data
        except Exception as e:
            raise ValueError(f"Failed to append few shot samples: {str(e)}")
