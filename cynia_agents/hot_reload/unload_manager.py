"""
Component unloading system for comprehensive module cleanup.

This module provides advanced unloading capabilities including memory cleanup,
reference tracking, rollback mechanisms, and validation.
"""

import sys
import gc
import weakref
import threading
import time
from typing import Dict, List, Optional, Set, Any, Tuple
from pathlib import Path
from datetime import datetime
import importlib.util

from .models import ComponentStatus, ComponentMetadata, ReloadResult, OperationType
from .cache import ModuleCache, ComponentStateTracker, ModuleReferenceCleanup
from .errors import ErrorHandler, ErrorReport, ErrorSeverity


class UnloadValidationResult:
    """Result of unload validation checks."""
    
    def __init__(self, can_unload: bool, blocking_dependencies: List[str] = None, 
                 warnings: List[str] = None, errors: List[str] = None):
        self.can_unload = can_unload
        self.blocking_dependencies = blocking_dependencies or []
        self.warnings = warnings or []
        self.errors = errors or []
    
    def has_blocking_dependencies(self) -> bool:
        """Check if there are dependencies blocking the unload."""
        return bool(self.blocking_dependencies)
    
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return bool(self.warnings)
    
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return bool(self.errors)


class UnloadSnapshot:
    """Snapshot of component state before unloading for rollback purposes."""
    
    def __init__(self, component_name: str):
        self.component_name = component_name
        self.timestamp = datetime.now()
        self.modules: Dict[str, Any] = {}
        self.component_state: Optional[Any] = None
        self.sys_modules_backup: Dict[str, Any] = {}
        self.cache_state: Dict[str, Any] = {}
        self.memory_usage_before: int = 0
        self.memory_usage_after: int = 0
    
    def add_module_backup(self, module_name: str, module: Any):
        """Add a module to the backup."""
        self.modules[module_name] = {
            'module': module,
            'file_path': getattr(module, '__file__', None),
            'name': getattr(module, '__name__', module_name),
            'package': getattr(module, '__package__', None)
        }
    
    def get_module_names(self) -> List[str]:
        """Get list of backed up module names."""
        return list(self.modules.keys())
    
    def can_rollback(self) -> bool:
        """Check if rollback is possible."""
        return bool(self.modules) and self.component_state is not None


