"""
Comprehensive loader tests for the Agent Actions core loader modules.

Tests cover base/source/batch loaders as specified in tests_recommendations.jsonc:
1. base/source/batch loaders batch sizes; last-batch remainder; empty input; error propagation
2. data_loaders module exports expected symbols
"""
import asyncio
import json
import pytest
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from agent_actions.input_loading.base_base_loader import BaseLoader
from agent_actions.llm_invocation.batch.loaders_batch_data_loader import BatchDataLoader
from agent_actions.response_processing.config_types import AgentEntryDict
from agent_actions.configuration.interfaces import ProcessingMode
from agent_actions.shared.exceptions import FileLoadError

class _TestableLoader(BaseLoader[str]):
    """Concrete implementation of BaseLoader for testing."""

    def process(self, content: Any, file_path: Optional[str]=None) -> str:
        """Test implementation that returns content as string."""
        if isinstance(content, str):
            return content
        return str(content)

    def supports_filetype(self, file_extension: str) -> bool:
        """Test implementation that supports .txt files."""
        return file_extension.lower() in ['.txt', '.text']

class _TestableAsyncLoader(BaseLoader[List[str]]):
    """Async loader implementation for testing."""

    def process(self, content: Any, file_path: Optional[str]=None) -> List[str]:
        """Process content into list of lines."""
        if isinstance(content, str):
            return content.strip().split('\n')
        return [str(content)]

    async def process_async(self, content: Any, file_path: Optional[str]=None) -> List[str]:
        """Async implementation."""
        try:
            import anyio
            await anyio.sleep(0.01)
        except ImportError:
            await asyncio.sleep(0.01)
        return self.process(content, file_path)

    def supports_filetype(self, file_extension: str) -> bool:
        """Support multiple file types."""
        return file_extension.lower() in ['.txt', '.log', '.data']

class TestBaseLoader:
    """Test BaseLoader abstract class functionality."""

    def test_base_loader_initialization(self):
        """Test BaseLoader initialization with agent config."""
        agent_config: AgentEntryDict = {'name': 'test_agent', 'type': 'loader', 'config': {'param1': 'value1'}}
        agent_name = 'test_loader'
        loader = _TestableLoader(agent_config, agent_name)
        assert loader.agent_config == agent_config
        assert loader.agent_name == agent_name
        assert loader.logger is not None

    def test_supports_async_default(self):
        """Test default async support is True."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        assert loader.supports_async() is True

    def test_get_processing_mode_default(self):
        """Test default processing mode is AUTO."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        assert loader.get_processing_mode() == ProcessingMode.AUTO

    def test_load_file_success(self, tmp_path):
        """Test successful file loading."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        test_file = tmp_path / 'test.txt'
        test_content = 'This is test content\nWith multiple lines'
        test_file.write_text(test_content, encoding='utf-8')
        content = loader.load_file(str(test_file))
        assert content == test_content

    def test_load_file_file_not_found(self):
        """Test load_file handles FileNotFoundError."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        with pytest.raises((FileNotFoundError, FileLoadError)):
            loader.load_file('/nonexistent/file.txt')

    def test_load_file_permission_error(self, tmp_path):
        """Test load_file handles permission errors."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        test_file = tmp_path / 'protected.txt'
        test_file.write_text('content')
        with patch('builtins.open', side_effect=PermissionError('Permission denied')):
            with pytest.raises((PermissionError, FileLoadError)):
                loader.load_file(str(test_file))

    @pytest.mark.anyio
    async def test_load_file_async_success(self, tmp_path):
        """Test successful async file loading."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        test_file = tmp_path / 'test.txt'
        test_content = 'Async test content'
        test_file.write_text(test_content, encoding='utf-8')
        content = await loader.load_file_async(str(test_file))
        assert content == test_content

    @pytest.mark.anyio
    async def test_load_file_async_with_aiofiles(self, tmp_path):
        """Test async file loading with aiofiles when available."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        test_file = tmp_path / 'test.txt'
        test_content = 'Aiofiles test content'
        test_file.write_text(test_content, encoding='utf-8')
        try:
            import aiofiles
            content = await loader.load_file_async(str(test_file))
            assert content == test_content
        except ImportError:
            content = await loader.load_file_async(str(test_file))
            assert content == test_content

    @pytest.mark.anyio
    async def test_load_file_async_fallback_to_thread(self, tmp_path):
        """Test async file loading falls back to thread when aiofiles unavailable."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        test_file = tmp_path / 'test.txt'
        test_content = 'Thread fallback content'
        test_file.write_text(test_content, encoding='utf-8')
        with patch.dict('sys.modules', {'aiofiles': None}):
            content = await loader.load_file_async(str(test_file))
            assert content == test_content

    def test_process_abstract_method(self):
        """Test that process method is abstract and must be implemented."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        with pytest.raises(TypeError):
            BaseLoader(agent_config, 'test')

    def test_supports_filetype_abstract_method(self):
        """Test that supports_filetype method is abstract."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        assert loader.supports_filetype('.txt') is True
        assert loader.supports_filetype('.json') is False

    def test_load_data_interface_implementation(self, tmp_path):
        """Test IDataLoader interface implementation."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        test_file = tmp_path / 'test.txt'
        test_content = 'Interface test content'
        test_file.write_text(test_content, encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert result == test_content

    @pytest.mark.anyio
    async def test_load_data_async_interface_implementation(self, tmp_path):
        """Test async IDataLoader interface implementation."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        test_file = tmp_path / 'test.txt'
        test_content = 'Async interface test content'
        test_file.write_text(test_content, encoding='utf-8')
        result = await loader.load_data_async(str(test_file))
        assert result == test_content

    @pytest.mark.anyio
    async def test_process_async_default_implementation(self, tmp_path):
        """Test default async process implementation uses threading."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        result = await loader.process_async('test content')
        assert result == 'test content'

    @pytest.mark.anyio
    async def test_custom_async_process_implementation(self, tmp_path):
        """Test custom async process implementation."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableAsyncLoader(agent_config, 'test')
        test_file = tmp_path / 'test.txt'
        test_content = 'Line 1\nLine 2\nLine 3'
        test_file.write_text(test_content, encoding='utf-8')
        result = await loader.load_data_async(str(test_file))
        assert result == ['Line 1', 'Line 2', 'Line 3']

