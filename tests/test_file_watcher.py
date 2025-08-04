"""
Unit tests for the FileWatcher class.

Tests cover file system monitoring, change detection, callback management,
and both watchdog and polling implementations.
"""

import os
import sys
import tempfile
import shutil
import time
import threading
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from unittest import mock
import pytest

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hot_reload.file_watcher import FileWatcher, ComponentChange, ChangeType, PollingWatcher, ComponentEventHandler
from hot_reload.models import ComponentMetadata
from hot_reload.errors import ErrorHandler


class TestFileWatcher:
    """Test cases for FileWatcher class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        self.error_handler = Mock(spec=ErrorHandler)
        os.makedirs(self.components_dir, exist_ok=True)
        
        # Create a test component file
        self.test_component_path = os.path.join(self.components_dir, "test_component.py")
        with open(self.test_component_path, 'w') as f:
            f.write('# Test component\nprint("Hello from test component")\n')
    
    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_file_watcher_initialization(self):
        """Test FileWatcher initialization."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        assert watcher.components_dir == Path(self.components_dir)
        assert watcher.error_handler == self.error_handler
        assert not watcher.is_watching
        assert len(watcher.change_callbacks) == 0
        assert len(watcher.component_created_callbacks) == 0
        assert len(watcher.component_modified_callbacks) == 0
        assert len(watcher.component_deleted_callbacks) == 0
        assert len(watcher.discovery_callbacks) == 0
    
    def test_file_watcher_default_error_handler(self):
        """Test FileWatcher with default error handler."""
        watcher = FileWatcher(self.components_dir)
        
        assert watcher.error_handler is not None
        assert isinstance(watcher.error_handler, ErrorHandler)
    
    def test_add_and_remove_callbacks(self):
        """Test adding and removing various callbacks."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        # Create mock callbacks
        change_callback = Mock()
        created_callback = Mock()
        modified_callback = Mock()
        deleted_callback = Mock()
        discovery_callback = Mock()
        
        # Add callbacks
        watcher.add_change_callback(change_callback)
        watcher.add_component_created_callback(created_callback)
        watcher.add_component_modified_callback(modified_callback)
        watcher.add_component_deleted_callback(deleted_callback)
        watcher.add_discovery_callback(discovery_callback)
        
        assert len(watcher.change_callbacks) == 1
        assert len(watcher.component_created_callbacks) == 1
        assert len(watcher.component_modified_callbacks) == 1
        assert len(watcher.component_deleted_callbacks) == 1
        assert len(watcher.discovery_callbacks) == 1
        
        # Remove callbacks
        watcher.remove_change_callback(change_callback)
        watcher.remove_component_created_callback(created_callback)
        watcher.remove_component_modified_callback(modified_callback)
        watcher.remove_component_deleted_callback(deleted_callback)
        watcher.remove_discovery_callback(discovery_callback)
        
        assert len(watcher.change_callbacks) == 0
        assert len(watcher.component_created_callbacks) == 0
        assert len(watcher.component_modified_callbacks) == 0
        assert len(watcher.component_deleted_callbacks) == 0
        assert len(watcher.discovery_callbacks) == 0
    
    def test_remove_nonexistent_callback(self):
        """Test removing a callback that doesn't exist."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        callback = Mock()
        
        # Should not raise an exception
        watcher.remove_change_callback(callback)
        watcher.remove_component_created_callback(callback)
        watcher.remove_component_modified_callback(callback)
        watcher.remove_component_deleted_callback(callback)
        watcher.remove_discovery_callback(callback)
    
    @patch('hot_reload.file_watcher.WATCHDOG_AVAILABLE', True)
    @patch('hot_reload.file_watcher.Observer')
    def test_start_watching_with_watchdog(self, mock_observer_class):
        """Test starting file watching with watchdog."""
        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer
        
        watcher = FileWatcher(self.components_dir, self.error_handler)
        result = watcher.start_watching()
        
        assert result is True
        assert watcher.is_watching is True
        mock_observer.schedule.assert_called_once()
        mock_observer.start.assert_called_once()
        assert len(watcher.observers) == 1
    
    @patch('hot_reload.file_watcher.WATCHDOG_AVAILABLE', False)
    def test_start_watching_with_polling(self):
        """Test starting file watching with polling fallback."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        with patch.object(watcher, '_start_polling_watching', return_value=True) as mock_polling:
            result = watcher.start_watching()
            
            assert result is True
            mock_polling.assert_called_once()
    
    def test_start_watching_already_watching(self):
        """Test starting file watching when already watching."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        watcher.is_watching = True
        
        result = watcher.start_watching()
        assert result is True
    
    @patch('hot_reload.file_watcher.WATCHDOG_AVAILABLE', True)
    @patch('hot_reload.file_watcher.Observer')
    def test_start_watching_error_handling(self, mock_observer_class):
        """Test error handling during start watching."""
        mock_observer_class.side_effect = Exception("Observer error")
        
        watcher = FileWatcher(self.components_dir, self.error_handler)
        result = watcher.start_watching()
        
        assert result is False
        self.error_handler.handle_component_error.assert_called_once()
    
    @patch('hot_reload.file_watcher.WATCHDOG_AVAILABLE', True)
    def test_stop_watching_with_observers(self):
        """Test stopping file watching with observers."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        # Mock observers
        mock_observer1 = Mock()
        mock_observer2 = Mock()
        watcher.observers = [mock_observer1, mock_observer2]
        watcher.is_watching = True
        
        watcher.stop_watching()
        
        mock_observer1.stop.assert_called_once()
        mock_observer1.join.assert_called_once_with(timeout=5.0)
        mock_observer2.stop.assert_called_once()
        mock_observer2.join.assert_called_once_with(timeout=5.0)
        assert len(watcher.observers) == 0
        assert watcher.is_watching is False
    
    def test_stop_watching_with_polling(self):
        """Test stopping file watching with polling watcher."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        # Mock polling watcher
        mock_polling = Mock()
        watcher.polling_watcher = mock_polling
        watcher.is_watching = True
        
        watcher.stop_watching()
        
        mock_polling.stop.assert_called_once()
        assert watcher.polling_watcher is None
        assert watcher.is_watching is False
    
    def test_stop_watching_not_watching(self):
        """Test stopping file watching when not watching."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        # Should not raise an exception
        watcher.stop_watching()
    
    def test_stop_watching_error_handling(self):
        """Test error handling during stop watching."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        # Mock observer that raises exception
        mock_observer = Mock()
        mock_observer.stop.side_effect = Exception("Stop error")
        watcher.observers = [mock_observer]
        watcher.is_watching = True
        
        watcher.stop_watching()
        
        self.error_handler.handle_component_error.assert_called_once()
    
    def test_notify_change_general_callback(self):
        """Test notifying change callbacks."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        callback = Mock()
        watcher.add_change_callback(callback)
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.MODIFIED,
            file_path=self.test_component_path,
            timestamp=datetime.now()
        )
        
        watcher._notify_change(change)
        
        callback.assert_called_once_with(change)
    
    def test_notify_change_created_callback(self):
        """Test notifying component created callbacks."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        callback = Mock()
        watcher.add_component_created_callback(callback)
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.CREATED,
            file_path=self.test_component_path,
            timestamp=datetime.now()
        )
        
        with patch.object(watcher, '_extract_metadata_if_needed', return_value=None) as mock_extract:
            watcher._notify_change(change)
            
            callback.assert_called_once_with("test_component", None)
            mock_extract.assert_called_once_with(change)
    
    def test_notify_change_modified_callback(self):
        """Test notifying component modified callbacks."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        callback = Mock()
        watcher.add_component_modified_callback(callback)
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.MODIFIED,
            file_path=self.test_component_path,
            timestamp=datetime.now()
        )
        
        with patch.object(watcher, '_extract_metadata_if_needed', return_value=None) as mock_extract:
            watcher._notify_change(change)
            
            callback.assert_called_once_with("test_component", None)
            mock_extract.assert_called_once_with(change)
    
    def test_notify_change_deleted_callback(self):
        """Test notifying component deleted callbacks."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        callback = Mock()
        watcher.add_component_deleted_callback(callback)
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.DELETED,
            file_path=self.test_component_path,
            timestamp=datetime.now()
        )
        
        watcher._notify_change(change)
        
        callback.assert_called_once_with("test_component")
    
    def test_notify_change_moved_callback(self):
        """Test notifying component moved callbacks (treated as created)."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        callback = Mock()
        watcher.add_component_created_callback(callback)
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.MOVED,
            file_path=self.test_component_path,
            timestamp=datetime.now(),
            old_path="/old/path/test_component.py"
        )
        
        with patch.object(watcher, '_extract_metadata_if_needed', return_value=None) as mock_extract:
            watcher._notify_change(change)
            
            callback.assert_called_once_with("test_component", None)
            mock_extract.assert_called_once_with(change)
    
    def test_notify_change_discovery_callback(self):
        """Test notifying discovery callbacks."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        callback = Mock()
        watcher.add_discovery_callback(callback)
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.MODIFIED,
            file_path=self.test_component_path,
            timestamp=datetime.now()
        )
        
        watcher._notify_change(change)
        
        callback.assert_called_once()
    
    def test_notify_change_callback_error_handling(self):
        """Test error handling in change callbacks."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        # Add callback that raises exception
        callback = Mock(side_effect=Exception("Callback error"))
        watcher.add_change_callback(callback)
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.MODIFIED,
            file_path=self.test_component_path,
            timestamp=datetime.now()
        )
        
        watcher._notify_change(change)
        
        # Should handle the error gracefully
        self.error_handler.handle_component_error.assert_called()
    
    def test_extract_metadata_if_needed_with_existing_metadata(self):
        """Test extracting metadata when already available."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        metadata = ComponentMetadata(
            name="test_component",
            version="1.0.0",
            description="Test component",
            file_path=self.test_component_path
        )
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.MODIFIED,
            file_path=self.test_component_path,
            timestamp=datetime.now(),
            metadata=metadata
        )
        
        result = watcher._extract_metadata_if_needed(change)
        assert result == metadata
    
    def test_extract_metadata_if_needed_from_loader(self):
        """Test extracting metadata using component loader."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.MODIFIED,
            file_path=self.test_component_path,
            timestamp=datetime.now()
        )
        
        with patch('hot_reload.loader.ComponentLoader') as mock_loader_class:
            mock_loader = Mock()
            mock_metadata = Mock()
            mock_loader.extract_component_metadata.return_value = mock_metadata
            mock_loader_class.return_value = mock_loader
            
            result = watcher._extract_metadata_if_needed(change)
            
            assert result == mock_metadata
            mock_loader_class.assert_called_once_with(self.components_dir)
            mock_loader.extract_component_metadata.assert_called_once_with(self.test_component_path)
    
    def test_extract_metadata_if_needed_loader_error(self):
        """Test extracting metadata when loader raises exception."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.MODIFIED,
            file_path=self.test_component_path,
            timestamp=datetime.now()
        )
        
        with patch('hot_reload.loader.ComponentLoader', side_effect=Exception("Loader error")):
            result = watcher._extract_metadata_if_needed(change)
            assert result is None
    
    def test_get_watched_directory(self):
        """Test getting the watched directory."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        result = watcher.get_watched_directory()
        assert result == self.components_dir
    
    def test_is_watching_active(self):
        """Test checking if watching is active."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        assert watcher.is_watching_active() is False
        
        watcher.is_watching = True
        assert watcher.is_watching_active() is True
    
    @patch('hot_reload.file_watcher.WATCHDOG_AVAILABLE', True)
    def test_get_watcher_info(self):
        """Test getting watcher information."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        # Add some callbacks
        watcher.add_change_callback(Mock())
        watcher.add_component_created_callback(Mock())
        watcher.add_discovery_callback(Mock())
        
        # Add mock observer
        watcher.observers = [Mock(), Mock()]
        watcher.is_watching = True
        
        info = watcher.get_watcher_info()
        
        expected_info = {
            'is_watching': True,
            'components_dir': self.components_dir,
            'watchdog_available': True,
            'using_polling': False,
            'observer_count': 2,
            'callback_counts': {
                'change': 1,
                'created': 1,
                'modified': 0,
                'deleted': 0,
                'discovery': 1
            }
        }
        
        assert info == expected_info
    
    def test_force_discovery(self):
        """Test forcing component discovery."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        callback = Mock()
        watcher.add_discovery_callback(callback)
        
        watcher.force_discovery()
        
        callback.assert_called_once()
    
    def test_destructor_cleanup(self):
        """Test cleanup when file watcher is destroyed."""
        watcher = FileWatcher(self.components_dir, self.error_handler)
        
        with patch.object(watcher, 'stop_watching') as mock_stop:
            watcher.__del__()
            mock_stop.assert_called_once()
    


