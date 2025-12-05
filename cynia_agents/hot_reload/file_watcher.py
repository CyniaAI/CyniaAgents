"""
File system watcher for component monitoring.

This module provides the FileWatcher class for monitoring component directories
and automatically detecting changes, additions, and removals of components.
"""

import os
import sys
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Callable, Set, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    # Fallback implementation without watchdog
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = None
    FileSystemEvent = None

from .models import ComponentMetadata
from .errors import ErrorHandler


class ChangeType(Enum):
    """Types of file system changes."""
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass
class ComponentChange:
    """Information about a component change event."""
    component_name: str
    change_type: ChangeType
    file_path: str
    timestamp: datetime
    old_path: Optional[str] = None  # For move events
    metadata: Optional[ComponentMetadata] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class ComponentEventHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    """
    Event handler for component file system events.
    
    This class processes file system events and converts them into
    component change notifications.
    """
    
    def __init__(self, file_watcher: 'FileWatcher'):
        """
        Initialize the event handler.
        
        Args:
            file_watcher: The FileWatcher instance that owns this handler
        """
        if WATCHDOG_AVAILABLE:
            super().__init__()
        self.file_watcher = file_watcher
        self.last_events: Dict[str, float] = {}  # Debounce duplicate events
        self.debounce_time = 1.0  # 1 second debounce (increased from 500ms)
        self.component_event_counts: Dict[str, int] = {}  # Track event counts per component
        self.max_events_per_component = 5  # Maximum events per component in debounce window
    
    def on_created(self, event):
        """Handle file/directory creation events."""
        if not self._should_process_event(event):
            return
        
        self._process_event(event.src_path, ChangeType.CREATED)
    
    def on_modified(self, event):
        """Handle file/directory modification events."""
        if not self._should_process_event(event):
            return
        
        # Debounce rapid modification events
        if self._is_debounced(event.src_path):
            return
        
        self._process_event(event.src_path, ChangeType.MODIFIED)
    
    def on_deleted(self, event):
        """Handle file/directory deletion events."""
        if not self._should_process_event(event):
            return
        
        self._process_event(event.src_path, ChangeType.DELETED)
    
    def on_moved(self, event):
        """Handle file/directory move events."""
        if not self._should_process_event(event):
            return
        
        self._process_event(event.dest_path, ChangeType.MOVED, event.src_path)
    
    def _should_process_event(self, event) -> bool:
        """Check if an event should be processed."""
        if event.is_directory:
            # Only process directory events for package components
            return self._is_component_directory(event.src_path)
        else:
            # Process Python file events
            return event.src_path.endswith('.py') or event.src_path.endswith('requirements.txt')
    
    def _is_component_directory(self, dir_path: str) -> bool:
        """Check if a directory is a component package."""
        path = Path(dir_path)
        return (path / '__init__.py').exists() or (path / 'main.py').exists()
    
    def _is_debounced(self, file_path: str) -> bool:
        """Check if an event should be debounced."""
        current_time = time.time()
        last_time = self.last_events.get(file_path, 0)
        
        # Basic time-based debouncing
        if current_time - last_time < self.debounce_time:
            return True
        
        # Component-based event limiting
        component_name = self._extract_component_name(file_path)
        if component_name:
            # Reset count if enough time has passed
            if current_time - last_time > self.debounce_time * 2:
                self.component_event_counts[component_name] = 0
            
            # Increment event count
            count = self.component_event_counts.get(component_name, 0) + 1
            self.component_event_counts[component_name] = count
            
            # Block if too many events for this component
            if count > self.max_events_per_component:
                return True
        
        self.last_events[file_path] = current_time
        return False
    
    def _process_event(self, file_path: str, change_type: ChangeType, old_path: Optional[str] = None):
        """Process a file system event and notify the file watcher."""
        try:
            component_name = self._extract_component_name(file_path)
            if not component_name:
                return
            
            change = ComponentChange(
                component_name=component_name,
                change_type=change_type,
                file_path=file_path,
                timestamp=datetime.now(),
                old_path=old_path
            )
            
            self.file_watcher._notify_change(change)
            
        except Exception as e:
            self.file_watcher.error_handler.handle_component_error(
                "file_watcher", "process_event", e
            )
    
    def _extract_component_name(self, file_path: str) -> Optional[str]:
        """Extract component name from file path."""
        path = Path(file_path)
        
        # For files in the components directory
        components_dir = Path(self.file_watcher.components_dir)
        
        try:
            relative_path = path.relative_to(components_dir)
            
            # If it's a direct Python file
            if len(relative_path.parts) == 1 and relative_path.suffix == '.py':
                return relative_path.stem
            
            # If it's in a package directory
            if len(relative_path.parts) >= 2:
                return relative_path.parts[0]
            
            return None
            
        except ValueError:
            # Path is not relative to components directory
            return None


