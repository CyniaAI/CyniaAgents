"""
Global component loading guard to prevent infinite loops.

This module provides a centralized mechanism to prevent components from being
loaded multiple times simultaneously, which can cause infinite loops.
"""

import threading
import time
from typing import Set, Dict
from datetime import datetime, timedelta

class ComponentLoadGuard:
    """
    Global singleton guard to prevent infinite component loading loops.
    """
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._loading_components: Set[str] = set()
        self._load_attempts: Dict[str, int] = {}
        self._last_load_time: Dict[str, datetime] = {}
        self._max_attempts_per_minute = 3
        self._cooldown_seconds = 5
        self._operation_lock = threading.RLock()
        self._initialized = True
    
    def can_load_component(self, component_name: str) -> bool:
        """
        Check if a component can be loaded right now.
        
        Args:
            component_name: Name of the component to check
            
        Returns:
            bool: True if the component can be loaded, False otherwise
        """
        with self._operation_lock:
            current_time = datetime.now()
            
            # Check if component is already being loaded
            if component_name in self._loading_components:
                return False
            
            # Check cooldown period
            last_load = self._last_load_time.get(component_name)
            if last_load and (current_time - last_load).total_seconds() < self._cooldown_seconds:
                return False
            
            # Check load attempts in the last minute
            attempts = self._load_attempts.get(component_name, 0)
            if attempts >= self._max_attempts_per_minute:
                # Reset counter if more than a minute has passed
                if last_load and (current_time - last_load) > timedelta(minutes=1):
                    self._load_attempts[component_name] = 0
                else:
                    return False
            
            return True
    
    def start_loading(self, component_name: str) -> bool:
        """
        Mark a component as being loaded.
        
        Args:
            component_name: Name of the component being loaded
            
        Returns:
            bool: True if loading was started, False if already loading
        """
        with self._operation_lock:
            if not self.can_load_component(component_name):
                return False
            
            self._loading_components.add(component_name)
            self._load_attempts[component_name] = self._load_attempts.get(component_name, 0) + 1
            self._last_load_time[component_name] = datetime.now()
            return True
    
    def finish_loading(self, component_name: str, success: bool = True):
        """
        Mark a component as finished loading.
        
        Args:
            component_name: Name of the component that finished loading
            success: Whether the loading was successful
        """
        with self._operation_lock:
            self._loading_components.discard(component_name)
            
            if success:
                # Reset attempt counter on successful load
                self._load_attempts[component_name] = 0
    
    def is_loading(self, component_name: str) -> bool:
        """
        Check if a component is currently being loaded.
        
        Args:
            component_name: Name of the component to check
            
        Returns:
            bool: True if the component is currently being loaded
        """
        with self._operation_lock:
            return component_name in self._loading_components
    
    def get_loading_components(self) -> Set[str]:
        """
        Get the set of components currently being loaded.
        
        Returns:
            Set[str]: Set of component names currently being loaded
        """
        with self._operation_lock:
            return self._loading_components.copy()
    
    def reset_component(self, component_name: str):
        """
        Reset all tracking data for a component.
        
        Args:
            component_name: Name of the component to reset
        """
        with self._operation_lock:
            self._loading_components.discard(component_name)
            self._load_attempts.pop(component_name, None)
            self._last_load_time.pop(component_name, None)
    
    def reset_all(self):
        """Reset all tracking data."""
        with self._operation_lock:
            self._loading_components.clear()
            self._load_attempts.clear()
            self._last_load_time.clear()
    
    def get_stats(self) -> Dict[str, any]:
        """
        Get statistics about component loading.
        
        Returns:
            Dict with loading statistics
        """
        with self._operation_lock:
            return {
                'currently_loading': len(self._loading_components),
                'loading_components': list(self._loading_components),
                'total_tracked_components': len(self._load_attempts),
                'load_attempts': self._load_attempts.copy(),
                'last_load_times': {k: v.isoformat() for k, v in self._last_load_time.items()}
            }

# Global instance
_guard = ComponentLoadGuard()

def can_load_component(component_name: str) -> bool:
    """Global function to check if a component can be loaded."""
    return _guard.can_load_component(component_name)

def start_loading_component(component_name: str) -> bool:
    """Global function to start loading a component."""
    return _guard.start_loading(component_name)

def finish_loading_component(component_name: str, success: bool = True):
    """Global function to finish loading a component."""
    _guard.finish_loading(component_name, success)

def is_component_loading(component_name: str) -> bool:
    """Global function to check if a component is loading."""
    return _guard.is_loading(component_name)

def reset_component_guard(component_name: str = None):
    """Global function to reset component guard data."""
    if component_name:
        _guard.reset_component(component_name)
    else:
        _guard.reset_all()

def get_guard_stats() -> Dict[str, any]:
    """Global function to get guard statistics."""
    return _guard.get_stats()