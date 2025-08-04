"""
Unit tests for the ErrorRecoveryManager class.

This module provides comprehensive tests for error recovery functionality
including recovery plans, fallback strategies, and automatic error handling.
"""

import unittest
import sys
import tempfile
import shutil
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

# Add the parent directory to the path to import hot_reload modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from hot_reload.error_recovery import (
    ErrorRecoveryManager, RecoveryPlan, RecoveryAttempt, RecoveryStrategy, RecoveryAction
)
from hot_reload.models import ComponentStatus, ComponentMetadata, ReloadResult, OperationType
from hot_reload.cache import ModuleCache, ComponentStateTracker
from hot_reload.errors import ErrorHandler


class TestRecoveryPlan(unittest.TestCase):
    """Test cases for RecoveryPlan."""
    
    def test_initialization(self):
        """Test RecoveryPlan initialization."""
        plan = RecoveryPlan(
            component_name="test_component",
            failed_operation=OperationType.RELOAD,
            error_type="import_error",
            recovery_strategy=RecoveryStrategy.RETRY
        )
        
        self.assertEqual(plan.component_name, "test_component")
        self.assertEqual(plan.failed_operation, OperationType.RELOAD)
        self.assertEqual(plan.error_type, "import_error")
        self.assertEqual(plan.recovery_strategy, RecoveryStrategy.RETRY)
        self.assertEqual(plan.max_retries, 3)
        self.assertEqual(plan.retry_delay, 1.0)
        self.assertEqual(plan.timeout, 30.0)
        self.assertIsNotNone(plan.created_at)
    
    def test_is_expired(self):
        """Test expiration check."""
        # Create plan with past timestamp
        plan = RecoveryPlan(
            component_name="test_component",
            failed_operation=OperationType.RELOAD,
            error_type="import_error",
            recovery_strategy=RecoveryStrategy.RETRY,
            timeout=1.0
        )
        
        # Initially not expired
        self.assertFalse(plan.is_expired())
        
        # Manually set old timestamp
        plan.created_at = datetime.now() - timedelta(seconds=2)
        self.assertTrue(plan.is_expired())
    
    def test_should_retry(self):
        """Test retry decision logic."""
        plan = RecoveryPlan(
            component_name="test_component",
            failed_operation=OperationType.RELOAD,
            error_type="import_error",
            recovery_strategy=RecoveryStrategy.RETRY,
            max_retries=3
        )
        
        # Should retry within limits (including max_retries)
        self.assertTrue(plan.should_retry(0))
        self.assertTrue(plan.should_retry(2))
        self.assertTrue(plan.should_retry(3))
        self.assertFalse(plan.should_retry(4))
        
        # Should not retry if expired
        plan.created_at = datetime.now() - timedelta(seconds=plan.timeout + 1)
        self.assertFalse(plan.should_retry(0))


class TestRecoveryAttempt(unittest.TestCase):
    """Test cases for RecoveryAttempt."""
    
    def test_initialization(self):
        """Test RecoveryAttempt initialization."""
        plan = RecoveryPlan(
            component_name="test_component",
            failed_operation=OperationType.RELOAD,
            error_type="import_error",
            recovery_strategy=RecoveryStrategy.RETRY
        )
        
        attempt = RecoveryAttempt(plan=plan, attempt_number=1)
        
        self.assertEqual(attempt.plan, plan)
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.actions_taken, [])
        self.assertFalse(attempt.success)
        self.assertIsNone(attempt.error_message)
        self.assertEqual(attempt.duration, 0.0)
        self.assertIsNotNone(attempt.timestamp)
    
    def test_add_action(self):
        """Test adding actions to attempt."""
        plan = RecoveryPlan(
            component_name="test_component",
            failed_operation=OperationType.RELOAD,
            error_type="import_error",
            recovery_strategy=RecoveryStrategy.RETRY
        )
        
        attempt = RecoveryAttempt(plan=plan, attempt_number=1)
        
        attempt.add_action(RecoveryAction.CLEAR_CACHE)
        attempt.add_action(RecoveryAction.RETRY_OPERATION)
        
        self.assertEqual(len(attempt.actions_taken), 2)
        self.assertIn(RecoveryAction.CLEAR_CACHE, attempt.actions_taken)
        self.assertIn(RecoveryAction.RETRY_OPERATION, attempt.actions_taken)


