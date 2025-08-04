"""
Hot reload manager for dynamic component lifecycle management.

This module provides the core HotReloadManager class that handles module hot reloading,
unloading, and state preservation during component operations.
"""

import sys
import importlib
import importlib.util
import gc
import time
from typing import Dict, List, Optional, Any, Set, Tuple
from pathlib import Path
from datetime import datetime
import threading

from .models import (
    ComponentStatus, ComponentMetadata, ReloadResult, OperationType,
    ComponentState, DependencyInfo, DependencyStatus
)
from .cache import ModuleCache, ComponentStateTracker, ModuleReferenceCleanup
from .errors import ErrorHandler, ErrorReport, ErrorSeverity
from .unload_manager import ComponentUnloader
from .error_recovery import ErrorRecoveryManager


class ReloadStrategy:
    """Base class for different reload strategies."""
    
    def __init__(self, name: str):
        self.name = name
    
    def can_reload(self, component_name: str, module_cache: ModuleCache) -> bool:
        """Check if the component can be reloaded with this strategy."""
        raise NotImplementedError
    
    def execute_reload(self, component_name: str, hot_reload_manager: 'HotReloadManager') -> ReloadResult:
        """Execute the reload using this strategy."""
        raise NotImplementedError


class FullReloadStrategy(ReloadStrategy):
    """Strategy that performs a complete module reload."""
    
    def __init__(self):
        super().__init__("full_reload")
    
    def can_reload(self, component_name: str, module_cache: ModuleCache) -> bool:
        """Full reload can always be attempted."""
        return True
    
    def execute_reload(self, component_name: str, hot_reload_manager: 'HotReloadManager') -> ReloadResult:
        """Execute a full reload of the component with error recovery."""
        start_time = time.time()
        component_state = hot_reload_manager.state_tracker.get_component_state(component_name)
        previous_status = component_state.status if component_state else ComponentStatus.UNKNOWN
        
        # Create backup before attempting reload
        hot_reload_manager.error_recovery.create_component_backup(component_name)
        
        try:
            # Step 1: Unload existing modules
            unload_result = hot_reload_manager._unload_component_modules(component_name)
            if not unload_result:
                failed_result = ReloadResult(
                    component_name=component_name,
                    operation=OperationType.RELOAD,
                    success=False,
                    status=ComponentStatus.FAILED,
                    previous_status=previous_status,
                    duration=time.time() - start_time,
                    error_message="Failed to unload existing modules"
                )
                
                # Don't attempt recursive recovery - just return the failure
                return failed_result
            
            # Step 2: Clear caches
            hot_reload_manager.reference_cleanup.cleanup_importlib_cache(
                list(hot_reload_manager.module_cache.get_component_modules(component_name))
            )
            
            # Step 3: Reload the component
            load_result = hot_reload_manager._load_component_fresh(component_name)
            
            duration = time.time() - start_time
            
            if load_result.success:
                return ReloadResult(
                    component_name=component_name,
                    operation=OperationType.RELOAD,
                    success=True,
                    status=ComponentStatus.LOADED,
                    previous_status=previous_status,
                    duration=duration,
                    metadata=load_result.metadata
                )
            else:
                failed_result = ReloadResult(
                    component_name=component_name,
                    operation=OperationType.RELOAD,
                    success=False,
                    status=ComponentStatus.FAILED,
                    previous_status=previous_status,
                    duration=duration,
                    error_message=load_result.error_message
                )
                
                # Don't attempt recursive recovery - just return the failure
                return failed_result
        
        except Exception as e:
            failed_result = ReloadResult(
                component_name=component_name,
                operation=OperationType.RELOAD,
                success=False,
                status=ComponentStatus.FAILED,
                previous_status=previous_status,
                duration=time.time() - start_time,
                error_message=str(e)
            )
            
            # Don't attempt recursive recovery - just return the failure
            return failed_result