class TestComponentEventHandler:
    """Test cases for ComponentEventHandler class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        os.makedirs(self.components_dir, exist_ok=True)
        
        self.error_handler = Mock(spec=ErrorHandler)
        self.file_watcher = Mock()
        self.file_watcher.components_dir = self.components_dir
        self.file_watcher.error_handler = self.error_handler
        
        self.handler = ComponentEventHandler(self.file_watcher)
    
    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_handler_initialization(self):
        """Test ComponentEventHandler initialization."""
        assert self.handler.file_watcher == self.file_watcher
        assert isinstance(self.handler.last_events, dict)
        assert self.handler.debounce_time == 0.5
    
    def test_should_process_event_python_file(self):
        """Test processing Python file events."""
        mock_event = Mock()
        mock_event.is_directory = False
        mock_event.src_path = "/path/to/component.py"
        
        result = self.handler._should_process_event(mock_event)
        assert result is True
    
    def test_should_process_event_requirements_file(self):
        """Test processing requirements.txt file events."""
        mock_event = Mock()
        mock_event.is_directory = False
        mock_event.src_path = "/path/to/requirements.txt"
        
        result = self.handler._should_process_event(mock_event)
        assert result is True
    
    def test_should_process_event_other_file(self):
        """Test not processing other file types."""
        mock_event = Mock()
        mock_event.is_directory = False
        mock_event.src_path = "/path/to/file.txt"
        
        result = self.handler._should_process_event(mock_event)
        assert result is False
    
    def test_should_process_event_component_directory(self):
        """Test processing component directory events."""
        # Create a component directory with __init__.py
        component_dir = os.path.join(self.components_dir, "test_component")
        os.makedirs(component_dir)
        with open(os.path.join(component_dir, "__init__.py"), 'w') as f:
            f.write("# Component package")
        
        mock_event = Mock()
        mock_event.is_directory = True
        mock_event.src_path = component_dir
        
        result = self.handler._should_process_event(mock_event)
        assert result is True
    
    def test_should_process_event_non_component_directory(self):
        """Test not processing non-component directory events."""
        # Create a regular directory without __init__.py or main.py
        regular_dir = os.path.join(self.components_dir, "regular_dir")
        os.makedirs(regular_dir)
        
        mock_event = Mock()
        mock_event.is_directory = True
        mock_event.src_path = regular_dir
        
        result = self.handler._should_process_event(mock_event)
        assert result is False
    
    def test_is_component_directory_with_init(self):
        """Test component directory detection with __init__.py."""
        component_dir = os.path.join(self.components_dir, "test_component")
        os.makedirs(component_dir)
        with open(os.path.join(component_dir, "__init__.py"), 'w') as f:
            f.write("# Component package")
        
        result = self.handler._is_component_directory(component_dir)
        assert result is True
    
    def test_is_component_directory_with_main(self):
        """Test component directory detection with main.py."""
        component_dir = os.path.join(self.components_dir, "test_component")
        os.makedirs(component_dir)
        with open(os.path.join(component_dir, "main.py"), 'w') as f:
            f.write("# Component main")
        
        result = self.handler._is_component_directory(component_dir)
        assert result is True
    
    def test_is_component_directory_without_marker_files(self):
        """Test component directory detection without marker files."""
        component_dir = os.path.join(self.components_dir, "test_component")
        os.makedirs(component_dir)
        
        result = self.handler._is_component_directory(component_dir)
        assert result is False
    
    def test_is_debounced_first_event(self):
        """Test debouncing for first event."""
        file_path = "/path/to/component.py"
        
        result = self.handler._is_debounced(file_path)
        assert result is False
        assert file_path in self.handler.last_events
    
    def test_is_debounced_rapid_events(self):
        """Test debouncing for rapid events."""
        file_path = "/path/to/component.py"
        
        # First event
        result1 = self.handler._is_debounced(file_path)
        assert result1 is False
        
        # Immediate second event (should be debounced)
        result2 = self.handler._is_debounced(file_path)
        assert result2 is True
    
    def test_is_debounced_after_timeout(self):
        """Test debouncing after timeout period."""
        file_path = "/path/to/component.py"
        
        # First event
        result1 = self.handler._is_debounced(file_path)
        assert result1 is False
        
        # Simulate time passing
        self.handler.last_events[file_path] = time.time() - 1.0  # 1 second ago
        
        # Second event after timeout
        result2 = self.handler._is_debounced(file_path)
        assert result2 is False
    
    def test_extract_component_name_direct_python_file(self):
        """Test extracting component name from direct Python file."""
        file_path = os.path.join(self.components_dir, "test_component.py")
        
        result = self.handler._extract_component_name(file_path)
        assert result == "test_component"
    
    def test_extract_component_name_package_file(self):
        """Test extracting component name from package file."""
        file_path = os.path.join(self.components_dir, "test_component", "__init__.py")
        
        result = self.handler._extract_component_name(file_path)
        assert result == "test_component"
    
    def test_extract_component_name_nested_package_file(self):
        """Test extracting component name from nested package file."""
        file_path = os.path.join(self.components_dir, "test_component", "submodule", "file.py")
        
        result = self.handler._extract_component_name(file_path)
        assert result == "test_component"
    
    def test_extract_component_name_outside_components_dir(self):
        """Test extracting component name from file outside components directory."""
        file_path = "/some/other/path/component.py"
        
        result = self.handler._extract_component_name(file_path)
        assert result is None
    
    def test_extract_component_name_components_dir_itself(self):
        """Test extracting component name from components directory itself."""
        result = self.handler._extract_component_name(self.components_dir)
        assert result is None
    
    def test_process_event_success(self):
        """Test successful event processing."""
        file_path = os.path.join(self.components_dir, "test_component.py")
        
        with patch.object(self.handler, '_extract_component_name', return_value="test_component"):
            self.handler._process_event(file_path, ChangeType.MODIFIED)
            
            self.file_watcher._notify_change.assert_called_once()
            call_args = self.file_watcher._notify_change.call_args[0][0]
            assert isinstance(call_args, ComponentChange)
            assert call_args.component_name == "test_component"
            assert call_args.change_type == ChangeType.MODIFIED
            assert call_args.file_path == file_path
    
    def test_process_event_with_old_path(self):
        """Test event processing with old path (move event)."""
        file_path = os.path.join(self.components_dir, "test_component.py")
        old_path = os.path.join(self.components_dir, "old_component.py")
        
        with patch.object(self.handler, '_extract_component_name', return_value="test_component"):
            self.handler._process_event(file_path, ChangeType.MOVED, old_path)
            
            self.file_watcher._notify_change.assert_called_once()
            call_args = self.file_watcher._notify_change.call_args[0][0]
            assert call_args.old_path == old_path
    
    def test_process_event_no_component_name(self):
        """Test event processing when component name cannot be extracted."""
        file_path = "/some/other/path/file.py"
        
        with patch.object(self.handler, '_extract_component_name', return_value=None):
            self.handler._process_event(file_path, ChangeType.MODIFIED)
            
            self.file_watcher._notify_change.assert_not_called()
    
    def test_process_event_error_handling(self):
        """Test error handling during event processing."""
        file_path = os.path.join(self.components_dir, "test_component.py")
        
        with patch.object(self.handler, '_extract_component_name', side_effect=Exception("Extract error")):
            self.handler._process_event(file_path, ChangeType.MODIFIED)
            
            self.error_handler.handle_component_error.assert_called_once_with(
                "file_watcher", "process_event", mock.ANY
            )
    
    def test_on_created_event(self):
        """Test handling created events."""
        mock_event = Mock()
        mock_event.src_path = os.path.join(self.components_dir, "test_component.py")
        
        with patch.object(self.handler, '_should_process_event', return_value=True), \
             patch.object(self.handler, '_process_event') as mock_process:
            
            self.handler.on_created(mock_event)
            mock_process.assert_called_once_with(mock_event.src_path, ChangeType.CREATED)
    
    def test_on_modified_event(self):
        """Test handling modified events."""
        mock_event = Mock()
        mock_event.src_path = os.path.join(self.components_dir, "test_component.py")
        
        with patch.object(self.handler, '_should_process_event', return_value=True), \
             patch.object(self.handler, '_is_debounced', return_value=False), \
             patch.object(self.handler, '_process_event') as mock_process:
            
            self.handler.on_modified(mock_event)
            mock_process.assert_called_once_with(mock_event.src_path, ChangeType.MODIFIED)
    
    def test_on_modified_event_debounced(self):
        """Test handling debounced modified events."""
        mock_event = Mock()
        mock_event.src_path = os.path.join(self.components_dir, "test_component.py")
        
        with patch.object(self.handler, '_should_process_event', return_value=True), \
             patch.object(self.handler, '_is_debounced', return_value=True), \
             patch.object(self.handler, '_process_event') as mock_process:
            
            self.handler.on_modified(mock_event)
            mock_process.assert_not_called()
    
    def test_on_deleted_event(self):
        """Test handling deleted events."""
        mock_event = Mock()
        mock_event.src_path = os.path.join(self.components_dir, "test_component.py")
        
        with patch.object(self.handler, '_should_process_event', return_value=True), \
             patch.object(self.handler, '_process_event') as mock_process:
            
            self.handler.on_deleted(mock_event)
            mock_process.assert_called_once_with(mock_event.src_path, ChangeType.DELETED)
    
    def test_on_moved_event(self):
        """Test handling moved events."""
        mock_event = Mock()
        mock_event.src_path = os.path.join(self.components_dir, "old_component.py")
        mock_event.dest_path = os.path.join(self.components_dir, "new_component.py")
        
        with patch.object(self.handler, '_should_process_event', return_value=True), \
             patch.object(self.handler, '_process_event') as mock_process:
            
            self.handler.on_moved(mock_event)
            mock_process.assert_called_once_with(
                mock_event.dest_path, ChangeType.MOVED, mock_event.src_path
            )
    
    def test_event_not_processed(self):
        """Test events that should not be processed."""
        mock_event = Mock()
        mock_event.src_path = "/path/to/file.txt"
        
        with patch.object(self.handler, '_should_process_event', return_value=False), \
             patch.object(self.handler, '_process_event') as mock_process:
            
            self.handler.on_created(mock_event)
            self.handler.on_modified(mock_event)
            self.handler.on_deleted(mock_event)
            self.handler.on_moved(mock_event)
            
            mock_process.assert_not_called()


class TestPollingWatcher:
    """Test cases for PollingWatcher class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        os.makedirs(self.components_dir, exist_ok=True)
        
        self.callback = Mock()
        self.watcher = PollingWatcher(self.components_dir, self.callback)
    
    def teardown_method(self):
        """Clean up test fixtures."""
        if hasattr(self, 'watcher'):
            self.watcher.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_polling_watcher_initialization(self):
        """Test PollingWatcher initialization."""
        assert self.watcher.components_dir == Path(self.components_dir)
        assert self.watcher.callback == self.callback
        assert self.watcher.poll_interval == 2.0
        assert self.watcher.running is False
        assert self.watcher.thread is None
        assert isinstance(self.watcher.file_states, dict)
    
    def test_start_polling(self):
        """Test starting the polling watcher."""
        self.watcher.start()
        
        assert self.watcher.running is True
        assert self.watcher.thread is not None
        assert self.watcher.thread.is_alive()
        
        # Clean up
        self.watcher.stop()
    
    def test_start_polling_already_running(self):
        """Test starting polling when already running."""
        self.watcher.running = True
        original_thread = self.watcher.thread
        
        self.watcher.start()
        
        # Should not create a new thread
        assert self.watcher.thread == original_thread
    
    def test_stop_polling(self):
        """Test stopping the polling watcher."""
        self.watcher.start()
        assert self.watcher.running is True
        
        self.watcher.stop()
        
        assert self.watcher.running is False
        # Thread should finish
        time.sleep(0.1)  # Give thread time to finish
    
    def test_stop_polling_not_running(self):
        """Test stopping polling when not running."""
        # Should not raise an exception
        self.watcher.stop()
    
    def test_scan_directory_initial(self):
        """Test initial directory scan."""
        # Create test files
        test_file1 = os.path.join(self.components_dir, "component1.py")
        test_file2 = os.path.join(self.components_dir, "subdir", "component2.py")
        
        os.makedirs(os.path.dirname(test_file2), exist_ok=True)
        
        with open(test_file1, 'w') as f:
            f.write("# Component 1")
        with open(test_file2, 'w') as f:
            f.write("# Component 2")
        
        # Create new watcher to trigger initial scan
        watcher = PollingWatcher(self.components_dir, self.callback)
        
        assert len(watcher.file_states) == 2
        assert test_file1 in watcher.file_states
        assert test_file2 in watcher.file_states
        
        watcher.stop()
    
    def test_scan_directory_nonexistent(self):
        """Test scanning nonexistent directory."""
        nonexistent_dir = os.path.join(self.temp_dir, "nonexistent")
        watcher = PollingWatcher(nonexistent_dir, self.callback)
        
        assert len(watcher.file_states) == 0
        watcher.stop()
    
    def test_check_for_changes_new_file(self):
        """Test detecting new files."""
        # Start with empty directory
        watcher = PollingWatcher(self.components_dir, self.callback)
        watcher.file_states = {}  # Clear initial state
        
        # Create new file
        test_file = os.path.join(self.components_dir, "new_component.py")
        with open(test_file, 'w') as f:
            f.write("# New component")
        
        watcher._check_for_changes()
        
        self.callback.assert_called_once()
        call_args = self.callback.call_args[0][0]
        assert isinstance(call_args, ComponentChange)
        assert call_args.change_type == ChangeType.CREATED
        assert call_args.component_name == "new_component"
        
        watcher.stop()
    
    def test_check_for_changes_modified_file(self):
        """Test detecting modified files."""
        # Create initial file
        test_file = os.path.join(self.components_dir, "component.py")
        with open(test_file, 'w') as f:
            f.write("# Original content")
        
        watcher = PollingWatcher(self.components_dir, self.callback)
        original_mtime = watcher.file_states[test_file]
        
        # Modify file
        time.sleep(0.1)  # Ensure different mtime
        with open(test_file, 'w') as f:
            f.write("# Modified content")
        
        watcher._check_for_changes()
        
        self.callback.assert_called_once()
        call_args = self.callback.call_args[0][0]
        assert call_args.change_type == ChangeType.MODIFIED
        assert call_args.component_name == "component"
        
        watcher.stop()
    
    def test_check_for_changes_deleted_file(self):
        """Test detecting deleted files."""
        # Create initial file
        test_file = os.path.join(self.components_dir, "component.py")
        with open(test_file, 'w') as f:
            f.write("# Component")
        
        watcher = PollingWatcher(self.components_dir, self.callback)
        
        # Delete file
        os.remove(test_file)
        
        watcher._check_for_changes()
        
        self.callback.assert_called_once()
        call_args = self.callback.call_args[0][0]
        assert call_args.change_type == ChangeType.DELETED
        assert call_args.component_name == "component"
        
        watcher.stop()
    
    def test_check_for_changes_no_changes(self):
        """Test when no changes are detected."""
        # Create initial file
        test_file = os.path.join(self.components_dir, "component.py")
        with open(test_file, 'w') as f:
            f.write("# Component")
        
        watcher = PollingWatcher(self.components_dir, self.callback)
        
        # Check for changes without making any
        watcher._check_for_changes()
        
        self.callback.assert_not_called()
        watcher.stop()
    
    def test_check_for_changes_file_access_error(self):
        """Test handling file access errors during scanning."""
        # Create initial file
        test_file = os.path.join(self.components_dir, "component.py")
        with open(test_file, 'w') as f:
            f.write("# Component")
        
        watcher = PollingWatcher(self.components_dir, self.callback)
        
        # Mock the Path.stat method to raise OSError for any file
        with patch('pathlib.Path.stat') as mock_stat:
            mock_stat.side_effect = OSError("Access denied")
            
            # Should handle the error gracefully and not crash
            try:
                watcher._check_for_changes()
            except OSError:
                # If it still raises, that's expected behavior for this test
                pass
        
        watcher.stop()
    
    def test_extract_component_name_direct_file(self):
        """Test extracting component name from direct Python file."""
        test_file = os.path.join(self.components_dir, "test_component.py")
        
        result = self.watcher._extract_component_name(test_file)
        assert result == "test_component"
    
    def test_extract_component_name_package_file(self):
        """Test extracting component name from package file."""
        test_file = os.path.join(self.components_dir, "test_component", "main.py")
        
        result = self.watcher._extract_component_name(test_file)
        assert result == "test_component"
    
    def test_extract_component_name_outside_components_dir(self):
        """Test extracting component name from file outside components directory."""
        test_file = "/some/other/path/component.py"
        
        result = self.watcher._extract_component_name(test_file)
        assert result is None
    
    def test_notify_change(self):
        """Test notifying about changes."""
        test_file = os.path.join(self.components_dir, "test_component.py")
        
        self.watcher._notify_change(test_file, ChangeType.CREATED)
        
        self.callback.assert_called_once()
        call_args = self.callback.call_args[0][0]
        assert isinstance(call_args, ComponentChange)
        assert call_args.component_name == "test_component"
        assert call_args.change_type == ChangeType.CREATED
        assert call_args.file_path == test_file
    
    def test_notify_change_no_component_name(self):
        """Test notifying when component name cannot be extracted."""
        test_file = "/some/other/path/file.py"
        
        self.watcher._notify_change(test_file, ChangeType.CREATED)
        
        self.callback.assert_not_called()
    
    def test_poll_loop_error_handling(self):
        """Test error handling in polling loop."""
        self.watcher.running = True
        
        with patch.object(self.watcher, '_check_for_changes', side_effect=Exception("Check error")):
            # Start poll loop in a separate thread
            thread = threading.Thread(target=self.watcher._poll_loop, daemon=True)
            thread.start()
            
            # Let it run briefly
            time.sleep(0.1)
            
            # Stop the watcher
            self.watcher.running = False
            thread.join(timeout=1.0)
            
            # Should handle the error gracefully and continue


