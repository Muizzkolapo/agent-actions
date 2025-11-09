from __future__ import annotations
'Utility classes for field-level chunking of structured data.'
from dataclasses import dataclass, field
from typing import Dict, List, Any
from agent_actions.preprocessing.string_transformer import Tokenizer
from agent_actions.preprocessing.strategies.chunking_strategies import (
    ChunkingStrategy,
    TiktokenChunkingStrategy,
    CharBasedChunkingStrategy,
    SpacyChunkingStrategy,
)
from agent_actions.preprocessing.strategies.fallback_strategies import (
    FallbackStrategy,
    PreserveOriginalStrategy,
    TruncateStrategy,
    SkipStrategy,
    ErrorStrategy,
)
from agent_actions.preprocessing.strategies.metadata_strategies import (
    MetadataStrategy,
    MetadataContext,
    BasicMetadataStrategy,
    EnhancedMetadataStrategy,
)
from agent_actions.preprocessing.strategies.validation import ConfigValidator

class FieldChunkingValidationError(ValueError):
    """Raised when field chunking configuration is invalid."""
    pass

class FieldChunkingError(Exception):
    """Raised when field chunking operations fail."""
    pass

@dataclass
class FieldAnalysisResult:
    """Result from analysing a record for chunking needs."""
    fields_to_chunk: List[str] = field(default_factory=list)
    field_sizes: Dict[str, int] = field(default_factory=dict)

    @property
    def requires_chunking(self) -> bool:
        """Return True if any fields require chunking."""
        return bool(self.fields_to_chunk)

class FieldAnalyzer:
    """Analyse structured records to determine which fields need chunking."""

    def __init__(self, chunk_config: Dict[str, Any]):
        self.chunk_config = chunk_config
        field_chunking = chunk_config.get('field_chunking', {})
        self.chunk_fields = field_chunking.get('chunk_fields', [])
        self.preserve_fields = field_chunking.get('preserve_fields', [])
        self.chunk_threshold = field_chunking.get('chunk_threshold', 0)
        self.tokenizer_model = chunk_config.get('tokenizer_model', 'cl100k_base')
        self.field_rules = field_chunking.get('field_rules', {})
        self.auto_detection = field_chunking.get('auto_detection', {})
        self.auto_detect_enabled = self.auto_detection.get('enabled', False)
        ConfigValidator.validate_field_analyzer_config(chunk_config)

    def analyze_record(self, record: Dict[str, Any]) -> FieldAnalysisResult:
        result = FieldAnalysisResult()
        if self.chunk_fields:
            fields_to_analyze = self.chunk_fields
        elif self.auto_detect_enabled:
            fields_to_analyze = self.detect_text_fields(record)
        else:
            fields_to_analyze = record.keys()
        for field_name in fields_to_analyze:
            if field_name not in record:
                continue
            value = record[field_name]
            if not isinstance(value, str):
                continue
            if field_name in self.preserve_fields:
                continue
            token_count = Tokenizer.num_tokens_from_string(value, self.tokenizer_model)
            result.field_sizes[field_name] = token_count
            if self.should_chunk_field(field_name, token_count):
                result.fields_to_chunk.append(field_name)
        return result

    def should_chunk_field(self, field_name: str, token_count: int) -> bool:
        if field_name in self.preserve_fields:
            return False
        if self.chunk_fields and field_name not in self.chunk_fields:
            return False
        field_rule = self.field_rules.get(field_name, {})
        threshold = field_rule.get('chunk_threshold', self.chunk_threshold)
        return token_count > threshold

    def detect_text_fields(self, record: Dict[str, Any]) -> List[str]:
        """
        Automatically detect text fields based on content size.

        Returns all string fields that could potentially need chunking.
        The actual chunking decision is made by should_chunk_field() based on token count.
        """
        if not self.auto_detect_enabled:
            return []
        detected_fields = []
        for field_name, value in record.items():
            if not isinstance(value, str):
                continue
            if field_name in self.preserve_fields:
                continue
            detected_fields.append(field_name)
        return detected_fields

