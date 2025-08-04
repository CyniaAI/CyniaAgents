"""
Error recovery and fallback mechanisms for hot reload operations.

This module provides comprehensive error recovery strategies, automatic fallback
mechanisms, and state restoration capabilities for failed reload operations.
"""

import sys
import time
import traceback
from typing import Dict, List, Optional, Any, Callable, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field

from .models import ComponentStatus, ComponentMetadata, ReloadResult, OperationType
from .cache import ModuleCache, ComponentStateTracker
from .errors import ErrorHandler, ErrorReport, ErrorSeverity


class RecoveryStrategy(Enum):
    """Available error recovery strategies."""
    RETRY = "retry"
    FALLBACK = "fallback"
    ROLLBACK = "rollback"
    ISOLATE = "isolate"
    SKIP = "skip"


class RecoveryAction(Enum):
    """Actions that can be taken during recovery."""
    RETRY_OPERATION = "retry_operation"
    SWITCH_STRATEGY = "switch_strategy"
    RESTORE_BACKUP = "restore_backup"
    CLEAR_CACHE = "clear_cache"
    FORCE_CLEANUP = "force_cleanup"
    ISOLATE_COMPONENT = "isolate_component"
    DISABLE_COMPONENT = "disable_component"


@dataclass
class RecoveryPlan:
    """Plan for recovering from a failed operation."""
    component_name: str
    failed_operation: OperationType
    error_type: str
    recovery_strategy: RecoveryStrategy
    actions: List[RecoveryAction] = field(default_factory=list)
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout: float = 30.0
    fallback_strategy: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    def is_expired(self) -> bool:
        """Check if the recovery plan has expired."""
        return datetime.now() - self.created_at > timedelta(seconds=self.timeout)
    
    def should_retry(self, attempt: int) -> bool:
        """Check if operation should be retried."""
        return attempt <= self.max_retries and not self.is_expired()


@dataclass
class RecoveryAttempt:
    """Record of a recovery attempt."""
    plan: RecoveryPlan
    attempt_number: int
    actions_taken: List[RecoveryAction] = field(default_factory=list)
    success: bool = False
    error_message: Optional[str] = None
    duration: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def add_action(self, action: RecoveryAction):
        """Add an action to the attempt record."""
        self.actions_taken.append(action)


