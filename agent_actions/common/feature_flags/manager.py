"""
Production-grade feature flag system for WHERE clause functionality.
Provides gradual rollout, A/B testing, and emergency kill switches.
"""
import json
import threading
import time
import hashlib
from typing import Dict, Any, Optional, List, Callable, Union
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import logging

from ..monitoring.metrics import get_metrics_collector, set_feature_flag_status
from ..monitoring.logging import get_logger, LoggingContext

logger = logging.getLogger(__name__)


class RolloutStrategy(Enum):
    """Rollout strategies for feature flags."""
    ALL_ON = "all_on"
    ALL_OFF = "all_off"
    PERCENTAGE = "percentage"
    USER_LIST = "user_list"
    AGENT_TYPE = "agent_type"
    CANARY = "canary"
    A_B_TEST = "a_b_test"


@dataclass
class FeatureFlagRule:
    """Individual rule for feature flag evaluation."""
    name: str
    strategy: RolloutStrategy
    enabled: bool = True
    percentage: float = 0.0  # 0-100
    user_ids: List[str] = None
    agent_types: List[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.user_ids is None:
            self.user_ids = []
        if self.agent_types is None:
            self.agent_types = []
        if self.metadata is None:
            self.metadata = {}


@dataclass
class FeatureFlag:
    """Feature flag configuration."""
    name: str
    description: str
    enabled: bool = False
    rules: List[FeatureFlagRule] = None
    emergency_kill_switch: bool = False
    created_at: str = None
    updated_at: str = None
    
    def __post_init__(self):
        if self.rules is None:
            self.rules = []
        if self.created_at is None:
            self.created_at = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
        if self.updated_at is None:
            self.updated_at = self.created_at


class FeatureFlagContext:
    """Context for feature flag evaluation."""
    
    def __init__(
        self,
        user_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        custom_attributes: Optional[Dict[str, Any]] = None
    ):
        self.user_id = user_id
        self.agent_type = agent_type
        self.session_id = session_id
        self.correlation_id = correlation_id
        self.custom_attributes = custom_attributes or {}
    
    def get_hash_key(self) -> str:
        """Generate hash key for consistent percentage-based rollouts."""
        components = [
            self.user_id or "",
            self.agent_type or "",
            self.session_id or ""
        ]
        return hashlib.md5("|".join(components).encode()).hexdigest()


class FeatureFlagManager:
    """
    Production-grade feature flag manager with comprehensive monitoring.
    Supports various rollout strategies and emergency controls.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.flags: Dict[str, FeatureFlag] = {}
        self._lock = threading.RLock()
        self._watchers: List[Callable[[str, bool, bool], None]] = []
        
        # Monitoring
        self.metrics = get_metrics_collector()
        self.structured_logger = get_logger()
        
        # Load initial configuration
        if config_path:
            self.load_from_file(config_path)
        
        # Initialize default WHERE clause flags
        self._initialize_where_clause_flags()
    
    def _initialize_where_clause_flags(self):
        """Initialize default feature flags for WHERE clause functionality."""
        default_flags = [
            FeatureFlag(
                name="where_clause_enabled",
                description="Enable WHERE clause filtering functionality",
                enabled=False,  # Start disabled for safety
                rules=[
                    FeatureFlagRule(
                        name="gradual_rollout",
                        strategy=RolloutStrategy.PERCENTAGE,
                        enabled=True,
                        percentage=0.0  # Start at 0%
                    )
                ]
            ),
            FeatureFlag(
                name="where_clause_caching",
                description="Enable caching for WHERE clause parsing",
                enabled=False,
                rules=[
                    FeatureFlagRule(
                        name="performance_feature",
                        strategy=RolloutStrategy.PERCENTAGE,
                        enabled=True,
                        percentage=0.0
                    )
                ]
            ),
            FeatureFlag(
                name="where_clause_advanced_operators",
                description="Enable advanced operators (OR, LIKE, etc.)",
                enabled=False,
                rules=[
                    FeatureFlagRule(
                        name="beta_feature",
                        strategy=RolloutStrategy.AGENT_TYPE,
                        enabled=False,
                        agent_types=["test_agent"]
                    )
                ]
            ),
            FeatureFlag(
                name="where_clause_debug_mode",
                description="Enable debug mode for WHERE clause evaluation",
                enabled=False,
                rules=[
                    FeatureFlagRule(
                        name="debug_users",
                        strategy=RolloutStrategy.USER_LIST,
                        enabled=True,
                        user_ids=["admin", "developer"]
                    )
                ]
            ),
            FeatureFlag(
                name="where_clause_security_mode",
                description="Enable enhanced security checks",
                enabled=True,  # Security should be on by default
                rules=[
                    FeatureFlagRule(
                        name="security_always_on",
                        strategy=RolloutStrategy.ALL_ON,
                        enabled=True
                    )
                ]
            )
        ]
        
        for flag in default_flags:
            self.register_flag(flag)
    
    def register_flag(self, flag: FeatureFlag):
        """Register a feature flag."""
        with self._lock:
            old_enabled = None
            if flag.name in self.flags:
                old_enabled = self.flags[flag.name].enabled
            
            self.flags[flag.name] = flag
            
            # Update metrics
            set_feature_flag_status(flag.name, "default", flag.enabled)
            
            # Log registration
            self.structured_logger.info(
                f"Feature flag registered: {flag.name}",
                context={'component': 'feature_flags', 'operation': 'register'},
                error_details={
                    'flag_name': flag.name,
                    'enabled': flag.enabled,
                    'rules_count': len(flag.rules),
                    'emergency_kill_switch': flag.emergency_kill_switch
                }
            )
            
            # Notify watchers if status changed
            if old_enabled is not None and old_enabled != flag.enabled:
                self._notify_watchers(flag.name, old_enabled, flag.enabled)
    
    def is_enabled(
        self,
        flag_name: str,
        context: Optional[FeatureFlagContext] = None,
        default: bool = False
    ) -> bool:
        """
        Check if a feature flag is enabled for the given context.
        
        Args:
            flag_name: Name of the feature flag
            context: Evaluation context
            default: Default value if flag doesn't exist
            
        Returns:
            True if flag is enabled, False otherwise
        """
        start_time = time.time()
        
        try:
            with self._lock:
                flag = self.flags.get(flag_name)
                if not flag:
                    self.structured_logger.warning(
                        f"Feature flag not found: {flag_name}",
                        context={'component': 'feature_flags', 'operation': 'evaluation'},
                        error_details={'flag_name': flag_name, 'default_used': default}
                    )
                    return default
                
                # Check emergency kill switch
                if flag.emergency_kill_switch:
                    self.structured_logger.warning(
                        f"Feature flag {flag_name} disabled by emergency kill switch",
                        context={'component': 'feature_flags', 'operation': 'kill_switch'}
                    )
                    return False
                
                # If flag is globally disabled
                if not flag.enabled:
                    return False
                
                # Evaluate rules
                result = self._evaluate_rules(flag, context)
                
                # Record metrics
                evaluation_time = time.time() - start_time
                self.metrics.increment_counter(
                    "feature_flag_evaluations_total",
                    {
                        'flag_name': flag_name,
                        'result': str(result),
                        'agent_type': context.agent_type if context else 'unknown'
                    }
                )
                self.metrics.observe_histogram(
                    "feature_flag_evaluation_duration_seconds",
                    {'flag_name': flag_name},
                    evaluation_time
                )
                
                # Log evaluation (debug level to avoid spam)
                self.structured_logger.debug(
                    f"Feature flag evaluated: {flag_name} = {result}",
                    context={'component': 'feature_flags', 'operation': 'evaluation'},
                    performance_metrics={
                        'flag_name': flag_name,
                        'result': result,
                        'evaluation_time_ms': evaluation_time * 1000,
                        'rules_count': len(flag.rules)
                    }
                )
                
                return result
        
        except Exception as e:
            evaluation_time = time.time() - start_time
            self.structured_logger.error(
                f"Error evaluating feature flag {flag_name}",
                context={'component': 'feature_flags', 'operation': 'evaluation_error'},
                error_details={
                    'flag_name': flag_name,
                    'exception_type': type(e).__name__,
                    'exception_message': str(e),
                    'evaluation_time_ms': evaluation_time * 1000
                }
            )
            
            # Return default on error
            return default
    
    def _evaluate_rules(self, flag: FeatureFlag, context: Optional[FeatureFlagContext]) -> bool:
        """Evaluate feature flag rules."""
        if not flag.rules:
            return True
        
        # Evaluate each rule
        for rule in flag.rules:
            if not rule.enabled:
                continue
                
            result = self._evaluate_single_rule(rule, context)
            if result:
                return True
        
        return False
    
    def _evaluate_single_rule(self, rule: FeatureFlagRule, context: Optional[FeatureFlagContext]) -> bool:
        """Evaluate a single feature flag rule."""
        if rule.strategy == RolloutStrategy.ALL_ON:
            return True
        
        elif rule.strategy == RolloutStrategy.ALL_OFF:
            return False
        
        elif rule.strategy == RolloutStrategy.PERCENTAGE:
            if not context:
                return False
            
            hash_key = context.get_hash_key()
            hash_value = int(hashlib.md5(hash_key.encode()).hexdigest()[:8], 16)
            percentage_bucket = (hash_value % 100) + 1
            return percentage_bucket <= rule.percentage
        
        elif rule.strategy == RolloutStrategy.USER_LIST:
            if not context or not context.user_id:
                return False
            return context.user_id in rule.user_ids
        
        elif rule.strategy == RolloutStrategy.AGENT_TYPE:
            if not context or not context.agent_type:
                return False
            return context.agent_type in rule.agent_types
        
        elif rule.strategy == RolloutStrategy.CANARY:
            # Canary is like percentage but for specific users/agents
            if not context:
                return False
            
            # Check if user/agent is in canary list
            if context.user_id in rule.user_ids or context.agent_type in rule.agent_types:
                return True
            
            # Otherwise use percentage
            hash_key = context.get_hash_key()
            hash_value = int(hashlib.md5(hash_key.encode()).hexdigest()[:8], 16)
            percentage_bucket = (hash_value % 100) + 1
            return percentage_bucket <= rule.percentage
        
        elif rule.strategy == RolloutStrategy.A_B_TEST:
            # A/B test assigns users to variant A or B
            if not context:
                return False
            
            hash_key = context.get_hash_key()
            hash_value = int(hashlib.md5(hash_key.encode()).hexdigest()[:8], 16)
            variant = "A" if hash_value % 2 == 0 else "B"
            
            # Rule metadata should contain variant assignment
            target_variant = rule.metadata.get("variant", "A")
            return variant == target_variant and (hash_value % 100) + 1 <= rule.percentage
        
        return False
    
    def set_emergency_kill_switch(self, flag_name: str, enabled: bool):
        """Set emergency kill switch for a flag."""
        with self._lock:
            flag = self.flags.get(flag_name)
            if not flag:
                raise ValueError(f"Feature flag not found: {flag_name}")
            
            old_kill_switch = flag.emergency_kill_switch
            flag.emergency_kill_switch = enabled
            flag.updated_at = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
            
            self.structured_logger.warning(
                f"Emergency kill switch {'enabled' if enabled else 'disabled'} for {flag_name}",
                context={'component': 'feature_flags', 'operation': 'kill_switch'},
                error_details={
                    'flag_name': flag_name,
                    'old_value': old_kill_switch,
                    'new_value': enabled
                }
            )
    
    def update_percentage_rollout(self, flag_name: str, rule_name: str, percentage: float):
        """Update percentage rollout for a specific rule."""
        if not 0 <= percentage <= 100:
            raise ValueError("Percentage must be between 0 and 100")
        
        with self._lock:
            flag = self.flags.get(flag_name)
            if not flag:
                raise ValueError(f"Feature flag not found: {flag_name}")
            
            rule = next((r for r in flag.rules if r.name == rule_name), None)
            if not rule:
                raise ValueError(f"Rule not found: {rule_name}")
            
            old_percentage = rule.percentage
            rule.percentage = percentage
            flag.updated_at = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
            
            self.structured_logger.info(
                f"Updated percentage rollout for {flag_name}.{rule_name}: {old_percentage}% -> {percentage}%",
                context={'component': 'feature_flags', 'operation': 'percentage_update'},
                error_details={
                    'flag_name': flag_name,
                    'rule_name': rule_name,
                    'old_percentage': old_percentage,
                    'new_percentage': percentage
                }
            )
    
    def add_watcher(self, callback: Callable[[str, bool, bool], None]):
        """Add a watcher for feature flag changes."""
        self._watchers.append(callback)
    
    def _notify_watchers(self, flag_name: str, old_value: bool, new_value: bool):
        """Notify watchers of flag changes."""
        for watcher in self._watchers:
            try:
                watcher(flag_name, old_value, new_value)
            except Exception as e:
                self.structured_logger.error(
                    f"Error in feature flag watcher: {e}",
                    context={'component': 'feature_flags', 'operation': 'watcher_error'},
                    error_details={
                        'flag_name': flag_name,
                        'exception_type': type(e).__name__,
                        'exception_message': str(e)
                    }
                )
    
    def get_flag_status(self, flag_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed status of a feature flag."""
        with self._lock:
            flag = self.flags.get(flag_name)
            if not flag:
                return None
            
            return {
                'name': flag.name,
                'description': flag.description,
                'enabled': flag.enabled,
                'emergency_kill_switch': flag.emergency_kill_switch,
                'rules_count': len(flag.rules),
                'rules': [
                    {
                        'name': rule.name,
                        'strategy': rule.strategy.value,
                        'enabled': rule.enabled,
                        'percentage': rule.percentage,
                        'user_ids_count': len(rule.user_ids),
                        'agent_types_count': len(rule.agent_types)
                    }
                    for rule in flag.rules
                ],
                'created_at': flag.created_at,
                'updated_at': flag.updated_at
            }
    
    def get_all_flags_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all feature flags."""
        with self._lock:
            return {name: self.get_flag_status(name) for name in self.flags.keys()}
    
    def load_from_file(self, config_path: str):
        """Load feature flags from configuration file."""
        try:
            with open(config_path, 'r') as f:
                config_data = json.load(f)
            
            for flag_data in config_data.get('flags', []):
                # Convert rules
                rules = []
                for rule_data in flag_data.get('rules', []):
                    rule = FeatureFlagRule(
                        name=rule_data['name'],
                        strategy=RolloutStrategy(rule_data['strategy']),
                        enabled=rule_data.get('enabled', True),
                        percentage=rule_data.get('percentage', 0.0),
                        user_ids=rule_data.get('user_ids', []),
                        agent_types=rule_data.get('agent_types', []),
                        metadata=rule_data.get('metadata', {})
                    )
                    rules.append(rule)
                
                flag = FeatureFlag(
                    name=flag_data['name'],
                    description=flag_data.get('description', ''),
                    enabled=flag_data.get('enabled', False),
                    rules=rules,
                    emergency_kill_switch=flag_data.get('emergency_kill_switch', False),
                    created_at=flag_data.get('created_at'),
                    updated_at=flag_data.get('updated_at')
                )
                
                self.register_flag(flag)
            
            self.structured_logger.info(
                f"Loaded {len(config_data.get('flags', []))} feature flags from {config_path}",
                context={'component': 'feature_flags', 'operation': 'load_config'}
            )
        
        except Exception as e:
            self.structured_logger.error(
                f"Failed to load feature flags from {config_path}",
                context={'component': 'feature_flags', 'operation': 'load_config_error'},
                error_details={
                    'config_path': config_path,
                    'exception_type': type(e).__name__,
                    'exception_message': str(e)
                }
            )
            raise
    
    def save_to_file(self, config_path: str):
        """Save feature flags to configuration file."""
        try:
            config_data = {
                'flags': [
                    {
                        'name': flag.name,
                        'description': flag.description,
                        'enabled': flag.enabled,
                        'emergency_kill_switch': flag.emergency_kill_switch,
                        'created_at': flag.created_at,
                        'updated_at': flag.updated_at,
                        'rules': [
                            {
                                'name': rule.name,
                                'strategy': rule.strategy.value,
                                'enabled': rule.enabled,
                                'percentage': rule.percentage,
                                'user_ids': rule.user_ids,
                                'agent_types': rule.agent_types,
                                'metadata': rule.metadata
                            }
                            for rule in flag.rules
                        ]
                    }
                    for flag in self.flags.values()
                ]
            }
            
            with open(config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            self.structured_logger.info(
                f"Saved {len(self.flags)} feature flags to {config_path}",
                context={'component': 'feature_flags', 'operation': 'save_config'}
            )
        
        except Exception as e:
            self.structured_logger.error(
                f"Failed to save feature flags to {config_path}",
                context={'component': 'feature_flags', 'operation': 'save_config_error'},
                error_details={
                    'config_path': config_path,
                    'exception_type': type(e).__name__,
                    'exception_message': str(e)
                }
            )
            raise


# Global feature flag manager
_feature_flag_manager: Optional[FeatureFlagManager] = None
_manager_lock = threading.Lock()


def get_feature_flag_manager() -> FeatureFlagManager:
    """Get or create the global feature flag manager."""
    global _feature_flag_manager
    
    if _feature_flag_manager is None:
        with _manager_lock:
            if _feature_flag_manager is None:
                _feature_flag_manager = FeatureFlagManager()
    
    return _feature_flag_manager


def init_feature_flags(config_path: Optional[str] = None) -> FeatureFlagManager:
    """Initialize the global feature flag manager."""
    global _feature_flag_manager
    
    with _manager_lock:
        _feature_flag_manager = FeatureFlagManager(config_path=config_path)
    
    return _feature_flag_manager


# Convenience functions
def is_enabled(flag_name: str, context: Optional[FeatureFlagContext] = None, default: bool = False) -> bool:
    """Check if a feature flag is enabled."""
    manager = get_feature_flag_manager()
    return manager.is_enabled(flag_name, context, default)


def where_clause_enabled(agent_type: str, user_id: Optional[str] = None) -> bool:
    """Check if WHERE clause functionality is enabled for the given context."""
    context = FeatureFlagContext(agent_type=agent_type, user_id=user_id)
    return is_enabled("where_clause_enabled", context, default=False)


def where_clause_caching_enabled(agent_type: str, user_id: Optional[str] = None) -> bool:
    """Check if WHERE clause caching is enabled."""
    context = FeatureFlagContext(agent_type=agent_type, user_id=user_id)
    return is_enabled("where_clause_caching", context, default=False)


def where_clause_debug_enabled(agent_type: str, user_id: Optional[str] = None) -> bool:
    """Check if WHERE clause debug mode is enabled."""
    context = FeatureFlagContext(agent_type=agent_type, user_id=user_id)
    return is_enabled("where_clause_debug_mode", context, default=False)


def where_clause_security_enabled(agent_type: str, user_id: Optional[str] = None) -> bool:
    """Check if WHERE clause enhanced security is enabled."""
    context = FeatureFlagContext(agent_type=agent_type, user_id=user_id)
    return is_enabled("where_clause_security_mode", context, default=True)  # Default to secure