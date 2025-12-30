"""Utility classes for field-level chunking of structured data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any

from agent_actions.preprocessing.transformation.string_transformer import Tokenizer
from agent_actions.preprocessing.chunking.strategies.chunking_strategies import (
    ChunkingStrategy,
    TiktokenChunkingStrategy,
    CharBasedChunkingStrategy,
    SpacyChunkingStrategy,
)
from agent_actions.preprocessing.chunking.strategies.fallback_strategies import (
    FallbackStrategy,
    PreserveOriginalStrategy,
    TruncateStrategy,
    SkipStrategy,
    ErrorStrategy,
)
from agent_actions.preprocessing.chunking.strategies.metadata_strategies import (
    MetadataStrategy,
    MetadataContext,
    BasicMetadataStrategy,
    EnhancedMetadataStrategy,
)
from agent_actions.preprocessing.chunking.strategies.validation import ConfigValidator


class FieldChunkingValidationError(ValueError):
    """Raised when field chunking configuration is invalid."""


class FieldChunkingError(Exception):
    """Raised when field chunking operations fail."""


@dataclass
class FieldAnalysisResult:
    """Result from analysing a record for chunking needs."""

    fields_to_chunk: List[str] = field(default_factory=list)
    field_sizes: Dict[str, int] = field(default_factory=dict)

    @property
    def requires_chunking(self) -> bool:
        """Return True if any fields require chunking."""
        return bool(self.fields_to_chunk)


@dataclass
class AnalyzerConfig:
    """Configuration for field analyzer."""

    chunk_fields: List[str] = field(default_factory=list)
    preserve_fields: List[str] = field(default_factory=list)
    chunk_threshold: int = 0
    tokenizer_model: str = "cl100k_base"
    field_rules: Dict[str, Any] = field(default_factory=dict)
    auto_detect_enabled: bool = False


class FieldAnalyzer:
    """Analyse structured records to determine which fields need chunking."""

    def __init__(self, chunk_config: Dict[str, Any]):
        field_chunking = chunk_config.get("field_chunking", {})
        auto_detection = field_chunking.get("auto_detection", {})

        self.config = AnalyzerConfig(
            chunk_fields=field_chunking.get("chunk_fields", []),
            preserve_fields=field_chunking.get("preserve_fields", []),
            chunk_threshold=field_chunking.get("chunk_threshold", 0),
            tokenizer_model=chunk_config.get("tokenizer_model", "cl100k_base"),
            field_rules=field_chunking.get("field_rules", {}),
            auto_detect_enabled=auto_detection.get("enabled", False),
        )
        ConfigValidator.validate_field_analyzer_config(chunk_config)

    def analyze_record(self, record: Dict[str, Any]) -> FieldAnalysisResult:
        """
        Analyze a record to determine which fields need chunking.

        Args:
            record: Dictionary containing record data to analyze

        Returns:
            FieldAnalysisResult with fields that require chunking
        """
        result = FieldAnalysisResult()
        if self.config.chunk_fields:
            fields_to_analyze = self.config.chunk_fields
        elif self.config.auto_detect_enabled:
            fields_to_analyze = self.detect_text_fields(record)
        else:
            fields_to_analyze = record.keys()
        for field_name in fields_to_analyze:
            if field_name not in record:
                continue
            value = record[field_name]
            if not isinstance(value, str):
                continue
            if field_name in self.config.preserve_fields:
                continue
            token_count = Tokenizer.num_tokens_from_string(value, self.config.tokenizer_model)
            result.field_sizes[field_name] = token_count
            if self.should_chunk_field(field_name, token_count):
                result.fields_to_chunk.append(field_name)
        return result

    def should_chunk_field(self, field_name: str, token_count: int) -> bool:
        """
        Determine if a field should be chunked based on token count and rules.

        Args:
            field_name: Name of the field to check
            token_count: Token count of the field content

        Returns:
            True if field should be chunked, False otherwise
        """
        if field_name in self.config.preserve_fields:
            return False
        if self.config.chunk_fields and field_name not in self.config.chunk_fields:
            return False
        field_rule = self.config.field_rules.get(field_name, {})
        threshold = field_rule.get("chunk_threshold", self.config.chunk_threshold)
        return token_count > threshold

    def detect_text_fields(self, record: Dict[str, Any]) -> List[str]:
        """
        Automatically detect text fields based on content size.

        Returns all string fields that could potentially need chunking.
        The actual chunking decision is made by should_chunk_field() based on token count.
        """
        if not self.config.auto_detect_enabled:
            return []
        detected_fields = []
        for field_name, value in record.items():
            if not isinstance(value, str):
                continue
            if field_name in self.config.preserve_fields:
                continue
            detected_fields.append(field_name)
        return detected_fields


@dataclass
class ChunkMetadataParams:
    """Parameters for creating chunk metadata."""

    record: Dict[str, Any]
    field_name: str
    field_value: str
    chunk_text: str
    chunk_index: int
    total_chunks: int
    fallback_msg: str


@dataclass
class ChunkerConfig:
    """Configuration for field chunker."""

    chunk_size: int = 1000
    overlap: int = 200
    tokenizer_model: str = "cl100k_base"
    max_chunks_per_record: int = 100
    truncate_at: int = 50000
    field_rules: Dict[str, Any] = field(default_factory=dict)
    chunk_metadata: Dict[str, Any] = field(default_factory=dict)


class FieldChunker:
    """Chunk specific fields within structured records."""

    def __init__(self, chunk_config: Dict[str, Any]):
        self.chunk_config = chunk_config
        field_chunking = chunk_config.get("field_chunking", {})

        # Extract configuration into structured config object
        self.config = ChunkerConfig(
            chunk_size=chunk_config.get("chunk_size", 1000),
            overlap=chunk_config.get("overlap", 200),
            tokenizer_model=chunk_config.get("tokenizer_model", "cl100k_base"),
            max_chunks_per_record=field_chunking.get("max_chunks_per_record", 100),
            truncate_at=field_chunking.get("truncate_at", 50000),
            field_rules=field_chunking.get("field_rules", {}),
            chunk_metadata=field_chunking.get("chunk_metadata", {}),
        )

        # Initialize strategies
        self.chunking_strategy = self._create_chunking_strategy(chunk_config)
        self.fallback_strategy = self._create_fallback_strategy(chunk_config)
        self.metadata_strategy = self._create_metadata_strategy(chunk_config)

        # Validate configuration
        ConfigValidator.validate_field_chunker_config(chunk_config)

    def _create_chunking_strategy(self, config: Dict[str, Any]) -> ChunkingStrategy:
        """Factory method to create chunking strategy."""
        split_method = config.get("split_method", "tiktoken")
        tokenizer_model = config.get("tokenizer_model", "cl100k_base")

        if split_method == "tiktoken":
            return TiktokenChunkingStrategy(tokenizer_model)
        if split_method == "chars":
            return CharBasedChunkingStrategy()
        if split_method == "spacy":
            return SpacyChunkingStrategy()
        return TiktokenChunkingStrategy(tokenizer_model)

    def _create_fallback_strategy(self, config: Dict[str, Any]) -> FallbackStrategy:
        """Factory method to create fallback strategy."""
        strategy_name = config.get("field_chunking", {}).get(
            "fallback_strategy", "preserve_original"
        )

        if strategy_name == "preserve_original":
            return PreserveOriginalStrategy()
        if strategy_name == "truncate":
            return TruncateStrategy()
        if strategy_name == "skip":
            return SkipStrategy()
        if strategy_name == "error":
            return ErrorStrategy()
        return PreserveOriginalStrategy()

    def _create_metadata_strategy(self, config: Dict[str, Any]) -> MetadataStrategy:
        """Factory method to create metadata strategy."""
        chunk_metadata = config.get("field_chunking", {}).get("chunk_metadata", {})

        if chunk_metadata.get("add_chunk_info", False):
            return EnhancedMetadataStrategy(chunk_metadata, self.config.tokenizer_model)
        return BasicMetadataStrategy()

    def _prepare_field_value(self, field_value: str, field_name: str):
        """Prepare field value by handling oversized fields."""
        fallback_message = None
        if len(field_value) > self.config.truncate_at:
            field_value, fallback_message = self.fallback_strategy.handle_oversized_field(
                field_value, field_name, self.config.truncate_at
            )
        return field_value, fallback_message

    def _prepare_chunk_list(self, chunk_list: List[str], field_name: str, fallback_msg: str):
        """Prepare chunk list by handling excessive chunk count."""
        if len(chunk_list) > self.config.max_chunks_per_record:
            chunk_list, fallback_msg = self.fallback_strategy.handle_excessive_chunk_count(
                chunk_list, field_name, self.config.max_chunks_per_record
            )
        return chunk_list, fallback_msg

    def _create_chunk_metadata(self, params: ChunkMetadataParams) -> Dict[str, Any]:
        """Create metadata for a chunk."""
        metadata_context = MetadataContext(
            record=params.record,
            field_name=params.field_name,
            field_value=params.field_value,
            chunk=params.chunk_text,
            chunk_index=params.chunk_index,
            total_chunks=params.total_chunks,
        )
        chunk_metadata_info = self.metadata_strategy.create_metadata(metadata_context)

        if params.fallback_msg:
            chunk_metadata_info["fallback_applied"] = params.fallback_msg

        return chunk_metadata_info

    def _create_chunked_record(
        self,
        record: Dict[str, Any],
        field_name: str,
        chunk_text: str,
        chunk_metadata_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a single chunked record with metadata."""
        chunked_record = record.copy()
        chunked_record[field_name] = chunk_text

        # Extract special metadata fields to record level
        self._extract_special_metadata(chunked_record, chunk_metadata_info)

        chunked_record["chunk_info"] = chunk_metadata_info
        return chunked_record

    def _extract_special_metadata(
        self, chunked_record: Dict[str, Any], chunk_metadata_info: Dict[str, Any]
    ):
        """Extract special metadata fields to record level."""
        chunk_id_field = self.config.chunk_metadata.get("chunk_id_field")
        parent_id_field = self.config.chunk_metadata.get("original_record_id")

        if chunk_id_field and chunk_id_field in chunk_metadata_info:
            chunked_record[chunk_id_field] = chunk_metadata_info.pop(chunk_id_field)

        if parent_id_field and parent_id_field in chunk_metadata_info:
            chunked_record[parent_id_field] = chunk_metadata_info.pop(parent_id_field)

    def chunk_record(
        self, record: Dict[str, Any], analysis: FieldAnalysisResult
    ) -> List[Dict[str, Any]]:
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
                field_value = record.get(field_name, "")

                # Prepare field value (handle oversized fields)
                field_value, fallback_msg = self._prepare_field_value(field_value, field_name)

                # Chunk the field into smaller pieces
                chunk_list = self.chunk_field(field_value, field_name)

                # Handle excessive chunk count
                chunk_list, fallback_msg = self._prepare_chunk_list(
                    chunk_list, field_name, fallback_msg
                )

                # Create individual chunk records
                for chunk_index, chunk_text in enumerate(chunk_list, 1):
                    metadata_params = ChunkMetadataParams(
                        record=record,
                        field_name=field_name,
                        field_value=field_value,
                        chunk_text=chunk_text,
                        chunk_index=chunk_index,
                        total_chunks=len(chunk_list),
                        fallback_msg=fallback_msg,
                    )
                    chunk_metadata_info = self._create_chunk_metadata(metadata_params)
                    chunked_record = self._create_chunked_record(
                        record, field_name, chunk_text, chunk_metadata_info
                    )
                    all_chunks.append(chunked_record)

            except (ValueError, TypeError, KeyError, AttributeError) as exception:
                error_fallback_result = self.fallback_strategy.handle_chunking_error(
                    record, field_name, str(exception)
                )
                if error_fallback_result:
                    all_chunks.extend(error_fallback_result)

        return all_chunks

    def chunk_field(self, field_value: str, field_name: str = None) -> List[str]:
        """Chunk a specific field value using field-specific or global rules."""
        if not field_value:
            return [""]

        # Get field-specific rules or use defaults
        field_rule = self.config.field_rules.get(field_name, {}) if field_name else {}
        chunk_size = field_rule.get("chunk_size", self.config.chunk_size)
        overlap = field_rule.get("overlap", self.config.overlap)

        # Use field-specific chunking strategy if specified, otherwise use default
        if field_name and "split_method" in field_rule:
            field_specific_strategy = self._create_chunking_strategy(
                {
                    "split_method": field_rule["split_method"],
                    "tokenizer_model": field_rule.get(
                        "tokenizer_model", self.config.tokenizer_model
                    ),
                }
            )
        else:
            field_specific_strategy = self.chunking_strategy

        return field_specific_strategy.split_text_into_chunks(field_value, chunk_size, overlap)
