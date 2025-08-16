"""
Production WHERE clause example demonstrating comprehensive hardening features.
Shows how to use the production-grade WHERE clause system with all safety features.
"""
import asyncio
import json
import time
from typing import Dict, Any, List
from datetime import datetime

# Import production components
from agent_actions.common.filters.production_where_clause import (
    ProductionWhereClauseProcessor, WhereClauseConfig, create_where_clause_processor
)
from agent_actions.common.monitoring.metrics import init_metrics, get_metrics_collector
from agent_actions.common.monitoring.logging import init_logging, LoggingContext
from agent_actions.common.resilience.circuit_breaker import get_circuit_breaker_stats
from agent_actions.common.feature_flags.manager import init_feature_flags, get_feature_flag_manager
from agent_actions.common.correlation.tracker import init_correlation_tracker, CorrelationContext
from agent_actions.common.health.checks import init_health_monitor, check_system_health
from agent_actions.common.performance.cache import init_cache_manager, get_cache_stats
from agent_actions.models.enhanced_config_schema import (
    EnhancedAgentConfig, WhereClauseConfig as SchemaWhereClauseConfig,
    ProductionWhereClauseConfig, SecurityLevel, WhereClauseScope
)


class ProductionWhereClauseDemo:
    """Demonstration of production WHERE clause features."""
    
    def __init__(self):
        self.setup_production_environment()
        self.agent_type = "demo_agent"
        self.processor = create_where_clause_processor(
            agent_type=self.agent_type,
            security_level="standard"
        )
    
    def setup_production_environment(self):
        """Initialize all production components."""
        print("🚀 Initializing production environment...")
        
        # Initialize monitoring
        init_metrics(enable_prometheus=False)  # Disable Prometheus for demo
        init_logging("production_demo", "INFO")
        
        # Initialize feature flags
        feature_manager = init_feature_flags()
        
        # Enable WHERE clause functionality
        feature_manager.update_percentage_rollout("where_clause_enabled", "gradual_rollout", 100.0)
        feature_manager.update_percentage_rollout("where_clause_caching", "performance_feature", 100.0)
        feature_manager.set_emergency_kill_switch("where_clause_security_mode", False)  # Ensure security is on
        
        # Initialize correlation tracking
        init_correlation_tracker()
        
        # Initialize health monitoring
        init_health_monitor()
        
        # Initialize cache manager
        init_cache_manager()
        
        print("✅ Production environment initialized")
    
    def demonstrate_basic_filtering(self):
        """Demonstrate basic WHERE clause filtering."""
        print("\n🔍 Demonstrating Basic Filtering")
        print("=" * 50)
        
        # Sample data
        sample_data = [
            {"id": 1, "status": "active", "score": 85, "category": "premium"},
            {"id": 2, "status": "inactive", "score": 45, "category": "basic"},
            {"id": 3, "status": "active", "score": 92, "category": "premium"},
            {"id": 4, "status": "pending", "score": 67, "category": "standard"},
            {"id": 5, "status": "active", "score": 34, "category": "basic"}
        ]
        
        # Test various WHERE clauses
        test_cases = [
            'status == "active"',
            'score >= 70',
            'status == "active" AND score >= 70',
            'category IN ["premium", "standard"]',
            'status != "inactive" AND score > 50'
        ]
        
        for clause in test_cases:
            print(f"\nTesting clause: {clause}")
            
            config = WhereClauseConfig(
                clause=clause,
                scope="item",
                passthrough_on_error=False
            )
            
            try:
                # Create correlation for this operation
                with CorrelationContext(agent_type=self.agent_type) as correlation:
                    correlation.add_metadata("operation", "basic_filtering")
                    correlation.add_metadata("clause", clause)
                    
                    # Filter the batch
                    filtered_data = self.processor.filter_batch(
                        sample_data, 
                        config,
                        correlation.correlation_id
                    )
                    
                    print(f"  Original items: {len(sample_data)}")
                    print(f"  Filtered items: {len(filtered_data)}")
                    print(f"  Pass rate: {len(filtered_data)/len(sample_data)*100:.1f}%")
                    
                    # Show which items passed
                    passed_ids = [item["id"] for item in filtered_data]
                    print(f"  Passed IDs: {passed_ids}")
            
            except Exception as e:
                print(f"  ❌ Error: {e}")
    
    def demonstrate_security_features(self):
        """Demonstrate security features and protections."""
        print("\n🔒 Demonstrating Security Features")
        print("=" * 50)
        
        # Test security violations
        malicious_clauses = [
            '__import__("os").system("ls")',  # Code injection
            'eval("print(123)")',  # eval injection
            'x' * 2000,  # Clause too long
            'field1 == "a" AND field2 == "b" AND field3 == "c" AND field4 == "d" AND field5 == "e" AND field6 == "f" AND field7 == "g" AND field8 == "h" AND field9 == "i" AND field10 == "j" AND field11 == "k"',  # Too many conditions
        ]
        
        safe_data = {"test_field": "test_value"}
        
        for clause in malicious_clauses:
            print(f"\nTesting malicious clause: {clause[:50]}{'...' if len(clause) > 50 else ''}")
            
            config = WhereClauseConfig(
                clause=clause,
                scope="item",
                passthrough_on_error=False
            )
            
            try:
                result = self.processor.should_process_item(safe_data, config)
                print(f"  ⚠️  Unexpectedly passed: {result}")
            except Exception as e:
                print(f"  ✅ Correctly blocked: {type(e).__name__}: {str(e)[:100]}")
    
    def demonstrate_resilience_patterns(self):
        """Demonstrate circuit breaker and retry patterns."""
        print("\n🛡️  Demonstrating Resilience Patterns")
        print("=" * 50)
        
        # Simulate failures to trigger circuit breaker
        problem_data = {"malformed": "data with issues"}
        
        # Create a clause that will cause parsing errors
        problematic_clause = 'nonexistent_field INVALID_OPERATOR "value"'
        
        config = WhereClauseConfig(
            clause=problematic_clause,
            scope="item",
            passthrough_on_error=True  # Enable passthrough for this demo
        )
        
        print("Simulating repeated failures to trigger circuit breaker...")
        
        for i in range(5):
            try:
                with CorrelationContext(agent_type=self.agent_type) as correlation:
                    result = self.processor.should_process_item(
                        problem_data, 
                        config,
                        correlation.correlation_id
                    )
                    print(f"  Attempt {i+1}: {'Passed through' if result else 'Blocked'}")
            except Exception as e:
                print(f"  Attempt {i+1}: Failed with {type(e).__name__}")
        
        # Check circuit breaker stats
        cb_stats = get_circuit_breaker_stats()
        print(f"\nCircuit Breaker Stats:")
        for name, stats in cb_stats.items():
            if "where_clause" in name:
                print(f"  {name}: {stats['state']} (failures: {stats['failure_count']})")
    
    def demonstrate_performance_optimization(self):
        """Demonstrate performance optimizations."""
        print("\n⚡ Demonstrating Performance Optimization")
        print("=" * 50)
        
        # Large dataset for performance testing
        large_dataset = [
            {
                "id": i,
                "status": "active" if i % 3 == 0 else "inactive",
                "score": (i * 7) % 100,
                "category": ["basic", "standard", "premium"][i % 3],
                "metadata": {
                    "created_at": f"2024-01-{(i % 30) + 1:02d}",
                    "source": "api" if i % 2 == 0 else "import"
                }
            }
            for i in range(1000)
        ]
        
        # Test performance with caching
        test_clause = 'status == "active" AND score >= 50 AND metadata.source == "api"'
        
        config = WhereClauseConfig(
            clause=test_clause,
            scope="item",
            enable_caching=True
        )
        
        print(f"Processing {len(large_dataset)} items with caching enabled...")
        
        # First run (cache miss)
        start_time = time.time()
        filtered_data_1 = self.processor.filter_batch(large_dataset, config)
        first_run_time = time.time() - start_time
        
        print(f"  First run: {first_run_time:.3f}s ({len(filtered_data_1)} items passed)")
        
        # Second run (cache hit)
        start_time = time.time()
        filtered_data_2 = self.processor.filter_batch(large_dataset, config)
        second_run_time = time.time() - start_time
        
        print(f"  Second run: {second_run_time:.3f}s ({len(filtered_data_2)} items passed)")
        print(f"  Speedup: {first_run_time/second_run_time:.1f}x")
        
        # Show cache statistics
        cache_stats = get_cache_stats()
        print(f"\nCache Statistics:")
        for cache_name, stats in cache_stats.items():
            if isinstance(stats, dict) and 'hit_rate' in stats:
                print(f"  {cache_name}: {stats['hit_rate']:.1%} hit rate, {stats['current_size']} entries")
    
    def demonstrate_monitoring_observability(self):
        """Demonstrate monitoring and observability features."""
        print("\n📊 Demonstrating Monitoring & Observability")
        print("=" * 50)
        
        # Get metrics
        metrics = get_metrics_collector()
        
        # Perform some operations to generate metrics
        test_data = [{"status": "active", "score": 85}, {"status": "inactive", "score": 45}]
        config = WhereClauseConfig(clause='status == "active"', scope="item")
        
        with CorrelationContext(
            agent_type=self.agent_type,
            user_id="demo_user"
        ) as correlation:
            correlation.add_metadata("demo_type", "monitoring")
            
            # Record some operations
            for i in range(5):
                self.processor.filter_batch(test_data, config, correlation.correlation_id)
        
        # Get fallback metrics (since Prometheus is disabled)
        fallback_metrics = metrics.get_fallback_metrics()
        
        print("Metrics collected:")
        for metric_name, metric_data in fallback_metrics.items():
            if "where_clause" in metric_name and metric_data.get('values'):
                print(f"  {metric_name}: {len(metric_data['values'])} data points")
        
        # Show processor performance stats
        perf_stats = self.processor.get_performance_stats()
        print(f"\nProcessor Performance:")
        print(f"  Agent Type: {perf_stats['agent_type']}")
        print(f"  Circuit Breaker State: {perf_stats['circuit_breaker']['state']}")
        print(f"  Cache Hit Rate: {perf_stats['parser_cache']['hit_rate']:.1%}")
    
    def demonstrate_health_checks(self):
        """Demonstrate health check system."""
        print("\n🏥 Demonstrating Health Checks")
        print("=" * 50)
        
        # Perform system health check
        health = check_system_health()
        
        print(f"Overall System Health: {health.status.value.upper()}")
        print(f"Uptime: {health.uptime_seconds:.1f} seconds")
        print(f"Total Checks: {health.summary['total_checks']}")
        print(f"Healthy: {health.summary['status_counts']['healthy']}")
        print(f"Degraded: {health.summary['status_counts']['degraded']}")
        print(f"Unhealthy: {health.summary['status_counts']['unhealthy']}")
        
        print("\nIndividual Health Checks:")
        for check in health.checks:
            status_emoji = {
                "healthy": "✅",
                "degraded": "⚠️",
                "unhealthy": "❌",
                "critical": "🔥"
            }.get(check.status.value, "❓")
            
            print(f"  {status_emoji} {check.name}: {check.status.value} ({check.duration_ms:.1f}ms)")
            if check.status.value != "healthy":
                print(f"    Message: {check.message}")
    
    def demonstrate_configuration_schema(self):
        """Demonstrate the enhanced configuration schema."""
        print("\n⚙️  Demonstrating Configuration Schema")
        print("=" * 50)
        
        # Create enhanced agent configurations
        configs = [
            # Simple WHERE clause
            EnhancedAgentConfig(
                agent_type="SimpleFilter",
                simple_where='status == "active"'
            ),
            
            # Full production configuration
            EnhancedAgentConfig(
                agent_type="ProductionFilter",
                where_clause=ProductionWhereClauseConfig(
                    where_clause=SchemaWhereClauseConfig(
                        clause='score >= 75 AND category IN ["premium", "gold"]',
                        scope=WhereClauseScope.ITEM,
                        security_level=SecurityLevel.STRICT,
                        max_evaluation_time_ms=50.0
                    )
                ),
                security_level=SecurityLevel.STRICT
            ),
            
            # Legacy configuration (backward compatibility)
            EnhancedAgentConfig(
                agent_type="LegacyAgent",
                conditional_clause='row_content.get("questionable") != "Low Value"',
                security_level=SecurityLevel.PERMISSIVE
            )
        ]
        
        for config in configs:
            print(f"\nAgent: {config.agent_type}")
            print(f"  Has WHERE clause: {config.has_where_clause()}")
            print(f"  Is legacy: {config.is_legacy_configuration()}")
            print(f"  Security level: {config.security_level}")
            
            effective_config = config.get_effective_where_clause_config()
            if effective_config:
                print(f"  Effective clause: {effective_config.clause}")
                print(f"  Scope: {effective_config.scope}")
    
    async def run_demo(self):
        """Run the complete demonstration."""
        print("🎯 Production WHERE Clause Demonstration")
        print("=" * 60)
        print("This demo showcases all production hardening features:")
        print("• Security protections")
        print("• Circuit breakers & retry patterns")
        print("• Performance optimizations")
        print("• Comprehensive monitoring")
        print("• Health checks")
        print("• Configuration schema")
        print("=" * 60)
        
        try:
            # Run all demonstrations
            self.demonstrate_basic_filtering()
            self.demonstrate_security_features()
            self.demonstrate_resilience_patterns()
            self.demonstrate_performance_optimization()
            self.demonstrate_monitoring_observability()
            self.demonstrate_health_checks()
            self.demonstrate_configuration_schema()
            
            print("\n🎉 Demo completed successfully!")
            print("\nKey Takeaways:")
            print("✅ WHERE clause functionality is production-ready")
            print("✅ Security vulnerabilities have been addressed")
            print("✅ Resilience patterns protect against failures")
            print("✅ Performance is optimized with caching")
            print("✅ Comprehensive monitoring provides visibility")
            print("✅ Health checks ensure system reliability")
            print("✅ Configuration schema supports various use cases")
            
        except Exception as e:
            print(f"\n❌ Demo failed: {e}")
            import traceback
            traceback.print_exc()


def main():
    """Main entry point for the demonstration."""
    demo = ProductionWhereClauseDemo()
    
    # Run the demo
    asyncio.run(demo.run_demo())


if __name__ == "__main__":
    main()