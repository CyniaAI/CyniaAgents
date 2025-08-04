"""
Component loading system with safe importing and error isolation.

This module provides the ComponentLoader class for safely loading components
with comprehensive error handling, metadata extraction, and validation.
"""

import ast
import importlib
import importlib.util
import os
import sys
import zipfile
import tempfile
import shutil
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

from .models import ComponentMetadata, ComponentStatus, ReloadResult, OperationType
from .errors import ErrorHandler, ErrorInfo, ErrorSeverity


@dataclass
class LoadResult:
    """Result of a component loading operation."""
    success: bool
    component_name: str
    metadata: Optional[ComponentMetadata] = None
    module: Optional[Any] = None
    error_message: Optional[str] = None
    warnings: List[str] = None
    load_time: float = 0.0
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@dataclass
class ValidationResult:
    """Result of component structure validation."""
    is_valid: bool
    errors: List[str] = None
    warnings: List[str] = None
    metadata: Optional[ComponentMetadata] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


class ComponentLoader:
    """
    Safe component loader with error isolation and comprehensive validation.
    
    This class handles loading Python components from files and directories,
    with support for metadata extraction, dependency checking, and error isolation.
    """
    
    def __init__(self, components_dir: str = "components", error_handler: Optional[ErrorHandler] = None):
        """
        Initialize the ComponentLoader.
        
        Args:
            components_dir: Directory containing components
            error_handler: Error handler instance for error management
        """
        self.components_dir = Path(components_dir)
        self.error_handler = error_handler or ErrorHandler()
        self.loaded_modules: Dict[str, Any] = {}
        self.component_cache: Dict[str, ComponentMetadata] = {}
        
        # Ensure components directory exists
        self.components_dir.mkdir(exist_ok=True)
    
    def load_component_from_path(self, path: str) -> LoadResult:
        """
        Load a component from a file path with comprehensive error handling.
        
        Args:
            path: Path to the component file or directory
            
        Returns:
            LoadResult: Result of the loading operation
        """
        start_time = datetime.now()
        component_path = Path(path)
        
        try:
            # Validate the path exists
            if not component_path.exists():
                return LoadResult(
                    success=False,
                    component_name=component_path.stem,
                    error_message=f"Component path does not exist: {path}"
                )
            
            # Determine component name and type
            if component_path.is_file():
                component_name = component_path.stem
                is_package = False
            else:
                component_name = component_path.name
                is_package = True
            
            # Validate component structure
            validation_result = self.validate_component_structure(str(component_path))
            if not validation_result.is_valid:
                return LoadResult(
                    success=False,
                    component_name=component_name,
                    error_message=f"Component validation failed: {'; '.join(validation_result.errors)}",
                    warnings=validation_result.warnings
                )
            
            # Extract metadata
            metadata = self.extract_component_metadata(str(component_path))
            if not metadata:
                return LoadResult(
                    success=False,
                    component_name=component_name,
                    error_message="Failed to extract component metadata"
                )
            
            # Attempt to load the module
            module = self._load_module_safely(component_path, component_name, is_package)
            if not module:
                return LoadResult(
                    success=False,
                    component_name=component_name,
                    error_message="Failed to load component module"
                )
            
            # Validate the loaded component
            component_instance = self._validate_loaded_component(module, component_name)
            if not component_instance:
                return LoadResult(
                    success=False,
                    component_name=component_name,
                    error_message="Component does not implement required interface"
                )
            
            # Store in cache
            self.loaded_modules[component_name] = module
            self.component_cache[component_name] = metadata
            
            load_time = (datetime.now() - start_time).total_seconds()
            
            return LoadResult(
                success=True,
                component_name=component_name,
                metadata=metadata,
                module=module,
                warnings=validation_result.warnings,
                load_time=load_time
            )
            
        except Exception as e:
            # Handle any unexpected errors
            error_report = self.error_handler.handle_component_error(
                component_name if 'component_name' in locals() else component_path.stem,
                'load',
                e
            )
            
            return LoadResult(
                success=False,
                component_name=component_name if 'component_name' in locals() else component_path.stem,
                error_message=str(e)
            )
    
    def load_component_from_zip(self, zip_data: bytes, extract_to: Optional[str] = None) -> LoadResult:
        """
        Load a component from ZIP file data.
        
        Args:
            zip_data: Raw ZIP file data
            extract_to: Optional directory to extract to (uses temp dir if None)
            
        Returns:
            LoadResult: Result of the loading operation
        """
        temp_dir = None
        try:
            # Create temporary directory for extraction
            if extract_to:
                extract_dir = Path(extract_to)
                extract_dir.mkdir(parents=True, exist_ok=True)
            else:
                temp_dir = tempfile.mkdtemp(prefix="component_")
                extract_dir = Path(temp_dir)
            
            # Validate and extract ZIP
            zip_result = self._extract_zip_safely(zip_data, extract_dir)
            if not zip_result.success:
                return LoadResult(
                    success=False,
                    component_name="unknown",
                    error_message=zip_result.error_message
                )
            
            # Find the main component file/directory
            component_path = self._find_component_in_directory(extract_dir)
            if not component_path:
                return LoadResult(
                    success=False,
                    component_name="unknown",
                    error_message="No valid component found in ZIP file"
                )
            
            # Load the component
            result = self.load_component_from_path(str(component_path))
            
            # If loading was successful and we used a temp directory, move to components dir
            if result.success and temp_dir:
                final_path = self.components_dir / result.component_name
                if final_path.exists():
                    shutil.rmtree(final_path)
                shutil.move(str(component_path), str(final_path))
                
                # Update metadata with final path
                if result.metadata:
                    result.metadata.file_path = str(final_path)
                    result.metadata.package_path = str(final_path) if component_path.is_dir() else None
            
            return result
            
        except Exception as e:
            return LoadResult(
                success=False,
                component_name="unknown",
                error_message=f"Failed to load component from ZIP: {str(e)}"
            )
        finally:
            # Clean up temporary directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass  # Ignore cleanup errors
    
    def validate_component_structure(self, path: str) -> ValidationResult:
        """
        Validate the structure of a component file or directory.
        
        Args:
            path: Path to validate
            
        Returns:
            ValidationResult: Validation results with errors and warnings
        """
        component_path = Path(path)
        errors = []
        warnings = []
        
        try:
            if not component_path.exists():
                errors.append(f"Path does not exist: {path}")
                return ValidationResult(is_valid=False, errors=errors)
            
            if component_path.is_file():
                # Validate single file component
                if not component_path.suffix == '.py':
                    errors.append("Component file must have .py extension")
                
                # Check for syntax errors
                try:
                    with open(component_path, 'r', encoding='utf-8') as f:
                        ast.parse(f.read(), filename=str(component_path))
                except SyntaxError as e:
                    errors.append(f"Syntax error in {component_path.name}: {e}")
                except Exception as e:
                    errors.append(f"Failed to parse {component_path.name}: {e}")
                
            else:
                # Validate package component
                main_files = ['__init__.py', 'main.py']
                has_main = any((component_path / f).exists() for f in main_files)
                
                if not has_main:
                    errors.append("Package component must contain __init__.py or main.py")
                
                # Check for syntax errors in main files
                for main_file in main_files:
                    main_path = component_path / main_file
                    if main_path.exists():
                        try:
                            with open(main_path, 'r', encoding='utf-8') as f:
                                ast.parse(f.read(), filename=str(main_path))
                        except SyntaxError as e:
                            errors.append(f"Syntax error in {main_file}: {e}")
                        except Exception as e:
                            warnings.append(f"Could not parse {main_file}: {e}")
            
            # Check for requirements.txt
            req_path = component_path / 'requirements.txt' if component_path.is_dir() else component_path.parent / 'requirements.txt'
            if req_path.exists():
                try:
                    with open(req_path, 'r', encoding='utf-8') as f:
                        requirements = f.read().strip()
                        if requirements:
                            warnings.append(f"Component has {len(requirements.splitlines())} dependencies")
                except Exception as e:
                    warnings.append(f"Could not read requirements.txt: {e}")
            
            return ValidationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings
            )
            
        except Exception as e:
            errors.append(f"Validation failed: {str(e)}")
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
    
    def extract_component_metadata(self, path: str) -> Optional[ComponentMetadata]:
        """
        Extract metadata from a component file or directory.
        
        Args:
            path: Path to the component
            
        Returns:
            ComponentMetadata: Extracted metadata or None if extraction failed
        """
        component_path = Path(path)
        
        try:
            if component_path.is_file():
                return self._extract_metadata_from_file(component_path)
            else:
                return self._extract_metadata_from_package(component_path)
                
        except Exception as e:
            # Log error but don't raise - return None to indicate failure
            return None
    
    def _extract_metadata_from_file(self, file_path: Path) -> Optional[ComponentMetadata]:
        """Extract metadata from a single Python file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=str(file_path))
            
            metadata = {
                'name': file_path.stem,
                'description': '',
                'version': '1.0.0',
                'author': '',
                'requirements': [],
                'file_path': str(file_path),
                'module_name': file_path.stem,
                'is_package': False
            }
            
            # Look for BaseComponent class and extract metadata
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check if this class inherits from BaseComponent
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == "BaseComponent":
                            # Extract class attributes
                            for stmt in node.body:
                                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                                    target = stmt.targets[0]
                                    if isinstance(target, ast.Name):
                                        key = target.id
                                        value = self._extract_ast_value(stmt.value)
                                        if key in metadata and value is not None:
                                            metadata[key] = value
                            break
            
            # Check for requirements.txt in the same directory
            req_path = file_path.parent / 'requirements.txt'
            if req_path.exists():
                req_list = self._read_requirements_file(str(req_path))
                metadata['requirements'].extend(req_list)
            
            # Calculate file checksum
            metadata['checksum'] = self._calculate_file_checksum(str(file_path))
            
            return ComponentMetadata(**metadata)
            
        except Exception as e:
            return None
    
    def _extract_metadata_from_package(self, package_path: Path) -> Optional[ComponentMetadata]:
        """Extract metadata from a package directory."""
        try:
            # Look for main files
            main_files = ['__init__.py', 'main.py']
            main_file = None
            
            for filename in main_files:
                candidate = package_path / filename
                if candidate.exists():
                    main_file = candidate
                    break
            
            if not main_file:
                return None
            
            metadata = {
                'name': package_path.name,
                'description': '',
                'version': '1.0.0',
                'author': '',
                'requirements': [],
                'file_path': str(main_file),
                'module_name': package_path.name,
                'is_package': True,
                'package_path': str(package_path)
            }
            
            # Extract metadata from main file
            with open(main_file, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=str(main_file))
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == "BaseComponent":
                            for stmt in node.body:
                                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                                    target = stmt.targets[0]
                                    if isinstance(target, ast.Name):
                                        key = target.id
                                        value = self._extract_ast_value(stmt.value)
                                        if key in metadata and value is not None:
                                            metadata[key] = value
                            break
            
            # Check for requirements.txt in package directory
            req_path = package_path / 'requirements.txt'
            if req_path.exists():
                req_list = self._read_requirements_file(str(req_path))
                metadata['requirements'].extend(req_list)
            
            # Calculate directory checksum (based on main file)
            metadata['checksum'] = self._calculate_file_checksum(str(main_file))
            
            return ComponentMetadata(**metadata)
            
        except Exception as e:
            return None
    
    def _extract_ast_value(self, node: ast.AST) -> Any:
        """Extract value from AST node."""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Str):  # Python < 3.8 compatibility
            return node.s
        elif isinstance(node, ast.List):
            return [self._extract_ast_value(elt) for elt in node.elts]
        elif isinstance(node, ast.Tuple):
            return [self._extract_ast_value(elt) for elt in node.elts]
        else:
            return None
    
    def _read_requirements_file(self, req_path: str) -> List[str]:
        """Read and parse requirements.txt file."""
        requirements = []
        try:
            with open(req_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        requirements.append(line)
        except Exception:
            pass
        return requirements
    
    def _calculate_file_checksum(self, file_path: str) -> str:
        """Calculate SHA-256 checksum of a file."""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ""
    
    def _load_module_safely(self, component_path: Path, component_name: str, is_package: bool) -> Optional[Any]:
        """Safely load a Python module with error isolation."""
        try:
            if is_package:
                # Load package
                main_files = ['__init__.py', 'main.py']
                main_file = None
                
                for filename in main_files:
                    candidate = component_path / filename
                    if candidate.exists():
                        main_file = candidate
                        break
                
                if not main_file:
                    return None
                
                spec = importlib.util.spec_from_file_location(
                    f"components.{component_name}",
                    str(main_file)
                )
            else:
                # Load single file
                spec = importlib.util.spec_from_file_location(
                    f"components.{component_name}",
                    str(component_path)
                )
            
            if not spec or not spec.loader:
                return None
            
            # Create and execute module
            module = importlib.util.module_from_spec(spec)
            
            # Add to sys.modules before execution to handle circular imports
            sys.modules[spec.name] = module
            
            try:
                spec.loader.exec_module(module)
                return module
            except Exception as e:
                # Remove from sys.modules if execution failed
                if spec.name in sys.modules:
                    del sys.modules[spec.name]
                raise e
                
        except Exception as e:
            # Handle loading errors
            self.error_handler.handle_component_error(component_name, 'load', e)
            return None
    
    def _validate_loaded_component(self, module: Any, component_name: str) -> Optional[Any]:
        """Validate that the loaded module contains a valid component."""
        try:
            # Check for get_component function
            if not hasattr(module, 'get_component'):
                return None
            
            # Try to get the component instance
            component_instance = module.get_component()
            
            # Basic validation - should have required attributes
            required_attrs = ['name', 'render']
            for attr in required_attrs:
                if not hasattr(component_instance, attr):
                    return None
            
            return component_instance
            
        except Exception as e:
            self.error_handler.handle_component_error(component_name, 'validate', e)
            return None
    
    def _extract_zip_safely(self, zip_data: bytes, extract_dir: Path) -> LoadResult:
        """Safely extract ZIP file with security validation."""
        try:
            # Create a temporary file for the ZIP data
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
                temp_zip.write(zip_data)
                temp_zip_path = temp_zip.name
            
            try:
                with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                    # Validate ZIP contents
                    validation_result = self._validate_zip_contents(zip_ref)
                    if not validation_result.success:
                        return validation_result
                    
                    # Extract safely
                    for member in zip_ref.infolist():
                        # Validate file path for security
                        if self._is_safe_path(member.filename):
                            zip_ref.extract(member, extract_dir)
                        else:
                            return LoadResult(
                                success=False,
                                component_name="unknown",
                                error_message=f"Unsafe path in ZIP: {member.filename}"
                            )
                
                return LoadResult(success=True, component_name="extracted")
                
            finally:
                # Clean up temporary ZIP file
                try:
                    os.unlink(temp_zip_path)
                except Exception:
                    pass
                    
        except Exception as e:
            return LoadResult(
                success=False,
                component_name="unknown",
                error_message=f"Failed to extract ZIP: {str(e)}"
            )
    
    def _validate_zip_contents(self, zip_ref: zipfile.ZipFile) -> LoadResult:
        """Validate ZIP file contents for security and structure."""
        try:
            # Check for suspicious files
            suspicious_extensions = ['.exe', '.bat', '.cmd', '.sh', '.dll', '.so']
            python_files = []
            
            for filename in zip_ref.namelist():
                # Check for path traversal attempts
                if not self._is_safe_path(filename):
                    return LoadResult(
                        success=False,
                        component_name="unknown",
                        error_message=f"Unsafe path detected: {filename}"
                    )
                
                # Check for suspicious file extensions
                for ext in suspicious_extensions:
                    if filename.lower().endswith(ext):
                        return LoadResult(
                            success=False,
                            component_name="unknown",
                            error_message=f"Suspicious file type detected: {filename}"
                        )
                
                # Collect Python files
                if filename.endswith('.py'):
                    python_files.append(filename)
            
            # Ensure there's at least one Python file
            if not python_files:
                return LoadResult(
                    success=False,
                    component_name="unknown",
                    error_message="No Python files found in ZIP"
                )
            
            return LoadResult(success=True, component_name="validated")
            
        except Exception as e:
            return LoadResult(
                success=False,
                component_name="unknown",
                error_message=f"ZIP validation failed: {str(e)}"
            )
    
    def _is_safe_path(self, path: str) -> bool:
        """Check if a file path is safe (no path traversal)."""
        # Normalize the path and check for traversal attempts
        normalized = os.path.normpath(path)
        return not (normalized.startswith('/') or normalized.startswith('\\') or '..' in normalized)
    
    def _find_component_in_directory(self, directory: Path) -> Optional[Path]:
        """Find the main component file or directory in an extracted directory."""
        # Look for Python files in the root
        python_files = list(directory.glob('*.py'))
        if python_files:
            return python_files[0]  # Return first Python file
        
        # Look for subdirectories that might contain components
        for item in directory.iterdir():
            if item.is_dir():
                # Check if it has __init__.py or main.py
                if (item / '__init__.py').exists() or (item / 'main.py').exists():
                    return item
        
        return None
    
    def get_loaded_component(self, component_name: str) -> Optional[Any]:
        """Get a loaded component module by name."""
        return self.loaded_modules.get(component_name)
    
    def get_component_metadata(self, component_name: str) -> Optional[ComponentMetadata]:
        """Get cached metadata for a component."""
        return self.component_cache.get(component_name)
    
    def unload_component(self, component_name: str) -> bool:
        """Unload a component and clean up its module references."""
        try:
            # Remove from cache
            if component_name in self.loaded_modules:
                del self.loaded_modules[component_name]
            
            if component_name in self.component_cache:
                del self.component_cache[component_name]
            
            # Clean up sys.modules
            modules_to_remove = []
            for module_name in sys.modules:
                if component_name in module_name:
                    modules_to_remove.append(module_name)
            
            for module_name in modules_to_remove:
                del sys.modules[module_name]
            
            return True
            
        except Exception as e:
            self.error_handler.handle_component_error(component_name, 'unload', e)
            return False
    
    def list_available_components(self) -> List[str]:
        """List all available components in the components directory."""
        components = []
        
        if not self.components_dir.exists():
            return components
        
        # Find Python files
        for py_file in self.components_dir.glob('*.py'):
            if py_file.stem != '__init__':
                components.append(py_file.stem)
        
        # Find package directories
        for item in self.components_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                if (item / '__init__.py').exists() or (item / 'main.py').exists():
                    components.append(item.name)
        
        return sorted(components)