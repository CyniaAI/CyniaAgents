"""
Module cache and tracking system for the hot reload functionality.

This module provides comprehensive module caching, state tracking, and cleanup
utilities for managing component modules during hot reload operations.
"""

import sys
import gc
import weakref
from typing import Dict, Set, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import importlib.util
import threading
from pathlib import Path

from .models import ComponentState, ComponentStatus, ComponentMetadata
from .errors import ErrorHandler, ErrorReport


@dataclass
class ModuleInfo:
    """Information about a cached module."""
    name: str
    module: Any
    file_path: Optional[str] = None
    load_time: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.now)
    size_bytes: int = 0
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)
    is_component: bool = False
    component_name: Optional[str] = None
    
    def __post_init__(self):
        """Post-initialization setup."""
        if not isinstance(self.dependencies, set):
            self.dependencies = set(self.dependencies) if self.dependencies else set()
        if not isinstance(self.dependents, set):
            self.dependents = set(self.dependents) if self.dependents else set()
    
    def mark_accessed(self):
        """Mark the module as accessed."""
        self.access_count += 1
        self.last_accessed = datetime.now()
    
    def add_dependency(self, module_name: str):
        """Add a module dependency."""
        self.dependencies.add(module_name)
    
    def remove_dependency(self, module_name: str):
        """Remove a module dependency."""
        self.dependencies.discard(module_name)
    
    def add_dependent(self, module_name: str):
        """Add a module that depends on this one."""
        self.dependents.add(module_name)
    
    def remove_dependent(self, module_name: str):
        """Remove a module that depends on this one."""
        self.dependents.discard(module_name)
    
    def has_dependencies(self) -> bool:
        """Check if the module has any dependencies."""
        return bool(self.dependencies)
    
    def has_dependents(self) -> bool:
        """Check if any modules depend on this one."""
        return bool(self.dependents)


