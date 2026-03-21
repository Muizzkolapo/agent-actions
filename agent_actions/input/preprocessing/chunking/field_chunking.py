"""Field-level chunking of structured data."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from agent_actions.input.preprocessing.chunking.strategies.chunking_strategies import (
    CharBasedChunkingStrategy,
    ChunkingStrategy,
    SpacyChunkingStrategy,
    TiktokenChunkingStrategy,
)
from agent_actions.input.preprocessing.chunking.strategies.fallback_strategies import (
    ErrorStrategy,
    FallbackStrategy,
    PreserveOriginalStrategy,
    SkipStrategy,
    TruncateStrategy,
)
from agent_actions.input.preprocessing.chunking.strategies.metadata_strategies import (
    BasicMetadataStrategy,
    EnhancedMetadataStrategy,
    MetadataContext,
    MetadataStrategy,
)
from agent_actions.input.preprocessing.chunking.strategies.validation import ConfigValidator
from agent_actions.input.preprocessing.transformation.string_transformer import Tokenizer
from agent_actions.output.response.config_fields import get_default


@dataclass
class FieldAnalysisResult:
    """Result from analysing a record for chunking needs."""

    fields_to_chunk: list[str] = field(default_factory=list)
    field_sizes: dict[str, int] = field(default_factory=dict)

    @property
    def requires_chunking(self) -> bool:
        """Return True if any fields require chunking."""
        return bool(self.fields_to_chunk)


@dataclass
class AnalyzerConfig:
    """Configuration for field analyzer."""

    chunk_fields: list[str] = field(default_factory=list)
    preserve_fields: list[str] = field(default_factory=list)
    chunk_threshold: int = 0
    tokenizer_model: str = "cl100k_base"
    field_rules: dict[str, Any] = field(default_factory=dict)
    auto_detect_enabled: bool = False


class FieldAnalyzer:
    """Analyzes structured records to determine which fields need chunking."""

    def __init__(self, chunk_config: dict[str, Any]):
        field_chunking = chunk_config.get("field_chunking", {})
        auto_detection = field_chunking.get("auto_detection", {})

        self.config = AnalyzerConfig(
            chunk_fields=field_chunking.get("chunk_fields", []),
            preserve_fields=field_chunking.get("preserve_fields", []),
            chunk_threshold=field_chunking.get("chunk_threshold", 0),
            tokenizer_model=chunk_config.get("tokenizer_model", get_default("tokenizer_model")),
            field_rules=field_chunking.get("field_rules", {}),
            auto_detect_enabled=auto_detection.get("enabled", False),
        )
        ConfigValidator.validate_field_analyzer_config(chunk_config)

    def _determine_fields_to_analyze(self, record: dict[str, Any]) -> Iterable[str]:
        """Determine which fields should be analyzed for chunking."""
        if self.config.chunk_fields:
            return self.config.chunk_fields
        if self.config.auto_detect_enabled:
            return self.detect_text_fields(record)
        return record.keys()

    def _should_analyze_field(self, field_name: str, record: dict[str, Any]) -> bool:
        """Check if a field should be analyzed (exists, is string, not preserved)."""
        if field_name not in record:
            return False
        if not isinstance(record[field_name], str):
            return False
        return field_name not in self.config.preserve_fields

    def analyze_record(self, record: dict[str, Any]) -> FieldAnalysisResult:
        """Analyze a record to determine which fields need chunking."""
        result = FieldAnalysisResult()
        for field_name in self._determine_fields_to_analyze(record):
            if not self._should_analyze_field(field_name, record):
                continue
            token_count = Tokenizer.num_tokens_from_string(
                record[field_name], self.config.tokenizer_model
            )
            result.field_sizes[field_name] = token_count
            if self.should_chunk_field(field_name, token_count):
                result.fields_to_chunk.append(field_name)
        return result

    def should_chunk_field(self, field_name: str, token_count: int) -> bool:
        """Return True if the field should be chunked based on token count and rules."""
        if field_name in self.config.preserve_fields:
            return False
        if self.config.chunk_fields and field_name not in self.config.chunk_fields:
            return False
        field_rule = self.config.field_rules.get(field_name, {})
        threshold: int = field_rule.get("chunk_threshold", self.config.chunk_threshold)
        return token_count > threshold

    def detect_text_fields(self, record: dict[str, Any]) -> list[str]:
        """Return all string fields that could potentially need chunking."""
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

    record: dict[str, Any]
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
    field_rules: dict[str, Any] = field(default_factory=dict)
    chunk_metadata: dict[str, Any] = field(default_factory=dict)


class FieldChunker:
    """Chunk specific fields within structured records."""

    def __init__(self, chunk_config: dict[str, Any]):
        self.chunk_config = chunk_config
        field_chunking = chunk_config.get("field_chunking", {})

        self.config = ChunkerConfig(
            chunk_size=chunk_config.get("chunk_size", get_default("chunk_size")),
            overlap=chunk_config.get("overlap", get_default("chunk_overlap")),
            tokenizer_model=chunk_config.get("tokenizer_model", get_default("tokenizer_model")),
            max_chunks_per_record=field_chunking.get("max_chunks_per_record", 100),
            truncate_at=field_chunking.get("truncate_at", 50000),
            field_rules=field_chunking.get("field_rules", {}),
            chunk_metadata=field_chunking.get("chunk_metadata", {}),
        )

        self.chunking_strategy = self._create_chunking_strategy(chunk_config)
        self.fallback_strategy = self._create_fallback_strategy(chunk_config)
        self.metadata_strategy = self._create_metadata_strategy(chunk_config)
        ConfigValidator.validate_field_chunker_config(chunk_config)

    def _create_chunking_strategy(self, config: dict[str, Any]) -> ChunkingStrategy:
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

    def _create_fallback_strategy(self, config: dict[str, Any]) -> FallbackStrategy:
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

    def _create_metadata_strategy(self, config: dict[str, Any]) -> MetadataStrategy:
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

    def _prepare_chunk_list(self, chunk_list: list[str], field_name: str, fallback_msg: str):
        """Prepare chunk list by handling excessive chunk count."""
        if len(chunk_list) > self.config.max_chunks_per_record:
            chunk_list, fallback_msg = self.fallback_strategy.handle_excessive_chunk_count(
                chunk_list, field_name, self.config.max_chunks_per_record
            )
        return chunk_list, fallback_msg

    def _create_chunk_metadata(self, params: ChunkMetadataParams) -> dict[str, Any]:
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
        record: dict[str, Any],
        field_name: str,
        chunk_text: str,
        chunk_metadata_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a single chunked record with metadata."""
        chunked_record = record.copy()
        chunked_record[field_name] = chunk_text

        self._extract_special_metadata(chunked_record, chunk_metadata_info)

        chunked_record["chunk_info"] = chunk_metadata_info
        return chunked_record

    def _extract_special_metadata(
        self, chunked_record: dict[str, Any], chunk_metadata_info: dict[str, Any]
    ):
        """Extract special metadata fields to record level."""
        chunk_id_field = self.config.chunk_metadata.get("chunk_id_field")
        parent_id_field = self.config.chunk_metadata.get("original_record_id")

        if chunk_id_field and chunk_id_field in chunk_metadata_info:
            chunked_record[chunk_id_field] = chunk_metadata_info.pop(chunk_id_field)

        if parent_id_field and parent_id_field in chunk_metadata_info:
            chunked_record[parent_id_field] = chunk_metadata_info.pop(parent_id_field)

    def chunk_record(
        self, record: dict[str, Any], analysis: FieldAnalysisResult
    ) -> list[dict[str, Any]]:
        """Chunk a record by processing each field separately (additive, not cartesian product)."""
        all_chunks = []

        for field_name in analysis.fields_to_chunk:
            try:
                field_value = record.get(field_name, "")

                field_value, fallback_msg = self._prepare_field_value(field_value, field_name)
                chunk_list = self.chunk_field(field_value, field_name)
                chunk_list, fallback_msg = self._prepare_chunk_list(
                    chunk_list, field_name, fallback_msg
                )

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

    def chunk_field(self, field_value: str, field_name: str | None = None) -> list[str]:
        """Chunk a specific field value using field-specific or global rules."""
        if not field_value:
            return [""]

        field_rule = self.config.field_rules.get(field_name, {}) if field_name else {}
        chunk_size = field_rule.get("chunk_size", self.config.chunk_size)
        overlap = field_rule.get("overlap", self.config.overlap)

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