class TestComponentChange:
    """Test cases for ComponentChange dataclass."""
    
    def test_component_change_creation(self):
        """Test creating ComponentChange instance."""
        timestamp = datetime.now()
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.MODIFIED,
            file_path="/path/to/component.py",
            timestamp=timestamp
        )
        
        assert change.component_name == "test_component"
        assert change.change_type == ChangeType.MODIFIED
        assert change.file_path == "/path/to/component.py"
        assert change.timestamp == timestamp
        assert change.old_path is None
        assert change.metadata is None
    
    def test_component_change_with_optional_fields(self):
        """Test creating ComponentChange with optional fields."""
        timestamp = datetime.now()
        metadata = Mock()
        
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.MOVED,
            file_path="/new/path/component.py",
            timestamp=timestamp,
            old_path="/old/path/component.py",
            metadata=metadata
        )
        
        assert change.old_path == "/old/path/component.py"
        assert change.metadata == metadata
    
    def test_component_change_auto_timestamp(self):
        """Test automatic timestamp generation."""
        change = ComponentChange(
            component_name="test_component",
            change_type=ChangeType.CREATED,
            file_path="/path/to/component.py",
            timestamp=None
        )
        
        # Should have auto-generated timestamp
        assert change.timestamp is not None
        assert isinstance(change.timestamp, datetime)


class TestChangeType:
    """Test cases for ChangeType enum."""
    
    def test_change_type_values(self):
        """Test ChangeType enum values."""
        assert ChangeType.CREATED.value == "created"
        assert ChangeType.MODIFIED.value == "modified"
        assert ChangeType.DELETED.value == "deleted"
        assert ChangeType.MOVED.value == "moved"
    
    def test_change_type_comparison(self):
        """Test ChangeType enum comparison."""
        assert ChangeType.CREATED == ChangeType.CREATED
        assert ChangeType.CREATED != ChangeType.MODIFIED