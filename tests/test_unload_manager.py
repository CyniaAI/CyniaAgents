"""
Unit tests for the ComponentUnloader class.

This module provides comprehensive tests for component unloading functionality
including validation, memory cleanup, rollback mechanisms, and error handling.
"""

import unittest
import sys
import tempfile
import shutil
import gc
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import threading
import time

# Add the parent directory to the path to import hot_reload modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from hot_reload.unload_manager import (
    ComponentUnloader, UnloadValidationResult, UnloadSnapshot, MemoryTracker
)
from hot_reload.models import ComponentStatus, ComponentMetadata, OperationType
from hot_reload.cache import ModuleCache, ComponentStateTracker, ModuleReferenceCleanup
from hot_reload.errors import ErrorHandler


class TestUnloadValidationResult(unittest.TestCase):
    """Test cases for UnloadValidationResult."""
    
    def test_initialization(self):
        """Test UnloadValidationResult initialization."""
        result = UnloadValidationResult(True)
        self.assertTrue(result.can_unload)
        self.assertEqual(result.blocking_dependencies, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.errors, [])
    
    def test_initialization_with_data(self):
        """Test UnloadValidationResult initialization with data."""
        result = UnloadValidationResult(
            False,
            blocking_dependencies=['dep1', 'dep2'],
            warnings=['warning1'],
            errors=['error1']
        )
        
        self.assertFalse(result.can_unload)
        self.assertEqual(result.blocking_dependencies, ['dep1', 'dep2'])
        self.assertEqual(result.warnings, ['warning1'])
        self.assertEqual(result.errors, ['error1'])
    
    def test_has_blocking_dependencies(self):
        """Test blocking dependencies check."""
        result1 = UnloadValidationResult(True)
        self.assertFalse(result1.has_blocking_dependencies())
        
        result2 = UnloadValidationResult(False, blocking_dependencies=['dep1'])
        self.assertTrue(result2.has_blocking_dependencies())
    
    def test_has_warnings(self):
        """Test warnings check."""
        result1 = UnloadValidationResult(True)
        self.assertFalse(result1.has_warnings())
        
        result2 = UnloadValidationResult(True, warnings=['warning'])
        self.assertTrue(result2.has_warnings())
    
    def test_has_errors(self):
        """Test errors check."""
        result1 = UnloadValidationResult(True)
        self.assertFalse(result1.has_errors())
        
        result2 = UnloadValidationResult(False, errors=['error'])
        self.assertTrue(result2.has_errors())


class TestUnloadSnapshot(unittest.TestCase):
    """Test cases for UnloadSnapshot."""
    
    def test_initialization(self):
        """Test UnloadSnapshot initialization."""
        snapshot = UnloadSnapshot("test_component")
        
        self.assertEqual(snapshot.component_name, "test_component")
        self.assertIsNotNone(snapshot.timestamp)
        self.assertEqual(snapshot.modules, {})
        self.assertIsNone(snapshot.component_state)
        self.assertEqual(snapshot.sys_modules_backup, {})
        self.assertEqual(snapshot.cache_state, {})
    
    def test_add_module_backup(self):
        """Test adding module backup."""
        snapshot = UnloadSnapshot("test_component")
        mock_module = Mock()
        mock_module.__file__ = "/path/to/module.py"
        mock_module.__name__ = "test_module"
        mock_module.__package__ = "test_package"
        
        snapshot.add_module_backup("test_module", mock_module)
        
        self.assertIn("test_module", snapshot.modules)
        module_data = snapshot.modules["test_module"]
        self.assertEqual(module_data['module'], mock_module)
        self.assertEqual(module_data['file_path'], "/path/to/module.py")
        self.assertEqual(module_data['name'], "test_module")
        self.assertEqual(module_data['package'], "test_package")
    
    def test_get_module_names(self):
        """Test getting module names."""
        snapshot = UnloadSnapshot("test_component")
        mock_module1 = Mock()
        mock_module2 = Mock()
        
        snapshot.add_module_backup("module1", mock_module1)
        snapshot.add_module_backup("module2", mock_module2)
        
        names = snapshot.get_module_names()
        self.assertEqual(set(names), {"module1", "module2"})
    
    def test_can_rollback(self):
        """Test rollback capability check."""
        snapshot = UnloadSnapshot("test_component")
        
        # Initially cannot rollback
        self.assertFalse(snapshot.can_rollback())
        
        # Add module but no component state
        mock_module = Mock()
        snapshot.add_module_backup("test_module", mock_module)
        self.assertFalse(snapshot.can_rollback())
        
        # Add component state
        snapshot.component_state = Mock()
        self.assertTrue(snapshot.can_rollback())