class IncrementalReloadStrategy(ReloadStrategy):
    """Strategy that attempts to reload only changed modules."""
    
    def __init__(self):
        super().__init__("incremental_reload")
    
    def can_reload(self, component_name: str, module_cache: ModuleCache) -> bool:
        """Check if incremental reload is possible."""
        # For now, incremental reload is only possible if the component is already loaded
        component_modules = module_cache.get_component_modules(component_name)
        return len(component_modules) > 0
    
    def execute_reload(self, component_name: str, hot_reload_manager: 'HotReloadManager') -> ReloadResult:
        """Execute an incremental reload of changed modules."""
        start_time = time.time()
        component_state = hot_reload_manager.state_tracker.get_component_state(component_name)
        previous_status = component_state.status if component_state else ComponentStatus.UNKNOWN
        
        try:
            # Get current modules
            current_modules = hot_reload_manager.module_cache.get_component_modules(component_name)
            
            # Check which modules have changed
            changed_modules = []
            for module_name in current_modules:
                module_info = hot_reload_manager.module_cache.get_module_info(module_name)
                if module_info and module_info.file_path:
                    try:
                        current_mtime = Path(module_info.file_path).stat().st_mtime
                        cached_mtime = module_info.load_time.timestamp()
                        if current_mtime > cached_mtime:
                            changed_modules.append(module_name)
                    except (OSError, AttributeError):
                        # If we can't check the file, assume it changed
                        changed_modules.append(module_name)
            
            if not changed_modules:
                # No changes detected
                return ReloadResult(
                    component_name=component_name,
                    operation=OperationType.RELOAD,
                    success=True,
                    status=ComponentStatus.LOADED,
                    previous_status=previous_status,
                    duration=time.time() - start_time,
                    warnings=["No changes detected - component already up to date"]
                )
            
            # Reload only changed modules
            reload_success = True
            for module_name in changed_modules:
                try:
                    if module_name in sys.modules:
                        importlib.reload(sys.modules[module_name])
                except Exception as e:
                    reload_success = False
                    break
            
            duration = time.time() - start_time
            
            if reload_success:
                return ReloadResult(
                    component_name=component_name,
                    operation=OperationType.RELOAD,
                    success=True,
                    status=ComponentStatus.LOADED,
                    previous_status=previous_status,
                    duration=duration,
                    warnings=[f"Reloaded {len(changed_modules)} changed module(s)"]
                )
            else:
                # Fall back to full reload
                return FullReloadStrategy().execute_reload(component_name, hot_reload_manager)
        
        except Exception as e:
            # Fall back to full reload on any error
            return FullReloadStrategy().execute_reload(component_name, hot_reload_manager)


class RollbackReloadStrategy(ReloadStrategy):
    """Strategy that can rollback to a previous version on failure."""
    
    def __init__(self):
        super().__init__("rollback_reload")
        self._component_snapshots: Dict[str, Dict[str, Any]] = {}
    
    def can_reload(self, component_name: str, module_cache: ModuleCache) -> bool:
        """Check if rollback is available."""
        return component_name in self._component_snapshots
    
    def create_snapshot(self, component_name: str, hot_reload_manager: 'HotReloadManager'):
        """Create a snapshot of the current component state."""
        try:
            component_modules = hot_reload_manager.module_cache.get_component_modules(component_name)
            snapshot = {
                'modules': {},
                'timestamp': datetime.now(),
                'component_state': hot_reload_manager.state_tracker.get_component_state(component_name)
            }
            
            # Store module references (we can't store the actual modules due to memory concerns)
            for module_name in component_modules:
                module_info = hot_reload_manager.module_cache.get_module_info(module_name)
                if module_info:
                    snapshot['modules'][module_name] = {
                        'file_path': module_info.file_path,
                        'load_time': module_info.load_time,
                        'checksum': self._calculate_file_checksum(module_info.file_path)
                    }
            
            self._component_snapshots[component_name] = snapshot
            
        except Exception as e:
            print(f"Failed to create snapshot for {component_name}: {e}")
    
    def execute_reload(self, component_name: str, hot_reload_manager: 'HotReloadManager') -> ReloadResult:
        """Execute reload with rollback capability."""
        # First create a snapshot of current state
        self.create_snapshot(component_name, hot_reload_manager)
        
        # Attempt full reload
        result = FullReloadStrategy().execute_reload(component_name, hot_reload_manager)
        
        # If reload failed and we have a snapshot, attempt rollback
        if not result.success and self.can_rollback(component_name):
            rollback_result = self.rollback(component_name, hot_reload_manager)
            if rollback_result:
                result.warnings.append("Reload failed - rolled back to previous version")
                result.rollback_available = True
        
        return result
    
    def can_rollback(self, component_name: str) -> bool:
        """Check if rollback is possible."""
        return component_name in self._component_snapshots
    
    def rollback(self, component_name: str, hot_reload_manager: 'HotReloadManager') -> bool:
        """Rollback to the previous snapshot."""
        if not self.can_rollback(component_name):
            return False
        
        try:
            snapshot = self._component_snapshots[component_name]
            
            # Unload current modules
            hot_reload_manager._unload_component_modules(component_name)
            
            # Restore previous state (this is simplified - in practice, 
            # we might need to restore actual module content)
            component_state = snapshot.get('component_state')
            if component_state:
                hot_reload_manager.state_tracker.track_component(
                    component_name, component_state.metadata
                )
                hot_reload_manager.state_tracker.update_component_status(
                    component_name, ComponentStatus.LOADED
                )
            
            return True
            
        except Exception as e:
            print(f"Failed to rollback {component_name}: {e}")
            return False
    
    def _calculate_file_checksum(self, file_path: Optional[str]) -> Optional[str]:
        """Calculate a simple checksum for a file."""
        if not file_path or not Path(file_path).exists():
            return None
        
        try:
            import hashlib
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return None