class FieldChunker:
    """Chunk specific fields within structured records."""

    def __init__(self, chunk_config: Dict[str, Any]):
        self.chunk_config = chunk_config
        self.field_chunking = chunk_config.get('field_chunking', {})
        self.chunk_size = chunk_config.get('chunk_size', 1000)
        self.overlap = chunk_config.get('overlap', 200)
        self.tokenizer_model = chunk_config.get('tokenizer_model', 'cl100k_base')
        self.max_chunks_per_record = self.field_chunking.get('max_chunks_per_record', 100)
        self.truncate_at = self.field_chunking.get('truncate_at', 50000)
        self.field_rules = self.field_chunking.get('field_rules', {})
        self.chunk_metadata = self.field_chunking.get('chunk_metadata', {})

        # Initialize strategies
        self.chunking_strategy = self._create_chunking_strategy(chunk_config)
        self.fallback_strategy = self._create_fallback_strategy(chunk_config)
        self.metadata_strategy = self._create_metadata_strategy(chunk_config)

        # Validate configuration
        ConfigValidator.validate_field_chunker_config(chunk_config)

    def _create_chunking_strategy(self, config: Dict[str, Any]) -> ChunkingStrategy:
        """Factory method to create chunking strategy."""
        split_method = config.get('split_method', 'tiktoken')
        tokenizer_model = config.get('tokenizer_model', 'cl100k_base')

        if split_method == 'tiktoken':
            return TiktokenChunkingStrategy(tokenizer_model)
        elif split_method == 'chars':
            return CharBasedChunkingStrategy()
        elif split_method == 'spacy':
            return SpacyChunkingStrategy()
        else:
            return TiktokenChunkingStrategy(tokenizer_model)

    def _create_fallback_strategy(self, config: Dict[str, Any]) -> FallbackStrategy:
        """Factory method to create fallback strategy."""
        strategy_name = config.get('field_chunking', {}).get(
            'fallback_strategy', 'preserve_original'
        )

        if strategy_name == 'preserve_original':
            return PreserveOriginalStrategy()
        elif strategy_name == 'truncate':
            return TruncateStrategy()
        elif strategy_name == 'skip':
            return SkipStrategy()
        elif strategy_name == 'error':
            return ErrorStrategy()
        else:
            return PreserveOriginalStrategy()

    def _create_metadata_strategy(self, config: Dict[str, Any]) -> MetadataStrategy:
        """Factory method to create metadata strategy."""
        chunk_metadata = config.get('field_chunking', {}).get('chunk_metadata', {})

        if chunk_metadata.get('add_chunk_info', False):
            return EnhancedMetadataStrategy(
                chunk_metadata, config.get('tokenizer_model', 'cl100k_base')
            )
        else:
            return BasicMetadataStrategy()

    def chunk_record(self, record: Dict[str, Any], analysis: FieldAnalysisResult) -> List[Dict[str, Any]]:
        """
        Chunk a record by processing each field separately (not cartesian product).

        For a record with multiple large fields, this creates separate chunks for each field
        instead of creating all possible combinations.

        Example:
            Record with page_content (3 chunks) and description (2 chunks)
            Creates: 3 + 2 = 5 records (not 3 × 2 = 6 records)
        """
        all_chunks = []

        for field_name in analysis.fields_to_chunk:
            try:
                field_value = record.get(field_name, '')
                fallback_msg = None

                # Apply truncation if needed using fallback strategy
                if len(field_value) > self.truncate_at:
                    field_value, fallback_msg = self.fallback_strategy.apply_truncation(
                        field_value, field_name, self.truncate_at
                    )

                # Chunk the field
                chunks = self.chunk_field(field_value, field_name)

                # Handle excessive chunks using fallback strategy
                if len(chunks) > self.max_chunks_per_record:
                    chunks, fallback_msg = self.fallback_strategy.apply_excessive_chunks(
                        chunks, field_name, self.max_chunks_per_record
                    )

                # Create chunk records
                for idx, chunk in enumerate(chunks, 1):
                    chunked_record = record.copy()
                    chunked_record[field_name] = chunk

                    # Create metadata using metadata strategy
                    context = MetadataContext(
                        record=record,
                        field_name=field_name,
                        field_value=field_value,
                        chunk=chunk,
                        chunk_index=idx,
                        total_chunks=len(chunks),
                    )
                    chunk_info = self.metadata_strategy.create_metadata(context)

                    # Add fallback message if applicable
                    if fallback_msg:
                        chunk_info['fallback_applied'] = fallback_msg

                    # Handle special metadata fields that should be at record level
                    chunk_id_field = self.chunk_metadata.get('chunk_id_field')
                    parent_id_field = self.chunk_metadata.get('original_record_id')
                    if chunk_id_field and chunk_id_field in chunk_info:
                        chunked_record[chunk_id_field] = chunk_info.pop(chunk_id_field)
                    if parent_id_field and parent_id_field in chunk_info:
                        chunked_record[parent_id_field] = chunk_info.pop(parent_id_field)

                    chunked_record['chunk_info'] = chunk_info
                    all_chunks.append(chunked_record)

            except Exception as e:
                fallback_result = self.fallback_strategy.handle_error(
                    record, field_name, str(e)
                )
                if fallback_result:
                    all_chunks.extend(fallback_result)

        return all_chunks

    def chunk_field(self, field_value: str, field_name: str = None) -> List[str]:
        """Chunk a specific field value using field-specific or global rules."""
        if not field_value:
            return ['']

        # Get field-specific rules or use defaults
        field_rule = self.field_rules.get(field_name, {}) if field_name else {}
        chunk_size = field_rule.get('chunk_size', self.chunk_size)
        overlap = field_rule.get('overlap', self.overlap)

        # Use field-specific strategy if specified, otherwise use default
        if field_name and 'split_method' in field_rule:
            strategy = self._create_chunking_strategy(
                {
                    'split_method': field_rule['split_method'],
                    'tokenizer_model': field_rule.get(
                        'tokenizer_model', self.tokenizer_model
                    ),
                }
            )
        else:
            strategy = self.chunking_strategy

        return strategy.chunk(field_value, chunk_size, overlap)