class ErrorRecoveryManager:
    """
    Manages error recovery and fallback mechanisms for hot reload operations.
    
    This class provides intelligent error recovery by analyzing failures,
    creating recovery plans, and executing appropriate recovery strategies.
    """
    
    def __init__(self, module_cache: ModuleCache, state_tracker: ComponentStateTracker,
                 error_handler: ErrorHandler):
        self.module_cache = module_cache
        self.state_tracker = state_tracker
        self.error_handler = error_handler
        
        # Recovery tracking
        self._recovery_plans: Dict[str, RecoveryPlan] = {}
        self._recovery_history: Dict[str, List[RecoveryAttempt]] = {}
        self._component_backups: Dict[str, Dict[str, Any]] = {}
        
        # Recovery strategy mappings
        self._error_strategy_map = {
            'import_error': RecoveryStrategy.RETRY,
            'dependency_error': RecoveryStrategy.FALLBACK,
            'syntax_error': RecoveryStrategy.ROLLBACK,
            'runtime_error': RecoveryStrategy.RETRY,
            'memory_error': RecoveryStrategy.ISOLATE,
            'timeout_error': RecoveryStrategy.SKIP,
            'general_error': RecoveryStrategy.RETRY
        }
        
        # Action generators for different strategies
        self._strategy_actions = {
            RecoveryStrategy.RETRY: self._generate_retry_actions,
            RecoveryStrategy.FALLBACK: self._generate_fallback_actions,
            RecoveryStrategy.ROLLBACK: self._generate_rollback_actions,
            RecoveryStrategy.ISOLATE: self._generate_isolate_actions,
            RecoveryStrategy.SKIP: self._generate_skip_actions
        }
        
        # Recovery statistics
        self._recovery_stats = {
            'total_recoveries': 0,
            'successful_recoveries': 0,
            'failed_recoveries': 0,
            'retries_performed': 0,
            'fallbacks_used': 0,
            'rollbacks_performed': 0,
            'components_isolated': 0
        }
    
    def create_recovery_plan(self, component_name: str, failed_result: ReloadResult) -> RecoveryPlan:
        """
        Create a recovery plan based on the failed operation.
        
        Args:
            component_name: Name of the component that failed
            failed_result: Result of the failed operation
            
        Returns:
            RecoveryPlan: Plan for recovering from the failure
        """
        # Determine error type
        error_type = self._categorize_error(failed_result.error_message or "unknown")
        
        # Select recovery strategy
        strategy = self._error_strategy_map.get(error_type, RecoveryStrategy.RETRY)
        
        # Create plan
        plan = RecoveryPlan(
            component_name=component_name,
            failed_operation=failed_result.operation,
            error_type=error_type,
            recovery_strategy=strategy,
            max_retries=self._get_max_retries(error_type),
            retry_delay=self._get_retry_delay(error_type),
            timeout=self._get_timeout(error_type),
            fallback_strategy=self._get_fallback_strategy(error_type)
        )
        
        # Generate actions for the strategy
        actions = self._strategy_actions[strategy](component_name, failed_result)
        plan.actions = actions
        
        # Store plan
        self._recovery_plans[component_name] = plan
        
        return plan
    
    def execute_recovery(self, component_name: str, recovery_function: Callable) -> ReloadResult:
        """
        Execute recovery for a component using the stored recovery plan.
        
        Args:
            component_name: Name of the component to recover
            recovery_function: Function to call for recovery (e.g., reload_component)
            
        Returns:
            ReloadResult: Result of the recovery operation
        """
        plan = self._recovery_plans.get(component_name)
        if not plan:
            return ReloadResult(
                component_name=component_name,
                operation=OperationType.RELOAD,
                success=False,
                status=ComponentStatus.FAILED,
                previous_status=ComponentStatus.UNKNOWN,
                error_message="No recovery plan found"
            )
        
        self._recovery_stats['total_recoveries'] += 1
        
        # Execute recovery attempts
        for attempt_num in range(plan.max_retries + 1):
            if not plan.should_retry(attempt_num):
                break
            
            attempt = RecoveryAttempt(plan=plan, attempt_number=attempt_num)
            start_time = time.time()
            
            try:
                # Execute recovery actions
                self._execute_recovery_actions(component_name, plan.actions, attempt)
                
                # Wait before retry if not first attempt
                if attempt_num > 0:
                    time.sleep(plan.retry_delay)
                
                # Attempt the operation
                result = recovery_function()
                
                attempt.duration = time.time() - start_time
                
                if result.success:
                    attempt.success = True
                    self._recovery_stats['successful_recoveries'] += 1
                    self._recovery_stats['retries_performed'] += attempt_num
                    
                    # Store successful attempt
                    self._store_recovery_attempt(component_name, attempt)
                    
                    # Clean up recovery plan
                    self._recovery_plans.pop(component_name, None)
                    
                    return result
                else:
                    attempt.error_message = result.error_message
                    
                    # Try fallback strategy if available
                    if plan.fallback_strategy and attempt_num == plan.max_retries:
                        fallback_result = self._try_fallback_strategy(
                            component_name, plan.fallback_strategy, recovery_function
                        )
                        if fallback_result.success:
                            self._recovery_stats['successful_recoveries'] += 1
                            self._recovery_stats['fallbacks_used'] += 1
                            return fallback_result
                
            except Exception as e:
                attempt.error_message = str(e)
                attempt.duration = time.time() - start_time
            
            # Store failed attempt
            self._store_recovery_attempt(component_name, attempt)
        
        # All recovery attempts failed
        self._recovery_stats['failed_recoveries'] += 1
        
        return ReloadResult(
            component_name=component_name,
            operation=plan.failed_operation,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.UNKNOWN,
            error_message=f"Recovery failed after {plan.max_retries} attempts"
        )
    
    def create_component_backup(self, component_name: str) -> bool:
        """
        Create a backup of the component's current state.
        
        Args:
            component_name: Name of the component to backup
            
        Returns:
            bool: True if backup was created successfully
        """
        try:
            component_state = self.state_tracker.get_component_state(component_name)
            if not component_state:
                return False
            
            # Create backup
            backup = {
                'timestamp': datetime.now(),
                'component_state': component_state,
                'modules': {},
                'sys_modules': {}
            }
            
            # Backup modules
            component_modules = self.module_cache.get_component_modules(component_name)
            for module_name in component_modules:
                if module_name in sys.modules:
                    backup['sys_modules'][module_name] = sys.modules[module_name]
                
                module_info = self.module_cache.get_module_info(module_name)
                if module_info:
                    backup['modules'][module_name] = {
                        'file_path': module_info.file_path,
                        'load_time': module_info.load_time,
                        'access_count': module_info.access_count
                    }
            
            self._component_backups[component_name] = backup
            return True
            
        except Exception as e:
            print(f"Failed to create backup for {component_name}: {e}")
            return False
    
    def restore_component_backup(self, component_name: str) -> bool:
        """
        Restore a component from backup.
        
        Args:
            component_name: Name of the component to restore
            
        Returns:
            bool: True if restore was successful
        """
        try:
            backup = self._component_backups.get(component_name)
            if not backup:
                return False
            
            # Restore sys.modules
            for module_name, module in backup['sys_modules'].items():
                sys.modules[module_name] = module
            
            # Restore module cache
            for module_name, module_data in backup['modules'].items():
                if module_name in sys.modules:
                    self.module_cache.add_module(
                        module_name, sys.modules[module_name], 
                        component_name, module_data.get('file_path')
                    )
            
            # Restore component state
            component_state = backup['component_state']
            self.state_tracker.track_component(component_name, component_state.metadata)
            self.state_tracker.update_component_status(component_name, ComponentStatus.LOADED)
            
            return True
            
        except Exception as e:
            print(f"Failed to restore backup for {component_name}: {e}")
            return False
    
    def get_recovery_statistics(self) -> Dict[str, Any]:
        """
        Get recovery statistics.
        
        Returns:
            Dictionary with recovery statistics
        """
        return {
            'operations': self._recovery_stats.copy(),
            'active_plans': len(self._recovery_plans),
            'components_with_history': len(self._recovery_history),
            'backups_available': len(self._component_backups)
        }
    
    def clear_recovery_data(self, component_name: Optional[str] = None):
        """
        Clear recovery data for a component or all components.
        
        Args:
            component_name: Component to clear data for, or None for all
        """
        if component_name:
            self._recovery_plans.pop(component_name, None)
            self._recovery_history.pop(component_name, None)
            self._component_backups.pop(component_name, None)
        else:
            self._recovery_plans.clear()
            self._recovery_history.clear()
            self._component_backups.clear()
    
    def _categorize_error(self, error_message: str) -> str:
        """Categorize an error based on its message."""
        error_msg = error_message.lower()
        
        if "import" in error_msg or "module" in error_msg:
            return "import_error"
        elif "dependency" in error_msg or "requirement" in error_msg:
            return "dependency_error"
        elif "syntax" in error_msg or "invalid syntax" in error_msg:
            return "syntax_error"
        elif "memory" in error_msg or "out of memory" in error_msg:
            return "memory_error"
        elif "timeout" in error_msg or "timed out" in error_msg:
            return "timeout_error"
        elif any(keyword in error_msg for keyword in ["runtime", "attribute", "type", "value"]):
            return "runtime_error"
        else:
            return "general_error"
    
    def _get_max_retries(self, error_type: str) -> int:
        """Get maximum retries for an error type."""
        retry_map = {
            'import_error': 3,
            'dependency_error': 2,
            'syntax_error': 1,
            'runtime_error': 3,
            'memory_error': 1,
            'timeout_error': 2,
            'general_error': 2
        }
        return retry_map.get(error_type, 2)
    
    def _get_retry_delay(self, error_type: str) -> float:
        """Get retry delay for an error type."""
        delay_map = {
            'import_error': 1.0,
            'dependency_error': 2.0,
            'syntax_error': 0.5,
            'runtime_error': 1.0,
            'memory_error': 3.0,
            'timeout_error': 5.0,
            'general_error': 1.0
        }
        return delay_map.get(error_type, 1.0)
    
    def _get_timeout(self, error_type: str) -> float:
        """Get timeout for an error type."""
        timeout_map = {
            'import_error': 30.0,
            'dependency_error': 60.0,
            'syntax_error': 15.0,
            'runtime_error': 30.0,
            'memory_error': 45.0,
            'timeout_error': 90.0,
            'general_error': 30.0
        }
        return timeout_map.get(error_type, 30.0)
    
    def _get_fallback_strategy(self, error_type: str) -> Optional[str]:
        """Get fallback strategy for an error type."""
        fallback_map = {
            'import_error': 'full',
            'dependency_error': None,  # No fallback for dependency errors
            'syntax_error': None,      # No fallback for syntax errors
            'runtime_error': 'full',
            'memory_error': None,      # No fallback for memory errors
            'timeout_error': 'incremental',
            'general_error': 'full'
        }
        return fallback_map.get(error_type)
    
    def _generate_retry_actions(self, component_name: str, failed_result: ReloadResult) -> List[RecoveryAction]:
        """Generate actions for retry strategy."""
        actions = [RecoveryAction.CLEAR_CACHE]
        
        if failed_result.operation == OperationType.RELOAD:
            actions.append(RecoveryAction.RETRY_OPERATION)
        
        return actions
    
    def _generate_fallback_actions(self, component_name: str, failed_result: ReloadResult) -> List[RecoveryAction]:
        """Generate actions for fallback strategy."""
        return [
            RecoveryAction.CLEAR_CACHE,
            RecoveryAction.SWITCH_STRATEGY,
            RecoveryAction.RETRY_OPERATION
        ]
    
    def _generate_rollback_actions(self, component_name: str, failed_result: ReloadResult) -> List[RecoveryAction]:
        """Generate actions for rollback strategy."""
        return [
            RecoveryAction.RESTORE_BACKUP,
            RecoveryAction.CLEAR_CACHE
        ]
    
    def _generate_isolate_actions(self, component_name: str, failed_result: ReloadResult) -> List[RecoveryAction]:
        """Generate actions for isolate strategy."""
        return [
            RecoveryAction.ISOLATE_COMPONENT,
            RecoveryAction.FORCE_CLEANUP
        ]
    
    def _generate_skip_actions(self, component_name: str, failed_result: ReloadResult) -> List[RecoveryAction]:
        """Generate actions for skip strategy."""
        return [
            RecoveryAction.DISABLE_COMPONENT,
            RecoveryAction.CLEAR_CACHE
        ]
    
    def _execute_recovery_actions(self, component_name: str, actions: List[RecoveryAction], 
                                 attempt: RecoveryAttempt):
        """Execute recovery actions."""
        for action in actions:
            try:
                if action == RecoveryAction.CLEAR_CACHE:
                    # Clear importlib cache
                    import importlib
                    importlib.invalidate_caches()
                    attempt.add_action(action)
                
                elif action == RecoveryAction.FORCE_CLEANUP:
                    # Force garbage collection
                    import gc
                    gc.collect()
                    attempt.add_action(action)
                
                elif action == RecoveryAction.RESTORE_BACKUP:
                    # Restore from backup
                    if self.restore_component_backup(component_name):
                        attempt.add_action(action)
                
                elif action == RecoveryAction.ISOLATE_COMPONENT:
                    # Isolate component
                    self.error_handler.component_isolator.isolate_component_error(
                        component_name, Exception("Recovery isolation"), "recovery"
                    )
                    attempt.add_action(action)
                
                elif action == RecoveryAction.DISABLE_COMPONENT:
                    # Disable component
                    component_state = self.state_tracker.get_component_state(component_name)
                    if component_state:
                        component_state.is_enabled = False
                        attempt.add_action(action)
                
            except Exception as e:
                print(f"Failed to execute recovery action {action}: {e}")
    
    def _try_fallback_strategy(self, component_name: str, fallback_strategy: str, 
                              recovery_function: Callable) -> ReloadResult:
        """Try a fallback strategy."""
        try:
            # This would integrate with the HotReloadManager to use a different strategy
            # For now, just attempt the operation again
            return recovery_function()
        except Exception as e:
            return ReloadResult(
                component_name=component_name,
                operation=OperationType.RELOAD,
                success=False,
                status=ComponentStatus.FAILED,
                previous_status=ComponentStatus.UNKNOWN,
                error_message=f"Fallback strategy failed: {str(e)}"
            )
    
    def _store_recovery_attempt(self, component_name: str, attempt: RecoveryAttempt):
        """Store a recovery attempt in history."""
        if component_name not in self._recovery_history:
            self._recovery_history[component_name] = []
        
        self._recovery_history[component_name].append(attempt)
        
        # Keep only last 10 attempts per component
        if len(self._recovery_history[component_name]) > 10:
            self._recovery_history[component_name] = self._recovery_history[component_name][-10:]