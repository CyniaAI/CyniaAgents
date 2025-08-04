"""
Integration tests for ComponentManager dynamic discovery functionality.

This module tests the dynamic component discovery features including
real-time component detection and change notifications.
"""

import unittest
import tempfile
import shutil
import os
import sys
import time
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from component_manager import ComponentManager
from component_base import BaseComponent
from hot_reload.models import ComponentStatus


class TestComponentManagerDynamicDiscovery(unittest.TestCase):
    """Test cases for ComponentManager dynamic discovery."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        self.config_path = os.path.join(self.temp_dir, "components.json")
        
        # Create components directory
        os.makedirs(self.components_dir, exist_ok=True)
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def create_test_component(self, name: str, content: str = None) -> str:
        """Create a test component file."""
        if content is None:
            content = f'''
from component_base import BaseComponent

class {name.title()}Component(BaseComponent):
    name = "{name}"
    description = "Test component {name}"
    
    def render(self):
        return "Test component {name} rendered"

def get_component():
    return {name.title()}Component()
'''
        
        component_path = os.path.join(self.components_dir, f"{name}.py")
        with open(component_path, "w") as f:
            f.write(content)
        
        return component_path
    
    def test_setup_dynamic_discovery(self):
        """Test dynamic discovery setup."""
        with patch('hot_reload.file_watcher.FileWatcher') as mock_file_watcher:
            mock_watcher_instance = Mock()
            mock_file_watcher.return_value = mock_watcher_instance
            
            manager = ComponentManager(self.components_dir, self.config_path)
            
            # Verify file watcher was created and configured
            mock_file_watcher.assert_called_once_with(self.components_dir)
            mock_watcher_instance.add_component_created_callback.assert_called_with(manager._on_component_created)
            mock_watcher_instance.add_component_modified_callback.assert_called_with(manager._on_component_modified)
            mock_watcher_instance.add_component_deleted_callback.assert_called_with(manager._on_component_deleted)
            mock_watcher_instance.start_watching.assert_called_once()
    
    def test_dynamic_discovery_setup(self):
        """Test that dynamic discovery is properly set up."""
        with patch('hot_reload.file_watcher.FileWatcher') as mock_file_watcher:
            mock_watcher_instance = Mock()
            mock_file_watcher.return_value = mock_watcher_instance
            
            manager = ComponentManager(self.components_dir, self.config_path)
            
            # Verify dynamic discovery was set up
            self.assertTrue(hasattr(manager, '_file_watcher_setup'))
            self.assertTrue(manager._file_watcher_setup)
    
    def test_on_component_created(self):
        """Test component creation handling."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Create a test component file
        component_path = self.create_test_component("new_component")
        
        # Mock the component loader
        from hot_reload.models import ComponentMetadata
        mock_metadata = ComponentMetadata(name="new_component", description="Test")
        
        class MockLoadResult:
            success = True
            module = Mock()
            metadata = mock_metadata
            error_message = None
        
        mock_load_result = MockLoadResult()
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "new_component"
        mock_load_result.module.get_component.return_value = mock_component
        
        manager.component_loader.load_component_from_path = Mock(return_value=mock_load_result)
        
        # Test component creation
        manager._on_component_created("new_component", mock_metadata)
        
        # Verify component was added
        self.assertIn("new_component", manager.available)
        self.assertEqual(manager.get_component_status("new_component"), ComponentStatus.LOADED)
        
        # Verify loader was called with correct path
        expected_path = os.path.join(self.components_dir, "new_component.py")
        manager.component_loader.load_component_from_path.assert_called_once_with(expected_path)
    
    def test_on_component_modified(self):
        """Test component modification handling."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Create and add a component first
        component_path = self.create_test_component("existing_component")
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "existing_component"
        manager.available["existing_component"] = mock_component
        
        # Mock reload_component
        from hot_reload.models import ReloadResult, OperationType, ComponentMetadata
        mock_result = ReloadResult(
            component_name="existing_component",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.LOADED
        )
        manager.reload_component = Mock(return_value=mock_result)
        
        # Create mock metadata
        mock_metadata = ComponentMetadata(name="existing_component", description="Test")
        
        # Test component modification
        manager._on_component_modified("existing_component", mock_metadata)
        
        # Verify reload was called
        manager.reload_component.assert_called_once_with("existing_component")
    
    def test_on_component_deleted(self):
        """Test component deletion handling."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Add a component first
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "removed_component"
        manager.available["removed_component"] = mock_component
        manager.enabled.append("removed_component")
        
        # Test component deletion
        manager._on_component_deleted("removed_component")
        
        # Verify component was removed
        self.assertNotIn("removed_component", manager.available)
        self.assertNotIn("removed_component", manager.enabled)
        self.assertEqual(manager.get_component_status("removed_component"), ComponentStatus.UNLOADED)
    
    def test_component_change_notifications(self):
        """Test component change notification system."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Test notification creation
        manager._notify_component_change('added', 'test_component')
        manager._notify_component_change('modified', 'test_component')
        manager._notify_component_change('removed', 'test_component')
        
        # Get notifications
        notifications = manager.get_component_change_notifications()
        
        # Verify notifications
        self.assertEqual(len(notifications), 3)
        self.assertEqual(notifications[0]['type'], 'added')
        self.assertEqual(notifications[1]['type'], 'modified')
        self.assertEqual(notifications[2]['type'], 'removed')
        
        # Test filtering by timestamp
        first_timestamp = notifications[0]['timestamp']
        filtered = manager.get_component_change_notifications(since=first_timestamp)
        self.assertEqual(len(filtered), 2)  # Should exclude the first one
        
        # Test clearing notifications
        manager.clear_component_change_notifications()
        notifications = manager.get_component_change_notifications()
        self.assertEqual(len(notifications), 0)
    
    def test_discover_components_dynamic(self):
        """Test dynamic component discovery method."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Create test components
        self.create_test_component("dynamic1")
        self.create_test_component("dynamic2")
        
        # Mock component loader
        manager.component_loader.list_available_components = Mock(return_value=["dynamic1", "dynamic2"])
        
        # Mock load results
        from hot_reload.models import ComponentMetadata
        
        class MockLoadResult:
            def __init__(self, name):
                self.success = True
                self.module = Mock()
                self.metadata = ComponentMetadata(name=name, description=f"Test {name}")
                self.error_message = None
                
                mock_component = Mock(spec=BaseComponent)
                mock_component.name = name
                self.module.get_component.return_value = mock_component
        
        def mock_load_component(path):
            if "dynamic1" in path:
                return MockLoadResult("dynamic1")
            elif "dynamic2" in path:
                return MockLoadResult("dynamic2")
            else:
                result = Mock()
                result.success = False
                result.error_message = "Not found"
                return result
        
        manager.component_loader.load_component_from_path = Mock(side_effect=mock_load_component)
        
        # Test dynamic discovery
        manager.discover_components_dynamic()
        
        # Verify components were discovered
        self.assertIn("dynamic1", manager.available)
        self.assertIn("dynamic2", manager.available)
        self.assertEqual(manager.get_component_status("dynamic1"), ComponentStatus.LOADED)
        self.assertEqual(manager.get_component_status("dynamic2"), ComponentStatus.LOADED)
    
    def test_discover_components_dynamic_force_reload(self):
        """Test dynamic discovery with force reload."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Add existing component
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "existing"
        manager.available["existing"] = mock_component
        manager.track_component_status("existing", ComponentStatus.LOADED)
        
        # Mock component loader and reload
        manager.component_loader.list_available_components = Mock(return_value=["existing"])
        
        from hot_reload.models import ReloadResult, OperationType
        mock_result = ReloadResult(
            component_name="existing",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.LOADED
        )
        manager.reload_component = Mock(return_value=mock_result)
        
        # Test force reload
        manager.discover_components_dynamic(force_reload=True)
        
        # Verify reload was called
        manager.reload_component.assert_called_once_with("existing")
    
    def test_discover_components_dynamic_cleanup(self):
        """Test dynamic discovery cleanup of non-existent components."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Add component that doesn't exist on disk
        mock_component = Mock(spec=BaseComponent)
        mock_component.name = "nonexistent"
        manager.available["nonexistent"] = mock_component
        manager.enabled.append("nonexistent")
        
        # Mock component loader to return empty list
        manager.component_loader.list_available_components = Mock(return_value=[])
        
        # Test dynamic discovery
        manager.discover_components_dynamic()
        
        # Verify component was removed
        self.assertNotIn("nonexistent", manager.available)
        self.assertNotIn("nonexistent", manager.enabled)
        self.assertEqual(manager.get_component_status("nonexistent"), ComponentStatus.UNLOADED)
    
    def test_stop_dynamic_discovery(self):
        """Test stopping dynamic discovery."""
        with patch('hot_reload.file_watcher.FileWatcher') as mock_file_watcher:
            mock_watcher_instance = Mock()
            mock_file_watcher.return_value = mock_watcher_instance
            
            manager = ComponentManager(self.components_dir, self.config_path)
            
            # Test stopping discovery
            manager.stop_dynamic_discovery()
            
            # Verify stop was called
            mock_watcher_instance.stop_watching.assert_called_once()
    
    def test_is_dynamic_discovery_active(self):
        """Test checking if dynamic discovery is active."""
        with patch('hot_reload.file_watcher.FileWatcher') as mock_file_watcher:
            mock_watcher_instance = Mock()
            mock_watcher_instance.is_watching.return_value = True
            mock_file_watcher.return_value = mock_watcher_instance
            
            manager = ComponentManager(self.components_dir, self.config_path)
            
            # Test active check
            is_active = manager.is_dynamic_discovery_active()
            
            # Verify result
            self.assertTrue(is_active)
            mock_watcher_instance.is_watching.assert_called_once()


