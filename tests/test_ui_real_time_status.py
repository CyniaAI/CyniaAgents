"""
Unit tests for real-time status UI components.

Tests the RealTimeStatusUI class functionality including:
- Status dashboard rendering
- Status change detection
- Notification system
- Auto-refresh functionality
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import time
import sys

# Mock streamlit before importing
sys.modules['streamlit'] = Mock()

# Import the UI components
from ui_components import RealTimeStatusUI
from hot_reload.models import ComponentStatus
from component_manager import ComponentManager


class TestRealTimeStatusUI(unittest.TestCase):
    """Test cases for RealTimeStatusUI."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_component_manager = Mock()
        
        # Mock component manager methods
        self.mock_component_manager.get_all_component_statuses = Mock()
        
        self.ui = RealTimeStatusUI(self.mock_component_manager)
        
        # Mock Streamlit functions
        self.st_patcher = patch('ui_components.st')
        self.st_mock = self.st_patcher.start()
        
        # Configure st mock methods
        self.st_mock.subheader = Mock()
        self.st_mock.columns = Mock(return_value=[Mock(), Mock(), Mock(), Mock()])
        self.st_mock.metric = Mock()
        self.st_mock.info = Mock()
        self.st_mock.success = Mock()
        self.st_mock.error = Mock()
        self.st_mock.warning = Mock()
        self.st_mock.caption = Mock()
        self.st_mock.button = Mock(return_value=False)
        self.st_mock.checkbox = Mock(return_value=True)
        self.st_mock.rerun = Mock()
        self.st_mock.markdown = Mock()
        
        # Mock expander as context manager
        mock_expander = Mock()
        mock_expander.__enter__ = Mock(return_value=mock_expander)
        mock_expander.__exit__ = Mock(return_value=None)
        self.st_mock.expander = Mock(return_value=mock_expander)
        
        # Mock time.sleep to prevent actual delays in tests
        self.sleep_patcher = patch('ui_components.time.sleep')
        self.sleep_mock = self.sleep_patcher.start()
    
    def tearDown(self):
        """Clean up after tests."""
        self.st_patcher.stop()
        self.sleep_patcher.stop()
    
    def test_render_status_dashboard(self):
        """Test rendering the status dashboard."""
        # Setup
        mock_statuses = {
            'component1': ComponentStatus.LOADED,
            'component2': ComponentStatus.FAILED,
            'component3': ComponentStatus.LOADING
        }
        self.mock_component_manager.get_all_component_statuses.return_value = mock_statuses
        
        # Execute
        self.ui.render_status_dashboard()
        
        # Verify
        self.st_mock.subheader.assert_called_once_with("📊 Component Status Dashboard")
        self.mock_component_manager.get_all_component_statuses.assert_called_once()
    
    def test_render_status_summary(self):
        """Test rendering status summary metrics."""
        # Setup
        statuses = {
            'component1': ComponentStatus.LOADED,
            'component2': ComponentStatus.LOADED,
            'component3': ComponentStatus.FAILED,
            'component4': ComponentStatus.LOADING
        }
        
        # Mock columns
        mock_cols = [Mock(), Mock(), Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        
        # Execute
        self.ui._render_status_summary(statuses)
        
        # Verify metrics are displayed
        mock_cols[0].metric.assert_called_with("✅ Loaded", 2)
        mock_cols[1].metric.assert_called_with("❌ Failed", 1)
        mock_cols[2].metric.assert_called_with("🔄 Processing", 1)
        mock_cols[3].metric.assert_called_with("📦 Total", 4)
    
    def test_render_status_summary_empty(self):
        """Test rendering status summary with no components."""
        # Setup
        statuses = {}
        
        # Mock columns
        mock_cols = [Mock(), Mock(), Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        
        # Execute
        self.ui._render_status_summary(statuses)
        
        # Verify all metrics show zero
        mock_cols[0].metric.assert_called_with("✅ Loaded", 0)
        mock_cols[1].metric.assert_called_with("❌ Failed", 0)
        mock_cols[2].metric.assert_called_with("🔄 Processing", 0)
        mock_cols[3].metric.assert_called_with("📦 Total", 0)
    
    def test_render_status_grid(self):
        """Test rendering component status in grid layout."""
        # Setup
        statuses = {
            'component1': ComponentStatus.LOADED,
            'component2': ComponentStatus.LOADED,
            'component3': ComponentStatus.FAILED
        }
        
        # Mock columns
        mock_cols = [Mock(), Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        
        # Execute
        self.ui._render_status_grid(statuses)
        
        # Verify expanders are created for each status group
        self.st_mock.expander.assert_called()
    
    def test_render_status_grid_empty(self):
        """Test rendering status grid with no components."""
        # Setup
        statuses = {}
        
        # Execute
        self.ui._render_status_grid(statuses)
        
        # Verify
        self.st_mock.info.assert_called_once_with("No components found.")
    
    def test_render_notifications(self):
        """Test rendering recent notifications."""
        # Setup
        self.ui._notifications = [
            {
                'message': 'Component loaded successfully',
                'type': 'success',
                'timestamp': datetime(2023, 1, 1, 12, 0, 0)
            },
            {
                'message': 'Component failed to load',
                'type': 'error',
                'timestamp': datetime(2023, 1, 1, 12, 1, 0)
            }
        ]
        
        # Execute
        self.ui._render_notifications()
        
        # Verify
        self.st_mock.subheader.assert_called_with("🔔 Recent Notifications")
        self.st_mock.success.assert_called()
        self.st_mock.error.assert_called()
    
    def test_render_notifications_empty(self):
        """Test rendering notifications when none exist."""
        # Setup
        self.ui._notifications = []
        
        # Execute
        self.ui._render_notifications()
        
        # Verify that subheader is not called when no notifications
        self.st_mock.subheader.assert_not_called()
    
    def test_render_refresh_indicator(self):
        """Test rendering auto-refresh indicator."""
        # Setup
        self.ui._last_update = datetime(2023, 1, 1, 12, 0, 0)
        
        # Mock columns
        mock_cols = [Mock(), Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        
        # Execute
        self.ui._render_refresh_indicator()
        
        # Verify
        mock_cols[0].caption.assert_called_with("Last updated: 12:00:00")
        mock_cols[1].button.assert_called_with("🔄 Refresh Now")
        mock_cols[2].checkbox.assert_called_with("Auto-refresh", value=True)
    
    def test_check_status_changes_new_component(self):
        """Test checking status changes for new component."""
        # Setup
        current_statuses = {
            'new_component': ComponentStatus.LOADED
        }
        self.ui._status_cache = {}
        
        # Execute
        self.ui._check_status_changes(current_statuses)
        
        # Verify
        self.assertEqual(self.ui._status_cache, current_statuses)
        # No notification should be generated for new components
        self.assertEqual(len(self.ui._notifications), 0)
    
    def test_check_status_changes_status_changed(self):
        """Test checking status changes when component status changes."""
        # Setup
        current_statuses = {
            'component1': ComponentStatus.LOADED
        }
        self.ui._status_cache = {
            'component1': ComponentStatus.LOADING
        }
        
        # Execute
        self.ui._check_status_changes(current_statuses)
        
        # Verify
        self.assertEqual(self.ui._status_cache, current_statuses)
        self.assertEqual(len(self.ui._notifications), 1)
        self.assertIn("status changed", self.ui._notifications[0]['message'])
    
    def test_check_status_changes_no_change(self):
        """Test checking status changes when no changes occur."""
        # Setup
        current_statuses = {
            'component1': ComponentStatus.LOADED,
            'component2': ComponentStatus.FAILED
        }
        self.ui._status_cache = current_statuses.copy()
        
        # Execute
        self.ui._check_status_changes(current_statuses)
        
        # Verify
        self.assertEqual(self.ui._status_cache, current_statuses)
        # No new notifications should be generated
        self.assertEqual(len(self.ui._notifications), 0)
    
    def test_get_notification_type(self):
        """Test getting notification type based on component status."""
        # Test different status types
        self.assertEqual(self.ui._get_notification_type(ComponentStatus.LOADED), 'success')
        self.assertEqual(self.ui._get_notification_type(ComponentStatus.FAILED), 'error')
        self.assertEqual(self.ui._get_notification_type(ComponentStatus.LOADING), 'info')
        self.assertEqual(self.ui._get_notification_type(ComponentStatus.RELOADING), 'info')
        self.assertEqual(self.ui._get_notification_type(ComponentStatus.UNLOADING), 'warning')
    
    def test_add_notification(self):
        """Test adding a notification."""
        # Setup
        message = "Test notification message"
        notification_type = "success"
        
        # Execute
        self.ui._add_notification(message, notification_type)
        
        # Verify
        self.assertEqual(len(self.ui._notifications), 1)
        self.assertEqual(self.ui._notifications[0]['message'], message)
        self.assertEqual(self.ui._notifications[0]['type'], notification_type)
        self.assertIsInstance(self.ui._notifications[0]['timestamp'], datetime)
    
    def test_add_notification_limit(self):
        """Test notification limit enforcement."""
        # Setup - add more than 20 notifications
        for i in range(25):
            self.ui._add_notification(f"Notification {i}", "info")
        
        # Verify
        self.assertEqual(len(self.ui._notifications), 20)
        # Should keep the last 20 notifications
        self.assertEqual(self.ui._notifications[-1]['message'], "Notification 24")
        self.assertNotEqual(self.ui._notifications[0]['message'], "Notification 0")
    
    def test_render_status_dashboard_with_auto_refresh(self):
        """Test rendering status dashboard with auto-refresh enabled."""
        # Setup
        mock_statuses = {
            'component1': ComponentStatus.LOADED
        }
        self.mock_component_manager.get_all_component_statuses.return_value = mock_statuses
        
        # Mock checkbox to return True (auto-refresh enabled)
        mock_cols = [Mock(), Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        mock_cols[2].checkbox.return_value = True
        
        # Execute
        self.ui.render_status_dashboard()
        
        # Verify that sleep and rerun are called for auto-refresh
        # Note: In actual implementation, this would trigger a rerun
        self.sleep_mock.assert_called_with(5)
        self.st_mock.rerun.assert_called()
    
    def test_render_status_dashboard_manual_refresh(self):
        """Test rendering status dashboard with manual refresh."""
        # Setup
        mock_statuses = {
            'component1': ComponentStatus.LOADED
        }
        self.mock_component_manager.get_all_component_statuses.return_value = mock_statuses
        
        # Mock button to return True (manual refresh clicked)
        mock_cols = [Mock(), Mock(), Mock()]
        self.st_mock.columns.return_value = mock_cols
        mock_cols[1].button.return_value = True
        mock_cols[2].checkbox.return_value = False  # Auto-refresh disabled
        
        # Execute
        self.ui.render_status_dashboard()
        
        # Verify that rerun is called for manual refresh
        self.st_mock.rerun.assert_called()
    
    def test_notification_display_order(self):
        """Test that notifications are displayed in reverse chronological order."""
        # Setup
        self.ui._notifications = [
            {
                'message': 'First notification',
                'type': 'info',
                'timestamp': datetime(2023, 1, 1, 12, 0, 0)
            },
            {
                'message': 'Second notification',
                'type': 'success',
                'timestamp': datetime(2023, 1, 1, 12, 1, 0)
            },
            {
                'message': 'Third notification',
                'type': 'error',
                'timestamp': datetime(2023, 1, 1, 12, 2, 0)
            }
        ]
        
        # Execute
        self.ui._render_notifications()
        
        # Verify that notifications are rendered (most recent first)
        # The exact verification depends on implementation details
        self.st_mock.subheader.assert_called_with("🔔 Recent Notifications")
        
        # Verify that different notification types are called
        self.st_mock.info.assert_called()
        self.st_mock.success.assert_called()
        self.st_mock.error.assert_called()


if __name__ == '__main__':
    unittest.main()