class ModuleCache:
    """
    Comprehensive module cache for tracking loaded modules and their relationships.
    
    This class provides thread-safe caching, dependency tracking, and cleanup
    utilities for managing Python modules during hot reload operations.
    """
    
    def __init__(self):
        self._cache: Dict[str, ModuleInfo] = {}
        self._component_modules: Dict[str, Set[str]] = {}  # component_name -> module_names
        self._lock = threading.RLock()
        self._weak_refs: Dict[str, weakref.ref] = {}
        self._cleanup_threshold = 100  # Maximum number of cached modules
        
    def add_module(self, module_name: str, module: Any, component_name: Optional[str] = None,
                   file_path: Optional[str] = None) -> bool:
        """
        Add a module to the cache.
        
        Args:
            module_name: Name of the module
            module: The module object
            component_name: Name of the component this module belongs to
            file_path: Path to the module file
            
        Returns:
            bool: True if added successfully, False otherwise
        """
        with self._lock:
            try:
                # Calculate module size (approximate)
                size_bytes = self._calculate_module_size(module)
                
                # Create module info
                module_info = ModuleInfo(
                    name=module_name,
                    module=module,
                    file_path=file_path,
                    size_bytes=size_bytes,
                    is_component=component_name is not None,
                    component_name=component_name
                )
                
                # Add to cache
                self._cache[module_name] = module_info
                
                # Track component modules
                if component_name:
                    if component_name not in self._component_modules:
                        self._component_modules[component_name] = set()
                    self._component_modules[component_name].add(module_name)
                
                # Create weak reference for cleanup detection
                self._weak_refs[module_name] = weakref.ref(module, self._module_cleanup_callback)
                
                # Update dependencies
                self._update_module_dependencies(module_name, module)
                
                # Check if cleanup is needed
                if len(self._cache) > self._cleanup_threshold:
                    self._cleanup_unused_modules()
                
                return True
                
            except Exception as e:
                print(f"Failed to add module {module_name} to cache: {e}")
                return False
    
    def get_module(self, module_name: str) -> Optional[Any]:
        """
        Get a module from the cache.
        
        Args:
            module_name: Name of the module
            
        Returns:
            The module object if found, None otherwise
        """
        with self._lock:
            if module_name in self._cache:
                module_info = self._cache[module_name]
                module_info.mark_accessed()
                return module_info.module
            return None
    
    def get_module_info(self, module_name: str) -> Optional[ModuleInfo]:
        """
        Get module information from the cache.
        
        Args:
            module_name: Name of the module
            
        Returns:
            ModuleInfo object if found, None otherwise
        """
        with self._lock:
            return self._cache.get(module_name)
    
    def remove_module(self, module_name: str) -> bool:
        """
        Remove a module from the cache.
        
        Args:
            module_name: Name of the module to remove
            
        Returns:
            bool: True if removed successfully, False otherwise
        """
        with self._lock:
            if module_name not in self._cache:
                return False
            
            try:
                module_info = self._cache[module_name]
                
                # Remove from component tracking
                if module_info.component_name:
                    component_modules = self._component_modules.get(module_info.component_name)
                    if component_modules:
                        component_modules.discard(module_name)
                        if not component_modules:
                            del self._component_modules[module_info.component_name]
                
                # Update dependency relationships
                self._remove_module_dependencies(module_name)
                
                # Remove weak reference
                if module_name in self._weak_refs:
                    del self._weak_refs[module_name]
                
                # Remove from cache
                del self._cache[module_name]
                
                return True
                
            except Exception as e:
                print(f"Failed to remove module {module_name} from cache: {e}")
                return False
    
    def get_component_modules(self, component_name: str) -> Set[str]:
        """
        Get all module names associated with a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            Set of module names
        """
        with self._lock:
            return self._component_modules.get(component_name, set()).copy()
    
    def remove_component_modules(self, component_name: str) -> List[str]:
        """
        Remove all modules associated with a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            List of removed module names
        """
        with self._lock:
            module_names = self.get_component_modules(component_name)
            removed_modules = []
            
            for module_name in module_names:
                if self.remove_module(module_name):
                    removed_modules.append(module_name)
            
            return removed_modules
    
    def has_module(self, module_name: str) -> bool:
        """
        Check if a module is in the cache.
        
        Args:
            module_name: Name of the module
            
        Returns:
            bool: True if module is cached, False otherwise
        """
        with self._lock:
            return module_name in self._cache
    
    def get_module_dependencies(self, module_name: str) -> Set[str]:
        """
        Get the dependencies of a module.
        
        Args:
            module_name: Name of the module
            
        Returns:
            Set of dependency module names
        """
        with self._lock:
            if module_name in self._cache:
                return self._cache[module_name].dependencies.copy()
            return set()
    
    def get_module_dependents(self, module_name: str) -> Set[str]:
        """
        Get the modules that depend on a given module.
        
        Args:
            module_name: Name of the module
            
        Returns:
            Set of dependent module names
        """
        with self._lock:
            if module_name in self._cache:
                return self._cache[module_name].dependents.copy()
            return set()
    
    def get_dependency_chain(self, module_name: str) -> List[str]:
        """
        Get the full dependency chain for a module.
        
        Args:
            module_name: Name of the module
            
        Returns:
            List of module names in dependency order
        """
        with self._lock:
            visited = set()
            chain = []
            
            def _build_chain(name: str):
                if name in visited:
                    return
                visited.add(name)
                
                if name in self._cache:
                    # Add dependencies first
                    for dep in self._cache[name].dependencies:
                        _build_chain(dep)
                    
                    chain.append(name)
            
            _build_chain(module_name)
            return chain
    
    def clear_cache(self) -> int:
        """
        Clear all cached modules.
        
        Returns:
            int: Number of modules cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._component_modules.clear()
            self._weak_refs.clear()
            return count
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            total_modules = len(self._cache)
            component_modules = sum(len(modules) for modules in self._component_modules.values())
            total_size = sum(info.size_bytes for info in self._cache.values())
            
            # Calculate access statistics
            total_accesses = sum(info.access_count for info in self._cache.values())
            avg_accesses = total_accesses / total_modules if total_modules > 0 else 0
            
            return {
                'total_modules': total_modules,
                'component_modules': component_modules,
                'total_size_bytes': total_size,
                'total_accesses': total_accesses,
                'average_accesses': avg_accesses,
                'components_tracked': len(self._component_modules)
            }
    
    def _calculate_module_size(self, module: Any) -> int:
        """Calculate approximate size of a module in bytes."""
        try:
            # This is an approximation - getting exact memory usage is complex
            size = sys.getsizeof(module)
            
            # Add size of module attributes
            if hasattr(module, '__dict__'):
                for attr_name, attr_value in module.__dict__.items():
                    try:
                        size += sys.getsizeof(attr_name) + sys.getsizeof(attr_value)
                    except (TypeError, RecursionError):
                        # Some objects can't be sized or cause recursion
                        pass
            
            return size
        except Exception:
            return 0
    
    def _update_module_dependencies(self, module_name: str, module: Any):
        """Update dependency relationships for a module."""
        try:
            if not hasattr(module, '__file__') or not module.__file__:
                return
            
            # Get module dependencies from imports (simplified approach)
            dependencies = set()
            
            # Check sys.modules for related modules
            for name, mod in sys.modules.items():
                if mod is None or mod is module:
                    continue
                
                # Check if this module imports the other
                if hasattr(mod, '__file__') and mod.__file__:
                    try:
                        # Simple heuristic: if module file paths are related
                        if module.__file__ and mod.__file__:
                            module_dir = Path(module.__file__).parent
                            mod_dir = Path(mod.__file__).parent
                            
                            # If they're in the same directory tree, consider it a dependency
                            if str(module_dir).startswith(str(mod_dir)) or str(mod_dir).startswith(str(module_dir)):
                                dependencies.add(name)
                    except Exception:
                        pass
            
            # Update cache with dependencies
            if module_name in self._cache:
                module_info = self._cache[module_name]
                module_info.dependencies.update(dependencies)
                
                # Update reverse dependencies
                for dep_name in dependencies:
                    if dep_name in self._cache:
                        self._cache[dep_name].add_dependent(module_name)
        
        except Exception as e:
            print(f"Failed to update dependencies for {module_name}: {e}")
    
    def _remove_module_dependencies(self, module_name: str):
        """Remove dependency relationships for a module."""
        if module_name not in self._cache:
            return
        
        module_info = self._cache[module_name]
        
        # Remove this module from dependents of its dependencies
        for dep_name in module_info.dependencies:
            if dep_name in self._cache:
                self._cache[dep_name].remove_dependent(module_name)
        
        # Remove this module from dependencies of its dependents
        for dependent_name in module_info.dependents:
            if dependent_name in self._cache:
                self._cache[dependent_name].remove_dependency(module_name)
    
    def _cleanup_unused_modules(self):
        """Clean up unused modules from the cache."""
        try:
            # Find modules that haven't been accessed recently
            now = datetime.now()
            modules_to_remove = []
            
            for module_name, module_info in self._cache.items():
                # Skip component modules (they should be managed explicitly)
                if module_info.is_component:
                    continue
                
                # Remove modules not accessed in the last hour with low access count
                time_since_access = (now - module_info.last_accessed).total_seconds()
                if time_since_access > 3600 and module_info.access_count < 5:
                    modules_to_remove.append(module_name)
            
            # Remove identified modules
            for module_name in modules_to_remove:
                self.remove_module(module_name)
            
            # Force garbage collection
            gc.collect()
            
        except Exception as e:
            print(f"Failed to cleanup unused modules: {e}")
    
    def _module_cleanup_callback(self, weak_ref):
        """Callback for when a module is garbage collected."""
        # Find and remove the module from cache
        module_name_to_remove = None
        for module_name, ref in self._weak_refs.items():
            if ref is weak_ref:
                module_name_to_remove = module_name
                break
        
        if module_name_to_remove:
            self.remove_module(module_name_to_remove)


class ComponentStateTracker:
    """
    Tracks the state of components and their modules throughout the hot reload lifecycle.
    """
    
    def __init__(self, module_cache: ModuleCache, error_handler: ErrorHandler):
        self.module_cache = module_cache
        self.error_handler = error_handler
        self._component_states: Dict[str, ComponentState] = {}
        self._lock = threading.RLock()
    
    def track_component(self, component_name: str, metadata: Optional[ComponentMetadata] = None) -> ComponentState:
        """
        Start tracking a component.
        
        Args:
            component_name: Name of the component
            metadata: Component metadata
            
        Returns:
            ComponentState object
        """
        with self._lock:
            if component_name in self._component_states:
                state = self._component_states[component_name]
                if metadata:
                    state.metadata = metadata
                return state
            
            state = ComponentState(
                name=component_name,
                status=ComponentStatus.UNKNOWN,
                metadata=metadata
            )
            
            self._component_states[component_name] = state
            return state
    
    def update_component_status(self, component_name: str, status: ComponentStatus, 
                              error_message: Optional[str] = None) -> bool:
        """
        Update the status of a component.
        
        Args:
            component_name: Name of the component
            status: New status
            error_message: Error message if status is FAILED
            
        Returns:
            bool: True if updated successfully
        """
        with self._lock:
            if component_name not in self._component_states:
                return False
            
            state = self._component_states[component_name]
            old_status = state.status
            state.update_status(status, error_message)
            
            # Update module references if status changed to LOADED
            if status == ComponentStatus.LOADED:
                module_names = self.module_cache.get_component_modules(component_name)
                for module_name in module_names:
                    state.add_module_reference(module_name)
            
            # Clear module references if unloaded
            elif status == ComponentStatus.UNLOADED:
                state.clear_module_references()
            
            return True
    
    def get_component_state(self, component_name: str) -> Optional[ComponentState]:
        """
        Get the current state of a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            ComponentState object if found, None otherwise
        """
        with self._lock:
            return self._component_states.get(component_name)
    
    def remove_component(self, component_name: str) -> bool:
        """
        Stop tracking a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            bool: True if removed successfully
        """
        with self._lock:
            if component_name in self._component_states:
                del self._component_states[component_name]
                return True
            return False
    
    def get_all_component_states(self) -> Dict[str, ComponentState]:
        """
        Get all tracked component states.
        
        Returns:
            Dictionary mapping component names to their states
        """
        with self._lock:
            return self._component_states.copy()
    
    def get_components_by_status(self, status: ComponentStatus) -> List[str]:
        """
        Get all components with a specific status.
        
        Args:
            status: Status to filter by
            
        Returns:
            List of component names
        """
        with self._lock:
            return [name for name, state in self._component_states.items() 
                   if state.status == status]
    
    def get_failed_components(self) -> List[Tuple[str, str]]:
        """
        Get all components that are in a failed state.
        
        Returns:
            List of tuples (component_name, error_message)
        """
        with self._lock:
            failed = []
            for name, state in self._component_states.items():
                if state.is_failed():
                    failed.append((name, state.last_error or "Unknown error"))
            return failed
    
    def cleanup_component_state(self, component_name: str) -> bool:
        """
        Clean up all state and cache entries for a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            bool: True if cleanup was successful
        """
        with self._lock:
            try:
                # Remove from module cache
                removed_modules = self.module_cache.remove_component_modules(component_name)
                
                # Clear error history
                self.error_handler.clear_component_errors(component_name)
                
                # Remove from state tracking
                self.remove_component(component_name)
                
                return True
                
            except Exception as e:
                print(f"Failed to cleanup component state for {component_name}: {e}")
                return False


class ModuleReferenceCleanup:
    """
    Utilities for cleaning up module references during hot reload operations.
    """
    
    def __init__(self, module_cache: ModuleCache):
        self.module_cache = module_cache
    
    def cleanup_sys_modules(self, module_names: List[str]) -> List[str]:
        """
        Clean up module references from sys.modules.
        
        Args:
            module_names: List of module names to clean up
            
        Returns:
            List of successfully cleaned module names
        """
        cleaned_modules = []
        
        for module_name in module_names:
            try:
                if module_name in sys.modules:
                    # Get module info before removal
                    module_info = self.module_cache.get_module_info(module_name)
                    
                    # Remove from sys.modules
                    del sys.modules[module_name]
                    
                    # Clean up related modules
                    if module_info:
                        self._cleanup_related_modules(module_name, module_info)
                    
                    cleaned_modules.append(module_name)
                    
            except Exception as e:
                print(f"Failed to cleanup sys.modules for {module_name}: {e}")
        
        return cleaned_modules
    
    def cleanup_importlib_cache(self, module_names: List[str]) -> bool:
        """
        Clean up importlib caches for the specified modules.
        
        Args:
            module_names: List of module names to clean up
            
        Returns:
            bool: True if cleanup was successful
        """
        # Add recursion protection
        if hasattr(self, '_cleanup_in_progress') and self._cleanup_in_progress:
            return True
            
        try:
            self._cleanup_in_progress = True
            
            # Clear importlib caches
            if hasattr(importlib.util, 'cache_from_source'):
                for module_name in module_names:
                    try:
                        module_info = self.module_cache.get_module_info(module_name)
                        if module_info and module_info.file_path:
                            cache_file = importlib.util.cache_from_source(module_info.file_path)
                            if Path(cache_file).exists():
                                Path(cache_file).unlink()
                    except Exception:
                        # Silently continue on individual module failures
                        continue
            
            # Invalidate import caches
            importlib.invalidate_caches()
            
            return True
            
        except Exception as e:
            print(f"Failed to cleanup importlib cache: {e}")
            return False
        finally:
            self._cleanup_in_progress = False
    
    def force_garbage_collection(self) -> Dict[str, int]:
        """
        Force garbage collection and return statistics.
        
        Returns:
            Dictionary with garbage collection statistics
        """
        try:
            # Get initial counts
            initial_objects = len(gc.get_objects())
            
            # Force collection
            collected = gc.collect()
            
            # Get final counts
            final_objects = len(gc.get_objects())
            
            return {
                'collected': collected,
                'initial_objects': initial_objects,
                'final_objects': final_objects,
                'freed_objects': initial_objects - final_objects
            }
            
        except Exception as e:
            print(f"Failed to force garbage collection: {e}")
            return {'error': str(e)}
    
    def cleanup_component_references(self, component_name: str) -> Dict[str, Any]:
        """
        Comprehensive cleanup of all references for a component.
        
        Args:
            component_name: Name of the component to clean up
            
        Returns:
            Dictionary with cleanup results
        """
        results = {
            'component_name': component_name,
            'modules_cleaned': [],
            'sys_modules_cleaned': [],
            'cache_cleaned': False,
            'gc_stats': {},
            'success': False
        }
        
        try:
            # Get component modules
            module_names = list(self.module_cache.get_component_modules(component_name))
            results['modules_cleaned'] = module_names
            
            # Clean up sys.modules
            results['sys_modules_cleaned'] = self.cleanup_sys_modules(module_names)
            
            # Clean up importlib cache
            results['cache_cleaned'] = self.cleanup_importlib_cache(module_names)
            
            # Remove from module cache
            self.module_cache.remove_component_modules(component_name)
            
            # Force garbage collection
            results['gc_stats'] = self.force_garbage_collection()
            
            results['success'] = True
            
        except Exception as e:
            results['error'] = str(e)
            print(f"Failed to cleanup component references for {component_name}: {e}")
        
        return results
    
    def _cleanup_related_modules(self, module_name: str, module_info: ModuleInfo):
        """Clean up modules related to the given module."""
        try:
            # Clean up submodules
            submodules_to_remove = []
            for name in sys.modules:
                if name.startswith(f"{module_name}."):
                    submodules_to_remove.append(name)
            
            for submodule in submodules_to_remove:
                if submodule in sys.modules:
                    del sys.modules[submodule]
            
        except Exception as e:
            print(f"Failed to cleanup related modules for {module_name}: {e}")