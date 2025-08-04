"""
Unit tests for the hot reload cache system.

Tests cover ModuleCache, ComponentStateTracker, and ModuleReferenceCleanup
functionality including thread safety, dependency tracking, and cleanup operations.
"""

import unittest
import sys
import threading
import time
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import os

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hot_reload.cache import (
    ModuleCache, ComponentStateTracker, ModuleReferenceCleanup, 
    ModuleInfo
)
from hot_reload.models import ComponentState, ComponentStatus, ComponentMetadata
from hot_reload.errors import ErrorHandler


class TestModuleInfo(unittest.TestCase):
    """Test cases for ModuleInfo data class."""
    
    def test_module_info_creation(self):
        """Test basic ModuleInfo creation."""
        mock_module = Mock()
        info = ModuleInfo(
            name="test_module",
            module=mock_module,
            file_path="/test/path.py"
        )
        
        self.assertEqual(info.name, "test_module")
        self.assertEqual(info.module, mock_module)
        self.assertEqual(info.file_path, "/test/path.py")
        self.assertEqual(info.access_count, 0)
        self.assertIsInstance(info.load_time, datetime)
        self.assertIsInstance(info.dependencies, set)
        self.assertIsInstance(info.dependents, set)
    
    def test_mark_accessed(self):
        """Test access tracking."""
        info = ModuleInfo(name="test", module=Mock())
        initial_time = info.last_accessed
        initial_count = info.access_count
        
        time.sleep(0.01)  # Small delay to ensure time difference
        info.mark_accessed()
        
        self.assertEqual(info.access_count, initial_count + 1)
        self.assertGreater(info.last_accessed, initial_time)
    
    def test_dependency_management(self):
        """Test dependency tracking."""
        info = ModuleInfo(name="test", module=Mock())
        
        # Test adding dependencies
        info.add_dependency("dep1")
        info.add_dependency("dep2")
        self.assertEqual(info.dependencies, {"dep1", "dep2"})
        self.assertTrue(info.has_dependencies())
        
        # Test removing dependencies
        info.remove_dependency("dep1")
        self.assertEqual(info.dependencies, {"dep2"})
        
        info.remove_dependency("dep2")
        self.assertEqual(info.dependencies, set())
        self.assertFalse(info.has_dependencies())
    
    def test_dependent_management(self):
        """Test dependent tracking."""
        info = ModuleInfo(name="test", module=Mock())
        
        # Test adding dependents
        info.add_dependent("dependent1")
        info.add_dependent("dependent2")
        self.assertEqual(info.dependents, {"dependent1", "dependent2"})
        self.assertTrue(info.has_dependents())
        
        # Test removing dependents
        info.remove_dependent("dependent1")
        self.assertEqual(info.dependents, {"dependent2"})
        
        info.remove_dependent("dependent2")
        self.assertEqual(info.dependents, set())
        self.assertFalse(info.has_dependents())


