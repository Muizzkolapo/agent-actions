from __future__ import annotations

"""Utility classes for field-level chunking of structured data."""

from dataclasses import dataclass, field
from typing import Dict, List, Any

from agent_actions.common.transformers.string_transformer import Tokenizer


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
        field_chunking = chunk_config.get("field_chunking", {})
        self.chunk_fields = field_chunking.get("chunk_fields", [])
        self.preserve_fields = field_chunking.get("preserve_fields", [])
        self.chunk_threshold = field_chunking.get("chunk_threshold", 0)
        self.tokenizer_model = chunk_config.get("tokenizer_model", "cl100k_base")

    def analyze_record(self, record: Dict[str, Any]) -> FieldAnalysisResult:
        result = FieldAnalysisResult()
        for field_name, value in record.items():
            if not isinstance(value, str):
                continue
            token_count = Tokenizer.num_tokens_from_string(value, self.tokenizer_model)
            result.field_sizes[field_name] = token_count
            if self.should_chunk_field(field_name, token_count):
                result.fields_to_chunk.append(field_name)
        return result

    def should_chunk_field(self, field_name: str, token_count: int) -> bool:
        if self.chunk_fields and field_name not in self.chunk_fields:
            return False
        if field_name in self.preserve_fields:
            return False
        return token_count > self.chunk_threshold


class FieldChunker:
    """Chunk specific fields within structured records."""

    def __init__(self, chunk_config: Dict[str, Any]):
        self.chunk_config = chunk_config
        self.field_chunking = chunk_config.get("field_chunking", {})
        self.chunk_size = chunk_config.get("chunk_size", 1000)
        self.overlap = chunk_config.get("overlap", 200)
        self.tokenizer_model = chunk_config.get("tokenizer_model", "cl100k_base")
        self.split_method = chunk_config.get("split_method", "tiktoken")

    def chunk_record(self, record: Dict[str, Any], analysis: FieldAnalysisResult) -> List[Dict[str, Any]]:
        records = [record]
        for field_name in analysis.fields_to_chunk:
            new_records: List[Dict[str, Any]] = []
            for rec in records:
                field_value = rec.get(field_name, "")
                chunks = self.chunk_field(field_value)
                total_chunks = len(chunks)
                for idx, chunk in enumerate(chunks, 1):
                    new_rec = {**rec, field_name: chunk}
                    chunk_info = {
                        "source_field": field_name,
                        "chunk_index": idx,
                        "total_chunks": total_chunks,
                    }
                    if "chunk_info" in new_rec:
                        # Append for multiple chunked fields
                        if isinstance(new_rec["chunk_info"], list):
                            new_rec["chunk_info"].append(chunk_info)
                        else:
                            new_rec["chunk_info"] = [new_rec["chunk_info"], chunk_info]
                    else:
                        new_rec["chunk_info"] = [chunk_info]
                    new_records.append(new_rec)
            records = new_records
        return records

    def chunk_field(self, field_value: str) -> List[str]:
        if not field_value:
            return [""]
        return Tokenizer.split_text_content(
            field_value,
            self.chunk_size,
            self.overlap,
            tokenizer_model=self.tokenizer_model,
            split_method=self.split_method,
        )
