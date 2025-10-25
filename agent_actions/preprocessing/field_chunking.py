from __future__ import annotations
'Utility classes for field-level chunking of structured data.'
from dataclasses import dataclass, field
from typing import Dict, List, Any
from agent_actions.preprocessing.string_transformer import Tokenizer

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
        self._validate_config()

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

    def _matches_pattern(self, field_name: str, pattern: str) -> bool:
        """Check if field name matches a pattern with wildcards."""
        import re
        regex_pattern = pattern.replace('*', '.*')
        return re.fullmatch(regex_pattern, field_name) is not None

    def _validate_config(self) -> None:
        """Validate field chunking configuration."""
        errors = []
        if self.chunk_fields and self.preserve_fields:
            conflicting_fields = set(self.chunk_fields) & set(self.preserve_fields)
            if conflicting_fields:
                errors.append(f'Fields cannot be both chunked and preserved: {sorted(conflicting_fields)}')
        if self.chunk_threshold < 0:
            errors.append('chunk_threshold must be non-negative')
        field_chunking = self.chunk_config.get('field_chunking', {})
        if field_chunking.get('enabled') and (not self.chunk_fields) and (not self.auto_detect_enabled):
            errors.append('chunk_fields must be specified when field_chunking is enabled and auto_detection is disabled')
        if self.field_rules:
            for field_name, field_rule in self.field_rules.items():
                if not isinstance(field_rule, dict):
                    errors.append(f'field_rules[{field_name}] must be a dictionary')
                    continue
                if 'chunk_size' in field_rule and field_rule['chunk_size'] <= 0:
                    errors.append(f'field_rules[{field_name}].chunk_size must be positive')
                if 'overlap' in field_rule and field_rule['overlap'] < 0:
                    errors.append(f'field_rules[{field_name}].overlap cannot be negative')
                if 'chunk_threshold' in field_rule and field_rule['chunk_threshold'] < 0:
                    errors.append(f'field_rules[{field_name}].chunk_threshold must be non-negative')
                chunk_size = field_rule.get('chunk_size', 1000)
                overlap = field_rule.get('overlap', 0)
                if overlap >= chunk_size:
                    errors.append(f'field_rules[{field_name}].overlap must be smaller than chunk_size')
        if errors:
            raise FieldChunkingValidationError(f"Invalid field chunking configuration: {'; '.join(errors)}")