class TestMemoryTracker(unittest.TestCase):
    """Test cases for MemoryTracker."""
    
    def test_initialization(self):
        """Test MemoryTracker initialization."""
        tracker = MemoryTracker()
        
        self.assertEqual(tracker._initial_objects, 0)
        self.assertEqual(tracker._final_objects, 0)
        self.assertEqual(tracker._gc_stats, {})
    
    def test_tracking_cycle(self):
        """Test complete tracking cycle."""
        tracker = MemoryTracker()
        
        # Start tracking
        tracker.start_tracking()
        self.assertGreater(tracker._initial_objects, 0)
        
        # Create some objects
        test_objects = [i for i in range(100)]
        
        # Stop tracking
        stats = tracker.stop_tracking()
        
        self.assertIsInstance(stats, dict)
        self.assertIn('initial_objects', stats)
        self.assertIn('final_objects', stats)
        self.assertIn('objects_freed', stats)
        self.assertIn('gc_collected', stats)
    
    def test_get_memory_stats(self):
        """Test getting memory statistics."""
        tracker = MemoryTracker()
        
        # Initially empty
        stats = tracker.get_memory_stats()
        self.assertEqual(stats, {})
        
        # After tracking
        tracker.start_tracking()
        tracker.stop_tracking()
        
        stats = tracker.get_memory_stats()
        self.assertIsInstance(stats, dict)
        self.assertIn('initial_objects', stats)


