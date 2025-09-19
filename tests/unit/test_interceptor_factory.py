"""
Unit tests for InterceptorFactory.

Tests factory creation of interceptors and chain building.
"""

import pytest
from unittest.mock import Mock, patch
from agent_actions.integrations.interceptors.factory import InterceptorFactory
from agent_actions.integrations.interceptors.base import ResponseInterceptor, InterceptorChain
from agent_actions.agents.validators.validation_interceptor import ValidationInterceptor
from agent_actions.integrations.interceptors.reprompt_interceptor import RepromptInterceptor


class TestInterceptorFactory:
    """Test suite for InterceptorFactory."""

    def test_create_validation_interceptor(self):
        """Test creating a validation interceptor."""
        config = {
            "type": "validation",
            "validator": "word_count",
            "validator_args": {"expected": 10},
            "on_failure": "retry"
        }
        
        with patch.object(ValidationInterceptor, 'configure') as mock_configure:
            interceptor = InterceptorFactory.create_interceptor(config)
            
            assert isinstance(interceptor, ValidationInterceptor)
            mock_configure.assert_called_once_with({
                "validator": "word_count",
                "validator_args": {"expected": 10},
                "on_failure": "retry"
            })

    def test_create_reprompt_interceptor(self):
        """Test creating a reprompt interceptor."""
        config = {
            "type": "reprompt",
            "strategy": "template",
            "max_attempts": 5,
            "templates": {"error": "Fix: {original_prompt}"}
        }
        
        with patch.object(RepromptInterceptor, 'configure') as mock_configure:
            interceptor = InterceptorFactory.create_interceptor(config)
            
            assert isinstance(interceptor, RepromptInterceptor)
            mock_configure.assert_called_once_with({
                "strategy": "template",
                "max_attempts": 5,
                "templates": {"error": "Fix: {original_prompt}"}
            })

    def test_create_unknown_interceptor(self):
        """Test creating an unknown interceptor type."""
        config = {"type": "unknown"}
        
        with pytest.raises(ValueError, match="Unknown interceptor type: unknown"):
            InterceptorFactory.create_interceptor(config)

    def test_build_chain_empty(self):
        """Test building an empty chain."""
        chain = InterceptorFactory.build_chain([])
        
        assert isinstance(chain, InterceptorChain)
        assert len(chain.interceptors) == 0

    def test_build_chain_single(self):
        """Test building a chain with single interceptor."""
        configs = [{
            "type": "validation",
            "validator": "word_count"
        }]
        
        chain = InterceptorFactory.build_chain(configs)
        
        assert isinstance(chain, InterceptorChain)
        assert len(chain.interceptors) == 1
        assert isinstance(chain.interceptors[0], ValidationInterceptor)

    def test_build_chain_multiple(self):
        """Test building a chain with multiple interceptors."""
        configs = [
            {
                "type": "validation",
                "validator": "word_count"
            },
            {
                "type": "reprompt",
                "strategy": "template"
            }
        ]
        
        chain = InterceptorFactory.build_chain(configs)
        
        assert isinstance(chain, InterceptorChain)
        assert len(chain.interceptors) == 2
        assert isinstance(chain.interceptors[0], ValidationInterceptor)
        assert isinstance(chain.interceptors[1], RepromptInterceptor)

    def test_register_custom_interceptor(self):
        """Test registering a custom interceptor type."""
        class CustomInterceptor(ResponseInterceptor):
            def configure(self, config):
                self.custom_config = config
                
            def intercept(self, response, context):
                pass
        
        # Register custom interceptor
        InterceptorFactory.register_interceptor("custom", CustomInterceptor)
        
        # Create custom interceptor
        config = {
            "type": "custom",
            "custom_param": "value"
        }
        
        interceptor = InterceptorFactory.create_interceptor(config)
        
        assert isinstance(interceptor, CustomInterceptor)
        assert interceptor.custom_config == {"custom_param": "value"}
        
        # Clean up
        InterceptorFactory._interceptor_types.pop("custom", None)

    def test_interceptor_types_registered(self):
        """Test that default interceptor types are registered."""
        assert "validation" in InterceptorFactory._interceptor_types
        assert "reprompt" in InterceptorFactory._interceptor_types
        assert InterceptorFactory._interceptor_types["validation"] == ValidationInterceptor
        assert InterceptorFactory._interceptor_types["reprompt"] == RepromptInterceptor

    def test_config_without_type(self):
        """Test creating interceptor without type field."""
        config = {"validator": "word_count"}
        
        with pytest.raises(ValueError, match="Unknown interceptor type: None"):
            InterceptorFactory.create_interceptor(config)

    def test_build_chain_preserves_order(self):
        """Test that chain preserves interceptor order."""
        configs = [
            {"type": "validation", "validator": "word_count", "id": "first"},
            {"type": "reprompt", "strategy": "template", "id": "second"},
            {"type": "validation", "validator": "char_count", "id": "third"}
        ]
        
        chain = InterceptorFactory.build_chain(configs)
        
        assert len(chain.interceptors) == 3
        # Verify order is preserved
        assert isinstance(chain.interceptors[0], ValidationInterceptor)
        assert isinstance(chain.interceptors[1], RepromptInterceptor)
        assert isinstance(chain.interceptors[2], ValidationInterceptor)

    def test_interceptor_configuration_isolation(self):
        """Test that interceptor configurations are isolated."""
        config1 = {
            "type": "validation",
            "validator": "word_count",
            "validator_args": {"expected": 5}
        }
        
        config2 = {
            "type": "validation",
            "validator": "char_count",
            "validator_args": {"min_chars": 10}
        }
        
        interceptor1 = InterceptorFactory.create_interceptor(config1)
        interceptor2 = InterceptorFactory.create_interceptor(config2)
        
        # Configurations should be independent
        assert interceptor1.validator_name == "word_count"
        assert interceptor2.validator_name == "char_count"

    def test_factory_thread_safety(self):
        """Test that factory can be used from multiple threads."""
        import threading
        results = []
        
        def create_interceptor():
            config = {"type": "validation", "validator": "word_count"}
            interceptor = InterceptorFactory.create_interceptor(config)
            results.append(interceptor)
        
        threads = [threading.Thread(target=create_interceptor) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(results) == 5
        assert all(isinstance(i, ValidationInterceptor) for i in results)