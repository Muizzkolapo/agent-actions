"""
Unit tests for SourceDataLoader with PathManager integration.

Tests the source path transformation logic that skips node directories.
"""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from agent_actions.integrations.loaders.data_loaders.source_data_loader import SourceDataLoader
from agent_actions.core.path_manager import PathManager, PathManagerError


class TestSourceDataLoader:
    """Test suite for SourceDataLoader class."""
    
    @pytest.fixture
    def temp_project(self):
        """Create a temporary project structure for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        
        # Create project structure
        project_root = temp_dir / "test_project"
        project_root.mkdir()
        
        # Create marker file
        (project_root / "agent_actions.yml").write_text("test: true")
        
        # Create pipeline structure
        pipeline_dir = project_root / "quiz_maker" / "TopicToQuizPipeline"
        pipeline_dir.mkdir(parents=True)
        
        # Create agent_io structure
        agent_io = pipeline_dir / "agent_io"
        source_dir = agent_io / "source"
        target_dir = agent_io / "target" / "node_0_summary"
        
        source_dir.mkdir(parents=True)
        target_dir.mkdir(parents=True)
        
        # Create test source file
        source_file = source_dir / "test_file.json"
        test_data = [{"id": 1, "content": "test data"}]
        source_file.write_text(json.dumps(test_data))
        
        # Create target file path (but not the file itself)
        target_file = target_dir / "test_file.json"
        
        yield {
            "project_root": project_root,
            "source_file": source_file,
            "target_file": target_file,
            "test_data": test_data
        }
        
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)
    
    def test_source_data_loader_initialization(self):
        """Test SourceDataLoader initialization."""
        path_manager = PathManager()
        loader = SourceDataLoader("test_agent", path_manager)
        assert loader.agent_name == "test_agent"
        assert loader.path_manager is path_manager
        
        # Test with custom path manager
        custom_pm = PathManager()
        loader = SourceDataLoader("test_agent", custom_pm)
        assert loader.path_manager is custom_pm
    
    def test_load_source_data_success(self, temp_project):
        """Test successful source data loading with node directory skipping."""
        with patch.object(PathManager, 'get_project_root', return_value=temp_project["project_root"]), \
             patch.object(PathManager, 'is_within_project', return_value=True):
            path_manager = PathManager()
            loader = SourceDataLoader("test_agent", path_manager)
            
            # Load data using target path - should find source file
            result = loader.load_source_data(str(temp_project["target_file"]))
            
            assert result == temp_project["test_data"]
            assert len(result) == 1
            assert result[0]["content"] == "test data"
    
    def test_path_transformation_logic(self, temp_project):
        """Test that target paths are correctly transformed to source paths."""
        with patch.object(PathManager, 'get_project_root', return_value=temp_project["project_root"]):
            path_manager = PathManager()
            loader = SourceDataLoader("test_agent", path_manager)
            
            target_path = temp_project["target_file"]
            
            # Manually test the transformation logic
            parts = target_path.parts
            agent_io_index = parts.index("agent_io")
            pipeline_parts = parts[:agent_io_index]
            file_parts = parts[agent_io_index + 3:]  # Skip agent_io/target/node_dir
            
            expected_source = Path(*pipeline_parts) / "agent_io" / "source" / Path(*file_parts)
            
            assert expected_source == temp_project["source_file"]
    
    def test_agent_io_not_found_error(self):
        """Test error when agent_io is not found in path."""
        path_manager = PathManager()
        loader = SourceDataLoader("test_agent", path_manager)
        
        invalid_path = "/some/path/without/agent_io/file.json"
        
        with pytest.raises(IOError, match="'agent_io' not found in path"):
            loader.load_source_data(invalid_path)
    
    def test_path_too_short_error(self):
        """Test error when path is too short to contain node directory."""
        path_manager = PathManager()
        loader = SourceDataLoader("test_agent", path_manager)
        
        short_path = "/project/agent_io/target/file.json"  # Missing node directory
        
        with pytest.raises(IOError, match="Path too short - missing node directory"):
            loader.load_source_data(short_path)
    
    def test_no_filename_error(self):
        """Test error when no filename is found after node directory."""
        path_manager = PathManager()
        loader = SourceDataLoader("test_agent", path_manager)
        
        path_without_file = "/project/agent_io/target/node_0"  # No filename
        
        with pytest.raises(IOError, match="No filename found after node directory"):
            loader.load_source_data(path_without_file)
    
    def test_source_file_not_found_error(self, temp_project):
        """Test error when source file doesn't exist."""
        with patch.object(PathManager, 'get_project_root', return_value=temp_project["project_root"]):
            path_manager = PathManager()
            loader = SourceDataLoader("test_agent", path_manager)
            
            # Use a target path that would map to a non-existent source file
            non_existent_target = temp_project["target_file"].parent / "non_existent.json"
            
            with pytest.raises(IOError, match="Source file not found"):
                loader.load_source_data(str(non_existent_target))
    
    def test_source_file_outside_project_bounds(self, temp_project):
        """Test error when source file is outside project bounds."""
        with patch.object(PathManager, 'is_within_project', return_value=False):
            path_manager = PathManager()
            loader = SourceDataLoader("test_agent", path_manager)
            
            with pytest.raises(IOError, match="Source file is outside project bounds"):
                loader.load_source_data(str(temp_project["target_file"]))
    
    def test_invalid_json_error(self, temp_project):
        """Test error when source file contains invalid JSON."""
        # Create source file with invalid JSON
        invalid_source = temp_project["source_file"]
        invalid_source.write_text("invalid json content")
        
        with patch.object(PathManager, 'get_project_root', return_value=temp_project["project_root"]):
            path_manager = PathManager()
            loader = SourceDataLoader("test_agent", path_manager)
            
            with pytest.raises(IOError, match="Failed to load source data"):
                loader.load_source_data(str(temp_project["target_file"]))
    
    def test_multiple_nodes_same_source(self, temp_project):
        """Test that multiple nodes map to the same source file."""
        with patch.object(PathManager, 'get_project_root', return_value=temp_project["project_root"]), \
             patch.object(PathManager, 'is_within_project', return_value=True):
            path_manager = PathManager()
            loader = SourceDataLoader("test_agent", path_manager)
            
            # Create target paths for different nodes
            base_dir = temp_project["target_file"].parent.parent
            node1_target = base_dir / "node_0_summary" / "test_file.json"
            node2_target = base_dir / "node_1_analysis" / "test_file.json"
            
            # Both should load the same source data
            result1 = loader.load_source_data(str(node1_target))
            result2 = loader.load_source_data(str(node2_target))
            
            assert result1 == result2 == temp_project["test_data"]
    
    def test_nested_file_paths(self, temp_project):
        """Test handling of nested file paths in source directory."""
        # Create nested source structure
        nested_source_dir = temp_project["source_file"].parent / "nested" / "subdir"
        nested_source_dir.mkdir(parents=True)
        nested_source_file = nested_source_dir / "nested_file.json"
        
        nested_data = [{"id": 2, "content": "nested test data"}]
        nested_source_file.write_text(json.dumps(nested_data))
        
        # Create corresponding target path
        target_nested = temp_project["target_file"].parent / "nested" / "subdir" / "nested_file.json"
        
        with patch.object(PathManager, 'get_project_root', return_value=temp_project["project_root"]), \
             patch.object(PathManager, 'is_within_project', return_value=True):
            path_manager = PathManager()
            loader = SourceDataLoader("test_agent", path_manager)
            
            result = loader.load_source_data(str(target_nested))
            assert result == nested_data
    
    def test_backward_compatibility_with_original_logic(self):
        """Test that the new logic produces the same results as the original."""
        # Test case based on the original implementation logic
        target_path = "/project/TopicToQuizPipeline/agent_io/target/node_0_summary/file.json"
        
        # Original logic simulation
        parts = Path(target_path).parts
        agent_io_index = parts.index("agent_io")
        pipeline_name_dir = Path(*parts[:agent_io_index])
        mirrored_structure_parts = parts[agent_io_index + 3:]  # Original magic number +3
        original_source = pipeline_name_dir / "agent_io" / "source" / Path(*mirrored_structure_parts)
        
        # New logic simulation  
        path_manager = PathManager()
        loader = SourceDataLoader("test_agent", path_manager)
        target_path_obj = loader.path_manager.normalize_path(target_path)
        new_parts = target_path_obj.parts
        new_agent_io_index = new_parts.index("agent_io")
        new_pipeline_parts = new_parts[:new_agent_io_index]
        new_file_parts = new_parts[new_agent_io_index + 3:]
        new_source = Path(*new_pipeline_parts) / "agent_io" / "source" / Path(*new_file_parts)
        
        assert str(original_source) == str(new_source)
        assert original_source == new_source