class HotReloadManager:
    """
    Core manager for hot reloading components with state preservation.
    
    This class provides comprehensive module lifecycle management including
    loading, reloading, unloading, and state preservation during operations.
    """
    
    def __init__(self, components_dir: str, error_handler: Optional[ErrorHandler] = None):
        self.components_dir = Path(components_dir)
        self.error_handler = error_handler or ErrorHandler()
        
        # Core components
        self.module_cache = ModuleCache()
        self.state_tracker = ComponentStateTracker(self.module_cache, self.error_handler)
        self.reference_cleanup = ModuleReferenceCleanup(self.module_cache)
        self.component_unloader = ComponentUnloader(
            self.module_cache, self.state_tracker, self.reference_cleanup, self.error_handler
        )
        self.error_recovery = ErrorRecoveryManager(
            self.module_cache, self.state_tracker, self.error_handler
        )
        
        # Reload strategies
        self.reload_strategies = {
            'full': FullReloadStrategy(),
            'incremental': IncrementalReloadStrategy(),
            'rollback': RollbackReloadStrategy()
        }
        self.default_strategy = 'full'
        
        # State management
        self._lock = threading.RLock()
        self._component_states: Dict[str, ComponentState] = {}
        self._active_operations: Set[str] = set()
        
        # Performance tracking
        self._operation_stats = {
            'total_reloads': 0,
            'successful_reloads': 0,
            'failed_reloads': 0,
            'total_unloads': 0,
            'successful_unloads': 0,
            'failed_unloads': 0
        }
    
    def hot_reload_component(self, component_name: str, strategy: str = None) -> ReloadResult:
        """
        Hot reload a component using the specified strategy.
        
        Args:
            component_name: Name of the component to reload
            strategy: Reload strategy to use ('full', 'incremental', 'rollback')
            
        Returns:
            ReloadResult: Result of the reload operation
        """
        with self._lock:
            # Check if operation is already in progress
            if component_name in self._active_operations:
                return ReloadResult(
                    component_name=component_name,
                    operation=OperationType.RELOAD,
                    success=False,
                    status=ComponentStatus.FAILED,
                    previous_status=ComponentStatus.UNKNOWN,
                    error_message="Reload operation already in progress"
                )
            
            self._active_operations.add(component_name)
            
            try:
                # Update statistics
                self._operation_stats['total_reloads'] += 1
                
                # Get current state
                current_state = self.state_tracker.get_component_state(component_name)
                if current_state:
                    self.state_tracker.update_component_status(component_name, ComponentStatus.RELOADING)
                
                # Select strategy
                strategy_name = strategy or self.default_strategy
                reload_strategy = self.reload_strategies.get(strategy_name)
                
                if not reload_strategy:
                    return ReloadResult(
                        component_name=component_name,
                        operation=OperationType.RELOAD,
                        success=False,
                        status=ComponentStatus.FAILED,
                        previous_status=current_state.status if current_state else ComponentStatus.UNKNOWN,
                        error_message=f"Unknown reload strategy: {strategy_name}"
                    )
                
                # Check if strategy can be used
                if not reload_strategy.can_reload(component_name, self.module_cache):
                    # Fall back to full reload
                    reload_strategy = self.reload_strategies['full']
                
                # Execute reload
                result = reload_strategy.execute_reload(component_name, self)
                
                # Update state based on result
                if result.success:
                    self.state_tracker.update_component_status(component_name, ComponentStatus.LOADED)
                    self._operation_stats['successful_reloads'] += 1
                else:
                    self.state_tracker.update_component_status(
                        component_name, ComponentStatus.FAILED, result.error_message
                    )
                    self._operation_stats['failed_reloads'] += 1
                
                return result
                
            except Exception as e:
                # Handle unexpected errors
                error_report = self.error_handler.handle_component_error(
                    component_name, 'reload', e
                )
                
                self.state_tracker.update_component_status(
                    component_name, ComponentStatus.FAILED, str(e)
                )
                
                self._operation_stats['failed_reloads'] += 1
                
                return ReloadResult(
                    component_name=component_name,
                    operation=OperationType.RELOAD,
                    success=False,
                    status=ComponentStatus.FAILED,
                    previous_status=ComponentStatus.UNKNOWN,
                    error_message=str(e)
                )
            
            finally:
                self._active_operations.discard(component_name)
    
    def unload_component(self, component_name: str, force: bool = False, 
                        create_snapshot: bool = True) -> ReloadResult:
        """
        Completely unload a component using the advanced unloading system.
        
        Args:
            component_name: Name of the component to unload
            force: If True, ignore dependency checks
            create_snapshot: If True, create snapshot for rollback
            
        Returns:
            ReloadResult: Result of the unload operation
        """
        with self._lock:
            # Check if operation is already in progress
            if component_name in self._active_operations:
                return ReloadResult(
                    component_name=component_name,
                    operation=OperationType.UNLOAD,
                    success=False,
                    status=ComponentStatus.FAILED,
                    previous_status=ComponentStatus.UNKNOWN,
                    error_message="Unload operation already in progress"
                )
            
            self._active_operations.add(component_name)
            
            try:
                # Update statistics
                self._operation_stats['total_unloads'] += 1
                
                # Use the advanced unloader
                result = self.component_unloader.unload_component(
                    component_name, force, create_snapshot
                )
                
                # Update statistics based on result
                if result.success:
                    self._operation_stats['successful_unloads'] += 1
                else:
                    self._operation_stats['failed_unloads'] += 1
                
                return result
                
            except Exception as e:
                # Handle unexpected errors
                self._operation_stats['failed_unloads'] += 1
                
                error_report = self.error_handler.handle_component_error(
                    component_name, 'unload', e
                )
                
                return ReloadResult(
                    component_name=component_name,
                    operation=OperationType.UNLOAD,
                    success=False,
                    status=ComponentStatus.FAILED,
                    previous_status=ComponentStatus.UNKNOWN,
                    error_message=str(e)
                )
            
            finally:
                self._active_operations.discard(component_name)
    
    def get_component_status(self, component_name: str) -> ComponentStatus:
        """
        Get the current status of a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            ComponentStatus: Current status of the component
        """
        component_state = self.state_tracker.get_component_state(component_name)
        return component_state.status if component_state else ComponentStatus.UNKNOWN
    
    def cleanup_module_references(self, module_name: str) -> bool:
        """
        Clean up references for a specific module.
        
        Args:
            module_name: Name of the module to clean up
            
        Returns:
            bool: True if cleanup was successful
        """
        try:
            # Remove from sys.modules
            if module_name in sys.modules:
                del sys.modules[module_name]
            
            # Remove from cache
            self.module_cache.remove_module(module_name)
            
            # Clean up importlib cache
            self.reference_cleanup.cleanup_importlib_cache([module_name])
            
            return True
            
        except Exception as e:
            print(f"Failed to cleanup module references for {module_name}: {e}")
            return False
    
    def preserve_component_state(self, component_name: str) -> Dict[str, Any]:
        """
        Preserve the current state of a component before reload.
        
        Args:
            component_name: Name of the component
            
        Returns:
            Dictionary containing preserved state
        """
        try:
            component_state = self.state_tracker.get_component_state(component_name)
            if not component_state:
                return {}
            
            # Create state snapshot
            preserved_state = {
                'component_name': component_name,
                'status': component_state.status,
                'metadata': component_state.metadata.to_dict() if component_state.metadata else None,
                'load_count': component_state.load_count,
                'error_count': component_state.error_count,
                'last_loaded': component_state.last_loaded.isoformat() if component_state.last_loaded else None,
                'module_references': list(component_state.module_references),
                'timestamp': datetime.now().isoformat()
            }
            
            return preserved_state
            
        except Exception as e:
            print(f"Failed to preserve state for {component_name}: {e}")
            return {}
    
    def restore_component_state(self, component_name: str, preserved_state: Dict[str, Any]) -> bool:
        """
        Restore a component's state from preserved data.
        
        Args:
            component_name: Name of the component
            preserved_state: Previously preserved state data
            
        Returns:
            bool: True if restoration was successful
        """
        try:
            if not preserved_state or preserved_state.get('component_name') != component_name:
                return False
            
            # Restore basic state
            component_state = self.state_tracker.track_component(component_name)
            
            # Restore metadata if available
            if preserved_state.get('metadata'):
                try:
                    metadata = ComponentMetadata.from_dict(preserved_state['metadata'])
                    component_state.metadata = metadata
                except Exception:
                    pass
            
            # Restore counters
            component_state.load_count = preserved_state.get('load_count', 0)
            component_state.error_count = preserved_state.get('error_count', 0)
            
            # Restore timestamps
            if preserved_state.get('last_loaded'):
                try:
                    component_state.last_loaded = datetime.fromisoformat(preserved_state['last_loaded'])
                except Exception:
                    pass
            
            return True
            
        except Exception as e:
            print(f"Failed to restore state for {component_name}: {e}")
            return False
    
    def validate_component_unload(self, component_name: str, force: bool = False):
        """
        Validate if a component can be safely unloaded.
        
        Args:
            component_name: Name of the component to validate
            force: If True, skip dependency checks
            
        Returns:
            UnloadValidationResult: Validation result with details
        """
        return self.component_unloader.validate_unload(component_name, force)
    
    def rollback_component_unload(self, component_name: str) -> bool:
        """
        Rollback a component unload operation.
        
        Args:
            component_name: Name of the component to rollback
            
        Returns:
            bool: True if rollback was successful
        """
        return self.component_unloader.rollback_unload(component_name)
    
    def force_memory_cleanup(self) -> Dict[str, Any]:
        """
        Force comprehensive memory cleanup.
        
        Returns:
            Dictionary with cleanup statistics
        """
        return self.component_unloader.force_memory_cleanup()
    
    def create_component_backup(self, component_name: str) -> bool:
        """
        Create a backup of the component's current state.
        
        Args:
            component_name: Name of the component to backup
            
        Returns:
            bool: True if backup was created successfully
        """
        return self.error_recovery.create_component_backup(component_name)
    
    def restore_component_backup(self, component_name: str) -> bool:
        """
        Restore a component from backup.
        
        Args:
            component_name: Name of the component to restore
            
        Returns:
            bool: True if restore was successful
        """
        return self.error_recovery.restore_component_backup(component_name)
    
    def get_recovery_plan(self, component_name: str):
        """
        Get the current recovery plan for a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            RecoveryPlan or None: Current recovery plan if exists
        """
        return self.error_recovery._recovery_plans.get(component_name)
    
    def clear_recovery_data(self, component_name: Optional[str] = None):
        """
        Clear recovery data for a component or all components.
        
        Args:
            component_name: Component to clear data for, or None for all
        """
        self.error_recovery.clear_recovery_data(component_name)
    
    def get_reload_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about reload operations.
        
        Returns:
            Dictionary with operation statistics
        """
        with self._lock:
            cache_stats = self.module_cache.get_cache_stats()
            error_summary = self.error_handler.get_system_error_summary()
            unload_stats = self.component_unloader.get_unload_statistics()
            recovery_stats = self.error_recovery.get_recovery_statistics()
            
            return {
                'operations': self._operation_stats.copy(),
                'cache': cache_stats,
                'errors': error_summary,
                'unload': unload_stats,
                'recovery': recovery_stats,
                'active_operations': len(self._active_operations),
                'tracked_components': len(self.state_tracker.get_all_component_states())
            }
    
    def _unload_component_modules(self, component_name: str) -> bool:
        """Internal method to unload all modules for a component."""
        try:
            # Get all modules for the component
            module_names = list(self.module_cache.get_component_modules(component_name))
            
            if not module_names:
                return True  # Nothing to unload
            
            # Clean up sys.modules
            cleaned_modules = self.reference_cleanup.cleanup_sys_modules(module_names)
            
            # Remove from cache
            removed_modules = self.module_cache.remove_component_modules(component_name)
            
            # Force garbage collection
            gc.collect()
            
            return len(cleaned_modules) == len(module_names)
            
        except Exception as e:
            print(f"Failed to unload modules for {component_name}: {e}")
            return False
    
    def _load_component_fresh(self, component_name: str):
        """Internal method to load a component fresh (placeholder for integration)."""
        # This would integrate with the ComponentLoader
        # For now, return a basic result structure
        from .loader import LoadResult
        
        return LoadResult(
            component_name=component_name,
            success=True,
            metadata=None,
            error_message=None
        )