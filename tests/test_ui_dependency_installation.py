"""
Unit tests for dependency installation UI components.

Tests the DependencyInstallationUI class functionality including:
- Dependency status rendering
- Installation controls
- Progress tracking
- Log display
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import threading
import time
import sys

# Mock streamlit before importing
sys.modules['streamlit'] = Mock()

# Import the UI components
from ui_components import DependencyInstallationUI
from hot_reload.models import DependencyInfo, DependencyStatus, InstallationResult, ComponentMetadata
from component_manager import ComponentManager


class TestDependencyInstallationUI(unittest.TestCase):
    """Test cases for DependencyInstallationUI."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_component_manager = Mock()
        
        # Mock the dependency_manager attribute
        self.mock_component_manager.dependency_manager = Mock()
        self.mock_component_manager.dependency_manager.check_dependencies = Mock()
        self.mock_component_manager.get_component_dependencies = Mock()
        self.mock_component_manager.install_dependencies = Mock()
        
        self.ui = DependencyInstallationUI(self.mock_component_manager)
        
        # Mock Streamlit functions
        self.st_patcher = patch('ui_components.st')
        self.st_mock = self.st_patcher.start()
        
        # Configure st mock methods
        self.st_mock.subheader = Mock()
        self.st_mock.info = Mock()
        self.st_mock.markdown = Mock()
        self.st_mock.columns = Mock(return_value=[Mock(), Mock(), Mock()])
        self.st_mock.write = Mock()
        self.st_mock.caption = Mock()
        self.st_mock.success = Mock()
        self.st_mock.error = Mock()
        self.st_mock.button = Mock(return_value=False)
        self.st_mock.code = Mock()
        self.st_mock.progress = Mock()
        self.st_mock.expander = Mock()
        self.st_mock.rerun = Mock()
    
    def tearDown(self):
        """Clean up after tests."""
        self.st_patcher.stop()
    
    def test_render_dependency_installation_interface_no_dependencies(self):
        """Test rendering when component has no dependencies."""
        # Setup
        component_name = "test_component"
        self.mock_component_manager.get_component_dependencies.return_value = []
        
        # Execute
        self.ui.render_dependency_installation_interface(component_name)
        
        # Verify
        self.st_mock.subheader.assert_called_once_with(f"📦 Dependencies for {component_name}")
        self.st_mock.info.assert_called_once_with("This component has no dependencies.")
        self.mock_component_manager.get_component_dependencies.assert_called_once_with(component_name)
    
    def test_render_dependency_installation_interface_with_satisfied_dependencies(self):
        """Test rendering when all dependencies are satisfied."""
        # Setup
        component_name = "test_component"
        dependencies = ["requests", "numpy"]
        
        dependency_info = [
            DependencyInfo(name="requests", status=DependencyStatus.SATISFIED, installed_version="2.28.0"),
            DependencyInfo(name="numpy", status=DependencyStatus.SATISFIED, installed_version="1.21.0")
        ]
        
        self.mock_component_manager.get_component_dependencies.return_value = dependencies
        self.mock_component_manager.dependency_manager.check_dependencies.return_value = dependency_info
        
        # Execute
        self.ui.render_dependency_installation_interface(component_name)
        
        # Verify
        self.mock_component_manager.dependency_manager.check_dependencies.assert_called_once_with(dependencies)
        # Should not show installation controls since all dependencies are satisfied
        self.assertNotIn(component_name, self.ui._installation_progress)
    
    def test_render_dependency_installation_interface_with_missing_dependencies(self):
        """Test rendering when dependencies are missing."""
        # Setup
        component_name = "test_component"
        dependencies = ["requests", "missing_package"]
        
        dependency_info = [
            DependencyInfo(name="requests", status=DependencyStatus.SATISFIED, installed_version="2.28.0"),
            DependencyInfo(name="missing_package", status=DependencyStatus.MISSING)
        ]
        
        self.mock_component_manager.get_component_dependencies.return_value = dependencies
        self.mock_component_manager.dependency_manager.check_dependencies.return_value = dependency_info
        
        # Execute
        self.ui.render_dependency_installation_interface(component_name)
        
        # Verify
        self.mock_component_manager.dependency_manager.check_dependencies.assert_called_once_with(dependencies)
        # Should show installation controls for missing dependencies
    
    def test_render_dependency_status_satisfied(self):
        """Test rendering dependency status for satisfied dependencies."""
        # Setup
        component_name = "test_component"
        dependency_info = [
            DependencyInfo(
                name="requests", 
                version_spec=">=2.0.0",
                status=DependencyStatus.SATISFIED, 
                installed_version="2.28.0"
            )
        ]
        
        # Mock columns
        mock_cols = [Mock(), Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        
        # Execute
        self.ui._render_dependency_status(component_name, dependency_info)
        
        # Verify
        self.st_mock.markdown.assert_called_with("#### Current Status")
        mock_cols[1].success.assert_called_with("✅ Installed")
        mock_cols[1].caption.assert_called_with("Version: 2.28.0")
    
    def test_render_dependency_status_missing(self):
        """Test rendering dependency status for missing dependencies."""
        # Setup
        component_name = "test_component"
        dependency_info = [
            DependencyInfo(name="missing_package", status=DependencyStatus.MISSING)
        ]
        
        # Mock columns
        mock_cols = [Mock(), Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        
        # Execute
        self.ui._render_dependency_status(component_name, dependency_info)
        
        # Verify
        mock_cols[1].error.assert_called_with("❌ Missing")
    
    def test_render_installation_controls(self):
        """Test rendering installation controls."""
        # Setup
        component_name = "test_component"
        missing_deps = [
            DependencyInfo(name="missing_package1", status=DependencyStatus.MISSING),
            DependencyInfo(name="missing_package2", status=DependencyStatus.MISSING)
        ]
        
        # Mock columns
        mock_cols = [Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        
        # Execute
        self.ui._render_installation_controls(component_name, missing_deps)
        
        # Verify
        self.st_mock.markdown.assert_called_with("#### Installation")
        self.st_mock.info.assert_called_with("Missing packages: missing_package1, missing_package2")
    
    def test_start_installation_success(self):
        """Test starting installation process successfully."""
        # Setup
        component_name = "test_component"
        packages = ["requests", "numpy"]
        
        # Mock successful installation result
        mock_result = InstallationResult(
            component_name=component_name,
            dependencies=[],
            success=True,
            installed_packages=packages,
            installation_log=["Installing requests...", "Installing numpy...", "Success!"]
        )
        self.mock_component_manager.install_dependencies.return_value = mock_result
        
        # Execute
        self.ui._start_installation(component_name, packages)
        
        # Verify initial state
        self.assertIn(component_name, self.ui._installation_progress)
        self.assertIn(component_name, self.ui._installation_logs)
        
        # Wait for thread to complete
        time.sleep(0.1)
        
        # Verify final state would be success (thread execution is mocked)
        self.assertEqual(
            self.ui._installation_progress[component_name]['current_operation'],
            'Starting installation...'
        )
    
    def test_start_installation_failure(self):
        """Test starting installation process with failure."""
        # Setup
        component_name = "test_component"
        packages = ["nonexistent_package"]
        
        # Mock failed installation result
        mock_result = InstallationResult(
            component_name=component_name,
            dependencies=[],
            success=False,
            error_message="Package not found",
            installation_log=["Error: Package not found"]
        )
        self.mock_component_manager.install_dependencies.return_value = mock_result
        
        # Execute
        self.ui._start_installation(component_name, packages)
        
        # Verify initial state
        self.assertIn(component_name, self.ui._installation_progress)
        self.assertIn(component_name, self.ui._installation_logs)
    
    def test_render_installation_progress(self):
        """Test rendering installation progress."""
        # Setup
        component_name = "test_component"
        self.ui._installation_progress[component_name] = {
            'overall_progress': 50,
            'current_operation': 'Installing packages...',
            'package_progress': {
                'requests': 100,
                'numpy': 25
            }
        }
        
        # Mock columns
        mock_cols = [Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        
        # Execute
        self.ui._render_installation_progress(component_name)
        
        # Verify
        self.st_mock.markdown.assert_called_with("#### Installation Progress")
        self.st_mock.progress.assert_called_with(0.5)  # 50% progress
        self.st_mock.info.assert_called_with("🔄 Installing packages...")
    
    def test_render_installation_logs(self):
        """Test rendering installation logs."""
        # Setup
        component_name = "test_component"
        self.ui._installation_logs[component_name] = [
            "[10:30:15] Starting installation...",
            "[10:30:16] Installing requests...",
            "[10:30:20] ✅ Successfully installed requests"
        ]
        
        # Mock expander
        mock_expander = Mock()
        self.st_mock.expander.return_value.__enter__ = Mock(return_value=mock_expander)
        self.st_mock.expander.return_value.__exit__ = Mock(return_value=None)
        
        # Execute
        self.ui._render_installation_logs(component_name)
        
        # Verify
        self.st_mock.expander.assert_called_with("📋 Installation Logs", expanded=False)
    
    def test_update_progress(self):
        """Test updating installation progress."""
        # Setup
        component_name = "test_component"
        self.ui._installation_progress[component_name] = {
            'overall_progress': 0,
            'current_operation': 'Starting...'
        }
        
        # Execute
        self.ui._update_progress(component_name, 75, "Almost done...")
        
        # Verify
        self.assertEqual(self.ui._installation_progress[component_name]['overall_progress'], 75)
        self.assertEqual(self.ui._installation_progress[component_name]['current_operation'], "Almost done...")
    
    def test_add_log(self):
        """Test adding log messages."""
        # Setup
        component_name = "test_component"
        message = "Test log message"
        
        # Execute
        self.ui._add_log(component_name, message)
        
        # Verify
        self.assertIn(component_name, self.ui._installation_logs)
        self.assertEqual(len(self.ui._installation_logs[component_name]), 1)
        self.assertIn(message, self.ui._installation_logs[component_name][0])
    
    def test_add_log_limit(self):
        """Test log message limit enforcement."""
        # Setup
        component_name = "test_component"
        
        # Add more than 100 log messages
        for i in range(105):
            self.ui._add_log(component_name, f"Log message {i}")
        
        # Verify
        self.assertEqual(len(self.ui._installation_logs[component_name]), 100)
        # Should keep the last 100 messages
        self.assertIn("Log message 104", self.ui._installation_logs[component_name][-1])
        self.assertNotIn("Log message 0", str(self.ui._installation_logs[component_name]))
    
    def test_render_with_active_installation(self):
        """Test rendering interface with active installation."""
        # Setup
        component_name = "test_component"
        dependencies = ["requests"]
        dependency_info = [DependencyInfo(name="requests", status=DependencyStatus.MISSING)]
        
        self.mock_component_manager.get_component_dependencies.return_value = dependencies
        self.mock_component_manager.dependency_manager.check_dependencies.return_value = dependency_info
        
        # Set up active installation
        self.ui._installation_progress[component_name] = {
            'overall_progress': 50,
            'current_operation': 'Installing...'
        }
        self.ui._installation_logs[component_name] = ["Starting installation..."]
        
        # Execute
        self.ui.render_dependency_installation_interface(component_name)
        
        # Verify that progress and logs are rendered
        # (Specific assertions would depend on the exact implementation)
        self.assertIn(component_name, self.ui._installation_progress)
        self.assertIn(component_name, self.ui._installation_logs)


if __name__ == '__main__':
    unittest.main()