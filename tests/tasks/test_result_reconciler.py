"""
Tests for ResultReconciler.

Tests the reconciliation logic for matching batch results to expected records.
"""
import pytest
from agent_actions.llm_invocation.batch.result_reconciler import ResultReconciler, ReconciliationResult


class TestResultReconciler:
    """Tests for ResultReconciler class."""

    def test_init_with_empty_context_map(self):
        """Test initialization with empty context map."""
        reconciler = ResultReconciler({})
        assert reconciler.context_map == {}
        assert reconciler._processed_ids == set()

    def test_init_with_none_context_map(self):
        """Test initialization with None context map."""
        reconciler = ResultReconciler(None)
        assert reconciler.context_map == {}

    def test_mark_processed_adds_to_set(self):
        """Test that mark_processed adds custom_id to processed set."""
        reconciler = ResultReconciler({})
        reconciler.mark_processed('rec_1')
        reconciler.mark_processed('rec_2')

        assert 'rec_1' in reconciler._processed_ids
        assert 'rec_2' in reconciler._processed_ids
        assert len(reconciler._processed_ids) == 2

    def test_mark_processed_converts_to_string(self):
        """Test that mark_processed converts custom_id to string."""
        reconciler = ResultReconciler({})
        reconciler.mark_processed(123)  # Integer
        reconciler.mark_processed('123')  # String

        # Both should be stored as string '123'
        assert '123' in reconciler._processed_ids
        assert len(reconciler._processed_ids) == 1  # Deduplicated

    def test_mark_processed_ignores_none(self):
        """Test that mark_processed ignores None values."""
        reconciler = ResultReconciler({})
        reconciler.mark_processed(None)

        assert len(reconciler._processed_ids) == 0

    def test_get_expected_ids_only_included(self):
        """Test that get_expected_ids only returns 'included' records."""
        context_map = {
            'rec_1': {'_batch_filter_status': 'included'},
            'rec_2': {'_batch_filter_status': 'filtered'},
            'rec_3': {'_batch_filter_status': 'skipped'},
            'rec_4': {'_batch_filter_status': 'included'}
        }

        reconciler = ResultReconciler(context_map)
        expected_ids = reconciler.get_expected_ids()

        assert expected_ids == {'rec_1', 'rec_4'}
        assert 'rec_2' not in expected_ids  # filtered
        assert 'rec_3' not in expected_ids  # skipped

    def test_get_expected_ids_defaults_to_included(self):
        """Test that records without _batch_filter_status default to 'included'."""
        context_map = {
            'rec_1': {},  # No _batch_filter_status
            'rec_2': {'_batch_filter_status': 'included'}
        }

        reconciler = ResultReconciler(context_map)
        expected_ids = reconciler.get_expected_ids()

        # Both should be expected (default is 'included')
        assert expected_ids == {'rec_1', 'rec_2'}

    def test_get_expected_ids_returns_strings(self):
        """Test that get_expected_ids converts keys to strings."""
        context_map = {
            1: {'_batch_filter_status': 'included'},
            '2': {'_batch_filter_status': 'included'},
            3: {'_batch_filter_status': 'filtered'}
        }

        reconciler = ResultReconciler(context_map)
        expected_ids = reconciler.get_expected_ids()

        assert all(isinstance(id, str) for id in expected_ids)
        assert expected_ids == {'1', '2'}

    def test_get_missing_ids_empty_when_all_processed(self):
        """Test that get_missing_ids returns empty set when all records processed."""
        context_map = {
            'rec_1': {'_batch_filter_status': 'included'},
            'rec_2': {'_batch_filter_status': 'included'}
        }

        reconciler = ResultReconciler(context_map)
        reconciler.mark_processed('rec_1')
        reconciler.mark_processed('rec_2')

        missing_ids = reconciler.get_missing_ids()
        assert missing_ids == set()

    def test_get_missing_ids_finds_unprocessed(self):
        """Test that get_missing_ids correctly identifies missing records."""
        context_map = {
            'rec_1': {'_batch_filter_status': 'included'},
            'rec_2': {'_batch_filter_status': 'included'},
            'rec_3': {'_batch_filter_status': 'included'}
        }

        reconciler = ResultReconciler(context_map)
        reconciler.mark_processed('rec_1')
        # rec_2 and rec_3 not processed

        missing_ids = reconciler.get_missing_ids()
        assert missing_ids == {'rec_2', 'rec_3'}

    def test_get_missing_ids_ignores_filtered(self):
        """Test that get_missing_ids doesn't report filtered records as missing."""
        context_map = {
            'rec_1': {'_batch_filter_status': 'included'},
            'rec_2': {'_batch_filter_status': 'filtered'}
        }

        reconciler = ResultReconciler(context_map)
        # Don't mark any as processed

        missing_ids = reconciler.get_missing_ids()
        # Only rec_1 should be missing, rec_2 is filtered so not expected
        assert missing_ids == {'rec_1'}

    def test_get_passthrough_records_includes_skipped(self):
        """Test that get_passthrough_records includes skipped records."""
        context_map = {
            'rec_1': {'content': 'data1', '_batch_filter_status': 'skipped'},
            'rec_2': {'content': 'data2', '_batch_filter_status': 'included'}
        }

        reconciler = ResultReconciler(context_map)
        reconciler.mark_processed('rec_2')  # rec_2 processed

        passthrough = reconciler.get_passthrough_records()

        # Only rec_1 (skipped) should be in passthrough
        assert len(passthrough) == 1
        assert passthrough[0][0] == 'rec_1'
        assert passthrough[0][1]['content'] == 'data1'

    def test_get_passthrough_records_includes_missing_included(self):
        """Test that get_passthrough_records includes missing 'included' records."""
        context_map = {
            'rec_1': {'content': 'data1', '_batch_filter_status': 'included'},
            'rec_2': {'content': 'data2', '_batch_filter_status': 'included'}
        }

        reconciler = ResultReconciler(context_map)
        reconciler.mark_processed('rec_1')  # Only rec_1 processed

        passthrough = reconciler.get_passthrough_records()

        # rec_2 (included but missing) should be passthrough
        assert len(passthrough) == 1
        assert passthrough[0][0] == 'rec_2'
        assert passthrough[0][1]['content'] == 'data2'

    def test_get_passthrough_records_excludes_filtered(self):
        """Test that get_passthrough_records excludes filtered records."""
        context_map = {
            'rec_1': {'_batch_filter_status': 'included'},
            'rec_2': {'_batch_filter_status': 'filtered'},
            'rec_3': {'_batch_filter_status': 'skipped'}
        }

        reconciler = ResultReconciler(context_map)
        # Don't process any

        passthrough = reconciler.get_passthrough_records()

        # rec_1 (missing included) and rec_3 (skipped) should be passthrough
        # rec_2 (filtered) should NOT be passthrough
        passthrough_ids = [id for id, _ in passthrough]
        assert 'rec_1' in passthrough_ids
        assert 'rec_3' in passthrough_ids
        assert 'rec_2' not in passthrough_ids

    def test_get_passthrough_records_excludes_processed(self):
        """Test that get_passthrough_records excludes already processed records."""
        context_map = {
            'rec_1': {'_batch_filter_status': 'skipped'},
            'rec_2': {'_batch_filter_status': 'included'}
        }

        reconciler = ResultReconciler(context_map)
        reconciler.mark_processed('rec_1')
        reconciler.mark_processed('rec_2')

        passthrough = reconciler.get_passthrough_records()

        # Both were processed, so nothing should be passthrough
        assert len(passthrough) == 0

    def test_reconcile_complete_workflow(self):
        """Test the complete reconcile workflow."""
        context_map = {
            'rec_1': {'content': 'data1', '_batch_filter_status': 'included'},
            'rec_2': {'content': 'data2', '_batch_filter_status': 'skipped'},
            'rec_3': {'content': 'data3', '_batch_filter_status': 'filtered'},
            'rec_4': {'content': 'data4', '_batch_filter_status': 'included'}
        }

        reconciler = ResultReconciler(context_map)
        reconciler.mark_processed('rec_1')
        # rec_1: processed
        # rec_2: skipped (not processed)
        # rec_3: filtered (not processed)
        # rec_4: included but missing (not processed)

        result = reconciler.reconcile()

        # Check processed_ids
        assert result.processed_ids == {'rec_1'}

        # Check missing_ids (only rec_4, since rec_2 is skipped and rec_3 is filtered)
        assert result.missing_ids == {'rec_4'}

        # Check passthrough_records (rec_2 skipped + rec_4 missing)
        passthrough_ids = [id for id, _ in result.passthrough_records]
        assert 'rec_2' in passthrough_ids
        assert 'rec_4' in passthrough_ids
        assert 'rec_3' not in passthrough_ids  # filtered, excluded

    def test_get_record_by_id(self):
        """Test retrieving record data by custom_id."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'content': 'data1'}
        }

        reconciler = ResultReconciler(context_map)
        record = reconciler.get_record_by_id('rec_1')

        assert record['target_id'] == 'rec_1'
        assert record['content'] == 'data1'

    def test_get_record_by_id_not_found(self):
        """Test get_record_by_id returns empty dict for missing ID."""
        reconciler = ResultReconciler({})
        record = reconciler.get_record_by_id('nonexistent')

        assert record == {}

    def test_get_source_guid(self):
        """Test get_source_guid retrieves source_guid from record."""
        context_map = {
            'rec_1': {'source_guid': 'src_1'}
        }

        reconciler = ResultReconciler(context_map)
        source_guid = reconciler.get_source_guid('rec_1')

        assert source_guid == 'src_1'

    def test_get_source_guid_fallback_to_custom_id(self):
        """Test get_source_guid uses custom_id as fallback."""
        context_map = {
            'rec_1': {}  # No source_guid
        }

        reconciler = ResultReconciler(context_map)
        source_guid = reconciler.get_source_guid('rec_1')

        assert source_guid == 'rec_1'

    def test_get_source_guid_custom_fallback(self):
        """Test get_source_guid with custom fallback value."""
        reconciler = ResultReconciler({})
        source_guid = reconciler.get_source_guid('nonexistent', fallback='unknown')

        assert source_guid == 'unknown'

    def test_get_record_index(self):
        """Test get_record_index returns correct position."""
        context_map = {
            'rec_0': {},
            'rec_1': {},
            'rec_2': {}
        }

        reconciler = ResultReconciler(context_map)

        assert reconciler.get_record_index('rec_0') == 0
        assert reconciler.get_record_index('rec_1') == 1
        assert reconciler.get_record_index('rec_2') == 2

    def test_get_record_index_not_found(self):
        """Test get_record_index returns -1 for missing ID."""
        reconciler = ResultReconciler({'rec_1': {}})

        assert reconciler.get_record_index('nonexistent') == -1


class TestReconciliationResult:
    """Tests for ReconciliationResult dataclass."""

    def test_reconciliation_result_creation(self):
        """Test creating ReconciliationResult."""
        result = ReconciliationResult(
            processed_ids={'rec_1', 'rec_2'},
            missing_ids={'rec_3'},
            passthrough_records=[('rec_3', {'content': 'data'})]
        )

        assert result.processed_ids == {'rec_1', 'rec_2'}
        assert result.missing_ids == {'rec_3'}
        assert len(result.passthrough_records) == 1
