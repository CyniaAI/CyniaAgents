"""
Unit tests for ComponentManager hot reload integration.

This module tests the extended ComponentManager functionality that integrates
with the hot reload system.
"""

import unittest
import tempfile
import shutil
import os
import sys
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from component_manager import ComponentManager
from component_base import BaseComponent, PlaceholderComponent
from hot_reload.models import ComponentStatus, ComponentMetadata, ReloadResult, InstallationResult, OperationType


class TestComponentManagerHotReload(unittest.TestCase):
    """Test cases for ComponentManager hot reload integration."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        self.config_path = os.path.join(self.temp_dir, "components.json")
        
        # Create components directory
        os.makedirs(self.components_dir, exist_ok=True)
        
        # Create a simple test component
        self.test_component_content = '''
from component_base import BaseComponent

class TestComponent(BaseComponent):
    name = "test_component"
    description = "A test component"
    requirements = ["requests"]
    
    def render(self):
        return "Test component rendered"

def get_component():
    return TestComponent()
'''
        
        # Write test component
        with open(os.path.join(self.components_dir, "test_component.py"), "w") as f:
            f.write(self.test_component_content)
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_component_manager_initialization(self):
        """Test that ComponentManager initializes with hot reload components."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Check that hot reload components are initialized
        self.assertIsNotNone(manager.hot_reload_manager)
        self.assertIsNotNone(manager.dependency_manager)
        self.assertIsNotNone(manager.component_loader)
        
        # Check that status tracking is initialized
        self.assertIsInstance(manager._component_statuses, dict)
        self.assertIsInstance(manager._component_metadata, dict)
    
    @patch('component_manager.ComponentManager._discover_components_legacy')
    def test_discover_components_with_hot_reload(self, mock_legacy_discover):
        """Test component discovery with hot reload integration."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Check that the test component was discovered
        self.assertIn("test_component", manager.available)
        
        # Check that component status is tracked
        status = manager.get_component_status("test_component")
        self.assertIn(status, [ComponentStatus.LOADED, ComponentStatus.FAILED])
        
        # Verify legacy discovery was called
        mock_legacy_discover.assert_called_once()
    
    def test_reload_component(self):
        """Test component reloading functionality."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Mock the hot reload manager
        mock_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.LOADED
        )
        manager.hot_reload_manager.hot_reload_component = Mock(return_value=mock_result)
        
        # Test reload
        result = manager.reload_component("test_component")
        
        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.component_name, "test_component")
        
        # Verify hot reload manager was called
        manager.hot_reload_manager.hot_reload_component.assert_called_once_with("test_component", None)
        
        # Verify status was updated
        self.assertEqual(manager.get_component_status("test_component"), ComponentStatus.LOADED)
    
    def test_reload_component_failure(self):
        """Test component reload failure handling."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Mock failed reload
        mock_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="Reload failed"
        )
        manager.hot_reload_manager.hot_reload_component = Mock(return_value=mock_result)
        
        # Test reload
        result = manager.reload_component("test_component")
        
        # Verify result
        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Reload failed")
        
        # Verify status was updated to failed
        self.assertEqual(manager.get_component_status("test_component"), ComponentStatus.FAILED)
    
    def test_unload_component(self):
        """Test component unloading functionality."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Add component to enabled list
        manager.enabled.append("test_component")
        
        # Mock the hot reload manager
        mock_result = ReloadResult(
            component_name="test_component",
            operation=OperationType.UNLOAD,
            success=True,
            status=ComponentStatus.UNLOADED,
            previous_status=ComponentStatus.LOADED
        )
        manager.hot_reload_manager.unload_component = Mock(return_value=mock_result)
        
        # Test unload
        result = manager.unload_component("test_component")
        
        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.component_name, "test_component")
        
        # Verify hot reload manager was called
        manager.hot_reload_manager.unload_component.assert_called_once_with("test_component", False)
        
        # Verify component was removed from available and enabled
        self.assertNotIn("test_component", manager.available)
        self.assertNotIn("test_component", manager.enabled)
        
        # Verify status was updated
        self.assertEqual(manager.get_component_status("test_component"), ComponentStatus.UNLOADED)
    
    def test_install_dependencies(self):
        """Test dependency installation functionality."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Create mock dependency info indicating missing dependency
        from hot_reload.models import DependencyInfo, DependencyStatus
        mock_dep_info = DependencyInfo(
            name="requests",
            status=DependencyStatus.MISSING
        )
        
        # Mock dependency manager
        mock_result = InstallationResult(
            component_name="test_component",
            dependencies=[],
            success=True,
            installed_packages=["requests"],
            failed_packages=[]
        )
        manager.dependency_manager.pip_installer.install_packages = Mock(return_value=mock_result)
        manager.dependency_manager.check_dependencies = Mock(return_value=[mock_dep_info])
        
        # Test installation
        result = manager.install_dependencies("test_component", ["requests"])
        
        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.component_name, "test_component")
        self.assertIn("requests", result.installed_packages)
    
    def test_install_dependencies_from_metadata(self):
        """Test dependency installation using component metadata."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Create mock metadata
        metadata = ComponentMetadata(
            name="metadata_component",
            requirements=["requests", "numpy"]
        )
        manager._component_metadata["metadata_component"] = metadata
        
        # Create mock dependency info indicating missing dependencies
        from hot_reload.models import DependencyInfo, DependencyStatus
        mock_dep_info1 = DependencyInfo(name="requests", status=DependencyStatus.MISSING)
        mock_dep_info2 = DependencyInfo(name="numpy", status=DependencyStatus.MISSING)
        
        # Mock dependency manager
        mock_result = InstallationResult(
            component_name="metadata_component",
            dependencies=[],
            success=True,
            installed_packages=["requests", "numpy"],
            failed_packages=[]
        )
        manager.dependency_manager.pip_installer.install_packages = Mock(return_value=mock_result)
        manager.dependency_manager.check_dependencies = Mock(return_value=[mock_dep_info1, mock_dep_info2])
        
        # Test installation without specifying requirements
        result = manager.install_dependencies("metadata_component")
        
        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(len(result.installed_packages), 2)
    
    def test_get_component_status(self):
        """Test component status retrieval."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Mock hot reload manager status
        manager.hot_reload_manager.get_component_status = Mock(return_value=ComponentStatus.LOADED)
        
        # Test status retrieval
        status = manager.get_component_status("test_component")
        
        # Verify status
        self.assertEqual(status, ComponentStatus.LOADED)
        
        # Verify hot reload manager was called
        manager.hot_reload_manager.get_component_status.assert_called_once_with("test_component")
    
    def test_get_component_status_fallback(self):
        """Test component status fallback to local tracking."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Mock hot reload manager to return unknown
        manager.hot_reload_manager.get_component_status = Mock(return_value=ComponentStatus.UNKNOWN)
        
        # Set local status
        manager._component_statuses["test_component"] = ComponentStatus.LOADED
        
        # Test status retrieval
        status = manager.get_component_status("test_component")
        
        # Verify fallback to local status
        self.assertEqual(status, ComponentStatus.LOADED)
    
    def test_get_component_metadata(self):
        """Test component metadata retrieval."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Create mock metadata
        metadata = ComponentMetadata(name="test_component", description="Test")
        manager._component_metadata["test_component"] = metadata
        
        # Test metadata retrieval
        retrieved_metadata = manager.get_component_metadata("test_component")
        
        # Verify metadata
        self.assertEqual(retrieved_metadata, metadata)
        self.assertEqual(retrieved_metadata.name, "test_component")
    
    def test_track_component_status(self):
        """Test component status tracking."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Create mock metadata
        metadata = ComponentMetadata(name="test_component", description="Test")
        
        # Track status
        manager.track_component_status("test_component", ComponentStatus.LOADED, metadata)
        
        # Verify tracking
        self.assertEqual(manager._component_statuses["test_component"], ComponentStatus.LOADED)
        self.assertEqual(manager._component_metadata["test_component"], metadata)
    
    def test_get_all_component_statuses(self):
        """Test retrieval of all component statuses."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Clear existing statuses and set specific ones
        manager._component_statuses.clear()
        manager._component_statuses["comp1"] = ComponentStatus.LOADED
        manager._component_statuses["comp2"] = ComponentStatus.FAILED
        
        # Get all statuses
        all_statuses = manager.get_all_component_statuses()
        
        # Verify statuses
        self.assertEqual(len(all_statuses), 2)
        self.assertEqual(all_statuses["comp1"], ComponentStatus.LOADED)
        self.assertEqual(all_statuses["comp2"], ComponentStatus.FAILED)
        
        # Verify it's a copy (not the original dict)
        all_statuses["comp3"] = ComponentStatus.UNKNOWN
        self.assertNotIn("comp3", manager._component_statuses)
    
    def test_validate_component_unload(self):
        """Test component unload validation."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Mock validation result
        mock_validation = Mock()
        manager.hot_reload_manager.validate_component_unload = Mock(return_value=mock_validation)
        
        # Test validation
        result = manager.validate_component_unload("test_component", force=True)
        
        # Verify result
        self.assertEqual(result, mock_validation)
        
        # Verify hot reload manager was called
        manager.hot_reload_manager.validate_component_unload.assert_called_once_with("test_component", True)
    
    def test_get_component_dependencies(self):
        """Test component dependencies retrieval."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Create mock metadata with dependencies
        metadata = ComponentMetadata(
            name="test_component",
            requirements=["requests", "numpy"]
        )
        manager._component_metadata["test_component"] = metadata
        
        # Test dependencies retrieval
        deps = manager.get_component_dependencies("test_component")
        
        # Verify dependencies
        self.assertEqual(deps, ["requests", "numpy"])
    
    def test_get_component_dependencies_fallback(self):
        """Test component dependencies fallback to component instance."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Clear metadata to force fallback
        manager._component_metadata.clear()
        
        # Create mock component with requirements
        mock_component = Mock()
        mock_component.requirements = ["pandas", "matplotlib"]
        manager.available["fallback_component"] = mock_component
        
        # Test dependencies retrieval (no metadata)
        deps = manager.get_component_dependencies("fallback_component")
        
        # Verify fallback to component instance
        self.assertEqual(deps, ["pandas", "matplotlib"])
    
    def test_get_component_dependencies_empty(self):
        """Test component dependencies when none exist."""
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Test dependencies retrieval for non-existent component
        deps = manager.get_component_dependencies("non_existent")
        
        # Verify empty list
        self.assertEqual(deps, [])