class MemoryTracker:
    """Tracks memory usage during unload operations."""
    
    def __init__(self):
        self._initial_objects = 0
        self._final_objects = 0
        self._gc_stats = {}
    
    def start_tracking(self):
        """Start memory tracking."""
        self._initial_objects = len(gc.get_objects())
        gc.collect()  # Clean up before tracking
    
    def stop_tracking(self) -> Dict[str, Any]:
        """Stop tracking and return memory statistics."""
        # Force garbage collection
        collected = gc.collect()
        self._final_objects = len(gc.get_objects())
        
        self._gc_stats = {
            'initial_objects': self._initial_objects,
            'final_objects': self._final_objects,
            'objects_freed': self._initial_objects - self._final_objects,
            'gc_collected': collected,
            'gc_counts': gc.get_count() if hasattr(gc, 'get_count') else None,
            'gc_stats': gc.get_stats() if hasattr(gc, 'get_stats') else None
        }
        
        return self._gc_stats
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get current memory statistics."""
        return self._gc_stats.copy()


class ComponentUnloader:
    """
    Comprehensive component unloading system with memory cleanup and rollback.
    
    This class provides advanced unloading capabilities including:
    - Complete module reference cleanup
    - Memory leak prevention
    - Dependency validation
    - Rollback mechanisms
    - Performance monitoring
    """
    
    def __init__(self, module_cache: ModuleCache, state_tracker: ComponentStateTracker,
                 reference_cleanup: ModuleReferenceCleanup, error_handler: ErrorHandler):
        self.module_cache = module_cache
        self.state_tracker = state_tracker
        self.reference_cleanup = reference_cleanup
        self.error_handler = error_handler
        
        # Unload tracking
        self._unload_snapshots: Dict[str, UnloadSnapshot] = {}
        self._unload_history: Dict[str, List[ReloadResult]] = {}
        self._lock = threading.RLock()
        
        # Memory tracking
        self.memory_tracker = MemoryTracker()
        
        # Unload statistics
        self._unload_stats = {
            'total_unloads': 0,
            'successful_unloads': 0,
            'failed_unloads': 0,
            'rollbacks_performed': 0,
            'memory_freed_bytes': 0,
            'modules_cleaned': 0
        }
    
    def validate_unload(self, component_name: str, force: bool = False) -> UnloadValidationResult:
        """
        Validate if a component can be safely unloaded.
        
        Args:
            component_name: Name of the component to validate
            force: If True, skip dependency checks
            
        Returns:
            UnloadValidationResult: Validation result with details
        """
        with self._lock:
            warnings = []
            errors = []
            blocking_dependencies = []
            
            try:
                # Check if component exists
                component_state = self.state_tracker.get_component_state(component_name)
                if not component_state:
                    errors.append(f"Component '{component_name}' not found")
                    return UnloadValidationResult(False, errors=errors)
                
                # Check if component is already unloaded
                if component_state.status == ComponentStatus.UNLOADED:
                    warnings.append("Component is already unloaded")
                    return UnloadValidationResult(True, warnings=warnings)
                
                # Check for dependent components (unless forced)
                if not force:
                    component_modules = self.module_cache.get_component_modules(component_name)
                    for module_name in component_modules:
                        dependents = self.module_cache.get_module_dependents(module_name)
                        for dependent in dependents:
                            dependent_info = self.module_cache.get_module_info(dependent)
                            if (dependent_info and dependent_info.component_name and 
                                dependent_info.component_name != component_name):
                                blocking_dependencies.append(dependent_info.component_name)
                
                # Check for active operations
                if component_state.status in [ComponentStatus.LOADING, ComponentStatus.RELOADING, ComponentStatus.UNLOADING]:
                    errors.append(f"Component is currently {component_state.status.value}")
                    return UnloadValidationResult(False, errors=errors)
                
                # Memory usage warnings
                component_modules = self.module_cache.get_component_modules(component_name)
                if len(component_modules) > 10:
                    warnings.append(f"Component has {len(component_modules)} modules - unload may take time")
                
                can_unload = len(errors) == 0 and (force or len(blocking_dependencies) == 0)
                
                return UnloadValidationResult(
                    can_unload=can_unload,
                    blocking_dependencies=blocking_dependencies,
                    warnings=warnings,
                    errors=errors
                )
                
            except Exception as e:
                errors.append(f"Validation failed: {str(e)}")
                return UnloadValidationResult(False, errors=errors)
    
    def create_unload_snapshot(self, component_name: str) -> UnloadSnapshot:
        """
        Create a snapshot of the component state before unloading.
        
        Args:
            component_name: Name of the component
            
        Returns:
            UnloadSnapshot: Snapshot for rollback purposes
        """
        with self._lock:
            snapshot = UnloadSnapshot(component_name)
            
            try:
                # Backup component state
                component_state = self.state_tracker.get_component_state(component_name)
                if component_state:
                    snapshot.component_state = component_state
                
                # Backup modules
                component_modules = self.module_cache.get_component_modules(component_name)
                for module_name in component_modules:
                    if module_name in sys.modules:
                        module = sys.modules[module_name]
                        snapshot.add_module_backup(module_name, module)
                        # Also backup in sys.modules
                        snapshot.sys_modules_backup[module_name] = module
                
                # Backup cache state
                for module_name in component_modules:
                    module_info = self.module_cache.get_module_info(module_name)
                    if module_info:
                        snapshot.cache_state[module_name] = {
                            'file_path': module_info.file_path,
                            'load_time': module_info.load_time,
                            'access_count': module_info.access_count,
                            'dependencies': list(module_info.dependencies),
                            'dependents': list(module_info.dependents)
                        }
                
                # Record memory usage
                snapshot.memory_usage_before = len(gc.get_objects())
                
                # Store snapshot
                self._unload_snapshots[component_name] = snapshot
                
                return snapshot
                
            except Exception as e:
                print(f"Failed to create unload snapshot for {component_name}: {e}")
                return snapshot
    
    def unload_component(self, component_name: str, force: bool = False, 
                        create_snapshot: bool = True) -> ReloadResult:
        """
        Completely unload a component with comprehensive cleanup.
        
        Args:
            component_name: Name of the component to unload
            force: If True, ignore dependency checks
            create_snapshot: If True, create snapshot for rollback
            
        Returns:
            ReloadResult: Result of the unload operation
        """
        with self._lock:
            start_time = time.time()
            self._unload_stats['total_unloads'] += 1
            
            # Get initial state
            component_state = self.state_tracker.get_component_state(component_name)
            previous_status = component_state.status if component_state else ComponentStatus.UNKNOWN
            
            try:
                # Validate unload
                validation = self.validate_unload(component_name, force)
                if not validation.can_unload:
                    self._unload_stats['failed_unloads'] += 1
                    return ReloadResult(
                        component_name=component_name,
                        operation=OperationType.UNLOAD,
                        success=False,
                        status=ComponentStatus.FAILED,
                        previous_status=previous_status,
                        duration=time.time() - start_time,
                        error_message=f"Validation failed: {'; '.join(validation.errors)}",
                        warnings=validation.warnings
                    )
                
                # Update status
                if component_state:
                    self.state_tracker.update_component_status(component_name, ComponentStatus.UNLOADING)
                
                # Create snapshot if requested
                snapshot = None
                if create_snapshot:
                    snapshot = self.create_unload_snapshot(component_name)
                
                # Start memory tracking
                self.memory_tracker.start_tracking()
                
                # Perform unload steps
                unload_result = self._perform_unload_steps(component_name)
                
                # Stop memory tracking
                memory_stats = self.memory_tracker.stop_tracking()
                
                duration = time.time() - start_time
                
                if unload_result['success']:
                    # Update statistics
                    self._unload_stats['successful_unloads'] += 1
                    self._unload_stats['modules_cleaned'] += unload_result.get('modules_cleaned', 0)
                    self._unload_stats['memory_freed_bytes'] += memory_stats.get('objects_freed', 0)
                    
                    # Update component state
                    if component_state:
                        self.state_tracker.update_component_status(component_name, ComponentStatus.UNLOADED)
                    
                    # Store unload history
                    result = ReloadResult(
                        component_name=component_name,
                        operation=OperationType.UNLOAD,
                        success=True,
                        status=ComponentStatus.UNLOADED,
                        previous_status=previous_status,
                        duration=duration,
                        warnings=validation.warnings + unload_result.get('warnings', []),
                        rollback_available=snapshot is not None
                    )
                    
                    self._store_unload_history(component_name, result)
                    return result
                
                else:
                    # Unload failed
                    self._unload_stats['failed_unloads'] += 1
                    
                    # Attempt rollback if snapshot exists
                    if snapshot and snapshot.can_rollback():
                        rollback_success = self.rollback_unload(component_name)
                        if rollback_success:
                            self._unload_stats['rollbacks_performed'] += 1
                    
                    result = ReloadResult(
                        component_name=component_name,
                        operation=OperationType.UNLOAD,
                        success=False,
                        status=ComponentStatus.FAILED,
                        previous_status=previous_status,
                        duration=duration,
                        error_message=unload_result.get('error', 'Unknown unload error'),
                        warnings=validation.warnings + unload_result.get('warnings', [])
                    )
                    
                    self._store_unload_history(component_name, result)
                    return result
                
            except Exception as e:
                # Handle unexpected errors
                self._unload_stats['failed_unloads'] += 1
                
                error_report = self.error_handler.handle_component_error(
                    component_name, 'unload', e
                )
                
                if component_state:
                    self.state_tracker.update_component_status(
                        component_name, ComponentStatus.FAILED, str(e)
                    )
                
                return ReloadResult(
                    component_name=component_name,
                    operation=OperationType.UNLOAD,
                    success=False,
                    status=ComponentStatus.FAILED,
                    previous_status=previous_status,
                    duration=time.time() - start_time,
                    error_message=str(e)
                )
    
    def rollback_unload(self, component_name: str) -> bool:
        """
        Rollback a component unload operation.
        
        Args:
            component_name: Name of the component to rollback
            
        Returns:
            bool: True if rollback was successful
        """
        with self._lock:
            try:
                snapshot = self._unload_snapshots.get(component_name)
                if not snapshot or not snapshot.can_rollback():
                    return False
                
                # Restore sys.modules
                for module_name, module in snapshot.sys_modules_backup.items():
                    sys.modules[module_name] = module
                
                # Restore module cache
                for module_name, module_data in snapshot.modules.items():
                    module = module_data['module']
                    self.module_cache.add_module(
                        module_name, module, component_name, module_data.get('file_path')
                    )
                
                # Restore component state
                if snapshot.component_state:
                    self.state_tracker.track_component(
                        component_name, snapshot.component_state.metadata
                    )
                    self.state_tracker.update_component_status(
                        component_name, ComponentStatus.LOADED
                    )
                
                return True
                
            except Exception as e:
                print(f"Failed to rollback unload for {component_name}: {e}")
                return False
    
    def force_memory_cleanup(self) -> Dict[str, Any]:
        """
        Force comprehensive memory cleanup.
        
        Returns:
            Dictionary with cleanup statistics
        """
        try:
            # Clear weak references
            gc.collect()
            
            # Clear import caches
            importlib.invalidate_caches()
            
            # Force multiple garbage collection cycles
            collected_total = 0
            for _ in range(3):
                collected = gc.collect()
                collected_total += collected
                if collected == 0:
                    break
            
            # Get final statistics
            final_objects = len(gc.get_objects())
            
            return {
                'objects_collected': collected_total,
                'final_object_count': final_objects,
                'gc_stats': gc.get_stats() if hasattr(gc, 'get_stats') else None,
                'success': True
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_unload_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive unload statistics.
        
        Returns:
            Dictionary with unload statistics
        """
        with self._lock:
            return {
                'operations': self._unload_stats.copy(),
                'snapshots_available': len(self._unload_snapshots),
                'components_with_history': len(self._unload_history),
                'memory_stats': self.memory_tracker.get_memory_stats()
            }
    
    def clear_unload_history(self, component_name: Optional[str] = None):
        """
        Clear unload history for a component or all components.
        
        Args:
            component_name: Component to clear history for, or None for all
        """
        with self._lock:
            if component_name:
                self._unload_history.pop(component_name, None)
                self._unload_snapshots.pop(component_name, None)
            else:
                self._unload_history.clear()
                self._unload_snapshots.clear()
    
    def _perform_unload_steps(self, component_name: str) -> Dict[str, Any]:
        """Internal method to perform the actual unload steps."""
        result = {
            'success': False,
            'modules_cleaned': 0,
            'warnings': [],
            'error': None
        }
        
        try:
            # Step 1: Get component modules
            component_modules = list(self.module_cache.get_component_modules(component_name))
            if not component_modules:
                result['success'] = True
                result['warnings'].append("No modules to unload")
                return result
            
            # Step 2: Clean up sys.modules
            cleaned_modules = self.reference_cleanup.cleanup_sys_modules(component_modules)
            result['modules_cleaned'] = len(cleaned_modules)
            
            # Step 3: Clean up importlib cache
            cache_cleaned = self.reference_cleanup.cleanup_importlib_cache(component_modules)
            if not cache_cleaned:
                result['warnings'].append("Failed to clean importlib cache")
            
            # Step 4: Remove from module cache
            removed_modules = self.module_cache.remove_component_modules(component_name)
            
            # Step 5: Clean up component state
            state_cleaned = self.state_tracker.cleanup_component_state(component_name)
            if not state_cleaned:
                result['warnings'].append("Failed to clean component state")
            
            # Step 6: Force garbage collection
            gc_stats = self.force_memory_cleanup()
            if not gc_stats.get('success'):
                result['warnings'].append("Memory cleanup had issues")
            
            # Check if all modules were cleaned
            if len(cleaned_modules) == len(component_modules):
                result['success'] = True
            else:
                result['error'] = f"Only {len(cleaned_modules)}/{len(component_modules)} modules cleaned"
            
            return result
            
        except Exception as e:
            result['error'] = str(e)
            return result
    
    def _store_unload_history(self, component_name: str, result: ReloadResult):
        """Store unload result in history."""
        if component_name not in self._unload_history:
            self._unload_history[component_name] = []
        
        self._unload_history[component_name].append(result)
        
        # Keep only last 10 results per component
        if len(self._unload_history[component_name]) > 10:
            self._unload_history[component_name] = self._unload_history[component_name][-10:]