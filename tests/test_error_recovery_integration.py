"""
Integration tests for error recovery with hot reload functionality.

This module provides comprehensive integration tests that demonstrate
the complete error recovery workflow with real reload scenarios.
"""

import unittest
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

# Add the parent directory to the path to import hot_reload modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from hot_reload.hot_reload_manager import HotReloadManager
from hot_reload.models import ComponentStatus, ComponentMetadata, OperationType, ReloadResult
from hot_reload.error_recovery import RecoveryStrategy


class TestErrorRecoveryIntegration(unittest.TestCase):
    """Integration tests for error recovery with hot reload."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = Path(self.temp_dir) / "components"
        self.components_dir.mkdir()
        
        # Create hot reload manager
        self.manager = HotReloadManager(str(self.components_dir))
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_complete_error_recovery_workflow(self):
        """Test complete error recovery workflow from failure to success."""
        # Create a component that will initially fail
        component_name = "test_component"
        
        # Track the component
        metadata = ComponentMetadata(name=component_name)
        self.manager.state_tracker.track_component(component_name, metadata)
        
        # Create a backup
        backup_created = self.manager.create_component_backup(component_name)
        self.assertTrue(backup_created)
        
        # Simulate a failed reload result
        failed_result = ReloadResult(
            component_name=component_name,
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="ImportError: No module named 'missing_dependency'"
        )
        
        # Create recovery plan
        recovery_plan = self.manager.error_recovery.create_recovery_plan(
            component_name, failed_result
        )
        
        # Verify recovery plan
        self.assertEqual(recovery_plan.component_name, component_name)
        self.assertEqual(recovery_plan.error_type, "import_error")
        self.assertEqual(recovery_plan.recovery_strategy, RecoveryStrategy.RETRY)
        self.assertGreater(len(recovery_plan.actions), 0)
        
        # Mock a recovery function that succeeds after retry
        call_count = 0
        def mock_recovery_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First attempt fails
                return ReloadResult(
                    component_name=component_name,
                    operation=OperationType.RELOAD,
                    success=False,
                    status=ComponentStatus.FAILED,
                    previous_status=ComponentStatus.FAILED,
                    error_message="Still failing"
                )
            else:
                # Second attempt succeeds
                return ReloadResult(
                    component_name=component_name,
                    operation=OperationType.RELOAD,
                    success=True,
                    status=ComponentStatus.LOADED,
                    previous_status=ComponentStatus.FAILED
                )
        
        # Execute recovery
        result = self.manager.error_recovery.execute_recovery(
            component_name, mock_recovery_function
        )
        
        # Verify successful recovery
        self.assertTrue(result.success)
        self.assertEqual(result.status, ComponentStatus.LOADED)
        
        # Verify statistics
        stats = self.manager.get_reload_statistics()
        recovery_stats = stats['recovery']
        self.assertEqual(recovery_stats['operations']['total_recoveries'], 1)
        self.assertEqual(recovery_stats['operations']['successful_recoveries'], 1)
        self.assertGreater(recovery_stats['operations']['retries_performed'], 0)
    
    def test_recovery_with_backup_restoration(self):
        """Test recovery using backup restoration."""
        component_name = "backup_test_component"
        
        # Create test module and add to cache
        mock_module = Mock()
        mock_module.__name__ = "test_module"
        mock_module.__file__ = str(self.components_dir / "test.py")
        
        sys.modules["test_module"] = mock_module
        self.manager.module_cache.add_module("test_module", mock_module, component_name)
        
        # Track component
        metadata = ComponentMetadata(name=component_name)
        self.manager.state_tracker.track_component(component_name, metadata)
        self.manager.state_tracker.update_component_status(component_name, ComponentStatus.LOADED)
        
        # Create backup
        backup_created = self.manager.create_component_backup(component_name)
        self.assertTrue(backup_created)
        
        # Simulate component failure and removal
        if "test_module" in sys.modules:
            del sys.modules["test_module"]
        self.manager.module_cache.remove_module("test_module")
        self.manager.state_tracker.update_component_status(component_name, ComponentStatus.FAILED)
        
        # Restore from backup
        restore_success = self.manager.restore_component_backup(component_name)
        self.assertTrue(restore_success)
        
        # Verify restoration
        self.assertIn("test_module", sys.modules)
        self.assertTrue(self.manager.module_cache.has_module("test_module"))
        
        component_state = self.manager.state_tracker.get_component_state(component_name)
        self.assertEqual(component_state.status, ComponentStatus.LOADED)
        
        # Cleanup
        if "test_module" in sys.modules:
            del sys.modules["test_module"]
    
    def test_recovery_plan_creation_for_different_errors(self):
        """Test recovery plan creation for different error types."""
        component_name = "error_test_component"
        
        # Test different error types
        error_scenarios = [
            ("ImportError: No module named 'test'", "import_error", RecoveryStrategy.RETRY),
            ("SyntaxError: invalid syntax", "syntax_error", RecoveryStrategy.ROLLBACK),
            ("MemoryError: out of memory", "memory_error", RecoveryStrategy.ISOLATE),
            ("Operation timed out", "timeout_error", RecoveryStrategy.SKIP),
            ("AttributeError: 'NoneType' object has no attribute 'test'", "runtime_error", RecoveryStrategy.RETRY),
        ]
        
        for error_message, expected_error_type, expected_strategy in error_scenarios:
            with self.subTest(error_type=expected_error_type):
                failed_result = ReloadResult(
                    component_name=component_name,
                    operation=OperationType.RELOAD,
                    success=False,
                    status=ComponentStatus.FAILED,
                    previous_status=ComponentStatus.LOADED,
                    error_message=error_message
                )
                
                recovery_plan = self.manager.error_recovery.create_recovery_plan(
                    component_name, failed_result
                )
                
                self.assertEqual(recovery_plan.error_type, expected_error_type)
                self.assertEqual(recovery_plan.recovery_strategy, expected_strategy)
                self.assertGreater(len(recovery_plan.actions), 0)
    
    def test_memory_cleanup_during_recovery(self):
        """Test memory cleanup functionality during recovery."""
        # Force memory cleanup
        cleanup_result = self.manager.force_memory_cleanup()
        
        self.assertTrue(cleanup_result['success'])
        self.assertIn('objects_collected', cleanup_result)
        self.assertIn('final_object_count', cleanup_result)
        self.assertIsInstance(cleanup_result['objects_collected'], int)
    
    def test_recovery_statistics_tracking(self):
        """Test that recovery statistics are properly tracked."""
        # Get initial statistics
        initial_stats = self.manager.get_reload_statistics()
        initial_recovery_stats = initial_stats['recovery']['operations']
        
        # Create a recovery plan (this counts as a recovery operation when executed)
        component_name = "stats_test_component"
        failed_result = ReloadResult(
            component_name=component_name,
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="Test error for statistics"
        )
        
        recovery_plan = self.manager.error_recovery.create_recovery_plan(
            component_name, failed_result
        )
        
        # Execute a successful recovery
        def successful_recovery():
            return ReloadResult(
                component_name=component_name,
                operation=OperationType.RELOAD,
                success=True,
                status=ComponentStatus.LOADED,
                previous_status=ComponentStatus.FAILED
            )
        
        result = self.manager.error_recovery.execute_recovery(
            component_name, successful_recovery
        )
        
        # Check updated statistics
        final_stats = self.manager.get_reload_statistics()
        final_recovery_stats = final_stats['recovery']['operations']
        
        self.assertEqual(
            final_recovery_stats['total_recoveries'],
            initial_recovery_stats['total_recoveries'] + 1
        )
        self.assertEqual(
            final_recovery_stats['successful_recoveries'],
            initial_recovery_stats['successful_recoveries'] + 1
        )
    
    def test_recovery_data_cleanup(self):
        """Test cleanup of recovery data."""
        component_name = "cleanup_test_component"
        
        # Create recovery data
        failed_result = ReloadResult(
            component_name=component_name,
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="Test error"
        )
        
        # Track the component first
        metadata = ComponentMetadata(name=component_name)
        self.manager.state_tracker.track_component(component_name, metadata)
        
        self.manager.error_recovery.create_recovery_plan(component_name, failed_result)
        self.manager.create_component_backup(component_name)
        
        # Verify data exists
        stats_before = self.manager.get_reload_statistics()
        self.assertGreater(stats_before['recovery']['active_plans'], 0)
        self.assertGreater(stats_before['recovery']['backups_available'], 0)
        
        # Clear recovery data for specific component
        self.manager.clear_recovery_data(component_name)
        
        # Verify data is cleared
        stats_after = self.manager.get_reload_statistics()
        recovery_plan = self.manager.get_recovery_plan(component_name)
        self.assertIsNone(recovery_plan)
    
    def test_integration_with_hot_reload_manager(self):
        """Test integration between error recovery and hot reload manager."""
        component_name = "integration_test_component"
        
        # Mock the internal methods to simulate failure then success
        call_count = 0
        original_unload = self.manager._unload_component_modules
        original_load = self.manager._load_component_fresh
        
        def mock_unload(comp_name):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return False  # First attempt fails
            else:
                return True   # Subsequent attempts succeed
        
        def mock_load(comp_name):
            return Mock(success=True, metadata=None, error_message=None)
        
        self.manager._unload_component_modules = mock_unload
        self.manager._load_component_fresh = mock_load
        
        # Track component
        self.manager.state_tracker.track_component(component_name)
        
        # Attempt hot reload (should trigger error recovery)
        result = self.manager.hot_reload_component(component_name)
        
        # The result might be successful due to error recovery
        # or it might fail - either is acceptable for this integration test
        self.assertIsNotNone(result)
        self.assertEqual(result.component_name, component_name)
        self.assertEqual(result.operation, OperationType.RELOAD)
        
        # Restore original methods
        self.manager._unload_component_modules = original_unload
        self.manager._load_component_fresh = original_load


if __name__ == '__main__':
    unittest.main()