class PollingWatcher:
    """
    Fallback polling-based file watcher for when watchdog is not available.
    
    This implementation periodically scans the components directory for changes.
    """
    
    def __init__(self, components_dir: str, callback: Callable[[ComponentChange], None]):
        """
        Initialize the polling watcher.
        
        Args:
            components_dir: Directory to watch
            callback: Function to call when changes are detected
        """
        self.components_dir = Path(components_dir)
        self.callback = callback
        self.poll_interval = 2.0  # Poll every 2 seconds
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.file_states: Dict[str, float] = {}  # file_path -> mtime
        
        # Initial scan
        self._scan_directory()
    
    def start(self):
        """Start the polling watcher."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Stop the polling watcher."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
    
    def _poll_loop(self):
        """Main polling loop."""
        while self.running:
            try:
                self._check_for_changes()
                time.sleep(self.poll_interval)
            except Exception:
                # Continue polling even if there are errors
                time.sleep(self.poll_interval)
    
    def _check_for_changes(self):
        """Check for file system changes."""
        current_states = {}
        
        # Scan current state
        if self.components_dir.exists():
            for item in self.components_dir.rglob('*'):
                if item.is_file() and (item.suffix == '.py' or item.name == 'requirements.txt'):
                    try:
                        mtime = item.stat().st_mtime
                        current_states[str(item)] = mtime
                    except OSError:
                        continue
        
        # Compare with previous state
        for file_path, mtime in current_states.items():
            if file_path not in self.file_states:
                # New file
                self._notify_change(file_path, ChangeType.CREATED)
            elif self.file_states[file_path] != mtime:
                # Modified file
                self._notify_change(file_path, ChangeType.MODIFIED)
        
        # Check for deleted files
        for file_path in self.file_states:
            if file_path not in current_states:
                self._notify_change(file_path, ChangeType.DELETED)
        
        # Update state
        self.file_states = current_states
    
    def _scan_directory(self):
        """Initial directory scan to establish baseline."""
        if not self.components_dir.exists():
            return
        
        for item in self.components_dir.rglob('*'):
            if item.is_file() and (item.suffix == '.py' or item.name == 'requirements.txt'):
                try:
                    mtime = item.stat().st_mtime
                    self.file_states[str(item)] = mtime
                except OSError:
                    continue
    
    def _notify_change(self, file_path: str, change_type: ChangeType):
        """Notify about a file change."""
        component_name = self._extract_component_name(file_path)
        if not component_name:
            return
        
        change = ComponentChange(
            component_name=component_name,
            change_type=change_type,
            file_path=file_path,
            timestamp=datetime.now()
        )
        
        self.callback(change)
    
    def _extract_component_name(self, file_path: str) -> Optional[str]:
        """Extract component name from file path."""
        path = Path(file_path)
        
        try:
            relative_path = path.relative_to(self.components_dir)
            
            # If it's a direct Python file
            if len(relative_path.parts) == 1 and relative_path.suffix == '.py':
                return relative_path.stem
            
            # If it's in a package directory
            if len(relative_path.parts) >= 2:
                return relative_path.parts[0]
            
            return None
            
        except ValueError:
            return None


class FileWatcher:
    """
    File system watcher for component monitoring.
    
    This class monitors the components directory for changes and provides
    callbacks for component creation, modification, and deletion events.
    """
    
    def __init__(self, components_dir: str = "components", error_handler: Optional[ErrorHandler] = None):
        """
        Initialize the FileWatcher.
        
        Args:
            components_dir: Directory to watch for component changes
            error_handler: Error handler instance for error management
        """
        self.components_dir = Path(components_dir)
        self.error_handler = error_handler or ErrorHandler()
        self.observers: List[Any] = []
        self.polling_watcher: Optional[PollingWatcher] = None
        self.is_watching = False
        
        # Event callbacks
        self.change_callbacks: List[Callable[[ComponentChange], None]] = []
        self.component_created_callbacks: List[Callable[[str, ComponentMetadata], None]] = []
        self.component_modified_callbacks: List[Callable[[str, ComponentMetadata], None]] = []
        self.component_deleted_callbacks: List[Callable[[str], None]] = []
        
        # Component discovery callbacks
        self.discovery_callbacks: List[Callable[[], None]] = []
        
        # Ensure components directory exists
        self.components_dir.mkdir(exist_ok=True)
    
    def start_watching(self) -> bool:
        """
        Start watching the components directory for changes.
        
        Returns:
            bool: True if watching started successfully, False otherwise
        """
        if self.is_watching:
            return True
        
        try:
            if WATCHDOG_AVAILABLE:
                return self._start_watchdog_watching()
            else:
                return self._start_polling_watching()
        except Exception as e:
            self.error_handler.handle_component_error("file_watcher", "start_watching", e)
            return False
    
    def stop_watching(self):
        """Stop watching the components directory."""
        if not self.is_watching:
            return
        
        try:
            if WATCHDOG_AVAILABLE and self.observers:
                for observer in self.observers:
                    observer.stop()
                    observer.join(timeout=5.0)
                self.observers.clear()
            
            if self.polling_watcher:
                self.polling_watcher.stop()
                self.polling_watcher = None
            
            self.is_watching = False
            
        except Exception as e:
            self.error_handler.handle_component_error("file_watcher", "stop_watching", e)
    
    def _start_watchdog_watching(self) -> bool:
        """Start watching using the watchdog library."""
        try:
            observer = Observer()
            event_handler = ComponentEventHandler(self)
            
            observer.schedule(
                event_handler,
                str(self.components_dir),
                recursive=True
            )
            
            observer.start()
            self.observers.append(observer)
            self.is_watching = True
            
            return True
            
        except Exception as e:
            self.error_handler.handle_component_error("file_watcher", "start_watchdog", e)
            return False
    
    def _start_polling_watching(self) -> bool:
        """Start watching using polling fallback."""
        try:
            self.polling_watcher = PollingWatcher(
                str(self.components_dir),
                self._notify_change
            )
            
            self.polling_watcher.start()
            self.is_watching = True
            
            return True
            
        except Exception as e:
            self.error_handler.handle_component_error("file_watcher", "start_polling", e)
            return False
    
    def add_change_callback(self, callback: Callable[[ComponentChange], None]):
        """Add a callback for any component change."""
        self.change_callbacks.append(callback)
    
    def add_component_created_callback(self, callback: Callable[[str, ComponentMetadata], None]):
        """Add a callback for component creation events."""
        self.component_created_callbacks.append(callback)
    
    def add_component_modified_callback(self, callback: Callable[[str, ComponentMetadata], None]):
        """Add a callback for component modification events."""
        self.component_modified_callbacks.append(callback)
    
    def add_component_deleted_callback(self, callback: Callable[[str], None]):
        """Add a callback for component deletion events."""
        self.component_deleted_callbacks.append(callback)
    
    def add_discovery_callback(self, callback: Callable[[], None]):
        """Add a callback to trigger component discovery."""
        self.discovery_callbacks.append(callback)
    
    def remove_change_callback(self, callback: Callable[[ComponentChange], None]):
        """Remove a change callback."""
        if callback in self.change_callbacks:
            self.change_callbacks.remove(callback)
    
    def remove_component_created_callback(self, callback: Callable[[str, ComponentMetadata], None]):
        """Remove a component created callback."""
        if callback in self.component_created_callbacks:
            self.component_created_callbacks.remove(callback)
    
    def remove_component_modified_callback(self, callback: Callable[[str, ComponentMetadata], None]):
        """Remove a component modified callback."""
        if callback in self.component_modified_callbacks:
            self.component_modified_callbacks.remove(callback)
    
    def remove_component_deleted_callback(self, callback: Callable[[str], None]):
        """Remove a component deleted callback."""
        if callback in self.component_deleted_callbacks:
            self.component_deleted_callbacks.remove(callback)
    
    def remove_discovery_callback(self, callback: Callable[[], None]):
        """Remove a discovery callback."""
        if callback in self.discovery_callbacks:
            self.discovery_callbacks.remove(callback)
    
    def _notify_change(self, change: ComponentChange):
        """Notify all callbacks about a component change."""
        try:
            # Call general change callbacks
            for callback in self.change_callbacks:
                try:
                    callback(change)
                except Exception as e:
                    self.error_handler.handle_component_error(
                        "file_watcher", "change_callback", e
                    )
            
            # Call specific callbacks based on change type
            if change.change_type == ChangeType.CREATED:
                self._notify_component_created(change)
            elif change.change_type == ChangeType.MODIFIED:
                self._notify_component_modified(change)
            elif change.change_type == ChangeType.DELETED:
                self._notify_component_deleted(change)
            elif change.change_type == ChangeType.MOVED:
                # Treat moves as creation at new location
                self._notify_component_created(change)
            
            # Trigger component discovery
            self._trigger_discovery()
            
        except Exception as e:
            self.error_handler.handle_component_error("file_watcher", "notify_change", e)
    
    def _notify_component_created(self, change: ComponentChange):
        """Notify about component creation."""
        metadata = self._extract_metadata_if_needed(change)
        
        for callback in self.component_created_callbacks:
            try:
                callback(change.component_name, metadata)
            except Exception as e:
                self.error_handler.handle_component_error(
                    "file_watcher", "created_callback", e
                )
    
    def _notify_component_modified(self, change: ComponentChange):
        """Notify about component modification."""
        metadata = self._extract_metadata_if_needed(change)
        
        for callback in self.component_modified_callbacks:
            try:
                callback(change.component_name, metadata)
            except Exception as e:
                self.error_handler.handle_component_error(
                    "file_watcher", "modified_callback", e
                )
    
    def _notify_component_deleted(self, change: ComponentChange):
        """Notify about component deletion."""
        for callback in self.component_deleted_callbacks:
            try:
                callback(change.component_name)
            except Exception as e:
                self.error_handler.handle_component_error(
                    "file_watcher", "deleted_callback", e
                )
    
    def _trigger_discovery(self):
        """Trigger component discovery callbacks."""
        for callback in self.discovery_callbacks:
            try:
                callback()
            except Exception as e:
                self.error_handler.handle_component_error(
                    "file_watcher", "discovery_callback", e
                )
    
    def _extract_metadata_if_needed(self, change: ComponentChange) -> Optional[ComponentMetadata]:
        """Extract metadata from component if not already available."""
        if change.metadata:
            return change.metadata
        
        # Try to extract metadata from the file
        try:
            from .loader import ComponentLoader
            loader = ComponentLoader(str(self.components_dir))
            return loader.extract_component_metadata(change.file_path)
        except Exception:
            return None
    
    def get_watched_directory(self) -> str:
        """Get the directory being watched."""
        return str(self.components_dir)
    
    def is_watching_active(self) -> bool:
        """Check if file watching is currently active."""
        return self.is_watching
    
    def get_watcher_info(self) -> Dict[str, Any]:
        """Get information about the file watcher."""
        return {
            'is_watching': self.is_watching,
            'components_dir': str(self.components_dir),
            'watchdog_available': WATCHDOG_AVAILABLE,
            'using_polling': self.polling_watcher is not None,
            'observer_count': len(self.observers),
            'callback_counts': {
                'change': len(self.change_callbacks),
                'created': len(self.component_created_callbacks),
                'modified': len(self.component_modified_callbacks),
                'deleted': len(self.component_deleted_callbacks),
                'discovery': len(self.discovery_callbacks)
            }
        }
    
    def force_discovery(self):
        """Force trigger component discovery."""
        self._trigger_discovery()
    
    def __del__(self):
        """Cleanup when the file watcher is destroyed."""
        self.stop_watching()