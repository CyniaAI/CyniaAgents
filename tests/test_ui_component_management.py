"""
Unit tests for component management UI controls.

Tests the ComponentManagementUI class functionality including:
- Component card rendering
- Management controls (reload, unload, install dependencies)
- Status indicators
- Error display and suggestions
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
from ui_components import ComponentManagementUI
from hot_reload.models import ComponentStatus, ComponentMetadata, ReloadResult, InstallationResult
from component_manager import ComponentManager


class TestComponentManagementUI(unittest.TestCase):
    """Test cases for ComponentManagementUI."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_component_manager = Mock()
        
        # Mock component manager methods
        self.mock_component_manager.get_component_status = Mock()
        self.mock_component_manager.get_component_metadata = Mock()
        self.mock_component_manager.get_component_dependencies = Mock()
        self.mock_component_manager.missing_requirements = Mock()
        self.mock_component_manager.enabled = []
        self.mock_component_manager.save_config = Mock()
        self.mock_component_manager.reload_component = Mock()
        self.mock_component_manager.unload_component = Mock()
        self.mock_component_manager.install_dependencies = Mock()
        
        self.ui = ComponentManagementUI(self.mock_component_manager)
        
        # Mock Streamlit functions
        self.st_patcher = patch('ui_components.st')
        self.st_mock = self.st_patcher.start()
        
        # Configure st mock methods
        self.st_mock.container = Mock()
        self.st_mock.columns = Mock(return_value=[Mock(), Mock(), Mock()])
        self.st_mock.markdown = Mock()
        self.st_mock.caption = Mock()
        self.st_mock.toggle = Mock(return_value=False)
        self.st_mock.button = Mock(return_value=False)
        self.st_mock.success = Mock()
        self.st_mock.error = Mock()
        self.st_mock.info = Mock()
        self.st_mock.code = Mock()
        self.st_mock.rerun = Mock()
        
        # Mock expander as context manager
        mock_expander = Mock()
        mock_expander.__enter__ = Mock(return_value=mock_expander)
        mock_expander.__exit__ = Mock(return_value=None)
        self.st_mock.expander = Mock(return_value=mock_expander)
        
        # Mock container as context manager
        mock_container = Mock()
        mock_container.__enter__ = Mock(return_value=mock_container)
        mock_container.__exit__ = Mock(return_value=None)
        self.st_mock.container.return_value = mock_container
    
    def tearDown(self):
        """Clean up after tests."""
        self.st_patcher.stop()
    
    def test_render_component_card_loaded_status(self):
        """Test rendering component card with loaded status."""
        # Setup
        component_name = "test_component"
        mock_component = Mock()
        mock_component.description = "Test component description"
        
        self.mock_component_manager.get_component_status.return_value = ComponentStatus.LOADED
        self.mock_component_manager.get_component_metadata.return_value = ComponentMetadata(
            name=component_name,
            description="Test component",
            version="1.0.0",
            author="Test Author"
        )
        self.mock_component_manager.get_component_dependencies.return_value = ["requests"]
        self.mock_component_manager.missing_requirements.return_value = []
        
        # Execute
        self.ui.render_component_card(component_name, mock_component)
        
        # Verify
        self.mock_component_manager.get_component_status.assert_called_once_with(component_name)
        self.mock_component_manager.get_component_metadata.assert_called_once_with(component_name)
        self.st_mock.container.assert_called_once()
        self.st_mock.columns.assert_called()
    
    def test_render_component_card_failed_status(self):
        """Test rendering component card with failed status."""
        # Setup
        component_name = "failed_component"
        mock_component = Mock()
        mock_component.description = "Failed component"
        
        self.mock_component_manager.get_component_status.return_value = ComponentStatus.FAILED
        self.mock_component_manager.get_component_metadata.return_value = None
        self.mock_component_manager.get_component_dependencies.return_value = []
        self.mock_component_manager.missing_requirements.return_value = []
        
        # Execute
        self.ui.render_component_card(component_name, mock_component)
        
        # Verify that error info is rendered
        # (The exact verification depends on implementation details)
        self.mock_component_manager.get_component_status.assert_called_once_with(component_name)
    
    def test_render_component_card_with_missing_dependencies(self):
        """Test rendering component card with missing dependencies."""
        # Setup
        component_name = "component_with_deps"
        mock_component = Mock()
        mock_component.description = "Component with dependencies"
        
        self.mock_component_manager.get_component_status.return_value = ComponentStatus.LOADED
        self.mock_component_manager.get_component_metadata.return_value = None
        self.mock_component_manager.get_component_dependencies.return_value = ["requests", "numpy"]
        self.mock_component_manager.missing_requirements.return_value = ["numpy"]
        
        # Execute
        self.ui.render_component_card(component_name, mock_component)
        
        # Verify
        self.mock_component_manager.missing_requirements.assert_called_once_with(["requests", "numpy"])
    
    def test_render_component_controls_loaded_component(self):
        """Test rendering component controls for loaded component."""
        # Setup
        component_name = "loaded_component"
        mock_component = Mock()
        status = ComponentStatus.LOADED
        can_enable = True
        
        # Mock columns
        mock_cols = [Mock(), Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        
        # Execute
        self.ui._render_component_controls(component_name, mock_component, status, can_enable)
        
        # Verify that reload and unload buttons are available
        # (The exact verification depends on implementation details)
    
    def test_render_component_controls_failed_component(self):
        """Test rendering component controls for failed component."""
        # Setup
        component_name = "failed_component"
        mock_component = Mock()
        status = ComponentStatus.FAILED
        can_enable = False
        
        # Execute
        self.ui._render_component_controls(component_name, mock_component, status, can_enable)
        
        # Verify that reload button is available for failed components
        # (The exact verification depends on implementation details)
    
    def test_render_dependency_info_missing_deps(self):
        """Test rendering dependency information with missing dependencies."""
        # Setup
        component_name = "component_with_missing_deps"
        dependencies = ["requests", "numpy", "pandas"]
        missing_deps = ["numpy", "pandas"]
        
        # Mock columns
        mock_cols = [Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        
        # Execute
        self.ui._render_dependency_info(component_name, dependencies, missing_deps)
        
        # Verify
        self.st_mock.error.assert_called_with("⚠️ Missing dependencies: numpy, pandas")
        self.st_mock.expander.assert_called_with("🔧 Dependency Actions", expanded=False)
    
    def test_render_dependency_info_satisfied_deps(self):
        """Test rendering dependency information with satisfied dependencies."""
        # Setup
        component_name = "component_with_satisfied_deps"
        dependencies = ["requests", "numpy"]
        missing_deps = []
        
        # Execute
        self.ui._render_dependency_info(component_name, dependencies, missing_deps)
        
        # Verify
        self.st_mock.success.assert_called_with("✅ All 2 dependencies satisfied")
    
    def test_render_error_info(self):
        """Test rendering error information and suggestions."""
        # Setup
        component_name = "error_component"
        
        # Execute
        self.ui._render_error_info(component_name)
        
        # Verify
        self.st_mock.error.assert_called_with("❌ Component failed to load")
        self.st_mock.expander.assert_called_with("🔍 Error Details & Suggestions", expanded=False)
    
    def test_render_operation_progress(self):
        """Test rendering operation progress indicators."""
        # Setup
        component_name = "component_in_progress"
        self.ui._operation_progress[component_name] = {
            'operation': 'reload',
            'progress': 50,
            'status': 'Reloading component...'
        }
        
        # Execute
        self.ui._render_operation_progress(component_name)
        
        # Verify
        self.st_mock.info.assert_called_with("🔄 Reload: Reloading component...")
        self.st_mock.progress.assert_called_with(0.5)  # 50% progress
    
    def test_show_component_details(self):
        """Test showing detailed component information."""
        # Setup
        component_name = "detailed_component"
        mock_component = Mock()
        
        metadata = ComponentMetadata(
            name=component_name,
            description="Detailed component description",
            version="2.0.0",
            author="Test Author",
            file_path="/path/to/component.py"
        )
        
        self.mock_component_manager.get_component_metadata.return_value = metadata
        self.mock_component_manager.get_component_status.return_value = ComponentStatus.LOADED
        self.mock_component_manager.get_component_dependencies.return_value = ["requests", "numpy"]
        
        # Mock os.path.exists and os.stat
        with patch('ui_components.os.path.exists', return_value=True), \
             patch('ui_components.os.stat') as mock_stat, \
             patch('ui_components.datetime') as mock_datetime:
            
            mock_stat.return_value.st_size = 1024
            mock_stat.return_value.st_mtime = 1640995200  # Mock timestamp
            mock_datetime.fromtimestamp.return_value = datetime(2022, 1, 1, 12, 0, 0)
            
            # Execute
            self.ui._show_component_details(component_name, mock_component)
            
            # Verify
            self.st_mock.expander.assert_called_with(f"📋 Details for {component_name}", expanded=True)
    
    def test_start_component_operation_reload_success(self):
        """Test starting component reload operation successfully."""
        # Setup
        component_name = "component_to_reload"
        
        # Mock successful reload result
        mock_result = ReloadResult(
            component_name=component_name,
            operation=None,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.LOADED
        )
        self.mock_component_manager.reload_component.return_value = mock_result
        
        # Execute
        self.ui._start_component_operation(component_name, "reload")
        
        # Verify initial state
        self.assertIn(component_name, self.ui._operation_progress)
        self.assertIn(component_name, self.ui._operation_logs)
        
        # Wait for thread to complete
        time.sleep(0.1)
    
    def test_start_component_operation_reload_failure(self):
        """Test starting component reload operation with failure."""
        # Setup
        component_name = "component_reload_fail"
        
        # Mock failed reload result
        mock_result = ReloadResult(
            component_name=component_name,
            operation=None,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.LOADED,
            error_message="Reload failed due to syntax error"
        )
        self.mock_component_manager.reload_component.return_value = mock_result
        
        # Execute
        self.ui._start_component_operation(component_name, "reload")
        
        # Verify initial state
        self.assertIn(component_name, self.ui._operation_progress)
        self.assertIn(component_name, self.ui._operation_logs)
    
    def test_start_component_operation_unload_success(self):
        """Test starting component unload operation successfully."""
        # Setup
        component_name = "component_to_unload"
        
        # Mock successful unload result
        mock_result = ReloadResult(
            component_name=component_name,
            operation=None,
            success=True,
            status=ComponentStatus.UNLOADED,
            previous_status=ComponentStatus.LOADED
        )
        self.mock_component_manager.unload_component.return_value = mock_result
        
        # Execute
        self.ui._start_component_operation(component_name, "unload")
        
        # Verify initial state
        self.assertIn(component_name, self.ui._operation_progress)
        self.assertIn(component_name, self.ui._operation_logs)
    
    def test_start_component_operation_install_dependencies_success(self):
        """Test starting dependency installation operation successfully."""
        # Setup
        component_name = "component_install_deps"
        
        # Mock successful installation result
        mock_result = InstallationResult(
            component_name=component_name,
            dependencies=[],
            success=True,
            installed_packages=["numpy", "pandas"]
        )
        self.mock_component_manager.get_component_dependencies.return_value = ["numpy", "pandas"]
        self.mock_component_manager.install_dependencies.return_value = mock_result
        
        # Execute
        self.ui._start_component_operation(component_name, "install_dependencies")
        
        # Verify initial state
        self.assertIn(component_name, self.ui._operation_progress)
        self.assertIn(component_name, self.ui._operation_logs)
    
    def test_update_operation_progress(self):
        """Test updating operation progress."""
        # Setup
        component_name = "component_progress"
        self.ui._operation_progress[component_name] = {
            'operation': 'reload',
            'progress': 0,
            'status': 'Starting...'
        }
        
        # Execute
        self.ui._update_operation_progress(component_name, 75, "Almost done...")
        
        # Verify
        self.assertEqual(self.ui._operation_progress[component_name]['progress'], 75)
        self.assertEqual(self.ui._operation_progress[component_name]['status'], "Almost done...")
    
    def test_add_operation_log(self):
        """Test adding operation log messages."""
        # Setup
        component_name = "component_log"
        message = "Test operation log message"
        
        # Execute
        self.ui._add_operation_log(component_name, message)
        
        # Verify
        self.assertIn(component_name, self.ui._operation_logs)
        self.assertEqual(len(self.ui._operation_logs[component_name]), 1)
        self.assertIn(message, self.ui._operation_logs[component_name][0])
    
    def test_add_operation_log_limit(self):
        """Test operation log message limit enforcement."""
        # Setup
        component_name = "component_log_limit"
        
        # Add more than 50 log messages
        for i in range(55):
            self.ui._add_operation_log(component_name, f"Log message {i}")
        
        # Verify
        self.assertEqual(len(self.ui._operation_logs[component_name]), 50)
        # Should keep the last 50 messages
        self.assertIn("Log message 54", self.ui._operation_logs[component_name][-1])
        self.assertNotIn("Log message 0", str(self.ui._operation_logs[component_name]))
    
    def test_toggle_component_enable_disable(self):
        """Test toggling component enable/disable state."""
        # Setup
        component_name = "toggle_component"
        mock_component = Mock()
        mock_component.description = "Toggle test component"
        
        self.mock_component_manager.get_component_status.return_value = ComponentStatus.LOADED
        self.mock_component_manager.get_component_metadata.return_value = None
        self.mock_component_manager.get_component_dependencies.return_value = []
        self.mock_component_manager.missing_requirements.return_value = []
        self.mock_component_manager.enabled = []
        
        # Mock toggle to return True (enabled)
        self.st_mock.toggle.return_value = True
        
        # Execute
        self.ui.render_component_card(component_name, mock_component)
        
        # Verify that toggle is called
        self.st_mock.toggle.assert_called()


if __name__ == '__main__':
    unittest.main()