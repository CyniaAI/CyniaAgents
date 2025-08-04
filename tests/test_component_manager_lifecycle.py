"""
End-to-end tests for ComponentManager lifecycle management.

This module tests the complete component lifecycle including enabling,
disabling, update detection, and dependency tracking.
"""

import unittest
import tempfile
import shutil
import os
import sys
import time
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from datetime import datetime, timedelta

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from component_manager import ComponentManager
from component_base import BaseComponent
from hot_reload.models import ComponentStatus, ComponentMetadata, ReloadResult, OperationType


class TestComponentManagerLifecycle(unittest.TestCase):
    """Test cases for ComponentManager lifecycle management."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        self.config_path = os.path.join(self.temp_dir, "components.json")
        
        # Create components directory
        os.makedirs(self.components_dir, exist_ok=True)
        
        # Mock FileWatcher to avoid recursion issues
        self.file_watcher_patcher = patch('hot_reload.file_watcher.FileWatcher')
        self.mock_file_watcher = self.file_watcher_patcher.start()
        self.mock_watcher_instance = Mock()
        self.mock_file_watcher.return_value = self.mock_watcher_instance
    
    def tearDown(self):
        """Clean up test environment."""
        self.file_watcher_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def create_test_component(self, name: str, requirements: list = None) -> str:
        """Create a test component file."""
        requirements = requirements or []
        req_str = str(requirements) if requirements else "[]"
        
        content = f'''
from component_base import BaseComponent

class {name.title()}Component(BaseComponent):
    name = "{name}"
    description = "Test component {name}"
    requirements = {req_str}
    
    def render(self):
        return "Test component {name} rendered"

def get_component():
    return {name.title()}Component()
'''
        
        component_path = os.path.join(self.components_dir, f"{name}.py")
        with open(component_path, "w") as f:
            f.write(content)
        
        return component_path
    
    def test_enable_component(self):
        """Test enabling a component."""
        # Create test component
        self.create_test_component("test_enable")
        
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Mock reload_component to avoid recursion
        mock_result = ReloadResult(
            component_name="test_enable",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNKNOWN
        )
        manager.reload_component = Mock(return_value=mock_result)
        
        # Add component to available (simulate discovery)
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "test_enable"
        manager.available["test_enable"] = mock_component
        
        # Test enabling component
        result = manager.enable_component("test_enable")
        
        # Verify result
        self.assertTrue(result)
        self.assertIn("test_enable", manager.enabled)
        self.assertTrue(manager.is_component_enabled("test_enable"))
    
    def test_enable_component_with_auto_reload(self):
        """Test enabling a component with auto-reload."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Mock reload_component
        mock_result = ReloadResult(
            component_name="test_auto_reload",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNKNOWN
        )
        manager.reload_component = Mock(return_value=mock_result)
        
        # Add component to available
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "test_auto_reload"
        manager.available["test_auto_reload"] = mock_component
        manager.track_component_status("test_auto_reload", ComponentStatus.FAILED)
        
        # Test enabling with auto-reload
        result = manager.enable_component("test_auto_reload", auto_reload=True)
        
        # Verify result
        self.assertTrue(result)
        self.assertIn("test_auto_reload", manager.enabled)
        manager.reload_component.assert_called_once_with("test_auto_reload")
    
    def test_disable_component(self):
        """Test disabling a component."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Add component to enabled list
        manager.enabled.append("test_disable")
        
        # Add component to available
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "test_disable"
        manager.available["test_disable"] = mock_component
        
        # Mock unload_component
        mock_result = ReloadResult(
            component_name="test_disable",
            operation=OperationType.UNLOAD,
            success=True,
            status=ComponentStatus.UNLOADED,
            previous_status=ComponentStatus.LOADED
        )
        manager.unload_component = Mock(return_value=mock_result)
        
        # Test disabling component
        result = manager.disable_component("test_disable", unload=True)
        
        # Verify result
        self.assertTrue(result)
        self.assertNotIn("test_disable", manager.enabled)
        self.assertFalse(manager.is_component_enabled("test_disable"))
        manager.unload_component.assert_called_once_with("test_disable")
    
    def test_disable_component_without_unload(self):
        """Test disabling a component without unloading."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Add component to enabled list
        manager.enabled.append("test_disable_no_unload")
        
        # Test disabling without unload
        result = manager.disable_component("test_disable_no_unload", unload=False)
        
        # Verify result
        self.assertTrue(result)
        self.assertNotIn("test_disable_no_unload", manager.enabled)
        self.assertEqual(manager.get_component_status("test_disable_no_unload"), ComponentStatus.DISABLED)
    
    def test_detect_component_updates(self):
        """Test component update detection."""
        # Create test component
        component_path = self.create_test_component("test_updates")
        
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Create metadata with old modification time
        old_time = datetime.now() - timedelta(hours=1)
        metadata = ComponentMetadata(
            name="test_updates",
            file_path=component_path,
            modified_at=old_time
        )
        manager._component_metadata["test_updates"] = metadata
        
        # Add to available
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "test_updates"
        manager.available["test_updates"] = mock_component
        
        # Test update detection
        updates = manager.detect_component_updates("test_updates")
        
        # Verify update detected (file should be newer than stored metadata)
        self.assertIn("test_updates", updates)
        self.assertTrue(updates["test_updates"])
    
    def test_detect_component_updates_no_updates(self):
        """Test component update detection when no updates exist."""
        # Create test component
        component_path = self.create_test_component("test_no_updates")
        
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Create metadata with current modification time
        current_time = datetime.fromtimestamp(Path(component_path).stat().st_mtime)
        metadata = ComponentMetadata(
            name="test_no_updates",
            file_path=component_path,
            modified_at=current_time
        )
        manager._component_metadata["test_no_updates"] = metadata
        
        # Add to available
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "test_no_updates"
        manager.available["test_no_updates"] = mock_component
        
        # Test update detection
        updates = manager.detect_component_updates("test_no_updates")
        
        # Verify no update detected
        self.assertIn("test_no_updates", updates)
        self.assertFalse(updates["test_no_updates"])
    
    def test_auto_reload_updated_components(self):
        """Test automatic reloading of updated components."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Mock detect_component_updates to return updates
        manager.detect_component_updates = Mock(return_value={
            "updated_component": True,
            "not_updated_component": False
        })
        
        # Add components to enabled list
        manager.enabled.extend(["updated_component", "not_updated_component"])
        
        # Mock reload_component
        mock_result = ReloadResult(
            component_name="updated_component",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.LOADED
        )
        manager.reload_component = Mock(return_value=mock_result)
        
        # Test auto-reload
        results = manager.auto_reload_updated_components(enabled_only=True)
        
        # Verify only updated component was reloaded
        self.assertIn("updated_component", results)
        self.assertNotIn("not_updated_component", results)
        self.assertTrue(results["updated_component"].success)
        manager.reload_component.assert_called_once_with("updated_component")
    
    def test_track_component_dependencies(self):
        """Test component dependency tracking."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Mock get_component_dependencies
        manager.get_component_dependencies = Mock(return_value=["requests", "numpy"])
        
        # Mock dependency manager
        from hot_reload.models import DependencyInfo, DependencyStatus
        mock_deps = [
            DependencyInfo(name="requests", status=DependencyStatus.SATISFIED),
            DependencyInfo(name="numpy", status=DependencyStatus.MISSING)
        ]
        manager.dependency_manager.check_dependencies = Mock(return_value=mock_deps)
        
        # Test dependency tracking
        result = manager.track_component_dependencies("test_deps")
        
        # Verify result
        self.assertEqual(result['component_name'], "test_deps")
        self.assertEqual(result['dependency_count'], 2)
        self.assertEqual(result['satisfied_count'], 1)
        self.assertEqual(result['missing_count'], 1)
        self.assertFalse(result['all_satisfied'])
        self.assertEqual(result['missing_dependencies'], ["numpy"])
    
    def test_get_component_lifecycle_info(self):
        """Test getting comprehensive component lifecycle information."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Set up component
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "lifecycle_test"
        manager.available["lifecycle_test"] = mock_component
        manager.enabled.append("lifecycle_test")
        manager.track_component_status("lifecycle_test", ComponentStatus.LOADED)
        
        # Mock metadata
        metadata = ComponentMetadata(name="lifecycle_test", description="Test component")
        manager._component_metadata["lifecycle_test"] = metadata
        
        # Mock dependency tracking
        manager.track_component_dependencies = Mock(return_value={
            'missing_count': 0,
            'all_satisfied': True
        })
        
        # Mock update detection
        manager.detect_component_updates = Mock(return_value={"lifecycle_test": False})
        
        # Test lifecycle info
        info = manager.get_component_lifecycle_info("lifecycle_test")
        
        # Verify comprehensive info
        self.assertEqual(info['component_name'], "lifecycle_test")
        self.assertEqual(info['status'], "loaded")
        self.assertTrue(info['is_enabled'])
        self.assertTrue(info['is_available'])
        self.assertFalse(info['has_updates'])
        self.assertIsNotNone(info['metadata'])
        self.assertIsNotNone(info['dependency_info'])
        self.assertIsNotNone(info['lifecycle_actions'])
        
        # Check lifecycle actions
        actions = info['lifecycle_actions']
        self.assertFalse(actions['can_enable'])  # Already enabled
        self.assertTrue(actions['can_disable'])
        self.assertTrue(actions['can_reload'])
        self.assertTrue(actions['can_unload'])
    
    def test_get_all_components_lifecycle_info(self):
        """Test getting lifecycle info for all components."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Set up multiple components
        components = ["comp1", "comp2", "comp3"]
        for comp_name in components:
            mock_component = Mock(spec=BaseComponent)
            mock_component.name = comp_name
            manager.available[comp_name] = mock_component
            manager.track_component_status(comp_name, ComponentStatus.LOADED)
        
        # Mock get_component_lifecycle_info
        def mock_lifecycle_info(name):
            return {'component_name': name, 'status': 'loaded'}
        
        manager.get_component_lifecycle_info = Mock(side_effect=mock_lifecycle_info)
        
        # Test getting all lifecycle info
        all_info = manager.get_all_components_lifecycle_info()
        
        # Verify all components included
        for comp_name in components:
            self.assertIn(comp_name, all_info)
            self.assertEqual(all_info[comp_name]['component_name'], comp_name)
    
    def test_cleanup_disabled_components(self):
        """Test cleanup of disabled components."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Set up components - some enabled, some disabled
        enabled_comp = Mock(spec=BaseComponent)
        enabled_comp.name = "enabled_comp"
        manager.available["enabled_comp"] = enabled_comp
        manager.enabled.append("enabled_comp")
        manager.track_component_status("enabled_comp", ComponentStatus.LOADED)
        
        disabled_comp = Mock(spec=BaseComponent)
        disabled_comp.name = "disabled_comp"
        manager.available["disabled_comp"] = disabled_comp
        manager.track_component_status("disabled_comp", ComponentStatus.DISABLED)
        
        failed_comp = Mock(spec=BaseComponent)
        failed_comp.name = "failed_comp"
        manager.available["failed_comp"] = failed_comp
        manager.track_component_status("failed_comp", ComponentStatus.FAILED)
        
        # Test cleanup
        cleaned_up = manager.cleanup_disabled_components()
        
        # Verify cleanup
        self.assertIn("disabled_comp", cleaned_up)
        self.assertIn("failed_comp", cleaned_up)
        self.assertNotIn("enabled_comp", cleaned_up)
        
        # Verify components were removed
        self.assertNotIn("disabled_comp", manager.available)
        self.assertNotIn("failed_comp", manager.available)
        self.assertIn("enabled_comp", manager.available)  # Should remain


class TestComponentManagerLifecycleIntegration(unittest.TestCase):
    """Integration tests for component lifecycle management."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        self.config_path = os.path.join(self.temp_dir, "components.json")
        
        # Create components directory
        os.makedirs(self.components_dir, exist_ok=True)
        
        # Mock FileWatcher to avoid issues
        self.file_watcher_patcher = patch('hot_reload.file_watcher.FileWatcher')
        self.mock_file_watcher = self.file_watcher_patcher.start()
        self.mock_watcher_instance = Mock()
        self.mock_file_watcher.return_value = self.mock_watcher_instance
    
    def tearDown(self):
        """Clean up test environment."""
        self.file_watcher_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_complete_lifecycle_workflow(self):
        """Test complete component lifecycle workflow."""
        # Create test component
        component_content = '''
from component_base import BaseComponent

class LifecycleComponent(BaseComponent):
    name = "lifecycle_component"
    description = "Complete lifecycle test"
    requirements = ["requests"]
    
    def render(self):
        return "Lifecycle component"

def get_component():
    return LifecycleComponent()
'''
        
        component_path = os.path.join(self.components_dir, "lifecycle_component.py")
        with open(component_path, "w") as f:
            f.write(component_content)
        
        # Initialize manager
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Mock hot reload operations to avoid recursion
        manager.reload_component = Mock(return_value=ReloadResult(
            component_name="lifecycle_component",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNKNOWN
        ))
        
        manager.unload_component = Mock(return_value=ReloadResult(
            component_name="lifecycle_component",
            operation=OperationType.UNLOAD,
            success=True,
            status=ComponentStatus.UNLOADED,
            previous_status=ComponentStatus.LOADED
        ))
        
        # Add component to available (simulate discovery)
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "lifecycle_component"
        manager.available["lifecycle_component"] = mock_component
        
        # Test complete workflow
        
        # 1. Enable component
        enable_result = manager.enable_component("lifecycle_component")
        self.assertTrue(enable_result)
        self.assertTrue(manager.is_component_enabled("lifecycle_component"))
        
        # 2. Get lifecycle info
        info = manager.get_component_lifecycle_info("lifecycle_component")
        self.assertEqual(info['component_name'], "lifecycle_component")
        self.assertTrue(info['is_enabled'])
        
        # 3. Disable component
        disable_result = manager.disable_component("lifecycle_component")
        self.assertTrue(disable_result)
        self.assertFalse(manager.is_component_enabled("lifecycle_component"))
        
        # 4. Cleanup
        cleaned_up = manager.cleanup_disabled_components()
        # Note: cleanup behavior depends on component status


if __name__ == '__main__':
    unittest.main()