class TestComponentManagerIntegration(unittest.TestCase):
    """Integration tests for ComponentManager with hot reload system."""
    
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
    
    def test_full_component_lifecycle(self):
        """Test complete component lifecycle with hot reload."""
        # Create initial component
        component_content = '''
from component_base import BaseComponent

class TestComponent(BaseComponent):
    name = "lifecycle_test"
    description = "Lifecycle test component"
    version = "1.0.0"
    
    def render(self):
        return "Version 1.0.0"

def get_component():
    return TestComponent()
'''
        
        component_path = os.path.join(self.components_dir, "lifecycle_test.py")
        with open(component_path, "w") as f:
            f.write(component_content)
        
        # Initialize manager
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Verify component was discovered
        self.assertIn("lifecycle_test", manager.available)
        
        # Get initial status
        initial_status = manager.get_component_status("lifecycle_test")
        self.assertIn(initial_status, [ComponentStatus.LOADED, ComponentStatus.FAILED])
        
        # Test metadata retrieval
        metadata = manager.get_component_metadata("lifecycle_test")
        if metadata:
            self.assertEqual(metadata.name, "lifecycle_test")
    
    def test_component_with_requirements(self):
        """Test component with requirements file."""
        # Create component with requirements
        component_content = '''
from component_base import BaseComponent

class RequirementsComponent(BaseComponent):
    name = "requirements_test"
    description = "Component with requirements"
    requirements = ["requests"]
    
    def render(self):
        return "Component with requirements"

def get_component():
    return RequirementsComponent()
'''
        
        # Create requirements.txt
        requirements_content = "numpy>=1.20.0\npandas>=1.3.0\n"
        
        component_path = os.path.join(self.components_dir, "requirements_test.py")
        requirements_path = os.path.join(self.components_dir, "requirements.txt")
        
        with open(component_path, "w") as f:
            f.write(component_content)
        with open(requirements_path, "w") as f:
            f.write(requirements_content)
        
        # Initialize manager
        manager = ComponentManager(self.components_dir, self.config_path)
        
        # Test dependencies retrieval
        deps = manager.get_component_dependencies("requirements_test")
        self.assertIn("requests", deps)


if __name__ == '__main__':
    unittest.main()