class TestErrorRecoveryManager(unittest.TestCase):
    """Test cases for ErrorRecoveryManager."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = Path(self.temp_dir) / "components"
        self.components_dir.mkdir()
        
        # Create core components
        self.module_cache = ModuleCache()
        self.error_handler = ErrorHandler()
        self.state_tracker = ComponentStateTracker(self.module_cache, self.error_handler)
        
        # Create recovery manager
        self.recovery_manager = ErrorRecoveryManager(
            self.module_cache, self.state_tracker, self.error_handler
        )
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_initialization(self):
        """Test ErrorRecoveryManager initialization."""
        self.assertIsNotNone(self.recovery_manager.module_cache)
        self.assertIsNotNone(self.recovery_manager.state_tracker)
        self.assertIsNotNone(self.recovery_manager.error_handler)
        
        # Check initial statistics
        stats = self.recovery_manager.get_recovery_statistics()
        self.assertEqual(stats['operations']['total_recoveries'], 0)
        self.assertEqual(stats['active_plans'], 0)
    
    def test_categorize_error(self):
        """Test error categorization."""
        # Test import errors
        self.assertEqual(
            self.recovery_manager._categorize_error("ImportError: No module named 'test'"),
            "import_error"
        )
        
        # Test dependency errors
        self.assertEqual(
            self.recovery_manager._categorize_error("Missing dependency: requests"),
            "dependency_error"
        )
        
        # Test syntax errors
        self.assertEqual(
            self.recovery_manager._categorize_error("SyntaxError: invalid syntax"),
            "syntax_error"
        )
        
        # Test runtime errors
        self.assertEqual(
            self.recovery_manager._categorize_error("AttributeError: 'NoneType' object has no attribute 'test'"),
            "runtime_error"
        )
        
        # Test memory errors
        self.assertEqual(
            self.recovery_manager._categorize_error("MemoryError: out of memory"),
            "memory_error"
        )
        
        # Test timeout errors
        self.assertEqual(
            self.recovery_manager._categorize_error("Operation timed out"),
            "timeout_error"
        )
        
        # Test general errors
        self.assertEqual(
            self.recovery_manager._categorize_error("Unknown error occurred"),
            "general_error"
        )
    
    def test_create_recovery_plan_import_error(self):
        """Test creating recovery plan for import error."""
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="ImportError: No module named 'test'"
        )
        
        plan = self.recovery_manager.create_recovery_plan("test_component", failed_result)
        
        self.assertEqual(plan.component_name, "test_component")
        self.assertEqual(plan.failed_operation, OperationType.RELOAD)
        self.assertEqual(plan.error_type, "import_error")
        self.assertEqual(plan.recovery_strategy, RecoveryStrategy.RETRY)
        self.assertEqual(plan.max_retries, 3)
        self.assertEqual(plan.fallback_strategy, "full")
        self.assertGreater(len(plan.actions), 0)
    
    def test_create_recovery_plan_syntax_error(self):
        """Test creating recovery plan for syntax error."""
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="SyntaxError: invalid syntax"
        )
        
        plan = self.recovery_manager.create_recovery_plan("test_component", failed_result)
        
        self.assertEqual(plan.error_type, "syntax_error")
        self.assertEqual(plan.recovery_strategy, RecoveryStrategy.ROLLBACK)
        self.assertEqual(plan.max_retries, 1)
        self.assertIsNone(plan.fallback_strategy)
    
    def test_create_recovery_plan_memory_error(self):
        """Test creating recovery plan for memory error."""
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="MemoryError: out of memory"
        )
        
        plan = self.recovery_manager.create_recovery_plan("test_component", failed_result)
        
        self.assertEqual(plan.error_type, "memory_error")
        self.assertEqual(plan.recovery_strategy, RecoveryStrategy.ISOLATE)
        self.assertEqual(plan.max_retries, 1)
        self.assertIn(RecoveryAction.ISOLATE_COMPONENT, plan.actions)
    
    def test_create_component_backup(self):
        """Test creating component backup."""
        # Create test component
        metadata = ComponentMetadata(name="test_component")
        self.state_tracker.track_component("test_component", metadata)
        
        # Add mock module
        mock_module = Mock()
        sys.modules["test_module"] = mock_module
        self.module_cache.add_module("test_module", mock_module, "test_component")
        
        # Create backup
        result = self.recovery_manager.create_component_backup("test_component")
        
        self.assertTrue(result)
        self.assertIn("test_component", self.recovery_manager._component_backups)
        
        backup = self.recovery_manager._component_backups["test_component"]
        self.assertIn("timestamp", backup)
        self.assertIn("component_state", backup)
        self.assertIn("modules", backup)
        self.assertIn("sys_modules", backup)
        
        # Cleanup
        if "test_module" in sys.modules:
            del sys.modules["test_module"]
    
    def test_create_component_backup_nonexistent(self):
        """Test creating backup for nonexistent component."""
        result = self.recovery_manager.create_component_backup("nonexistent_component")
        self.assertFalse(result)
    
    def test_restore_component_backup(self):
        """Test restoring component from backup."""
        # Create test component and backup
        metadata = ComponentMetadata(name="test_component")
        self.state_tracker.track_component("test_component", metadata)
        
        mock_module = Mock()
        sys.modules["test_module"] = mock_module
        self.module_cache.add_module("test_module", mock_module, "test_component")
        
        # Create backup
        self.recovery_manager.create_component_backup("test_component")
        
        # Remove module to simulate failure
        if "test_module" in sys.modules:
            del sys.modules["test_module"]
        self.module_cache.remove_module("test_module")
        
        # Restore backup
        result = self.recovery_manager.restore_component_backup("test_component")
        
        self.assertTrue(result)
        self.assertIn("test_module", sys.modules)
        self.assertTrue(self.module_cache.has_module("test_module"))
        
        # Cleanup
        if "test_module" in sys.modules:
            del sys.modules["test_module"]
    
    def test_restore_component_backup_no_backup(self):
        """Test restoring component without backup."""
        result = self.recovery_manager.restore_component_backup("nonexistent_component")
        self.assertFalse(result)
    
    def test_execute_recovery_no_plan(self):
        """Test executing recovery without a plan."""
        def mock_recovery_function():
            return ReloadResult(
                component_name="test_component",
                operation=OperationType.RELOAD,
                success=True,
                status=ComponentStatus.LOADED,
                previous_status=ComponentStatus.FAILED
            )
        
        result = self.recovery_manager.execute_recovery("test_component", mock_recovery_function)
        
        self.assertFalse(result.success)
        self.assertIn("No recovery plan found", result.error_message)
    
    def test_execute_recovery_success_first_attempt(self):
        """Test successful recovery on first attempt."""
        # Create failed result and recovery plan
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="ImportError: test error"
        )
        
        plan = self.recovery_manager.create_recovery_plan("test_component", failed_result)
        
        # Mock successful recovery function
        def mock_recovery_function():
            return ReloadResult(
                component_name="test_component",
                operation=OperationType.RELOAD,
                success=True,
                status=ComponentStatus.LOADED,
                previous_status=ComponentStatus.FAILED
            )
        
        result = self.recovery_manager.execute_recovery("test_component", mock_recovery_function)
        
        self.assertTrue(result.success)
        self.assertEqual(result.status, ComponentStatus.LOADED)
        
        # Check statistics
        stats = self.recovery_manager.get_recovery_statistics()
        self.assertEqual(stats['operations']['total_recoveries'], 1)
        self.assertEqual(stats['operations']['successful_recoveries'], 1)
        
        # Plan should be cleaned up
        self.assertNotIn("test_component", self.recovery_manager._recovery_plans)
    
    def test_execute_recovery_failure_all_attempts(self):
        """Test recovery failure after all attempts."""
        # Create failed result and recovery plan
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="ImportError: test error"
        )
        
        plan = self.recovery_manager.create_recovery_plan("test_component", failed_result)
        plan.max_retries = 2  # Limit retries for test
        
        # Mock failing recovery function
        def mock_recovery_function():
            return ReloadResult(
                component_name="test_component",
                operation=OperationType.RELOAD,
                success=False,
                status=ComponentStatus.FAILED,
                previous_status=ComponentStatus.FAILED,
                error_message="Still failing"
            )
        
        result = self.recovery_manager.execute_recovery("test_component", mock_recovery_function)
        
        self.assertFalse(result.success)
        self.assertIn("Recovery failed after", result.error_message)
        
        # Check statistics
        stats = self.recovery_manager.get_recovery_statistics()
        self.assertEqual(stats['operations']['total_recoveries'], 1)
        self.assertEqual(stats['operations']['failed_recoveries'], 1)
    
    def test_execute_recovery_with_fallback(self):
        """Test recovery with fallback strategy."""
        # Create failed result and recovery plan with fallback
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="ImportError: test error"
        )
        
        plan = self.recovery_manager.create_recovery_plan("test_component", failed_result)
        plan.max_retries = 1  # Limit retries to trigger fallback
        
        # Mock recovery function that always fails
        def mock_recovery_function():
            return ReloadResult(
                component_name="test_component",
                operation=OperationType.RELOAD,
                success=False,
                status=ComponentStatus.FAILED,
                previous_status=ComponentStatus.FAILED,
                error_message="Still failing"
            )
        
        # Mock the fallback strategy method to succeed
        self.recovery_manager._try_fallback_strategy = Mock(return_value=ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.FAILED
        ))
        
        result = self.recovery_manager.execute_recovery("test_component", mock_recovery_function)
        
        self.assertTrue(result.success)
        
        # Verify fallback was called
        self.recovery_manager._try_fallback_strategy.assert_called_once()
        
        # Check statistics
        stats = self.recovery_manager.get_recovery_statistics()
        self.assertEqual(stats['operations']['successful_recoveries'], 1)
        self.assertEqual(stats['operations']['fallbacks_used'], 1)
    
    def test_get_recovery_statistics(self):
        """Test getting recovery statistics."""
        stats = self.recovery_manager.get_recovery_statistics()
        
        self.assertIn('operations', stats)
        self.assertIn('active_plans', stats)
        self.assertIn('components_with_history', stats)
        self.assertIn('backups_available', stats)
        
        # Check operation stats structure
        ops = stats['operations']
        self.assertIn('total_recoveries', ops)
        self.assertIn('successful_recoveries', ops)
        self.assertIn('failed_recoveries', ops)
        self.assertIn('retries_performed', ops)
        self.assertIn('fallbacks_used', ops)
        self.assertIn('rollbacks_performed', ops)
        self.assertIn('components_isolated', ops)
    
    def test_clear_recovery_data_specific_component(self):
        """Test clearing recovery data for specific component."""
        # Add some recovery data
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="Test error"
        )
        
        self.recovery_manager.create_recovery_plan("test_component", failed_result)
        self.recovery_manager.create_component_backup("test_component")
        
        # Clear specific component
        self.recovery_manager.clear_recovery_data("test_component")
        
        self.assertNotIn("test_component", self.recovery_manager._recovery_plans)
        self.assertNotIn("test_component", self.recovery_manager._component_backups)
    
    def test_clear_recovery_data_all_components(self):
        """Test clearing recovery data for all components."""
        # Add some recovery data
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="Test error"
        )
        
        self.recovery_manager.create_recovery_plan("test_component", failed_result)
        
        # Clear all data
        self.recovery_manager.clear_recovery_data()
        
        self.assertEqual(len(self.recovery_manager._recovery_plans), 0)
        self.assertEqual(len(self.recovery_manager._recovery_history), 0)
        self.assertEqual(len(self.recovery_manager._component_backups), 0)
    
    def test_generate_retry_actions(self):
        """Test generating retry actions."""
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="Test error"
        )
        
        actions = self.recovery_manager._generate_retry_actions("test_component", failed_result)
        
        self.assertIn(RecoveryAction.CLEAR_CACHE, actions)
        self.assertIn(RecoveryAction.RETRY_OPERATION, actions)
    
    def test_generate_fallback_actions(self):
        """Test generating fallback actions."""
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="Test error"
        )
        
        actions = self.recovery_manager._generate_fallback_actions("test_component", failed_result)
        
        self.assertIn(RecoveryAction.CLEAR_CACHE, actions)
        self.assertIn(RecoveryAction.SWITCH_STRATEGY, actions)
        self.assertIn(RecoveryAction.RETRY_OPERATION, actions)
    
    def test_generate_rollback_actions(self):
        """Test generating rollback actions."""
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="Test error"
        )
        
        actions = self.recovery_manager._generate_rollback_actions("test_component", failed_result)
        
        self.assertIn(RecoveryAction.RESTORE_BACKUP, actions)
        self.assertIn(RecoveryAction.CLEAR_CACHE, actions)
    
    def test_generate_isolate_actions(self):
        """Test generating isolate actions."""
        failed_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="Test error"
        )
        
        actions = self.recovery_manager._generate_isolate_actions("test_component", failed_result)
        
        self.assertIn(RecoveryAction.ISOLATE_COMPONENT, actions)
        self.assertIn(RecoveryAction.FORCE_CLEANUP, actions)
    
    def test_execute_recovery_actions(self):
        """Test executing recovery actions."""
        plan = RecoveryPlan(
            component_name="test_component",
            failed_operation=OperationType.RELOAD,
            error_type="import_error",
            recovery_strategy=RecoveryStrategy.RETRY
        )
        
        attempt = RecoveryAttempt(plan=plan, attempt_number=1)
        
        actions = [
            RecoveryAction.CLEAR_CACHE,
            RecoveryAction.FORCE_CLEANUP
        ]
        
        # Mock importlib and gc
        with patch('importlib.invalidate_caches') as mock_invalidate, \
             patch('gc.collect') as mock_gc:
            
            self.recovery_manager._execute_recovery_actions("test_component", actions, attempt)
            
            mock_invalidate.assert_called_once()
            mock_gc.assert_called_once()
            
            self.assertEqual(len(attempt.actions_taken), 2)
            self.assertIn(RecoveryAction.CLEAR_CACHE, attempt.actions_taken)
            self.assertIn(RecoveryAction.FORCE_CLEANUP, attempt.actions_taken)


if __name__ == '__main__':
    unittest.main()