class TestModuleCache(unittest.TestCase):
    """Test cases for ModuleCache class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.cache = ModuleCache()
        self.mock_module1 = Mock()
        self.mock_module1.__name__ = "test_module1"
        self.mock_module1.__file__ = "/test/module1.py"
        
        self.mock_module2 = Mock()
        self.mock_module2.__name__ = "test_module2"
        self.mock_module2.__file__ = "/test/module2.py"
    
    def test_add_module(self):
        """Test adding modules to cache."""
        result = self.cache.add_module("test_module1", self.mock_module1)
        self.assertTrue(result)
        self.assertTrue(self.cache.has_module("test_module1"))
        
        # Test adding with component name
        result = self.cache.add_module("test_module2", self.mock_module2, 
                                     component_name="test_component")
        self.assertTrue(result)
        self.assertTrue(self.cache.has_module("test_module2"))
        
        # Check component tracking
        component_modules = self.cache.get_component_modules("test_component")
        self.assertEqual(component_modules, {"test_module2"})
    
    def test_get_module(self):
        """Test retrieving modules from cache."""
        self.cache.add_module("test_module1", self.mock_module1)
        
        retrieved = self.cache.get_module("test_module1")
        self.assertEqual(retrieved, self.mock_module1)
        
        # Test access count increment
        info = self.cache.get_module_info("test_module1")
        self.assertEqual(info.access_count, 1)
        
        # Test non-existent module
        self.assertIsNone(self.cache.get_module("non_existent"))
    
    def test_remove_module(self):
        """Test removing modules from cache."""
        self.cache.add_module("test_module1", self.mock_module1, 
                            component_name="test_component")
        
        self.assertTrue(self.cache.has_module("test_module1"))
        
        result = self.cache.remove_module("test_module1")
        self.assertTrue(result)
        self.assertFalse(self.cache.has_module("test_module1"))
        
        # Check component tracking cleanup
        component_modules = self.cache.get_component_modules("test_component")
        self.assertEqual(component_modules, set())
        
        # Test removing non-existent module
        result = self.cache.remove_module("non_existent")
        self.assertFalse(result)
    
    def test_component_module_tracking(self):
        """Test component module tracking."""
        # Add modules for a component
        self.cache.add_module("mod1", self.mock_module1, component_name="comp1")
        self.cache.add_module("mod2", self.mock_module2, component_name="comp1")
        
        modules = self.cache.get_component_modules("comp1")
        self.assertEqual(modules, {"mod1", "mod2"})
        
        # Remove all component modules
        removed = self.cache.remove_component_modules("comp1")
        self.assertEqual(set(removed), {"mod1", "mod2"})
        
        # Check they're gone
        self.assertFalse(self.cache.has_module("mod1"))
        self.assertFalse(self.cache.has_module("mod2"))
        self.assertEqual(self.cache.get_component_modules("comp1"), set())
    
    def test_dependency_tracking(self):
        """Test module dependency tracking."""
        # Add modules
        self.cache.add_module("mod1", self.mock_module1)
        self.cache.add_module("mod2", self.mock_module2)
        
        # Manually set up dependencies for testing
        info1 = self.cache.get_module_info("mod1")
        info2 = self.cache.get_module_info("mod2")
        
        info1.add_dependency("mod2")
        info2.add_dependent("mod1")
        
        # Test dependency retrieval
        deps = self.cache.get_module_dependencies("mod1")
        self.assertEqual(deps, {"mod2"})
        
        dependents = self.cache.get_module_dependents("mod2")
        self.assertEqual(dependents, {"mod1"})
        
        # Test dependency chain
        chain = self.cache.get_dependency_chain("mod1")
        self.assertEqual(chain, ["mod2", "mod1"])
    
    def test_cache_stats(self):
        """Test cache statistics."""
        # Add some modules
        self.cache.add_module("mod1", self.mock_module1, component_name="comp1")
        self.cache.add_module("mod2", self.mock_module2)
        
        # Access one module
        self.cache.get_module("mod1")
        
        stats = self.cache.get_cache_stats()
        
        self.assertEqual(stats['total_modules'], 2)
        self.assertEqual(stats['component_modules'], 1)
        self.assertEqual(stats['components_tracked'], 1)
        self.assertEqual(stats['total_accesses'], 1)
        self.assertGreater(stats['total_size_bytes'], 0)
    
    def test_clear_cache(self):
        """Test cache clearing."""
        self.cache.add_module("mod1", self.mock_module1)
        self.cache.add_module("mod2", self.mock_module2)
        
        count = self.cache.clear_cache()
        self.assertEqual(count, 2)
        self.assertFalse(self.cache.has_module("mod1"))
        self.assertFalse(self.cache.has_module("mod2"))
        
        stats = self.cache.get_cache_stats()
        self.assertEqual(stats['total_modules'], 0)
    
    def test_thread_safety(self):
        """Test thread safety of cache operations."""
        results = []
        errors = []
        
        def add_modules(start_idx):
            try:
                for i in range(start_idx, start_idx + 10):
                    mock_module = Mock()
                    mock_module.__name__ = f"module_{i}"
                    result = self.cache.add_module(f"module_{i}", mock_module)
                    results.append(result)
            except Exception as e:
                errors.append(e)
        
        def remove_modules(start_idx):
            try:
                for i in range(start_idx, start_idx + 5):
                    result = self.cache.remove_module(f"module_{i}")
                    results.append(result)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        threads.append(threading.Thread(target=add_modules, args=(0,)))
        threads.append(threading.Thread(target=add_modules, args=(10,)))
        threads.append(threading.Thread(target=remove_modules, args=(0,)))
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Check no errors occurred
        self.assertEqual(len(errors), 0)
        self.assertGreater(len(results), 0)


class TestComponentStateTracker(unittest.TestCase):
    """Test cases for ComponentStateTracker class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.cache = ModuleCache()
        self.error_handler = ErrorHandler()
        self.tracker = ComponentStateTracker(self.cache, self.error_handler)
        
        self.metadata = ComponentMetadata(
            name="test_component",
            description="Test component",
            version="1.0.0"
        )
    
    def test_track_component(self):
        """Test component tracking."""
        state = self.tracker.track_component("test_component", self.metadata)
        
        self.assertEqual(state.name, "test_component")
        self.assertEqual(state.status, ComponentStatus.UNKNOWN)
        self.assertEqual(state.metadata, self.metadata)
        
        # Test tracking existing component
        state2 = self.tracker.track_component("test_component")
        self.assertEqual(state, state2)
    
    def test_update_component_status(self):
        """Test component status updates."""
        self.tracker.track_component("test_component")
        
        result = self.tracker.update_component_status("test_component", 
                                                    ComponentStatus.LOADING)
        self.assertTrue(result)
        
        state = self.tracker.get_component_state("test_component")
        self.assertEqual(state.status, ComponentStatus.LOADING)
        
        # Test updating to LOADED status
        mock_module = Mock()
        self.cache.add_module("test_module", mock_module, 
                            component_name="test_component")
        
        result = self.tracker.update_component_status("test_component", 
                                                    ComponentStatus.LOADED)
        self.assertTrue(result)
        
        state = self.tracker.get_component_state("test_component")
        self.assertEqual(state.status, ComponentStatus.LOADED)
        self.assertIn("test_module", state.module_references)
        
        # Test updating non-existent component
        result = self.tracker.update_component_status("non_existent", 
                                                    ComponentStatus.LOADED)
        self.assertFalse(result)
    
    def test_get_components_by_status(self):
        """Test filtering components by status."""
        self.tracker.track_component("comp1")
        self.tracker.track_component("comp2")
        self.tracker.track_component("comp3")
        
        self.tracker.update_component_status("comp1", ComponentStatus.LOADED)
        self.tracker.update_component_status("comp2", ComponentStatus.FAILED)
        self.tracker.update_component_status("comp3", ComponentStatus.LOADED)
        
        loaded = self.tracker.get_components_by_status(ComponentStatus.LOADED)
        self.assertEqual(set(loaded), {"comp1", "comp3"})
        
        failed = self.tracker.get_components_by_status(ComponentStatus.FAILED)
        self.assertEqual(failed, ["comp2"])
    
    def test_get_failed_components(self):
        """Test getting failed components with error messages."""
        self.tracker.track_component("comp1")
        self.tracker.track_component("comp2")
        
        self.tracker.update_component_status("comp1", ComponentStatus.FAILED, 
                                           "Import error")
        self.tracker.update_component_status("comp2", ComponentStatus.LOADED)
        
        failed = self.tracker.get_failed_components()
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0][0], "comp1")
        self.assertEqual(failed[0][1], "Import error")
    
    def test_cleanup_component_state(self):
        """Test component state cleanup."""
        # Set up component with modules
        self.tracker.track_component("test_component")
        mock_module = Mock()
        self.cache.add_module("test_module", mock_module, 
                            component_name="test_component")
        
        self.tracker.update_component_status("test_component", 
                                           ComponentStatus.LOADED)
        
        # Verify setup
        self.assertIsNotNone(self.tracker.get_component_state("test_component"))
        self.assertTrue(self.cache.has_module("test_module"))
        
        # Cleanup
        result = self.tracker.cleanup_component_state("test_component")
        self.assertTrue(result)
        
        # Verify cleanup
        self.assertIsNone(self.tracker.get_component_state("test_component"))
        self.assertFalse(self.cache.has_module("test_module"))
    
    def test_remove_component(self):
        """Test component removal."""
        self.tracker.track_component("test_component")
        self.assertIsNotNone(self.tracker.get_component_state("test_component"))
        
        result = self.tracker.remove_component("test_component")
        self.assertTrue(result)
        self.assertIsNone(self.tracker.get_component_state("test_component"))
        
        # Test removing non-existent component
        result = self.tracker.remove_component("non_existent")
        self.assertFalse(result)