class TestComponentManagerDynamicDiscoveryIntegration(unittest.TestCase):
    """Integration tests for dynamic discovery functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        self.config_path = os.path.join(self.temp_dir, "components.json")
        
        # Create components directory
        os.makedirs(self.components_dir, exist_ok=True)
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_full_dynamic_discovery_workflow(self):
        """Test complete dynamic discovery workflow."""
        # Create initial component
        component_content = '''
from component_base import BaseComponent

class DynamicTestComponent(BaseComponent):
    name = "dynamic_test"
    description = "Dynamic test component"
    version = "1.0.0"
    
    def render(self):
        return "Dynamic test component"

def get_component():
    return DynamicTestComponent()
'''
        
        component_path = os.path.join(self.components_dir, "dynamic_test.py")
        with open(component_path, "w") as f:
            f.write(component_content)
        
        # Initialize manager with mocked file watcher
        with patch('hot_reload.file_watcher.FileWatcher'):
            manager = ComponentManager(self.components_dir, self.config_path)
            
            # Test dynamic discovery
            manager.discover_components_dynamic()
            
            # Verify component was discovered
            self.assertIn("dynamic_test", manager.available)
            
            # Test change notifications
            notifications = manager.get_component_change_notifications()
            # Note: Notifications might be empty in this test since we're not actually triggering file events
            
            # Test cleanup
            manager.stop_dynamic_discovery()


if __name__ == '__main__':
    unittest.main()