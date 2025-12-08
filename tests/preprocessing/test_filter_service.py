"""
Unit tests for FilterService.

Tests the centralized WHERE clause and conditional filtering logic
shared between batch and realtime modes.
"""

import pytest
from unittest.mock import Mock, patch
from agent_actions.preprocessing.filtering.filter_service import FilterService, FilterStatus, get_filter_service


class MockFilterResult:
    """Mock filter result for testing."""
    def __init__(self, success, matched, error=None):
        self.success = success
        self.matched = matched
        self.error = error


class TestFilterService:
    """Test suite for FilterService."""

    @pytest.fixture
    def filter_service(self):
        """Create a FilterService instance."""
        return FilterService()

    # WHERE clause - filter behavior tests

    def test_where_clause_filter_behavior_matched(self, filter_service):
        """Test WHERE clause with filter behavior when clause matches."""
        item_content = {'status': 'active', 'value': 100}
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'filter',
            'scope': 'item'
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = MockFilterResult(success=True, matched=True)

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is True
            assert result.status == 'included'
            assert result.error is None

    def test_where_clause_filter_behavior_not_matched(self, filter_service):
        """Test WHERE clause with filter behavior when clause doesn't match."""
        item_content = {'status': 'inactive', 'value': 50}
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'filter',
            'scope': 'item'
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = MockFilterResult(success=True, matched=False)

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is False
            assert result.status == 'filtered'
            assert result.error is None

    # WHERE clause - skip behavior tests

    def test_where_clause_skip_behavior_matched(self, filter_service):
        """Test WHERE clause with skip behavior when clause matches."""
        item_content = {'status': 'active'}
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'skip',
            'scope': 'item'
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = MockFilterResult(success=True, matched=True)

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is True
            assert result.status == 'included'

    def test_where_clause_skip_behavior_not_matched(self, filter_service):
        """Test WHERE clause with skip behavior when clause doesn't match."""
        item_content = {'status': 'inactive'}
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'skip',
            'scope': 'item'
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = MockFilterResult(success=True, matched=False)

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is False
            assert result.status == 'skipped'

    # passthrough_on_error tests

    def test_passthrough_on_error_true_filter_behavior(self, filter_service):
        """Test passthrough_on_error=True with filter behavior includes item on error."""
        item_content = {'status': 'active'}
        where_config = {
            'clause': 'invalid clause',
            'behavior': 'filter',
            'scope': 'item',
            'passthrough_on_error': True
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = MockFilterResult(success=False, matched=False, error='Parse error')

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is True
            assert result.status == 'included'
            assert result.error == 'Parse error'

    def test_passthrough_on_error_false_filter_behavior(self, filter_service):
        """Test passthrough_on_error=False with filter behavior filters item on error."""
        item_content = {'status': 'active'}
        where_config = {
            'clause': 'invalid clause',
            'behavior': 'filter',
            'scope': 'item',
            'passthrough_on_error': False
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = MockFilterResult(success=False, matched=False, error='Parse error')

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is False
            assert result.status == 'filtered'
            assert result.error == 'Parse error'

    def test_passthrough_on_error_false_skip_behavior(self, filter_service):
        """Test passthrough_on_error=False with skip behavior skips item on error."""
        item_content = {'status': 'active'}
        where_config = {
            'clause': 'invalid clause',
            'behavior': 'skip',
            'scope': 'item',
            'passthrough_on_error': False
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = MockFilterResult(success=False, matched=False, error='Parse error')

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is False
            assert result.status == 'skipped'
            assert result.error == 'Parse error'

    # Conditional clause tests

    def test_conditional_clause_passes(self, filter_service):
        """Test conditional clause when condition passes."""
        item_content = {'process': True}

        with patch('agent_actions.utilities.tooling.execute_user_defined_function') as mock_exec:
            mock_exec.return_value = True

            result = filter_service.filter_single_item(item_content, None, 'test_function')

            assert result.should_include is True
            assert result.status == 'included'
            mock_exec.assert_called_once_with('test_function', item_content)

    def test_conditional_clause_fails(self, filter_service):
        """Test conditional clause when condition fails."""
        item_content = {'process': False}

        with patch('agent_actions.utilities.tooling.execute_user_defined_function') as mock_exec:
            mock_exec.return_value = False

            result = filter_service.filter_single_item(item_content, None, 'test_function')

            assert result.should_include is False
            assert result.status == 'skipped'

    def test_conditional_clause_error_passthrough(self, filter_service):
        """Test conditional clause errors always passthrough (legacy behavior)."""
        item_content = {'process': True}

        with patch('agent_actions.utilities.tooling.execute_user_defined_function') as mock_exec:
            mock_exec.side_effect = Exception('UDF not found')

            result = filter_service.filter_single_item(item_content, None, 'test_function')

            assert result.should_include is True
            assert result.status == 'included'
            assert 'UDF not found' in result.error

    # Boolean filter result (legacy SimpleWhereFilter) tests

    def test_boolean_filter_result_true(self, filter_service):
        """Test legacy boolean filter result (True = matched)."""
        item_content = {'status': 'active'}
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'filter',
            'scope': 'item'
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = True  # Legacy boolean result

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is True
            assert result.status == 'included'

    def test_boolean_filter_result_false_filter_behavior(self, filter_service):
        """Test legacy boolean filter result (False = not matched) with filter behavior."""
        item_content = {'status': 'inactive'}
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'filter',
            'scope': 'item'
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = False  # Legacy boolean result

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is False
            assert result.status == 'filtered'

    def test_boolean_filter_result_false_skip_behavior(self, filter_service):
        """Test legacy boolean filter result (False = not matched) with skip behavior."""
        item_content = {'status': 'inactive'}
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'skip',
            'scope': 'item'
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = False  # Legacy boolean result

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is False
            assert result.status == 'skipped'

    # Exception handling tests

    def test_where_clause_exception_passthrough_on_error_true(self, filter_service):
        """Test exception during WHERE clause evaluation with passthrough_on_error=True."""
        item_content = {'status': 'active'}
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'filter',
            'scope': 'item',
            'passthrough_on_error': True
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.side_effect = Exception('Filter evaluation failed')

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is True
            assert result.status == 'included'
            assert 'Filter evaluation failed' in result.error

    def test_where_clause_exception_passthrough_on_error_false(self, filter_service):
        """Test exception during WHERE clause evaluation with passthrough_on_error=False."""
        item_content = {'status': 'active'}
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'filter',
            'scope': 'item',
            'passthrough_on_error': False
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.side_effect = Exception('Filter evaluation failed')

            result = filter_service.filter_single_item(item_content, where_config)

            assert result.should_include is False
            assert result.status == 'filtered'
            assert 'Filter evaluation failed' in result.error

    # Batch filtering tests

    def test_apply_where_clause_filtering_mixed_results(self, filter_service):
        """Test batch filtering with mixed results."""
        data = [
            {'target_id': 'id1', 'content': {'status': 'active'}},
            {'target_id': 'id2', 'content': {'status': 'inactive'}},
            {'target_id': 'id3', 'content': {'status': 'active'}}
        ]
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'filter',
            'scope': 'item'
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            # Return matched=True for active, matched=False for inactive
            def filter_side_effect(content, clause):
                return MockFilterResult(
                    success=True,
                    matched=content.get('status') == 'active'
                )
            mock_filter.side_effect = filter_side_effect

            filtered_data, status_map = filter_service.apply_where_clause_filtering(
                data, where_config
            )

            assert len(filtered_data) == 2
            assert filtered_data[0]['target_id'] == 'id1'
            assert filtered_data[1]['target_id'] == 'id3'

            assert status_map['id1'] == 'included'
            assert status_map['id2'] == 'filtered'
            assert status_map['id3'] == 'included'

    def test_apply_where_clause_filtering_skip_behavior(self, filter_service):
        """Test batch filtering with skip behavior."""
        data = [
            {'target_id': 'id1', 'content': {'status': 'active'}},
            {'target_id': 'id2', 'content': {'status': 'inactive'}}
        ]
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'skip',
            'scope': 'item'
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            def filter_side_effect(content, clause):
                return MockFilterResult(
                    success=True,
                    matched=content.get('status') == 'active'
                )
            mock_filter.side_effect = filter_side_effect

            filtered_data, status_map = filter_service.apply_where_clause_filtering(
                data, where_config
            )

            # With skip behavior, only matched items are included
            assert len(filtered_data) == 1
            assert filtered_data[0]['target_id'] == 'id1'

            assert status_map['id1'] == 'included'
            assert status_map['id2'] == 'skipped'

    # No filtering configured tests

    def test_no_filtering_configured(self, filter_service):
        """Test that items pass through when no filtering is configured."""
        item_content = {'status': 'active'}

        result = filter_service.filter_single_item(item_content, None, None)

        assert result.should_include is True
        assert result.status == 'included'
        assert result.error is None

    def test_where_clause_scope_not_item(self, filter_service):
        """Test that WHERE clause with scope != 'item' is ignored."""
        item_content = {'status': 'active'}
        where_config = {
            'clause': 'status == "active"',
            'behavior': 'filter',
            'scope': 'file'  # Not 'item'
        }

        result = filter_service.filter_single_item(item_content, where_config)

        assert result.should_include is True
        assert result.status == 'included'

    # Global instance test

    def test_get_filter_service_singleton(self):
        """Test that get_filter_service returns a singleton instance."""
        service1 = get_filter_service()
        service2 = get_filter_service()

        assert service1 is service2

    # Edge case: default passthrough_on_error

    def test_default_passthrough_on_error_is_true(self, filter_service):
        """Test that default passthrough_on_error is True."""
        item_content = {'status': 'active'}
        where_config = {
            'clause': 'invalid clause',
            'behavior': 'filter',
            'scope': 'item'
            # passthrough_on_error not specified
        }

        with patch.object(filter_service.where_filter, 'filter_item') as mock_filter:
            mock_filter.return_value = MockFilterResult(success=False, matched=False, error='Error')

            result = filter_service.filter_single_item(item_content, where_config)

            # Should passthrough by default
            assert result.should_include is True
            assert result.status == 'included'
