"""
Unit tests for the HotReloadManager class.

This module provides comprehensive tests for hot reload functionality including
module lifecycle management, state preservation, and error handling.
"""

import unittest
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import threading
import time

# Add the parent directory to the path to import hot_reload modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from hot_reload.hot_reload_manager import (
    HotReloadManager, FullReloadStrategy, IncrementalReloadStrategy, 
    RollbackReloadStrategy
)
from hot_reload.models import ComponentStatus, ComponentMetadata, OperationType
from hot_reload.cache import ModuleCache
from hot_reload.errors import ErrorHandler


class TestReloadStrategies(unittest.TestCase):
    """Test cases for different reload strategies."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = Path(self.temp_dir) / "components"
        self.components_dir.mkdir()
        
        self.error_handler = ErrorHandler()
        self.hot_reload_manager = HotReloadManager(str(self.components_dir), self.error_handler)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_full_reload_strategy_can_reload(self):
        """Test that full reload strategy can always reload."""
        strategy = FullReloadStrategy()
        module_cache = ModuleCache()
        
        # Full reload should always be possible
        self.assertTrue(strategy.can_reload("test_component", module_cache))
    
    def test_incremental_reload_strategy_can_reload(self):
        """Test incremental reload strategy requirements."""
        strategy = IncrementalReloadStrategy()
        module_cache = ModuleCache()
        
        # Should not be possible without loaded modules
        self.assertFalse(strategy.can_reload("test_component", module_cache))
        
        # Add a mock module to cache
        mock_module = Mock()
        module_cache.add_module("test_module", mock_module, "test_component")
        
        # Should now be possible
        self.assertTrue(strategy.can_reload("test_component", module_cache))
    
    def test_rollback_reload_strategy_can_reload(self):
        """Test rollback reload strategy requirements."""
        strategy = RollbackReloadStrategy()
        module_cache = ModuleCache()
        
        # Should not be possible without snapshot
        self.assertFalse(strategy.can_reload("test_component", module_cache))
        
        # Create a snapshot
        strategy.create_snapshot("test_component", self.hot_reload_manager)
        
        # Should now be possible
        self.assertTrue(strategy.can_reload("test_component", module_cache))
    
    @patch('hot_reload.hot_reload_manager.time.time')
    def test_full_reload_strategy_execution(self, mock_time):
        """Test full reload strategy execution."""
        mock_time.side_effect = [0.0, 1.0]  # Start and end times
        
        strategy = FullReloadStrategy()
        
        # Mock the hot reload manager methods
        self.hot_reload_manager._unload_component_modules = Mock(return_value=True)
        self.hot_reload_manager._load_component_fresh = Mock()
        self.hot_reload_manager._load_component_fresh.return_value = Mock(
            success=True, metadata=None, error_message=None
        )
        
        # Track component
        self.hot_reload_manager.state_tracker.track_component("test_component")
        
        result = strategy.execute_reload("test_component", self.hot_reload_manager)
        
        self.assertTrue(result.success)
        self.assertEqual(result.component_name, "test_component")
        self.assertEqual(result.operation, OperationType.RELOAD)
        self.assertEqual(result.status, ComponentStatus.LOADED)
        self.assertEqual(result.duration, 1.0)
    
    def test_rollback_strategy_snapshot_creation(self):
        """Test snapshot creation in rollback strategy."""
        strategy = RollbackReloadStrategy()
        
        # Create a test component file
        test_file = self.components_dir / "test_component.py"
        test_file.write_text("# Test component")
        
        # Add module to cache
        mock_module = Mock()
        self.hot_reload_manager.module_cache.add_module(
            "test_module", mock_module, "test_component", str(test_file)
        )
        
        # Track component
        metadata = ComponentMetadata(name="test_component", file_path=str(test_file))
        self.hot_reload_manager.state_tracker.track_component("test_component", metadata)
        
        # Create snapshot
        strategy.create_snapshot("test_component", self.hot_reload_manager)
        
        # Verify snapshot was created
        self.assertTrue(strategy.can_rollback("test_component"))


class TestHotReloadManager(unittest.TestCase):
    """Test cases for the HotReloadManager class."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = Path(self.temp_dir) / "components"
        self.components_dir.mkdir()
        
        self.error_handler = ErrorHandler()
        self.manager = HotReloadManager(str(self.components_dir), self.error_handler)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_initialization(self):
        """Test HotReloadManager initialization."""
        self.assertEqual(self.manager.components_dir, self.components_dir)
        self.assertIsNotNone(self.manager.module_cache)
        self.assertIsNotNone(self.manager.state_tracker)
        self.assertIsNotNone(self.manager.reference_cleanup)
        self.assertIsNotNone(self.manager.error_handler)
        
        # Check reload strategies
        self.assertIn('full', self.manager.reload_strategies)
        self.assertIn('incremental', self.manager.reload_strategies)
        self.assertIn('rollback', self.manager.reload_strategies)
        self.assertEqual(self.manager.default_strategy, 'full')
    
    def test_get_component_status_unknown(self):
        """Test getting status of unknown component."""
        status = self.manager.get_component_status("unknown_component")
        self.assertEqual(status, ComponentStatus.UNKNOWN)
    
    def test_get_component_status_tracked(self):
        """Test getting status of tracked component."""
        # Track a component
        self.manager.state_tracker.track_component("test_component")
        self.manager.state_tracker.update_component_status("test_component", ComponentStatus.LOADED)
        
        status = self.manager.get_component_status("test_component")
        self.assertEqual(status, ComponentStatus.LOADED)
    
    @patch('hot_reload.hot_reload_manager.time.time')
    def test_hot_reload_component_success(self, mock_time):
        """Test successful component hot reload."""
        mock_time.side_effect = [0.0, 1.0]
        
        # Mock internal methods
        self.manager._unload_component_modules = Mock(return_value=True)
        self.manager._load_component_fresh = Mock()
        self.manager._load_component_fresh.return_value = Mock(
            success=True, metadata=None, error_message=None
        )
        
        # Track component
        self.manager.state_tracker.track_component("test_component")
        
        result = self.manager.hot_reload_component("test_component")
        
        self.assertTrue(result.success)
        self.assertEqual(result.component_name, "test_component")
        self.assertEqual(result.operation, OperationType.RELOAD)
        self.assertEqual(result.status, ComponentStatus.LOADED)
        self.assertEqual(result.duration, 1.0)
        
        # Check statistics
        stats = self.manager.get_reload_statistics()
        self.assertEqual(stats['operations']['total_reloads'], 1)
        self.assertEqual(stats['operations']['successful_reloads'], 1)
    
    def test_hot_reload_component_already_in_progress(self):
        """Test reload when operation is already in progress."""
        # Simulate operation in progress
        self.manager._active_operations.add("test_component")
        
        result = self.manager.hot_reload_component("test_component")
        
        self.assertFalse(result.success)
        self.assertIn("already in progress", result.error_message)
    
    def test_hot_reload_component_unknown_strategy(self):
        """Test reload with unknown strategy."""
        result = self.manager.hot_reload_component("test_component", strategy="unknown")
        
        self.assertFalse(result.success)
        self.assertIn("Unknown reload strategy", result.error_message)
    
    @patch('hot_reload.hot_reload_manager.time.time')
    def test_unload_component_success(self, mock_time):
        """Test successful component unload."""
        mock_time.side_effect = [0.0, 1.0]
        
        # Mock internal methods
        self.manager._unload_component_modules = Mock(return_value=True)
        self.manager.reference_cleanup.cleanup_component_references = Mock(
            return_value={'success': True}
        )
        
        # Track component
        self.manager.state_tracker.track_component("test_component")
        
        result = self.manager.unload_component("test_component")
        
        self.assertTrue(result.success)
        self.assertEqual(result.component_name, "test_component")
        self.assertEqual(result.operation, OperationType.UNLOAD)
        self.assertEqual(result.status, ComponentStatus.UNLOADED)
        self.assertEqual(result.duration, 1.0)
        
        # Check statistics
        stats = self.manager.get_reload_statistics()
        self.assertEqual(stats['operations']['total_unloads'], 1)
        self.assertEqual(stats['operations']['successful_unloads'], 1)
    
    def test_unload_component_already_in_progress(self):
        """Test unload when operation is already in progress."""
        # Simulate operation in progress
        self.manager._active_operations.add("test_component")
        
        result = self.manager.unload_component("test_component")
        
        self.assertFalse(result.success)
        self.assertIn("already in progress", result.error_message)
    
    def test_cleanup_module_references(self):
        """Test module reference cleanup."""
        # Add a mock module to sys.modules
        mock_module = Mock()
        sys.modules["test_module"] = mock_module
        
        # Add to cache
        self.manager.module_cache.add_module("test_module", mock_module)
        
        # Cleanup
        result = self.manager.cleanup_module_references("test_module")
        
        self.assertTrue(result)
        self.assertNotIn("test_module", sys.modules)
        self.assertFalse(self.manager.module_cache.has_module("test_module"))
    
    def test_preserve_component_state(self):
        """Test component state preservation."""
        # Create component with metadata
        metadata = ComponentMetadata(name="test_component", version="1.0.0")
        component_state = self.manager.state_tracker.track_component("test_component", metadata)
        component_state.load_count = 5
        component_state.error_count = 2
        
        # Preserve state
        preserved = self.manager.preserve_component_state("test_component")
        
        self.assertEqual(preserved['component_name'], "test_component")
        self.assertEqual(preserved['load_count'], 5)
        self.assertEqual(preserved['error_count'], 2)
        self.assertIsNotNone(preserved['metadata'])
        self.assertIsNotNone(preserved['timestamp'])
    
    def test_preserve_component_state_unknown_component(self):
        """Test preserving state of unknown component."""
        preserved = self.manager.preserve_component_state("unknown_component")
        self.assertEqual(preserved, {})
    
    def test_restore_component_state(self):
        """Test component state restoration."""
        # Create preserved state
        preserved_state = {
            'component_name': 'test_component',
            'status': ComponentStatus.LOADED.value,
            'load_count': 5,
            'error_count': 2,
            'metadata': {
                'name': 'test_component',
                'version': '1.0.0',
                'description': 'Test component',
                'author': 'Test Author',
                'requirements': [],
                'file_path': None,
                'module_name': None,
                'class_name': None,
                'is_package': False,
                'package_path': None,
                'created_at': '2023-01-01T00:00:00',
                'modified_at': '2023-01-01T00:00:00',
                'size_bytes': 0,
                'checksum': None,
                'tags': [],
                'config': {}
            },
            'timestamp': '2023-01-01T00:00:00'
        }
        
        # Restore state
        result = self.manager.restore_component_state("test_component", preserved_state)
        
        self.assertTrue(result)
        
        # Verify restoration
        component_state = self.manager.state_tracker.get_component_state("test_component")
        self.assertIsNotNone(component_state)
        self.assertEqual(component_state.load_count, 5)
        self.assertEqual(component_state.error_count, 2)
        self.assertIsNotNone(component_state.metadata)
        self.assertEqual(component_state.metadata.name, "test_component")
    
    def test_restore_component_state_invalid_data(self):
        """Test restoring state with invalid data."""
        # Test with empty data
        result = self.manager.restore_component_state("test_component", {})
        self.assertFalse(result)
        
        # Test with mismatched component name
        invalid_state = {'component_name': 'other_component'}
        result = self.manager.restore_component_state("test_component", invalid_state)
        self.assertFalse(result)
    
    def test_get_reload_statistics(self):
        """Test getting reload statistics."""
        # Perform some operations to generate statistics
        self.manager._operation_stats['total_reloads'] = 10
        self.manager._operation_stats['successful_reloads'] = 8
        self.manager._operation_stats['failed_reloads'] = 2
        
        stats = self.manager.get_reload_statistics()
        
        self.assertIn('operations', stats)
        self.assertIn('cache', stats)
        self.assertIn('errors', stats)
        self.assertIn('active_operations', stats)
        self.assertIn('tracked_components', stats)
        
        self.assertEqual(stats['operations']['total_reloads'], 10)
        self.assertEqual(stats['operations']['successful_reloads'], 8)
        self.assertEqual(stats['operations']['failed_reloads'], 2)
    
    def test_thread_safety(self):
        """Test thread safety of hot reload operations."""
        results = []
        errors = []
        
        # Add a delay to the mock to simulate real work
        def slow_unload(*args, **kwargs):
            time.sleep(0.05)  # Small delay
            return True
        
        def slow_load(*args, **kwargs):
            time.sleep(0.05)  # Small delay
            return Mock(success=True, metadata=None, error_message=None)
        
        # Mock internal methods BEFORE creating threads
        self.manager._unload_component_modules = Mock(side_effect=slow_unload)
        self.manager._load_component_fresh = Mock(side_effect=slow_load)
        
        def reload_component(component_name):
            try:
                result = self.manager.hot_reload_component(component_name)
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads trying to reload the same component
        threads = []
        for i in range(5):
            thread = threading.Thread(target=reload_component, args=("test_component",))
            threads.append(thread)
        
        # Start all threads simultaneously
        for thread in threads:
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Unexpected errors: {errors}")
        self.assertEqual(len(results), 5)
        
        # With proper locking, all operations should succeed sequentially
        # The RLock ensures thread safety by serializing access
        successful_results = [r for r in results if r.success]
        failed_results = [r for r in results if not r.success]
        
        # All should succeed because the lock serializes the operations
        self.assertEqual(len(successful_results), 5)
        self.assertEqual(len(failed_results), 0)
        
        # Verify that the operations were properly tracked
        stats = self.manager.get_reload_statistics()
        self.assertEqual(stats['operations']['total_reloads'], 5)
        self.assertEqual(stats['operations']['successful_reloads'], 5)
    
    def test_unload_component_modules_internal(self):
        """Test internal module unloading method."""
        # Add mock modules to cache and sys.modules
        mock_module1 = Mock()
        mock_module2 = Mock()
        
        sys.modules["test_module1"] = mock_module1
        sys.modules["test_module2"] = mock_module2
        
        self.manager.module_cache.add_module("test_module1", mock_module1, "test_component")
        self.manager.module_cache.add_module("test_module2", mock_module2, "test_component")
        
        # Test unloading
        result = self.manager._unload_component_modules("test_component")
        
        self.assertTrue(result)
        self.assertNotIn("test_module1", sys.modules)
        self.assertNotIn("test_module2", sys.modules)
        self.assertFalse(self.manager.module_cache.has_module("test_module1"))
        self.assertFalse(self.manager.module_cache.has_module("test_module2"))
    
    def test_unload_component_modules_no_modules(self):
        """Test unloading when no modules exist."""
        result = self.manager._unload_component_modules("nonexistent_component")
        self.assertTrue(result)  # Should succeed when nothing to unload


class TestHotReloadManagerIntegration(unittest.TestCase):
    """Integration tests for HotReloadManager with real components."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = Path(self.temp_dir) / "components"
        self.components_dir.mkdir()
        
        self.manager = HotReloadManager(str(self.components_dir))
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_reload_with_file_changes(self):
        """Test reload detection with actual file changes."""
        # Create a test component file
        component_file = self.components_dir / "test_component.py"
        component_file.write_text("""
# Test component version 1
def get_version():
    return "1.0.0"
""")
        
        # Add to cache with current timestamp
        mock_module = Mock()
        self.manager.module_cache.add_module(
            "test_component", mock_module, "test_component", str(component_file)
        )
        
        # Wait a bit and modify the file
        time.sleep(0.1)
        component_file.write_text("""
# Test component version 2
def get_version():
    return "2.0.0"
""")
        
        # Test incremental reload strategy
        strategy = IncrementalReloadStrategy()
        
        # Should detect changes (though actual reload will be mocked)
        self.assertTrue(strategy.can_reload("test_component", self.manager.module_cache))


if __name__ == '__main__':
    unittest.main()