class FieldChunker:
    """Chunk specific fields within structured records."""

    def __init__(self, chunk_config: Dict[str, Any]):
        self.chunk_config = chunk_config
        self.field_chunking = chunk_config.get('field_chunking', {})
        self.chunk_size = chunk_config.get('chunk_size', 1000)
        self.overlap = chunk_config.get('overlap', 200)
        self.tokenizer_model = chunk_config.get('tokenizer_model', 'cl100k_base')
        self.split_method = chunk_config.get('split_method', 'tiktoken')
        self.fallback_strategy = self.field_chunking.get('fallback_strategy', 'preserve_original')
        self.max_chunks_per_record = self.field_chunking.get('max_chunks_per_record', 100)
        self.truncate_at = self.field_chunking.get('truncate_at', 50000)
        self.field_rules = self.field_chunking.get('field_rules', {})
        self.chunk_metadata = self.field_chunking.get('chunk_metadata', {})
        self._validate_config()

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
        total_chunks_count = 0
        for field_name in analysis.fields_to_chunk:
            try:
                field_value = record.get(field_name, '')
                if len(field_value) > self.truncate_at:
                    field_value = self._apply_truncation_fallback(field_value, field_name)
                chunks = self.chunk_field(field_value, field_name)
                if len(chunks) > self.max_chunks_per_record:
                    chunks = self._apply_excessive_chunks_fallback(chunks, field_name)
                total_chunks_count += len(chunks)
                for idx, chunk in enumerate(chunks, 1):
                    chunked_record = record.copy()
                    chunked_record[field_name] = chunk
                    chunk_info = {'source_field': field_name, 'chunk_index': idx, 'total_chunks': len(chunks)}
                    if self._should_add_enhanced_metadata():
                        enhanced_metadata = self._create_enhanced_metadata(record, field_name, field_value, chunk, idx)
                        chunk_id_field = self.chunk_metadata.get('chunk_id_field')
                        parent_id_field = self.chunk_metadata.get('original_record_id')
                        if chunk_id_field and chunk_id_field in enhanced_metadata:
                            chunked_record[chunk_id_field] = enhanced_metadata.pop(chunk_id_field)
                        if parent_id_field and parent_id_field in enhanced_metadata:
                            chunked_record[parent_id_field] = enhanced_metadata.pop(parent_id_field)
                        chunk_info.update(enhanced_metadata)
                    if hasattr(self, '_last_fallback_applied'):
                        chunk_info['fallback_applied'] = self._last_fallback_applied
                        delattr(self, '_last_fallback_applied')
                    chunked_record['chunk_info'] = chunk_info
                    all_chunks.append(chunked_record)
            except Exception as e:
                fallback_result = self._handle_chunking_error(record, field_name, str(e))
                if fallback_result:
                    all_chunks.extend(fallback_result)
        return all_chunks

    def chunk_field(self, field_value: str, field_name: str=None) -> List[str]:
        """Chunk a specific field value using field-specific or global rules."""
        if not field_value:
            return ['']
        field_rule = self.field_rules.get(field_name, {}) if field_name else {}
        chunk_size = field_rule.get('chunk_size', self.chunk_size)
        overlap = field_rule.get('overlap', self.overlap)
        tokenizer_model = field_rule.get('tokenizer_model', self.tokenizer_model)
        split_method = field_rule.get('split_method', self.split_method)
        return Tokenizer.split_text_content(field_value, chunk_size, overlap, tokenizer_model=tokenizer_model, split_method=split_method)

    def _validate_config(self) -> None:
        """Validate chunking configuration."""
        errors = []
        if self.chunk_size <= 0:
            errors.append('chunk_size must be positive')
        if self.overlap < 0:
            errors.append('overlap cannot be negative')
        if self.overlap >= self.chunk_size:
            errors.append('overlap must be smaller than chunk_size')
        if not isinstance(self.tokenizer_model, str) or not self.tokenizer_model.strip():
            errors.append('tokenizer_model must be a non-empty string')
        valid_split_methods = ['tiktoken', 'chars', 'spacy']
        if self.split_method not in valid_split_methods:
            if not isinstance(self.split_method, str) or not self.split_method.strip():
                errors.append(f'split_method must be a non-empty string, preferably one of: {valid_split_methods}')
        if errors:
            raise FieldChunkingValidationError(f"Invalid chunk configuration: {'; '.join(errors)}")

    def _apply_truncation_fallback(self, field_value: str, field_name: str) -> str:
        """Apply truncation fallback for overly large fields."""
        if self.fallback_strategy == 'truncate':
            self._last_fallback_applied = f'truncated_{field_name}_at_{self.truncate_at}'
            return field_value[:self.truncate_at]
        elif self.fallback_strategy == 'preserve_original':
            self._last_fallback_applied = f'preserved_large_{field_name}'
            return field_value
        else:
            return field_value

    def _apply_excessive_chunks_fallback(self, chunks: List[str], field_name: str) -> List[str]:
        """Apply fallback for fields that generate too many chunks."""
        if self.fallback_strategy == 'truncate':
            self._last_fallback_applied = f'limited_chunks_{field_name}_to_{self.max_chunks_per_record}'
            return chunks[:self.max_chunks_per_record]
        elif self.fallback_strategy == 'preserve_original':
            self._last_fallback_applied = f'preserved_excessive_chunks_{field_name}'
            return chunks
        else:
            return chunks

    def _should_add_enhanced_metadata(self) -> bool:
        """Check if enhanced metadata should be added."""
        return self.chunk_metadata.get('add_chunk_info', False)

    def _create_enhanced_metadata(self, record: Dict[str, Any], field_name: str, field_value: str, chunk: str, chunk_index: int) -> Dict[str, Any]:
        """Create enhanced metadata for a chunk."""
        metadata = {}
        if self.chunk_metadata.get('chunk_id_field'):
            original_id = record.get('id', 'unknown')
            chunk_id = f'{original_id}_{field_name}_{chunk_index}'
            metadata[self.chunk_metadata['chunk_id_field']] = chunk_id
        if self.chunk_metadata.get('original_record_id'):
            original_id = record.get('id')
            if original_id:
                metadata[self.chunk_metadata['original_record_id']] = original_id
        if self.chunk_metadata.get('add_char_positions', False):
            chunk_size_chars = len(chunk)
            estimated_start = (chunk_index - 1) * chunk_size_chars
            metadata.update({'chunk_start_char': max(0, estimated_start), 'chunk_end_char': estimated_start + chunk_size_chars, 'chunk_size_chars': chunk_size_chars, 'original_field_size_chars': len(field_value)})
        if self.chunk_metadata.get('add_token_counts', False):
            from agent_actions.preprocessing.string_transformer import Tokenizer
            chunk_tokens = Tokenizer.num_tokens_from_string(chunk, self.tokenizer_model)
            original_tokens = Tokenizer.num_tokens_from_string(field_value, self.tokenizer_model)
            metadata.update({'chunk_size_tokens': chunk_tokens, 'original_field_size_tokens': original_tokens})
        return metadata

    def _handle_chunking_error(self, record: Dict[str, Any], field_name: str, error_msg: str) -> List[Dict[str, Any]]:
        """Handle chunking errors based on fallback strategy."""
        if self.fallback_strategy == 'preserve_original':
            error_record = record.copy()
            error_record['chunk_info'] = {'source_field': field_name, 'chunk_index': 1, 'total_chunks': 1, 'chunking_error': error_msg, 'fallback_applied': 'preserve_original_on_error'}
            return [error_record]
        elif self.fallback_strategy == 'skip':
            return []
        elif self.fallback_strategy == 'error':
            raise FieldChunkingError(f"Failed to chunk field '{field_name}': {error_msg}")
        else:
            error_record = record.copy()
            error_record['chunk_info'] = {'source_field': field_name, 'chunk_index': 1, 'total_chunks': 1, 'chunking_error': error_msg, 'fallback_applied': 'preserve_original_on_error'}
            return [error_record]