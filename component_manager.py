import importlib
import importlib.util
import ast
import json
import os
import pkgutil
import sys
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from log_writer import logger

from component_base import BaseComponent, PlaceholderComponent
from hot_reload.hot_reload_manager import HotReloadManager
from hot_reload.dependency import DependencyManager
from hot_reload.loader import ComponentLoader
from hot_reload.models import ComponentStatus, ComponentMetadata, ReloadResult, InstallationResult
from component_load_guard import start_loading_component, finish_loading_component, can_load_component, is_component_loading
from version_checker import VersionChecker
import config


class ComponentManager:
    def __init__(self, components_dir="components", config_path="components.json"):
        self.components_dir = components_dir
        self.config_path = config_path
        self.available = {}
        self.enabled = []
        
        # Initialize hot reload system
        self.hot_reload_manager = HotReloadManager(components_dir)
        self.dependency_manager = DependencyManager()
        self.component_loader = ComponentLoader(components_dir)
        
        # Component status tracking
        self._component_statuses: Dict[str, ComponentStatus] = {}
        self._component_metadata: Dict[str, ComponentMetadata] = {}
        
        self.load_config()
        self.discover_components()

    @staticmethod
    def missing_requirements(requirements: list[str]) -> list[str]:
        """Return a list of packages that are not installed."""
        missing = []
        for req in requirements:
            try:
                importlib.import_module(req)
            except ImportError:
                missing.append(req)
        return missing

    @staticmethod
    def _read_requirements_file(req_path: str) -> list[str]:
        """Return package names listed in a requirements.txt file."""
        requirements: list[str] = []
        if os.path.isfile(req_path):
            try:
                with open(req_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            requirements.append(line)
            except Exception as e:
                logger(f"Failed to read requirements from {req_path}: {e}")
        return requirements

    @staticmethod
    def _extract_metadata(path: str, req_file: Optional[str] = None) -> dict:
        """Parse component file for class metadata without importing."""
        meta: dict = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
        except Exception as e:
            logger(f"Failed to parse {path} for metadata: {e}")
            return meta

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "BaseComponent":
                        for stmt in node.body:
                            if (
                                isinstance(stmt, ast.Assign)
                                and len(stmt.targets) == 1
                                and isinstance(stmt.targets[0], ast.Name)
                            ):
                                key = stmt.targets[0].id
                                if key in {"name", "description", "version", "author_name", "author_link"} and isinstance(
                                    stmt.value, (ast.Str, ast.Constant)
                                ):
                                    meta[key] = (
                                        stmt.value.s
                                        if hasattr(stmt.value, "s")
                                        else stmt.value.value
                                    )
                                elif key == "requirements" and isinstance(
                                    stmt.value, (ast.List, ast.Tuple)
                                ):
                                    reqs = []
                                    for elt in stmt.value.elts:
                                        if isinstance(elt, (ast.Str, ast.Constant)):
                                            reqs.append(
                                                elt.s if hasattr(elt, "s") else elt.value
                                            )
                                    meta[key] = reqs
                                elif key == "supported_framework_versions":
                                    # Handle supported_framework_versions which can be various types
                                    meta[key] = ComponentManager._extract_supported_versions(stmt.value)
                        break

        # Append requirements.txt content if provided
        if req_file:
            meta.setdefault("requirements", [])
            meta["requirements"] += ComponentManager._read_requirements_file(req_file)

        return meta

    @staticmethod
    def _extract_supported_versions(ast_node):
        """Extract supported_framework_versions from AST node."""
        try:
            if isinstance(ast_node, ast.Constant):
                # Handle None or string constants
                return ast_node.value
            elif isinstance(ast_node, (ast.Str,)):
                # Handle string literals (older Python versions)
                return ast_node.s
            elif isinstance(ast_node, (ast.List, ast.Tuple)):
                # Handle list/tuple of version specs
                versions = []
                for elt in ast_node.elts:
                    if isinstance(elt, (ast.Str, ast.Constant)):
                        versions.append(elt.s if hasattr(elt, "s") else elt.value)
                    elif isinstance(elt, ast.Dict):
                        # Handle dict elements like {"min_version": "1.0.0", "max_version": "2.0.0"}
                        version_dict = {}
                        for k, v in zip(elt.keys, elt.values):
                            if isinstance(k, (ast.Str, ast.Constant)) and isinstance(v, (ast.Str, ast.Constant)):
                                key = k.s if hasattr(k, "s") else k.value
                                value = v.s if hasattr(v, "s") else v.value
                                version_dict[key] = value
                        versions.append(version_dict)
                return versions
            elif isinstance(ast_node, ast.Dict):
                # Handle single dict like {"min_version": "1.0.0", "max_version": "2.0.0"}
                version_dict = {}
                for k, v in zip(ast_node.keys, ast_node.values):
                    if isinstance(k, (ast.Str, ast.Constant)) and isinstance(v, (ast.Str, ast.Constant)):
                        key = k.s if hasattr(k, "s") else k.value
                        value = v.s if hasattr(v, "s") else v.value
                        version_dict[key] = value
                return version_dict
            else:
                return None
        except Exception as e:
            logger(f"Error extracting supported versions: {e}")
            return None

    def _check_version_compatibility(self, component_name: str, component_metadata: dict) -> bool:
        """
        Check if a component is compatible with the current framework version.
        
        Args:
            component_name: Name of the component
            component_metadata: Component metadata dictionary
            
        Returns:
            bool: True if compatible or if force loading is enabled
        """
        # Check if force loading is enabled
        force_load = getattr(config, 'FORCE_LOAD_UNSUPPORTED_COMPONENT', 'false').lower() == 'true'
        if force_load:
            logger(f"Force loading enabled, skipping version check for {component_name}")
            return True
        
        # Get current framework version
        framework_version = getattr(config, 'VERSION_NUMBER', '1.0.0')
        
        # Get component's supported versions
        supported_versions = component_metadata.get('supported_framework_versions')
        
        # Check compatibility
        is_compatible = VersionChecker.is_version_supported(supported_versions, framework_version)
        
        if not is_compatible:
            compatibility_msg = VersionChecker.get_version_compatibility_message(
                component_name, supported_versions, framework_version
            )
            logger(f"Version incompatibility: {compatibility_msg}")
        
        return is_compatible

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.enabled = data.get("enabled", [])
        else:
            self.enabled = []

    def save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"enabled": self.enabled}, f, indent=2)

    def discover_components(self):
        """
        Discover components with hot reload support.
        This method now integrates with the hot reload system for better component tracking.
        """
        # Add recursion protection
        if hasattr(self, '_discovery_in_progress') and self._discovery_in_progress:
            logger("Component discovery already in progress, skipping...")
            return
            
        try:
            self._discovery_in_progress = True
            self.available = {}
            if not os.path.isdir(self.components_dir):
                return
            
            # Get list of available components from the component loader
            available_components = self.component_loader.list_available_components()
            
            package_name = self.components_dir.replace(os.sep, ".")
            
            # Process each available component
            for component_name in available_components:
                # Use global guard to prevent infinite loading loops
                if not can_load_component(component_name):
                    logger(f"Component {component_name} is already being loaded or in cooldown, skipping...")
                    continue
                
                if not start_loading_component(component_name):
                    logger(f"Failed to start loading component {component_name}, skipping...")
                    continue
                
                try:
                    # Try to load component using the hot reload system
                    component_path = os.path.join(self.components_dir, component_name)
                    
                    # Check if it's a package or single file
                    if os.path.isdir(component_path):
                        # Package component
                        main_files = ['__init__.py', 'main.py']
                        main_file = None
                        for filename in main_files:
                            candidate = os.path.join(component_path, filename)
                            if os.path.exists(candidate):
                                main_file = candidate
                                break
                        
                        if not main_file:
                            finish_loading_component(component_name, False)
                            continue
                            
                        load_path = component_path
                    else:
                        # Single file component
                        load_path = f"{component_path}.py"
                        if not os.path.exists(load_path):
                            finish_loading_component(component_name, False)
                            continue
                    
                    # Extract metadata first
                    metadata = self.component_loader.extract_component_metadata(load_path)
                    if metadata:
                        self._component_metadata[component_name] = metadata
                        self.track_component_status(component_name, ComponentStatus.LOADING, metadata)
                    
                    # Try to load the component
                    load_result = self.component_loader.load_component_from_path(load_path)
                    
                    if load_result.success and load_result.module:
                        # Successfully loaded - try to get component instance
                        if hasattr(load_result.module, 'get_component'):
                            try:
                                comp = load_result.module.get_component()
                                if isinstance(comp, BaseComponent):
                                    # Extract component metadata for version checking
                                    comp_metadata = {
                                        'name': getattr(comp, 'name', component_name),
                                        'description': getattr(comp, 'description', ''),
                                        'version': getattr(comp, 'version', '1.0.0'),
                                        'supported_framework_versions': getattr(comp, 'supported_framework_versions', None),
                                        'author_name': getattr(comp, 'author_name', ''),
                                        'author_link': getattr(comp, 'author_link', ''),
                                        'requirements': getattr(comp, 'requirements', [])
                                    }
                                    
                                    # Check version compatibility
                                    if self._check_version_compatibility(comp.name, comp_metadata):
                                        self.available[comp.name] = comp
                                        self.track_component_status(comp.name, ComponentStatus.LOADED, load_result.metadata)
                                        logger(f"Successfully loaded component: {comp.name}")
                                        finish_loading_component(component_name, True)
                                    else:
                                        # Create placeholder for incompatible component
                                        logger(f"Component {comp.name} is not compatible with current framework version")
                                        placeholder = PlaceholderComponent(
                                            comp_metadata['name'],
                                            f"[Version Incompatible] {comp_metadata['description']}",
                                            comp_metadata['requirements']
                                        )
                                        self.available[comp.name] = placeholder
                                        self.track_component_status(comp.name, ComponentStatus.FAILED)
                                        finish_loading_component(component_name, False)
                                else:
                                    logger(f"Component {component_name} does not inherit from BaseComponent")
                                    self.track_component_status(component_name, ComponentStatus.FAILED)
                                    finish_loading_component(component_name, False)
                            except Exception as e:
                                logger(f"Failed to get component instance from {component_name}: {e}")
                                self.track_component_status(component_name, ComponentStatus.FAILED)
                                finish_loading_component(component_name, False)
                        else:
                            logger(f"Module {component_name} does not have get_component function")
                            self.track_component_status(component_name, ComponentStatus.FAILED)
                            finish_loading_component(component_name, False)
                    else:
                        # Failed to load - create placeholder component
                        logger(f"Failed to load component {component_name}: {load_result.error_message}")
                        
                        # Try to extract metadata for placeholder
                        if not metadata:
                            try:
                                meta_dict = self._extract_metadata(load_path)
                                reqs = meta_dict.get("requirements", [])
                                
                                # Check for requirements.txt
                                if os.path.isdir(load_path):
                                    req_path = os.path.join(load_path, "requirements.txt")
                                else:
                                    req_path = os.path.join(os.path.dirname(load_path), "requirements.txt")
                                
                                if os.path.exists(req_path):
                                    reqs.extend(self._read_requirements_file(req_path))
                                
                                comp = PlaceholderComponent(
                                    meta_dict.get("name", component_name),
                                    meta_dict.get("description", ""),
                                    reqs,
                                )
                                self.available[comp.name] = comp
                                self.track_component_status(comp.name, ComponentStatus.FAILED)
                                finish_loading_component(component_name, False)
                            except Exception as e:
                                logger(f"Failed to create placeholder for {component_name}: {e}")
                                self.track_component_status(component_name, ComponentStatus.FAILED)
                                finish_loading_component(component_name, False)
                        else:
                            finish_loading_component(component_name, False)
                    
                except Exception as e:
                    logger(f"Error processing component {component_name}: {e}")
                    self.track_component_status(component_name, ComponentStatus.FAILED)
                    finish_loading_component(component_name, False)
        
            # Also discover using the original method for backward compatibility
            self._discover_components_legacy()
            
            # Set up file watching for dynamic discovery if not already set up
            if not hasattr(self, '_file_watcher_setup'):
                self._setup_dynamic_discovery()
                self._file_watcher_setup = True
        finally:
            self._discovery_in_progress = False
    
    def _discover_components_legacy(self):
        """
        Legacy component discovery method for backward compatibility.
        This handles edge cases that the new hot reload system might miss.
        """
        if not os.path.isdir(self.components_dir):
            return
            
        package_name = self.components_dir.replace(os.sep, ".")
        
        # Discover regular modules and packages first
        for _, name, ispkg in pkgutil.iter_modules([self.components_dir]):
            # Skip if already processed by new system
            if name in self.available or name in self._component_statuses:
                continue
                
            if ispkg:
                module_path = os.path.join(self.components_dir, name, "__init__.py")
                req_path = os.path.join(self.components_dir, name, "requirements.txt")
            else:
                module_path = os.path.join(self.components_dir, f"{name}.py")
                req_path = None
                
            try:
                module = importlib.import_module(f"{package_name}.{name}")
            except Exception as e:
                logger(f"Failed to import module {name}: {e}")
                meta = (
                    self._extract_metadata(module_path, req_path)
                    if os.path.isfile(module_path)
                    else {}
                )
                reqs = meta.get("requirements")
                if reqs is None and req_path:
                    reqs = self._read_requirements_file(req_path)
                comp = PlaceholderComponent(
                    meta.get("name", name),
                    meta.get("description", ""),
                    reqs or [],
                )
                self.available[comp.name] = comp
                self.track_component_status(comp.name, ComponentStatus.FAILED)
                continue

            if hasattr(module, "get_component"):
                try:
                    comp = module.get_component()
                    if isinstance(comp, BaseComponent):
                        self.available[comp.name] = comp
                        self.track_component_status(comp.name, ComponentStatus.LOADED)
                except Exception as e:
                    logger(f"Failed to load component from module {name}: {e}")
                    self.track_component_status(name, ComponentStatus.FAILED)

        # Also support components stored in a directory without __init__.py
        for entry in os.scandir(self.components_dir):
            if entry.is_dir() and not os.path.exists(
                os.path.join(entry.path, "__init__.py")
            ):
                # Skip if already processed
                if entry.name in self.available or entry.name in self._component_statuses:
                    continue
                    
                main_py = os.path.join(entry.path, "main.py")
                if not os.path.isfile(main_py):
                    continue
                spec = importlib.util.spec_from_file_location(
                    f"{package_name}.{entry.name}", main_py
                )
                if not spec or not spec.loader:
                    continue
                module = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(module)
                except Exception as e:
                    logger(f"Failed to import module {entry.name} from main.py: {e}")
                    req_file = os.path.join(entry.path, "requirements.txt")
                    meta = (
                        self._extract_metadata(main_py, req_file)
                        if os.path.isfile(main_py)
                        else {}
                    )
                    reqs = meta.get("requirements")
                    if reqs is None:
                        reqs = self._read_requirements_file(req_file)
                    comp = PlaceholderComponent(
                        meta.get("name", entry.name),
                        meta.get("description", ""),
                        reqs or [],
                    )
                    self.available[comp.name] = comp
                    self.track_component_status(comp.name, ComponentStatus.FAILED)
                    continue

                if hasattr(module, "get_component"):
                    try:
                        comp = module.get_component()
                        if isinstance(comp, BaseComponent):
                            self.available[comp.name] = comp
                            self.track_component_status(comp.name, ComponentStatus.LOADED)
                    except Exception as e:
                        logger(f"Failed to load component from module {entry.name}: {e}")
                        self.track_component_status(entry.name, ComponentStatus.FAILED)

    def get_enabled_components(self):
        return [c for c in self.available.values() if c.name in self.enabled]
    
    # Hot reload methods
    def reload_component(self, component_name: str, strategy: str = None) -> ReloadResult:
        """
        Hot reload a component using the specified strategy.
        
        Args:
            component_name: Name of the component to reload
            strategy: Reload strategy ('full', 'incremental', 'rollback')
            
        Returns:
            ReloadResult: Result of the reload operation
        """
        try:
            # Update component status to reloading
            self._component_statuses[component_name] = ComponentStatus.RELOADING
            
            # Perform hot reload
            result = self.hot_reload_manager.hot_reload_component(component_name, strategy)
            
            # Update status based on result
            if result.success:
                self._component_statuses[component_name] = ComponentStatus.LOADED
                
                # Update available components if reload was successful
                if result.metadata:
                    self._component_metadata[component_name] = result.metadata
                    # Try to get the actual component instance
                    loaded_module = self.component_loader.get_loaded_component(component_name)
                    if loaded_module and hasattr(loaded_module, 'get_component'):
                        try:
                            component_instance = loaded_module.get_component()
                            if isinstance(component_instance, BaseComponent):
                                self.available[component_name] = component_instance
                        except Exception as e:
                            logger(f"Failed to get component instance after reload: {e}")
            else:
                self._component_statuses[component_name] = ComponentStatus.FAILED
            
            logger(f"Component {component_name} reload {'succeeded' if result.success else 'failed'}")
            return result
            
        except Exception as e:
            error_msg = f"Failed to reload component {component_name}: {e}"
            logger(error_msg)
            self._component_statuses[component_name] = ComponentStatus.FAILED
            
            return ReloadResult(
                component_name=component_name,
                operation=result.operation if 'result' in locals() else None,
                success=False,
                status=ComponentStatus.FAILED,
                previous_status=ComponentStatus.UNKNOWN,
                error_message=error_msg
            )
    
    def unload_component(self, component_name: str, force: bool = False) -> ReloadResult:
        """
        Completely unload a component from memory.
        
        Args:
            component_name: Name of the component to unload
            force: If True, ignore dependency checks
            
        Returns:
            ReloadResult: Result of the unload operation
        """
        try:
            # Update component status to unloading
            self._component_statuses[component_name] = ComponentStatus.UNLOADING
            
            # Perform unload
            result = self.hot_reload_manager.unload_component(component_name, force)
            
            # Update status and clean up
            if result.success:
                self._component_statuses[component_name] = ComponentStatus.UNLOADED
                
                # Remove from available components
                if component_name in self.available:
                    del self.available[component_name]
                
                # Remove from enabled list
                if component_name in self.enabled:
                    self.enabled.remove(component_name)
                    self.save_config()
                
                # Clean up metadata
                if component_name in self._component_metadata:
                    del self._component_metadata[component_name]
            else:
                self._component_statuses[component_name] = ComponentStatus.FAILED
            
            logger(f"Component {component_name} unload {'succeeded' if result.success else 'failed'}")
            return result
            
        except Exception as e:
            error_msg = f"Failed to unload component {component_name}: {e}"
            logger(error_msg)
            self._component_statuses[component_name] = ComponentStatus.FAILED
            
            return ReloadResult(
                component_name=component_name,
                operation=result.operation if 'result' in locals() else None,
                success=False,
                status=ComponentStatus.FAILED,
                previous_status=ComponentStatus.UNKNOWN,
                error_message=error_msg
            )
    
    def install_dependencies(self, component_name: str, requirements: List[str] = None) -> InstallationResult:
        """
        Install dependencies for a component.
        
        Args:
            component_name: Name of the component
            requirements: Optional list of requirements to install (uses component metadata if None)
            
        Returns:
            InstallationResult: Result of the installation operation
        """
        try:
            # Get requirements from component metadata if not provided
            if requirements is None:
                if component_name in self._component_metadata:
                    requirements = self._component_metadata[component_name].requirements
                elif component_name in self.available:
                    component = self.available[component_name]
                    requirements = getattr(component, 'requirements', [])
                else:
                    return InstallationResult(
                        component_name=component_name,
                        dependencies=[],
                        success=False,
                        error_message="Component not found or no requirements specified"
                    )
            
            if not requirements:
                return InstallationResult(
                    component_name=component_name,
                    dependencies=[],
                    success=True,
                    error_message="No dependencies to install"
                )
            
            # Check current dependency status
            dependency_info = self.dependency_manager.check_dependencies(requirements)
            
            # Get missing dependencies
            missing_deps = [dep.name for dep in dependency_info if not dep.is_satisfied()]
            
            if not missing_deps:
                return InstallationResult(
                    component_name=component_name,
                    dependencies=dependency_info,
                    success=True,
                    installed_packages=[],
                    error_message="All dependencies already satisfied"
                )
            
            # Install missing dependencies
            install_result = self.dependency_manager.pip_installer.install_packages(
                missing_deps, component_name
            )
            
            # Update dependency info after installation
            if install_result.success:
                updated_dependency_info = self.dependency_manager.check_dependencies(requirements)
                install_result.dependencies = updated_dependency_info
            
            logger(f"Dependency installation for {component_name}: {'succeeded' if install_result.success else 'failed'}")
            return install_result
            
        except Exception as e:
            error_msg = f"Failed to install dependencies for {component_name}: {e}"
            logger(error_msg)
            
            return InstallationResult(
                component_name=component_name,
                dependencies=[],
                success=False,
                error_message=error_msg
            )
    
    def get_component_status(self, component_name: str) -> ComponentStatus:
        """
        Get the current status of a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            ComponentStatus: Current status of the component
        """
        # First check hot reload manager status
        hot_reload_status = self.hot_reload_manager.get_component_status(component_name)
        if hot_reload_status != ComponentStatus.UNKNOWN:
            self._component_statuses[component_name] = hot_reload_status
            return hot_reload_status
        
        # Fall back to local status tracking
        return self._component_statuses.get(component_name, ComponentStatus.UNKNOWN)
    
    def get_component_metadata(self, component_name: str) -> Optional[ComponentMetadata]:
        """
        Get metadata for a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            ComponentMetadata: Component metadata or None if not found
        """
        # Check local cache first
        if component_name in self._component_metadata:
            return self._component_metadata[component_name]
        
        # Try to get from component loader
        return self.component_loader.get_component_metadata(component_name)
    
    def track_component_status(self, component_name: str, status: ComponentStatus, metadata: ComponentMetadata = None):
        """
        Track the status of a component.
        
        Args:
            component_name: Name of the component
            status: New status of the component
            metadata: Optional metadata to store
        """
        self._component_statuses[component_name] = status
        
        if metadata:
            self._component_metadata[component_name] = metadata
    
    def get_all_component_statuses(self) -> Dict[str, ComponentStatus]:
        """
        Get status of all tracked components.
        
        Returns:
            Dict[str, ComponentStatus]: Dictionary mapping component names to their statuses
        """
        return self._component_statuses.copy()
    
    def validate_component_unload(self, component_name: str, force: bool = False):
        """
        Validate if a component can be safely unloaded.
        
        Args:
            component_name: Name of the component to validate
            force: If True, skip dependency checks
            
        Returns:
            Validation result with details
        """
        return self.hot_reload_manager.validate_component_unload(component_name, force)
    
    def get_component_dependencies(self, component_name: str) -> List[str]:
        """
        Get the dependencies for a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            List[str]: List of dependency requirement strings
        """
        metadata = self.get_component_metadata(component_name)
        if metadata:
            return metadata.requirements
        
        # Fall back to checking the component instance
        if component_name in self.available:
            component = self.available[component_name]
            return getattr(component, 'requirements', [])
        
        return []
    
    def _setup_dynamic_discovery(self):
        """
        Set up dynamic component discovery with file watching.
        This enables real-time detection of component changes.
        
        TEMPORARILY DISABLED to prevent infinite loops.
        """
        #logger("Dynamic component discovery is temporarily disabled to prevent infinite loops")
        return
        
        # Original code commented out to prevent infinite loops
        # try:
        #     from hot_reload.file_watcher import FileWatcher
        #     
        #     # Initialize file watcher if not already done
        #     if not hasattr(self, 'file_watcher'):
        #         self.file_watcher = FileWatcher(self.components_dir)
        #         
        #         # Set up callbacks for component changes
        #         self.file_watcher.add_component_created_callback(self._on_component_created)
        #         self.file_watcher.add_component_modified_callback(self._on_component_modified)
        #         self.file_watcher.add_component_deleted_callback(self._on_component_deleted)
        #         
        #         # Initialize component operation tracking
        #         if not hasattr(self, '_component_operations_in_progress'):
        #             self._component_operations_in_progress = set()
        #         
        #         # Start watching
        #         self.file_watcher.start_watching()
        #         logger("Dynamic component discovery enabled")
        #         
        # except Exception as e:
        #     logger(f"Failed to set up dynamic discovery: {e}")
    
    def _on_component_created(self, component_name: str, metadata: ComponentMetadata):
        """
        Handle component creation event.
        
        Args:
            component_name: Name of the created component
            metadata: Component metadata
        """
        # Use global guard to prevent infinite loading loops
        if not can_load_component(component_name):
            logger(f"Component {component_name} is already being loaded or in cooldown, skipping creation...")
            return
        
        if not start_loading_component(component_name):
            logger(f"Failed to start loading component {component_name} in creation handler, skipping...")
            return
            
        try:
            logger(f"Detected new component: {component_name}")
            
            # Load the new component
            component_path = os.path.join(self.components_dir, component_name)
            if os.path.isdir(component_path):
                load_path = component_path
            else:
                load_path = f"{component_path}.py"
                if not os.path.exists(load_path):
                    finish_loading_component(component_name, False)
                    return
            
            load_result = self.component_loader.load_component_from_path(load_path)
            
            if load_result.success and load_result.module:
                # Try to get component instance
                if hasattr(load_result.module, 'get_component'):
                    try:
                        comp = load_result.module.get_component()
                        if isinstance(comp, BaseComponent):
                            self.available[comp.name] = comp
                            self.track_component_status(comp.name, ComponentStatus.LOADED, load_result.metadata)
                            logger(f"Successfully loaded new component: {comp.name}")
                            finish_loading_component(component_name, True)
                            
                            # Notify about new component (but don't trigger file system events)
                            self._notify_component_change('added', comp.name)
                        else:
                            logger(f"New component {component_name} does not inherit from BaseComponent")
                            self.track_component_status(component_name, ComponentStatus.FAILED)
                            finish_loading_component(component_name, False)
                    except Exception as e:
                        logger(f"Failed to get component instance from new component {component_name}: {e}")
                        self.track_component_status(component_name, ComponentStatus.FAILED)
                        finish_loading_component(component_name, False)
                else:
                    logger(f"New component {component_name} does not have get_component function")
                    self.track_component_status(component_name, ComponentStatus.FAILED)
                    finish_loading_component(component_name, False)
            else:
                logger(f"Failed to load new component {component_name}: {load_result.error_message}")
                self.track_component_status(component_name, ComponentStatus.FAILED)
                finish_loading_component(component_name, False)
                
        except Exception as e:
            logger(f"Error handling component creation for {component_name}: {e}")
            finish_loading_component(component_name, False)
    
    def _on_component_modified(self, component_name: str, metadata: ComponentMetadata):
        """
        Handle component modification event.
        
        Args:
            component_name: Name of the modified component
            metadata: Component metadata
        """
        # Use global guard to prevent infinite loading loops
        if is_component_loading(component_name):
            logger(f"Component {component_name} is already being loaded, skipping modification...")
            return
            
        # For modifications, we allow more frequent operations but still with some protection
        if not can_load_component(component_name):
            logger(f"Component {component_name} is in cooldown, skipping modification...")
            return
            
        try:
            if not hasattr(self, '_reload_in_progress'):
                self._reload_in_progress = set()
            self._reload_in_progress.add(component_name)
            self._component_operations_in_progress.add(component_name)
            
            logger(f"Detected component modification: {component_name}")
            
            # Check if component is currently loaded
            if component_name in self.available:
                # Automatically reload the component
                result = self.reload_component(component_name)
                
                if result.success:
                    logger(f"Successfully reloaded modified component: {component_name}")
                    self._notify_component_change('modified', component_name)
                else:
                    logger(f"Failed to reload modified component {component_name}: {result.error_message}")
            else:
                # Component wasn't loaded before, try to load it now
                # But don't call _on_component_created to avoid recursion
                logger(f"Component {component_name} not currently loaded, attempting to load...")
                
                component_path = os.path.join(self.components_dir, component_name)
                if os.path.isdir(component_path):
                    load_path = component_path
                else:
                    load_path = f"{component_path}.py"
                    if not os.path.exists(load_path):
                        return
                
                load_result = self.component_loader.load_component_from_path(load_path)
                
                if load_result.success and load_result.module:
                    if hasattr(load_result.module, 'get_component'):
                        try:
                            comp = load_result.module.get_component()
                            if isinstance(comp, BaseComponent):
                                self.available[comp.name] = comp
                                self.track_component_status(comp.name, ComponentStatus.LOADED, load_result.metadata)
                                logger(f"Successfully loaded component: {comp.name}")
                                self._notify_component_change('added', comp.name)
                        except Exception as e:
                            logger(f"Failed to get component instance: {e}")
                            self.track_component_status(component_name, ComponentStatus.FAILED)
                
        except Exception as e:
            logger(f"Error handling component modification for {component_name}: {e}")
        finally:
            if hasattr(self, '_reload_in_progress'):
                self._reload_in_progress.discard(component_name)
            if hasattr(self, '_component_operations_in_progress'):
                self._component_operations_in_progress.discard(component_name)
    
    def _on_component_deleted(self, component_name: str):
        """
        Handle component deletion event.
        
        Args:
            component_name: Name of the deleted component
        """
        try:
            logger(f"Detected component removal: {component_name}")
            
            # Remove from available components
            if component_name in self.available:
                del self.available[component_name]
            
            # Remove from enabled list
            if component_name in self.enabled:
                self.enabled.remove(component_name)
                self.save_config()
            
            # Update status
            self.track_component_status(component_name, ComponentStatus.UNLOADED)
            
            # Clean up metadata
            if component_name in self._component_metadata:
                del self._component_metadata[component_name]
            
            # Notify about removal
            self._notify_component_change('removed', component_name)
            
            logger(f"Successfully removed component: {component_name}")
            
        except Exception as e:
            logger(f"Error handling component removal for {component_name}: {e}")
    

    
    def _notify_component_change(self, change_type: str, component_name: str):
        """
        Notify about component changes.
        
        Args:
            change_type: Type of change ('added', 'modified', 'removed')
            component_name: Name of the component that changed
        """
        try:
            # Store change notification for UI or other consumers
            if not hasattr(self, '_component_change_notifications'):
                self._component_change_notifications = []
            
            notification = {
                'type': change_type,
                'component_name': component_name,
                'timestamp': datetime.now().isoformat()
            }
            
            self._component_change_notifications.append(notification)
            
            # Keep only the last 100 notifications
            if len(self._component_change_notifications) > 100:
                self._component_change_notifications = self._component_change_notifications[-100:]
            
            logger(f"Component change notification: {change_type} - {component_name}")
            
        except Exception as e:
            logger(f"Error creating component change notification: {e}")
    
    def get_component_change_notifications(self, since: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get component change notifications.
        
        Args:
            since: ISO timestamp to get notifications since (optional)
            
        Returns:
            List of change notifications
        """
        if not hasattr(self, '_component_change_notifications'):
            return []
        
        notifications = self._component_change_notifications
        
        if since:
            try:
                since_dt = datetime.fromisoformat(since)
                notifications = [
                    n for n in notifications 
                    if datetime.fromisoformat(n['timestamp']) > since_dt
                ]
            except Exception as e:
                logger(f"Error filtering notifications by timestamp: {e}")
        
        return notifications
    
    def clear_component_change_notifications(self):
        """Clear all component change notifications."""
        if hasattr(self, '_component_change_notifications'):
            self._component_change_notifications.clear()
    
    def discover_components_dynamic(self, force_reload: bool = False):
        """
        Enhanced component discovery with hot reload support.
        
        Args:
            force_reload: If True, force reload of all components
        """
        # Add protection against concurrent dynamic discovery
        if hasattr(self, '_dynamic_discovery_in_progress') and self._dynamic_discovery_in_progress:
            logger("Dynamic component discovery already in progress, skipping...")
            return
            
        try:
            self._dynamic_discovery_in_progress = True
            logger("Starting dynamic component discovery...")
            
            # Get list of available components
            available_components = self.component_loader.list_available_components()
            
            # Track which components we've processed
            processed_components = set()
            
            for component_name in available_components:
                try:
                    processed_components.add(component_name)
                    
                    # Check if component is already loaded and doesn't need reload
                    if not force_reload and component_name in self.available:
                        current_status = self.get_component_status(component_name)
                        if current_status == ComponentStatus.LOADED:
                            continue
                    
                    # Determine component path
                    component_path = os.path.join(self.components_dir, component_name)
                    if os.path.isdir(component_path):
                        load_path = component_path
                    else:
                        load_path = f"{component_path}.py"
                        if not os.path.exists(load_path):
                            continue
                    
                    # Load or reload the component
                    if component_name in self.available and force_reload:
                        # Reload existing component
                        result = self.reload_component(component_name)
                        if result.success:
                            logger(f"Reloaded component: {component_name}")
                        else:
                            logger(f"Failed to reload component {component_name}: {result.error_message}")
                    else:
                        # Load new component
                        load_result = self.component_loader.load_component_from_path(load_path)
                        
                        if load_result.success and load_result.module:
                            if hasattr(load_result.module, 'get_component'):
                                try:
                                    comp = load_result.module.get_component()
                                    if isinstance(comp, BaseComponent):
                                        self.available[comp.name] = comp
                                        self.track_component_status(comp.name, ComponentStatus.LOADED, load_result.metadata)
                                        logger(f"Loaded component: {comp.name}")
                                    else:
                                        logger(f"Component {component_name} does not inherit from BaseComponent")
                                        self.track_component_status(component_name, ComponentStatus.FAILED)
                                except Exception as e:
                                    logger(f"Failed to get component instance from {component_name}: {e}")
                                    self.track_component_status(component_name, ComponentStatus.FAILED)
                            else:
                                logger(f"Component {component_name} does not have get_component function")
                                self.track_component_status(component_name, ComponentStatus.FAILED)
                        else:
                            logger(f"Failed to load component {component_name}: {load_result.error_message}")
                            self.track_component_status(component_name, ComponentStatus.FAILED)
                    
                except Exception as e:
                    logger(f"Error processing component {component_name}: {e}")
                    self.track_component_status(component_name, ComponentStatus.FAILED)
            
            # Remove components that no longer exist
            components_to_remove = []
            for component_name in list(self.available.keys()):
                if component_name not in processed_components:
                    # Check if the component file/directory still exists
                    component_path = os.path.join(self.components_dir, component_name)
                    file_path = f"{component_path}.py"
                    
                    if not (os.path.exists(component_path) or os.path.exists(file_path)):
                        components_to_remove.append(component_name)
            
            for component_name in components_to_remove:
                logger(f"Removing non-existent component: {component_name}")
                if component_name in self.available:
                    del self.available[component_name]
                if component_name in self.enabled:
                    self.enabled.remove(component_name)
                self.track_component_status(component_name, ComponentStatus.UNLOADED)
                if component_name in self._component_metadata:
                    del self._component_metadata[component_name]
            
            if components_to_remove:
                self.save_config()
            
            logger(f"Dynamic component discovery completed. Processed {len(processed_components)} components.")
        finally:
            self._dynamic_discovery_in_progress = False
    
    def stop_dynamic_discovery(self):
        """Stop dynamic component discovery and file watching."""
        try:
            if hasattr(self, 'file_watcher'):
                self.file_watcher.stop_watching()
                logger("Dynamic component discovery stopped")
        except Exception as e:
            logger(f"Error stopping dynamic discovery: {e}")
    
    def is_dynamic_discovery_active(self) -> bool:
        """Check if dynamic component discovery is active."""
        return hasattr(self, 'file_watcher') and self.file_watcher.is_watching()
    
    # Component lifecycle management methods
    def enable_component(self, component_name: str, auto_reload: bool = True) -> bool:
        """
        Enable a component with optional hot reload.
        
        Args:
            component_name: Name of the component to enable
            auto_reload: If True, reload the component if it's not loaded
            
        Returns:
            bool: True if component was enabled successfully
        """
        try:
            # Check if component exists
            if component_name not in self.available and component_name not in self._component_statuses:
                logger(f"Component {component_name} not found")
                return False
            
            # Add to enabled list if not already there
            if component_name not in self.enabled:
                self.enabled.append(component_name)
                self.save_config()
            
            # Check current status
            current_status = self.get_component_status(component_name)
            
            # If component is not loaded and auto_reload is True, try to load it
            if auto_reload and current_status not in [ComponentStatus.LOADED, ComponentStatus.LOADING]:
                if component_name in self.available:
                    # Component is available but may need reloading
                    result = self.reload_component(component_name)
                    if result.success:
                        logger(f"Component {component_name} enabled and reloaded")
                        return True
                    else:
                        logger(f"Failed to reload component {component_name}: {result.error_message}")
                        return False
                else:
                    # Try to discover and load the component
                    self.discover_components_dynamic()
                    if component_name in self.available:
                        logger(f"Component {component_name} enabled and loaded")
                        return True
                    else:
                        logger(f"Component {component_name} could not be loaded")
                        return False
            
            logger(f"Component {component_name} enabled")
            return True
            
        except Exception as e:
            logger(f"Error enabling component {component_name}: {e}")
            return False
    
    def disable_component(self, component_name: str, unload: bool = True) -> bool:
        """
        Disable a component with optional unloading.
        
        Args:
            component_name: Name of the component to disable
            unload: If True, unload the component from memory
            
        Returns:
            bool: True if component was disabled successfully
        """
        try:
            # Remove from enabled list
            if component_name in self.enabled:
                self.enabled.remove(component_name)
                self.save_config()
            
            # Unload component if requested
            if unload and component_name in self.available:
                result = self.unload_component(component_name)
                if result.success:
                    logger(f"Component {component_name} disabled and unloaded")
                    return True
                else:
                    logger(f"Component {component_name} disabled but failed to unload: {result.error_message}")
                    return False
            
            # Update status to disabled
            self.track_component_status(component_name, ComponentStatus.DISABLED)
            
            logger(f"Component {component_name} disabled")
            return True
            
        except Exception as e:
            logger(f"Error disabling component {component_name}: {e}")
            return False
    
    def is_component_enabled(self, component_name: str) -> bool:
        """
        Check if a component is enabled.
        
        Args:
            component_name: Name of the component
            
        Returns:
            bool: True if component is enabled
        """
        return component_name in self.enabled
    
    def detect_component_updates(self, component_name: str = None) -> Dict[str, bool]:
        """
        Detect if components have been updated on disk.
        
        Args:
            component_name: Specific component to check, or None for all components
            
        Returns:
            Dict[str, bool]: Dictionary mapping component names to update status
        """
        updates = {}
        
        try:
            components_to_check = [component_name] if component_name else list(self.available.keys())
            
            for comp_name in components_to_check:
                try:
                    # Get component metadata
                    metadata = self.get_component_metadata(comp_name)
                    if not metadata or not metadata.file_path:
                        updates[comp_name] = False
                        continue
                    
                    # Check if file exists and get modification time
                    file_path = Path(metadata.file_path)
                    if not file_path.exists():
                        updates[comp_name] = False
                        continue
                    
                    # Compare modification times
                    current_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    stored_mtime = metadata.modified_at
                    
                    # Component is updated if file is newer than stored metadata
                    updates[comp_name] = current_mtime > stored_mtime
                    
                except Exception as e:
                    logger(f"Error checking updates for component {comp_name}: {e}")
                    updates[comp_name] = False
            
            return updates
            
        except Exception as e:
            logger(f"Error detecting component updates: {e}")
            return {}
    
    def auto_reload_updated_components(self, enabled_only: bool = True) -> Dict[str, ReloadResult]:
        """
        Automatically reload components that have been updated on disk.
        
        Args:
            enabled_only: If True, only reload enabled components
            
        Returns:
            Dict[str, ReloadResult]: Dictionary mapping component names to reload results
        """
        results = {}
        
        try:
            # Detect updates
            updates = self.detect_component_updates()
            
            # Filter to only enabled components if requested
            if enabled_only:
                updates = {name: updated for name, updated in updates.items() 
                          if updated and self.is_component_enabled(name)}
            else:
                updates = {name: updated for name, updated in updates.items() if updated}
            
            # Reload updated components
            for component_name in updates:
                try:
                    logger(f"Auto-reloading updated component: {component_name}")
                    result = self.reload_component(component_name)
                    results[component_name] = result
                    
                    if result.success:
                        logger(f"Successfully auto-reloaded {component_name}")
                    else:
                        logger(f"Failed to auto-reload {component_name}: {result.error_message}")
                        
                except Exception as e:
                    logger(f"Error auto-reloading component {component_name}: {e}")
                    # Create a failed result
                    from hot_reload.models import OperationType
                    results[component_name] = ReloadResult(
                        component_name=component_name,
                        operation=OperationType.RELOAD,
                        success=False,
                        status=ComponentStatus.FAILED,
                        previous_status=ComponentStatus.UNKNOWN,
                        error_message=str(e)
                    )
            
            return results
            
        except Exception as e:
            logger(f"Error in auto-reload process: {e}")
            return {}
    
    def track_component_dependencies(self, component_name: str) -> Dict[str, Any]:
        """
        Track and analyze component dependencies.
        
        Args:
            component_name: Name of the component to analyze
            
        Returns:
            Dict containing dependency information and status
        """
        try:
            # Get component dependencies
            dependencies = self.get_component_dependencies(component_name)
            
            if not dependencies:
                return {
                    'component_name': component_name,
                    'dependencies': [],
                    'dependency_count': 0,
                    'satisfied_count': 0,
                    'missing_count': 0,
                    'all_satisfied': True,
                    'missing_dependencies': [],
                    'dependency_info': []
                }
            
            # Check dependency status
            dependency_info = self.dependency_manager.check_dependencies(dependencies)
            
            # Analyze results
            satisfied_count = sum(1 for dep in dependency_info if dep.is_satisfied())
            missing_count = len(dependency_info) - satisfied_count
            missing_dependencies = [dep.name for dep in dependency_info if not dep.is_satisfied()]
            
            return {
                'component_name': component_name,
                'dependencies': dependencies,
                'dependency_count': len(dependencies),
                'satisfied_count': satisfied_count,
                'missing_count': missing_count,
                'all_satisfied': missing_count == 0,
                'missing_dependencies': missing_dependencies,
                'dependency_info': [dep.to_dict() for dep in dependency_info]
            }
            
        except Exception as e:
            logger(f"Error tracking dependencies for component {component_name}: {e}")
            return {
                'component_name': component_name,
                'error': str(e),
                'dependencies': [],
                'dependency_count': 0,
                'satisfied_count': 0,
                'missing_count': 0,
                'all_satisfied': False,
                'missing_dependencies': [],
                'dependency_info': []
            }
    
    def get_component_lifecycle_info(self, component_name: str) -> Dict[str, Any]:
        """
        Get comprehensive lifecycle information for a component.
        
        Args:
            component_name: Name of the component
            
        Returns:
            Dict containing complete lifecycle information
        """
        try:
            # Get basic info
            status = self.get_component_status(component_name)
            metadata = self.get_component_metadata(component_name)
            is_enabled = self.is_component_enabled(component_name)
            is_available = component_name in self.available
            
            # Get dependency info
            dependency_info = self.track_component_dependencies(component_name)
            
            # Check for updates
            updates = self.detect_component_updates(component_name)
            has_updates = updates.get(component_name, False)
            
            # Get component instance info if available
            component_instance = None
            component_type = None
            if is_available:
                component_instance = self.available[component_name]
                component_type = type(component_instance).__name__
            
            return {
                'component_name': component_name,
                'status': status.value if status else 'unknown',
                'is_enabled': is_enabled,
                'is_available': is_available,
                'has_updates': has_updates,
                'component_type': component_type,
                'metadata': metadata.to_dict() if metadata else None,
                'dependency_info': dependency_info,
                'lifecycle_actions': {
                    'can_enable': not is_enabled,
                    'can_disable': is_enabled,
                    'can_reload': is_available,
                    'can_unload': is_available,
                    'can_install_dependencies': dependency_info['missing_count'] > 0,
                    'should_auto_reload': has_updates and is_enabled
                }
            }
            
        except Exception as e:
            logger(f"Error getting lifecycle info for component {component_name}: {e}")
            return {
                'component_name': component_name,
                'error': str(e),
                'status': 'error',
                'is_enabled': False,
                'is_available': False,
                'has_updates': False,
                'component_type': None,
                'metadata': None,
                'dependency_info': {},
                'lifecycle_actions': {}
            }
    
    def get_all_components_lifecycle_info(self) -> Dict[str, Dict[str, Any]]:
        """
        Get lifecycle information for all known components.
        
        Returns:
            Dict mapping component names to their lifecycle information
        """
        all_components = set()
        all_components.update(self.available.keys())
        all_components.update(self._component_statuses.keys())
        all_components.update(self.enabled)
        
        return {
            component_name: self.get_component_lifecycle_info(component_name)
            for component_name in all_components
        }
    
    def cleanup_disabled_components(self) -> List[str]:
        """
        Clean up components that are disabled and not in use.
        
        Returns:
            List of component names that were cleaned up
        """
        cleaned_up = []
        
        try:
            # Find disabled components
            disabled_components = []
            for component_name in list(self.available.keys()):
                if not self.is_component_enabled(component_name):
                    status = self.get_component_status(component_name)
                    if status in [ComponentStatus.FAILED, ComponentStatus.DISABLED, ComponentStatus.UNLOADED]:
                        disabled_components.append(component_name)
            
            # Clean up disabled components
            for component_name in disabled_components:
                try:
                    # Remove from available
                    if component_name in self.available:
                        del self.available[component_name]
                    
                    # Clean up metadata
                    if component_name in self._component_metadata:
                        del self._component_metadata[component_name]
                    
                    # Update status
                    self.track_component_status(component_name, ComponentStatus.UNLOADED)
                    
                    cleaned_up.append(component_name)
                    logger(f"Cleaned up disabled component: {component_name}")
                    
                except Exception as e:
                    logger(f"Error cleaning up component {component_name}: {e}")
            
            return cleaned_up
            
        except Exception as e:
            logger(f"Error during component cleanup: {e}")
            return cleaned_up