class TestModuleReferenceCleanup(unittest.TestCase):
    """Test cases for ModuleReferenceCleanup class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.cache = ModuleCache()
        self.cleanup = ModuleReferenceCleanup(self.cache)
        
        # Create temporary test modules
        self.test_modules = {}
        for i in range(3):
            mock_module = Mock()
            mock_module.__name__ = f"test_module_{i}"
            mock_module.__file__ = f"/test/module_{i}.py"
            self.test_modules[f"test_module_{i}"] = mock_module
    
    def test_cleanup_sys_modules(self):
        """Test sys.modules cleanup."""
        # Add test modules to sys.modules and cache
        for name, module in self.test_modules.items():
            sys.modules[name] = module
            self.cache.add_module(name, module)
        
        # Verify they're in sys.modules
        for name in self.test_modules:
            self.assertIn(name, sys.modules)
        
        # Cleanup
        module_names = list(self.test_modules.keys())
        cleaned = self.cleanup.cleanup_sys_modules(module_names)
        
        # Verify cleanup
        self.assertEqual(set(cleaned), set(module_names))
        for name in self.test_modules:
            self.assertNotIn(name, sys.modules)
    
    @patch('importlib.invalidate_caches')
    def test_cleanup_importlib_cache(self, mock_invalidate):
        """Test importlib cache cleanup."""
        # Add modules to cache
        for name, module in self.test_modules.items():
            self.cache.add_module(name, module, file_path=f"/test/{name}.py")
        
        module_names = list(self.test_modules.keys())
        result = self.cleanup.cleanup_importlib_cache(module_names)
        
        self.assertTrue(result)
        mock_invalidate.assert_called_once()
    
    @patch('gc.collect')
    @patch('gc.get_objects')
    def test_force_garbage_collection(self, mock_get_objects, mock_collect):
        """Test forced garbage collection."""
        mock_get_objects.side_effect = [list(range(100)), list(range(90))]
        mock_collect.return_value = 10
        
        stats = self.cleanup.force_garbage_collection()
        
        self.assertEqual(stats['collected'], 10)
        self.assertEqual(stats['initial_objects'], 100)
        self.assertEqual(stats['final_objects'], 90)
        self.assertEqual(stats['freed_objects'], 10)
        
        mock_collect.assert_called_once()
        self.assertEqual(mock_get_objects.call_count, 2)
    
    def test_cleanup_component_references(self):
        """Test comprehensive component reference cleanup."""
        component_name = "test_component"
        
        # Add modules to cache and sys.modules
        for name, module in self.test_modules.items():
            sys.modules[name] = module
            self.cache.add_module(name, module, component_name=component_name)
        
        # Perform cleanup
        results = self.cleanup.cleanup_component_references(component_name)
        
        # Verify results
        self.assertTrue(results['success'])
        self.assertEqual(results['component_name'], component_name)
        self.assertEqual(set(results['modules_cleaned']), set(self.test_modules.keys()))
        self.assertEqual(set(results['sys_modules_cleaned']), set(self.test_modules.keys()))
        self.assertTrue(results['cache_cleaned'])
        self.assertIn('gc_stats', results)
        
        # Verify cleanup
        for name in self.test_modules:
            self.assertNotIn(name, sys.modules)
            self.assertFalse(self.cache.has_module(name))


class TestCacheIntegration(unittest.TestCase):
    """Integration tests for cache system components."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.cache = ModuleCache()
        self.error_handler = ErrorHandler()
        self.tracker = ComponentStateTracker(self.cache, self.error_handler)
        self.cleanup = ModuleReferenceCleanup(self.cache)
    
    def test_full_component_lifecycle(self):
        """Test complete component lifecycle with cache management."""
        component_name = "test_component"
        metadata = ComponentMetadata(name=component_name, version="1.0.0")
        
        # 1. Track component
        state = self.tracker.track_component(component_name, metadata)
        self.assertEqual(state.status, ComponentStatus.UNKNOWN)
        
        # 2. Add modules to cache
        mock_module1 = Mock()
        mock_module1.__name__ = "comp_module1"
        mock_module1.__file__ = "/test/comp_module1.py"
        
        mock_module2 = Mock()
        mock_module2.__name__ = "comp_module2"
        mock_module2.__file__ = "/test/comp_module2.py"
        
        self.cache.add_module("comp_module1", mock_module1, component_name)
        self.cache.add_module("comp_module2", mock_module2, component_name)
        
        # 3. Update status to loaded
        self.tracker.update_component_status(component_name, ComponentStatus.LOADED)
        
        state = self.tracker.get_component_state(component_name)
        self.assertEqual(state.status, ComponentStatus.LOADED)
        self.assertEqual(len(state.module_references), 2)
        
        # 4. Verify cache state
        self.assertTrue(self.cache.has_module("comp_module1"))
        self.assertTrue(self.cache.has_module("comp_module2"))
        
        component_modules = self.cache.get_component_modules(component_name)
        self.assertEqual(component_modules, {"comp_module1", "comp_module2"})
        
        # 5. Cleanup component
        cleanup_results = self.cleanup.cleanup_component_references(component_name)
        self.assertTrue(cleanup_results['success'])
        
        # 6. Verify cleanup
        self.assertFalse(self.cache.has_module("comp_module1"))
        self.assertFalse(self.cache.has_module("comp_module2"))
        self.assertEqual(self.cache.get_component_modules(component_name), set())
    
    def test_error_handling_integration(self):
        """Test error handling integration with cache system."""
        component_name = "failing_component"
        
        # Track component
        self.tracker.track_component(component_name)
        
        # Simulate error during loading
        error = ImportError("Module not found")
        error_report = self.error_handler.handle_component_error(
            component_name, "load", error
        )
        
        # Update status to failed
        self.tracker.update_component_status(component_name, ComponentStatus.FAILED, 
                                           str(error))
        
        # Verify error state
        state = self.tracker.get_component_state(component_name)
        self.assertEqual(state.status, ComponentStatus.FAILED)
        self.assertEqual(state.last_error, str(error))
        
        failed_components = self.tracker.get_failed_components()
        self.assertEqual(len(failed_components), 1)
        self.assertEqual(failed_components[0][0], component_name)
        
        # Cleanup should still work
        result = self.tracker.cleanup_component_state(component_name)
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()