class TestComponentUnloader(unittest.TestCase):
    """Test cases for ComponentUnloader."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = Path(self.temp_dir) / "components"
        self.components_dir.mkdir()
        
        # Create core components
        self.module_cache = ModuleCache()
        self.error_handler = ErrorHandler()
        self.state_tracker = ComponentStateTracker(self.module_cache, self.error_handler)
        self.reference_cleanup = ModuleReferenceCleanup(self.module_cache)
        
        # Create unloader
        self.unloader = ComponentUnloader(
            self.module_cache, self.state_tracker, 
            self.reference_cleanup, self.error_handler
        )
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_initialization(self):
        """Test ComponentUnloader initialization."""
        self.assertIsNotNone(self.unloader.module_cache)
        self.assertIsNotNone(self.unloader.state_tracker)
        self.assertIsNotNone(self.unloader.reference_cleanup)
        self.assertIsNotNone(self.unloader.error_handler)
        self.assertIsNotNone(self.unloader.memory_tracker)
        
        # Check initial statistics
        stats = self.unloader.get_unload_statistics()
        self.assertEqual(stats['operations']['total_unloads'], 0)
        self.assertEqual(stats['snapshots_available'], 0)
    
    def test_validate_unload_nonexistent_component(self):
        """Test validation of nonexistent component."""
        result = self.unloader.validate_unload("nonexistent_component")
        
        self.assertFalse(result.can_unload)
        self.assertTrue(result.has_errors())
        self.assertIn("not found", result.errors[0])
    
    def test_validate_unload_already_unloaded(self):
        """Test validation of already unloaded component."""
        # Track component and set as unloaded
        self.state_tracker.track_component("test_component")
        self.state_tracker.update_component_status("test_component", ComponentStatus.UNLOADED)
        
        result = self.unloader.validate_unload("test_component")
        
        self.assertTrue(result.can_unload)
        self.assertTrue(result.has_warnings())
        self.assertIn("already unloaded", result.warnings[0])
    
    def test_validate_unload_with_dependencies(self):
        """Test validation with blocking dependencies."""
        # Create component with dependencies
        mock_module1 = Mock()
        mock_module2 = Mock()
        
        # Add modules to cache
        self.module_cache.add_module("module1", mock_module1, "test_component")
        self.module_cache.add_module("module2", mock_module2, "dependent_component")
        
        # Create dependency relationship
        module1_info = self.module_cache.get_module_info("module1")
        module2_info = self.module_cache.get_module_info("module2")
        
        if module1_info and module2_info:
            module1_info.add_dependent("module2")
            module2_info.add_dependency("module1")
        
        # Track components
        self.state_tracker.track_component("test_component")
        self.state_tracker.track_component("dependent_component")
        
        result = self.unloader.validate_unload("test_component")
        
        # Should have blocking dependencies
        self.assertFalse(result.can_unload)
        self.assertTrue(result.has_blocking_dependencies())
    
    def test_validate_unload_force_mode(self):
        """Test validation in force mode."""
        # Create component with dependencies
        mock_module1 = Mock()
        mock_module2 = Mock()
        
        self.module_cache.add_module("module1", mock_module1, "test_component")
        self.module_cache.add_module("module2", mock_module2, "dependent_component")
        
        # Track components
        self.state_tracker.track_component("test_component")
        self.state_tracker.track_component("dependent_component")
        
        # Force mode should ignore dependencies
        result = self.unloader.validate_unload("test_component", force=True)
        
        self.assertTrue(result.can_unload)
    
    def test_validate_unload_active_operation(self):
        """Test validation during active operation."""
        # Track component and set as loading
        self.state_tracker.track_component("test_component")
        self.state_tracker.update_component_status("test_component", ComponentStatus.LOADING)
        
        result = self.unloader.validate_unload("test_component")
        
        self.assertFalse(result.can_unload)
        self.assertTrue(result.has_errors())
        self.assertIn("currently loading", result.errors[0])
    
    def test_create_unload_snapshot(self):
        """Test creating unload snapshot."""
        # Create test component with modules
        mock_module = Mock()
        mock_module.__file__ = str(self.components_dir / "test.py")
        mock_module.__name__ = "test_module"
        
        # Add to sys.modules and cache
        sys.modules["test_module"] = mock_module
        self.module_cache.add_module("test_module", mock_module, "test_component")
        
        # Track component
        metadata = ComponentMetadata(name="test_component")
        self.state_tracker.track_component("test_component", metadata)
        
        # Create snapshot
        snapshot = self.unloader.create_unload_snapshot("test_component")
        
        self.assertEqual(snapshot.component_name, "test_component")
        self.assertIn("test_module", snapshot.get_module_names())
        self.assertIn("test_module", snapshot.sys_modules_backup)
        self.assertTrue(snapshot.can_rollback())
        
        # Cleanup
        if "test_module" in sys.modules:
            del sys.modules["test_module"]
    
    def test_unload_component_validation_failure(self):
        """Test unload with validation failure."""
        result = self.unloader.unload_component("nonexistent_component")
        
        self.assertFalse(result.success)
        self.assertEqual(result.operation, OperationType.UNLOAD)
        self.assertEqual(result.status, ComponentStatus.FAILED)
        self.assertIn("Validation failed", result.error_message)
    
    def test_unload_component_success(self):
        """Test successful component unload."""
        # Create test component
        mock_module = Mock()
        sys.modules["test_module"] = mock_module
        self.module_cache.add_module("test_module", mock_module, "test_component")
        
        # Track component
        self.state_tracker.track_component("test_component")
        self.state_tracker.update_component_status("test_component", ComponentStatus.LOADED)
        
        # Mock internal methods
        self.unloader._perform_unload_steps = Mock(return_value={
            'success': True,
            'modules_cleaned': 1,
            'warnings': []
        })
        
        result = self.unloader.unload_component("test_component")
        
        self.assertTrue(result.success)
        self.assertEqual(result.operation, OperationType.UNLOAD)
        self.assertEqual(result.status, ComponentStatus.UNLOADED)
        self.assertTrue(result.rollback_available)
        
        # Check statistics
        stats = self.unloader.get_unload_statistics()
        self.assertEqual(stats['operations']['total_unloads'], 1)
        self.assertEqual(stats['operations']['successful_unloads'], 1)
        
        # Cleanup
        if "test_module" in sys.modules:
            del sys.modules["test_module"]
    
    def test_unload_component_failure_with_rollback(self):
        """Test unload failure with rollback."""
        # Create test component
        mock_module = Mock()
        sys.modules["test_module"] = mock_module
        self.module_cache.add_module("test_module", mock_module, "test_component")
        
        # Track component
        metadata = ComponentMetadata(name="test_component")
        self.state_tracker.track_component("test_component", metadata)
        self.state_tracker.update_component_status("test_component", ComponentStatus.LOADED)
        
        # Mock internal methods to simulate failure
        self.unloader._perform_unload_steps = Mock(return_value={
            'success': False,
            'error': 'Simulated unload failure',
            'warnings': []
        })
        
        # Mock rollback to succeed
        self.unloader.rollback_unload = Mock(return_value=True)
        
        result = self.unloader.unload_component("test_component")
        
        self.assertFalse(result.success)
        self.assertEqual(result.status, ComponentStatus.FAILED)
        self.assertIn("Simulated unload failure", result.error_message)
        
        # Verify rollback was attempted
        self.unloader.rollback_unload.assert_called_once_with("test_component")
        
        # Check statistics
        stats = self.unloader.get_unload_statistics()
        self.assertEqual(stats['operations']['failed_unloads'], 1)
        self.assertEqual(stats['operations']['rollbacks_performed'], 1)
        
        # Cleanup
        if "test_module" in sys.modules:
            del sys.modules["test_module"]
    
    def test_rollback_unload_success(self):
        """Test successful unload rollback."""
        # Create snapshot
        snapshot = UnloadSnapshot("test_component")
        mock_module = Mock()
        snapshot.add_module_backup("test_module", mock_module)
        snapshot.sys_modules_backup["test_module"] = mock_module
        snapshot.component_state = Mock()
        snapshot.component_state.metadata = ComponentMetadata(name="test_component")
        
        self.unloader._unload_snapshots["test_component"] = snapshot
        
        # Mock state tracker methods
        self.state_tracker.track_component = Mock()
        self.state_tracker.update_component_status = Mock()
        
        result = self.unloader.rollback_unload("test_component")
        
        self.assertTrue(result)
        self.assertIn("test_module", sys.modules)
        
        # Verify state restoration
        self.state_tracker.track_component.assert_called_once()
        self.state_tracker.update_component_status.assert_called_once_with(
            "test_component", ComponentStatus.LOADED
        )
        
        # Cleanup
        if "test_module" in sys.modules:
            del sys.modules["test_module"]
    
    def test_rollback_unload_no_snapshot(self):
        """Test rollback without snapshot."""
        result = self.unloader.rollback_unload("nonexistent_component")
        self.assertFalse(result)
    
    def test_force_memory_cleanup(self):
        """Test force memory cleanup."""
        result = self.unloader.force_memory_cleanup()
        
        self.assertTrue(result['success'])
        self.assertIn('objects_collected', result)
        self.assertIn('final_object_count', result)
        self.assertIsInstance(result['objects_collected'], int)
    
    def test_get_unload_statistics(self):
        """Test getting unload statistics."""
        stats = self.unloader.get_unload_statistics()
        
        self.assertIn('operations', stats)
        self.assertIn('snapshots_available', stats)
        self.assertIn('components_with_history', stats)
        self.assertIn('memory_stats', stats)
        
        # Check operation stats structure
        ops = stats['operations']
        self.assertIn('total_unloads', ops)
        self.assertIn('successful_unloads', ops)
        self.assertIn('failed_unloads', ops)
        self.assertIn('rollbacks_performed', ops)
    
    def test_clear_unload_history_specific_component(self):
        """Test clearing history for specific component."""
        # Add some history
        self.unloader._unload_history["test_component"] = [Mock()]
        self.unloader._unload_snapshots["test_component"] = Mock()
        
        self.unloader.clear_unload_history("test_component")
        
        self.assertNotIn("test_component", self.unloader._unload_history)
        self.assertNotIn("test_component", self.unloader._unload_snapshots)
    
    def test_clear_unload_history_all_components(self):
        """Test clearing history for all components."""
        # Add some history
        self.unloader._unload_history["comp1"] = [Mock()]
        self.unloader._unload_history["comp2"] = [Mock()]
        self.unloader._unload_snapshots["comp1"] = Mock()
        
        self.unloader.clear_unload_history()
        
        self.assertEqual(len(self.unloader._unload_history), 0)
        self.assertEqual(len(self.unloader._unload_snapshots), 0)
    
    def test_perform_unload_steps_no_modules(self):
        """Test unload steps with no modules."""
        result = self.unloader._perform_unload_steps("empty_component")
        
        self.assertTrue(result['success'])
        self.assertEqual(result['modules_cleaned'], 0)
        self.assertIn("No modules to unload", result['warnings'])
    
    def test_perform_unload_steps_with_modules(self):
        """Test unload steps with modules."""
        # Create test modules
        mock_module = Mock()
        sys.modules["test_module"] = mock_module
        self.module_cache.add_module("test_module", mock_module, "test_component")
        
        # Track component
        self.state_tracker.track_component("test_component")
        
        result = self.unloader._perform_unload_steps("test_component")
        
        self.assertTrue(result['success'])
        self.assertGreater(result['modules_cleaned'], 0)
        
        # Verify module was removed from sys.modules
        self.assertNotIn("test_module", sys.modules)
    
    def test_thread_safety(self):
        """Test thread safety of unload operations."""
        results = []
        errors = []
        
        # Create test component
        mock_module = Mock()
        sys.modules["test_module"] = mock_module
        self.module_cache.add_module("test_module", mock_module, "test_component")
        self.state_tracker.track_component("test_component")
        self.state_tracker.update_component_status("test_component", ComponentStatus.LOADED)
        
        def unload_component():
            try:
                result = self.unloader.unload_component("test_component")
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=unload_component)
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Unexpected errors: {errors}")
        self.assertEqual(len(results), 3)
        
        # Only one should succeed (first one), others should fail due to validation
        successful_results = [r for r in results if r.success]
        failed_results = [r for r in results if not r.success]
        
        # With proper locking, operations should be serialized
        # The first should succeed, subsequent ones should fail validation
        self.assertGreaterEqual(len(successful_results), 1)
        
        # Cleanup
        if "test_module" in sys.modules:
            del sys.modules["test_module"]


if __name__ == '__main__':
    unittest.main()