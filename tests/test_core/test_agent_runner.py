"""Unit tests for the AgentRunner class."""

import os
from unittest.mock import Mock, patch
import pytest

from agent_actions.core.agent_runner import AgentRunner
from agent_actions.core.agent_strategies import (
    InitialStrategy,
    TerminalStrategy,
    IntermediateStrategy
)


@pytest.fixture
def agent_runner():
    """Fixture to create an AgentRunner instance."""
    return AgentRunner(use_tools=True)


@pytest.fixture
def mock_file_handler():
    """Fixture to mock FileHandler."""
    with patch('agent_actions.core.agent_runner.FileHandler') as mock:
        mock.find_specific_folder.return_value = '/mock/path/agent_io'
        yield mock


@pytest.fixture
def mock_strategy():
    """Fixture to create a mock strategy."""
    strategy = Mock()
    strategy.execute.return_value = None
    return strategy


def test_agent_runner_initialization(agent_runner):
    """Test AgentRunner initialization."""
    assert agent_runner.use_tools is True
    assert isinstance(agent_runner.strategies['initial'], InitialStrategy)
    assert isinstance(agent_runner.strategies['terminal'], TerminalStrategy)
    assert isinstance(agent_runner.strategies['intermediate'], IntermediateStrategy)


def test_run_agent_initial_strategy(agent_runner, mock_file_handler):
    """Test run_agent with initial strategy (idx=0)."""
    with patch.object(agent_runner, 'process_and_generate_for_agent') as mock_process:
        mock_process.return_value = '/mock/output/path'
        
        result = agent_runner.run_agent(
            agent_config={'agent_type': 'test_type'},
            agent_name='test_agent',
            previous_agent_type=None,
            idx=0
        )
        
        assert result == '/mock/output/path'
        mock_process.assert_called_once()
        assert isinstance(
            mock_process.call_args[0][3],
            InitialStrategy
        )


def test_run_agent_terminal_strategy(agent_runner, mock_file_handler):
    """Test run_agent with terminal strategy (idx=-1)."""
    with patch.object(agent_runner, 'process_and_generate_for_agent') as mock_process:
        mock_process.return_value = '/mock/output/path'
        
        result = agent_runner.run_agent(
            agent_config={'agent_type': 'test_type'},
            agent_name='test_agent',
            previous_agent_type='prev_type',
            idx=-1
        )
        
        assert result == '/mock/output/path'
        mock_process.assert_called_once()
        assert isinstance(
            mock_process.call_args[0][3],
            TerminalStrategy
        )


def test_process_and_generate_for_agent(agent_runner, mock_file_handler, mock_strategy):
    """Test process_and_generate_for_agent with valid inputs."""
    with patch('os.walk') as mock_walk, \
         patch('os.path.join', side_effect=os.path.join):
        
        mock_walk.return_value = [
            ('/mock/path', [], ['test_file.txt'])
        ]
        
        result = agent_runner.process_and_generate_for_agent(
            agent_config={'agent_type': 'test_type'},
            agent_name='test_agent',
            previous_agent_type='prev_type',
            strategy=mock_strategy
        )
        
        assert result == '/mock/path/agent_io/target/test_type'
        mock_strategy.execute.assert_called_once()


def test_process_and_generate_for_agent_no_files(agent_runner, mock_file_handler, mock_strategy):
    """Test process_and_generate_for_agent when no files are found."""
    with patch('os.walk') as mock_walk:
        mock_walk.return_value = [('/mock/path', [], [])]
        
        with pytest.raises(FileNotFoundError):
            agent_runner.process_and_generate_for_agent(
                agent_config={'agent_type': 'test_type'},
                agent_name='test_agent',
                previous_agent_type='prev_type',
                strategy=mock_strategy
            )


def test_process_and_generate_for_agent_folder_not_found(agent_runner):
    """Test process_and_generate_for_agent when agent folder is not found."""
    with patch('agent_actions.core.agent_runner.FileHandler') as mock_file_handler:
        mock_file_handler.find_specific_folder.return_value = None
        
        with pytest.raises(FileNotFoundError):
            agent_runner.process_and_generate_for_agent(
                agent_config={'agent_type': 'test_type'},
                agent_name='test_agent',
                previous_agent_type='prev_type',
                strategy=Mock()
            )


def test_process_and_generate_for_agent_strategy_error(agent_runner, mock_file_handler, mock_strategy):
    """Test process_and_generate_for_agent when strategy execution fails."""
    mock_strategy.execute.side_effect = ValueError("Strategy execution failed")
    
    with patch('os.walk') as mock_walk:
        mock_walk.return_value = [('/mock/path', [], ['test_file.txt'])]
        
        with pytest.raises(ValueError):
            agent_runner.process_and_generate_for_agent(
                agent_config={'agent_type': 'test_type'},
                agent_name='test_agent',
                previous_agent_type='prev_type',
                strategy=mock_strategy
            ) 