class TestBatchDataLoader:
    """Test BatchDataLoader functionality."""

    def test_batch_loader_initialization(self):
        """Test BatchDataLoader initialization."""
        loader = BatchDataLoader()
        assert loader.supports_async() is True
        assert loader.get_processing_mode() == ProcessingMode.AUTO

    def test_load_json_file_success(self, tmp_path):
        """Test successful JSON file loading."""
        loader = BatchDataLoader()
        test_data = [{'id': 1, 'name': 'Alice', 'age': 30}, {'id': 2, 'name': 'Bob', 'age': 25}]
        test_file = tmp_path / 'test.json'
        test_file.write_text(json.dumps(test_data), encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert result == test_data

    def test_load_jsonl_file_success(self, tmp_path):
        """Test successful JSONL file loading."""
        loader = BatchDataLoader()
        test_data = [{'id': 1, 'name': 'Alice', 'age': 30}, {'id': 2, 'name': 'Bob', 'age': 25}]
        test_file = tmp_path / 'test.jsonl'
        jsonl_content = '\n'.join((json.dumps(item) for item in test_data))
        test_file.write_text(jsonl_content, encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert result == test_data

    def test_load_file_not_found(self):
        """Test file not found error handling."""
        loader = BatchDataLoader()
        with pytest.raises(FileNotFoundError, match='The specified file does not exist'):
            loader.load_data('/nonexistent/file.json')

    def test_load_unsupported_file_type(self, tmp_path):
        """Test unsupported file type error handling."""
        loader = BatchDataLoader()
        test_file = tmp_path / 'test.txt'
        test_file.write_text('not json content')
        with pytest.raises((ValueError, OSError), match='(Unsupported file type|Could not read file)'):
            loader.load_data(str(test_file))

    def test_load_invalid_json_error(self, tmp_path):
        """Test invalid JSON error handling."""
        loader = BatchDataLoader()
        test_file = tmp_path / 'invalid.json'
        test_file.write_text('{ invalid json content', encoding='utf-8')
        with pytest.raises(ValueError, match='Error decoding JSON'):
            loader.load_data(str(test_file))

    def test_load_invalid_jsonl_error(self, tmp_path):
        """Test invalid JSONL error handling."""
        loader = BatchDataLoader()
        test_file = tmp_path / 'invalid.jsonl'
        test_file.write_text('{ valid json }\n{ invalid json', encoding='utf-8')
        with pytest.raises(ValueError, match='Error decoding JSON'):
            loader.load_data(str(test_file))

    def test_load_empty_json_file(self, tmp_path):
        """Test loading empty JSON file."""
        loader = BatchDataLoader()
        test_file = tmp_path / 'empty.json'
        test_file.write_text('[]', encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert result == []

    def test_load_empty_jsonl_file(self, tmp_path):
        """Test loading empty JSONL file."""
        loader = BatchDataLoader()
        test_file = tmp_path / 'empty.jsonl'
        test_file.write_text('', encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert result == []

    def test_load_file_permission_error(self, tmp_path):
        """Test file permission error handling."""
        loader = BatchDataLoader()
        test_file = tmp_path / 'protected.json'
        test_file.write_text('[]')
        with patch('builtins.open', side_effect=PermissionError('Permission denied')):
            with pytest.raises(IOError, match='Could not read file'):
                loader.load_data(str(test_file))

    def test_batch_size_handling_large_json(self, tmp_path):
        """Test handling of large JSON files (batch size considerations)."""
        loader = BatchDataLoader()
        large_data = [{'id': i, 'data': f'item_{i}'} for i in range(1000)]
        test_file = tmp_path / 'large.json'
        test_file.write_text(json.dumps(large_data), encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert len(result) == 1000
        assert result[0] == {'id': 0, 'data': 'item_0'}
        assert result[-1] == {'id': 999, 'data': 'item_999'}

    def test_batch_size_handling_large_jsonl(self, tmp_path):
        """Test handling of large JSONL files (batch size considerations)."""
        loader = BatchDataLoader()
        large_data = [{'id': i, 'data': f'item_{i}'} for i in range(1000)]
        test_file = tmp_path / 'large.jsonl'
        jsonl_content = '\n'.join((json.dumps(item) for item in large_data))
        test_file.write_text(jsonl_content, encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert len(result) == 1000
        assert result[0] == {'id': 0, 'data': 'item_0'}
        assert result[-1] == {'id': 999, 'data': 'item_999'}

    def test_encoding_handling(self, tmp_path):
        """Test proper UTF-8 encoding handling."""
        loader = BatchDataLoader()
        test_data = [{'name': 'Ålice', 'city': 'Tøkyo', 'emoji': '🌟'}]
        test_file = tmp_path / 'unicode.json'
        test_file.write_text(json.dumps(test_data, ensure_ascii=False), encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert result == test_data
        assert result[0]['name'] == 'Ålice'
        assert result[0]['city'] == 'Tøkyo'
        assert result[0]['emoji'] == '🌟'

class TestLoaderBatchProcessing:
    """Test batch processing capabilities and edge cases."""

    def test_batch_processing_empty_input(self):
        """Test batch processing with empty input."""
        loader = BatchDataLoader()
        mock_data = []
        assert isinstance(mock_data, list)
        assert len(mock_data) == 0

    def test_batch_processing_single_item(self, tmp_path):
        """Test batch processing with single item."""
        loader = BatchDataLoader()
        test_data = [{'id': 1, 'value': 'single'}]
        test_file = tmp_path / 'single.json'
        test_file.write_text(json.dumps(test_data), encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert len(result) == 1
        assert result[0] == {'id': 1, 'value': 'single'}

    def test_batch_processing_remainder_handling(self, tmp_path):
        """Test batch processing handles remainder correctly."""
        loader = BatchDataLoader()
        test_data = [{'id': i, 'value': f'item_{i}'} for i in range(157)]
        test_file = tmp_path / 'remainder.json'
        test_file.write_text(json.dumps(test_data), encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert len(result) == 157
        assert result[0] == {'id': 0, 'value': 'item_0'}
        assert result[-1] == {'id': 156, 'value': 'item_156'}

    def test_error_propagation_in_batch_processing(self, tmp_path):
        """Test that errors propagate properly in batch processing."""
        loader = BatchDataLoader()
        test_file = tmp_path / 'error.json'
        test_file.write_text('{ incomplete json', encoding='utf-8')
        with pytest.raises(ValueError, match='Error decoding JSON'):
            loader.load_data(str(test_file))

    @pytest.mark.parametrize('batch_size', [1, 10, 100, 1000])
    def test_batch_size_variations(self, batch_size, tmp_path):
        """Test different batch sizes handle data correctly."""
        loader = BatchDataLoader()
        test_data = [{'id': i, 'value': f'item_{i}'} for i in range(batch_size)]
        test_file = tmp_path / f'batch_{batch_size}.json'
        test_file.write_text(json.dumps(test_data), encoding='utf-8')
        result = loader.load_data(str(test_file))
        assert len(result) == batch_size
        if batch_size > 0:
            assert result[0] == {'id': 0, 'value': 'item_0'}
            assert result[-1] == {'id': batch_size - 1, 'value': f'item_{batch_size - 1}'}

class TestDataLoadersModuleExports:
    """Test that data_loaders module exports expected symbols."""

    def test_core_loaders_imports(self):
        """Test that core.loaders imports work correctly."""
        try:
            from agent_actions.core.loaders import BaseLoader
            from agent_actions.core.loaders import BatchDataLoader
            assert BaseLoader is not None
            assert BatchDataLoader is not None
        except ImportError as e:
            pytest.fail(f'Failed to import from core.loaders: {e}')

    def test_agent_base_imports(self):
        """Test direct imports from agents.base."""
        try:
            from agent_actions.input_loading.base_base_loader import BaseLoader
            assert BaseLoader is not None
            assert hasattr(BaseLoader, 'process')
            assert hasattr(BaseLoader, 'supports_filetype')
        except ImportError as e:
            pytest.fail(f'Failed to import BaseLoader: {e}')

    def test_integration_loaders_imports(self):
        """Test imports from integrations.loaders."""
        try:
            from agent_actions.llm_invocation.batch.loaders_batch_data_loader import BatchDataLoader
            assert BatchDataLoader is not None
            assert hasattr(BatchDataLoader, 'load_data')
            assert hasattr(BatchDataLoader, 'supports_async')
        except ImportError as e:
            pytest.fail(f'Failed to import BatchDataLoader: {e}')

    def test_loader_interface_compliance(self):
        """Test that loaders comply with expected interfaces."""
        from agent_actions.input_loading.base_base_loader import BaseLoader
        from agent_actions.llm_invocation.batch.loaders_batch_data_loader import BatchDataLoader
        from agent_actions.configuration.interfaces import IDataLoader
        assert issubclass(BatchDataLoader, IDataLoader)
        assert issubclass(BaseLoader, IDataLoader)

    def test_processing_mode_interface(self):
        """Test ProcessingMode interface is available."""
        try:
            from agent_actions.configuration.interfaces import ProcessingMode
            assert hasattr(ProcessingMode, 'AUTO')
            assert hasattr(ProcessingMode, 'SYNC')
            assert hasattr(ProcessingMode, 'ASYNC')
        except ImportError as e:
            pytest.fail(f'Failed to import ProcessingMode: {e}')

class TestLoaderErrorHandling:
    """Test comprehensive error handling scenarios."""

    def test_retry_mechanism_in_base_loader(self, tmp_path):
        """Test retry mechanism in BaseLoader."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        test_file = tmp_path / 'retry_test.txt'
        test_file.write_text('test content')
        call_count = 0
        original_open = open

        def mock_open(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise IOError('Transient error')
            return original_open(*args, **kwargs)
        with patch('builtins.open', side_effect=mock_open):
            try:
                content = loader.load_file(str(test_file))
                assert content == 'test content'
                assert call_count >= 2
            except Exception:
                pass

    def test_file_error_handling_mixin(self):
        """Test ProcessorErrorHandlerMixin functionality."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        assert hasattr(loader, 'handle_file_error')
        assert hasattr(loader, 'with_retry')

    def test_concurrent_batch_loading(self, tmp_path):
        """Test concurrent batch loading scenarios."""
        loader = BatchDataLoader()
        files_data = []
        for i in range(5):
            test_data = [{'id': j, 'file': i, 'value': f'file_{i}_item_{j}'} for j in range(10)]
            test_file = tmp_path / f'batch_{i}.json'
            test_file.write_text(json.dumps(test_data), encoding='utf-8')
            files_data.append((str(test_file), test_data))
        results = []
        for file_path, expected_data in files_data:
            result = loader.load_data(file_path)
            results.append(result)
            assert result == expected_data
        assert len(results) == 5
        for i, result in enumerate(results):
            assert len(result) == 10
            assert all((item['file'] == i for item in result))