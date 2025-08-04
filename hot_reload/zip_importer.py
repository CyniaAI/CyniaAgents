"""
ZIP importer for component packages with security validation.

This module provides the ZipImporter class for safely importing components
from ZIP files with comprehensive security checks and validation.
"""

import os
import sys
import zipfile
import tempfile
import shutil
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass
from datetime import datetime

from .models import ComponentMetadata
from .errors import ErrorHandler, ErrorInfo, ErrorSeverity


@dataclass
class ZipValidationResult:
    """Result of ZIP file validation."""
    is_valid: bool
    errors: List[str] = None
    warnings: List[str] = None
    file_count: int = 0
    python_files: List[str] = None
    suspicious_files: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.python_files is None:
            self.python_files = []
        if self.suspicious_files is None:
            self.suspicious_files = []


@dataclass
class ZipImportResult:
    """Result of ZIP import operation."""
    success: bool
    component_name: Optional[str] = None
    extracted_path: Optional[str] = None
    metadata: Optional[ComponentMetadata] = None
    error_message: Optional[str] = None
    warnings: List[str] = None
    validation_result: Optional[ZipValidationResult] = None
    import_time: float = 0.0
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class ZipImporter:
    """
    Secure ZIP importer for component packages.
    
    This class handles importing components from ZIP files with comprehensive
    security validation, malicious content detection, and safe extraction.
    """
    
    # File extensions that are considered suspicious
    SUSPICIOUS_EXTENSIONS = {
        '.exe', '.bat', '.cmd', '.sh', '.dll', '.so', '.dylib',
        '.scr', '.com', '.pif', '.vbs', '.js', '.jar', '.class',
        '.msi', '.deb', '.rpm', '.dmg', '.pkg', '.app'
    }
    
    # Maximum file size for individual files (100MB)
    MAX_FILE_SIZE = 100 * 1024 * 1024
    
    # Maximum total extracted size (500MB)
    MAX_TOTAL_SIZE = 500 * 1024 * 1024
    
    # Maximum number of files in ZIP
    MAX_FILE_COUNT = 1000
    
    def __init__(self, error_handler: Optional[ErrorHandler] = None):
        """
        Initialize the ZipImporter.
        
        Args:
            error_handler: Error handler instance for error management
        """
        self.error_handler = error_handler or ErrorHandler()
        self.temp_dirs: Set[str] = set()  # Track temp directories for cleanup
    
    def import_from_bytes(self, zip_data: bytes, extract_to: Optional[str] = None) -> ZipImportResult:
        """
        Import a component from ZIP file bytes.
        
        Args:
            zip_data: Raw ZIP file data
            extract_to: Optional directory to extract to (uses temp dir if None)
            
        Returns:
            ZipImportResult: Result of the import operation
        """
        start_time = datetime.now()
        temp_zip_path = None
        
        try:
            # Create temporary file for ZIP data
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
                temp_zip.write(zip_data)
                temp_zip_path = temp_zip.name
            
            return self.import_from_file(temp_zip_path, extract_to)
            
        except Exception as e:
            return ZipImportResult(
                success=False,
                error_message=f"Failed to process ZIP data: {str(e)}",
                import_time=(datetime.now() - start_time).total_seconds()
            )
        finally:
            # Clean up temporary ZIP file
            if temp_zip_path and os.path.exists(temp_zip_path):
                try:
                    os.unlink(temp_zip_path)
                except Exception:
                    pass  # Ignore cleanup errors
    
    def import_from_file(self, zip_path: str, extract_to: Optional[str] = None) -> ZipImportResult:
        """
        Import a component from a ZIP file path.
        
        Args:
            zip_path: Path to the ZIP file
            extract_to: Optional directory to extract to (uses temp dir if None)
            
        Returns:
            ZipImportResult: Result of the import operation
        """
        start_time = datetime.now()
        extract_dir = None
        
        try:
            # Validate ZIP file exists
            if not os.path.exists(zip_path):
                return ZipImportResult(
                    success=False,
                    error_message=f"ZIP file does not exist: {zip_path}"
                )
            
            # Validate ZIP file
            validation_result = self.validate_zip_file(zip_path)
            if not validation_result.is_valid:
                return ZipImportResult(
                    success=False,
                    error_message=f"ZIP validation failed: {'; '.join(validation_result.errors)}",
                    warnings=validation_result.warnings,
                    validation_result=validation_result
                )
            
            # Determine extraction directory
            if extract_to:
                extract_dir = Path(extract_to)
                extract_dir.mkdir(parents=True, exist_ok=True)
            else:
                extract_dir = Path(tempfile.mkdtemp(prefix="zip_import_"))
                self.temp_dirs.add(str(extract_dir))
            
            # Extract ZIP file
            extraction_result = self._extract_zip_safely(zip_path, extract_dir)
            if not extraction_result.success:
                return extraction_result
            
            # Find component in extracted files
            component_path = self._find_main_component(extract_dir)
            if not component_path:
                return ZipImportResult(
                    success=False,
                    error_message="No valid component found in ZIP file",
                    extracted_path=str(extract_dir),
                    validation_result=validation_result
                )
            
            # Extract component metadata
            metadata = self._extract_component_metadata(component_path)
            component_name = metadata.name if metadata else component_path.stem
            
            import_time = (datetime.now() - start_time).total_seconds()
            
            return ZipImportResult(
                success=True,
                component_name=component_name,
                extracted_path=str(component_path),
                metadata=metadata,
                warnings=validation_result.warnings,
                validation_result=validation_result,
                import_time=import_time
            )
            
        except Exception as e:
            return ZipImportResult(
                success=False,
                error_message=f"Import failed: {str(e)}",
                extracted_path=str(extract_dir) if extract_dir else None,
                import_time=(datetime.now() - start_time).total_seconds()
            )
    
    def validate_zip_file(self, zip_path: str) -> ZipValidationResult:
        """
        Validate a ZIP file for security and structure.
        
        Args:
            zip_path: Path to the ZIP file
            
        Returns:
            ZipValidationResult: Validation results
        """
        errors = []
        warnings = []
        python_files = []
        suspicious_files = []
        file_count = 0
        total_size = 0
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_list = zip_ref.infolist()
                file_count = len(file_list)
                
                # Check file count limit
                if file_count > self.MAX_FILE_COUNT:
                    errors.append(f"Too many files in ZIP: {file_count} (max: {self.MAX_FILE_COUNT})")
                
                for file_info in file_list:
                    filename = file_info.filename
                    file_size = file_info.file_size
                    
                    # Check for path traversal
                    if not self._is_safe_path(filename):
                        errors.append(f"Unsafe path detected: {filename}")
                        continue
                    
                    # Check file size
                    if file_size > self.MAX_FILE_SIZE:
                        errors.append(f"File too large: {filename} ({file_size} bytes)")
                        continue
                    
                    total_size += file_size
                    
                    # Check for suspicious file extensions
                    file_ext = Path(filename).suffix.lower()
                    if file_ext in self.SUSPICIOUS_EXTENSIONS:
                        suspicious_files.append(filename)
                        errors.append(f"Suspicious file type: {filename}")
                        continue
                    
                    # Collect Python files
                    if file_ext == '.py':
                        python_files.append(filename)
                    
                    # Check for hidden files (warning only)
                    if Path(filename).name.startswith('.') and file_ext != '.py':
                        warnings.append(f"Hidden file detected: {filename}")
                
                # Check total size
                if total_size > self.MAX_TOTAL_SIZE:
                    errors.append(f"Total size too large: {total_size} bytes (max: {self.MAX_TOTAL_SIZE})")
                
                # Ensure there are Python files
                if not python_files:
                    errors.append("No Python files found in ZIP")
                
                # Check for common component files
                has_component_structure = any(
                    filename.endswith(('__init__.py', 'main.py')) or 
                    any(keyword in filename.lower() for keyword in ['component', 'plugin'])
                    for filename in [f.filename for f in file_list]
                )
                
                if not has_component_structure:
                    warnings.append("No obvious component structure detected")
                
        except zipfile.BadZipFile:
            errors.append("Invalid ZIP file format")
        except Exception as e:
            errors.append(f"ZIP validation error: {str(e)}")
        
        return ZipValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            file_count=file_count,
            python_files=python_files,
            suspicious_files=suspicious_files
        )
    
    def _extract_zip_safely(self, zip_path: str, extract_dir: Path) -> ZipImportResult:
        """
        Safely extract ZIP file with security checks.
        
        Args:
            zip_path: Path to ZIP file
            extract_dir: Directory to extract to
            
        Returns:
            ZipImportResult: Extraction result
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for member in zip_ref.infolist():
                    # Double-check path safety during extraction
                    if not self._is_safe_path(member.filename):
                        return ZipImportResult(
                            success=False,
                            error_message=f"Unsafe path in ZIP: {member.filename}"
                        )
                    
                    # Extract the file
                    zip_ref.extract(member, extract_dir)
                    
                    # Set safe permissions (remove execute permissions)
                    extracted_path = extract_dir / member.filename
                    if extracted_path.exists() and extracted_path.is_file():
                        try:
                            # Remove execute permissions for security
                            os.chmod(extracted_path, 0o644)
                        except Exception:
                            pass  # Ignore permission errors on Windows
            
            return ZipImportResult(success=True)
            
        except Exception as e:
            return ZipImportResult(
                success=False,
                error_message=f"Extraction failed: {str(e)}"
            )
    
    def _is_safe_path(self, path: str) -> bool:
        """
        Check if a file path is safe (no path traversal).
        
        Args:
            path: File path to check
            
        Returns:
            bool: True if path is safe, False otherwise
        """
        # Normalize the path and check for traversal attempts
        normalized = os.path.normpath(path)
        
        # Check for absolute paths
        if os.path.isabs(normalized):
            return False
        
        # Check for parent directory references
        if '..' in normalized.split(os.sep):
            return False
        
        # Check for drive letters on Windows
        if ':' in normalized:
            return False
        
        return True
    
    def _find_main_component(self, extract_dir: Path) -> Optional[Path]:
        """
        Find the main component file or directory in extracted files.
        
        Args:
            extract_dir: Directory containing extracted files
            
        Returns:
            Path: Path to main component or None if not found
        """
        # Look for Python files in the root
        python_files = list(extract_dir.glob('*.py'))
        if python_files:
            # Prefer files with 'component' or 'main' in the name
            for py_file in python_files:
                if any(keyword in py_file.stem.lower() for keyword in ['component', 'main']):
                    return py_file
            # Otherwise return the first Python file
            return python_files[0]
        
        # Look for package directories
        for item in extract_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                # Check if it has __init__.py or main.py
                if (item / '__init__.py').exists() or (item / 'main.py').exists():
                    return item
        
        # Look in subdirectories
        for item in extract_dir.rglob('*.py'):
            if item.name in ['__init__.py', 'main.py']:
                return item.parent
            if any(keyword in item.stem.lower() for keyword in ['component', 'main']):
                return item
        
        return None
    
    def _extract_component_metadata(self, component_path: Path) -> Optional[ComponentMetadata]:
        """
        Extract metadata from a component file or directory.
        
        Args:
            component_path: Path to component file or directory
            
        Returns:
            ComponentMetadata: Extracted metadata or None if failed
        """
        try:
            import ast
            
            if component_path.is_file():
                main_file = component_path
                component_name = component_path.stem
                is_package = False
            else:
                # Look for main files in package
                main_files = ['__init__.py', 'main.py']
                main_file = None
                
                for filename in main_files:
                    candidate = component_path / filename
                    if candidate.exists():
                        main_file = candidate
                        break
                
                if not main_file:
                    return None
                
                component_name = component_path.name
                is_package = True
            
            # Parse the Python file for metadata
            with open(main_file, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=str(main_file))
            
            metadata = {
                'name': component_name,
                'description': '',
                'version': '1.0.0',
                'author': '',
                'requirements': [],
                'file_path': str(main_file),
                'module_name': component_name,
                'is_package': is_package,
                'package_path': str(component_path) if is_package else None
            }
            
            # Extract metadata from AST
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
            
            # Check for requirements.txt
            if is_package:
                req_path = component_path / 'requirements.txt'
            else:
                req_path = component_path.parent / 'requirements.txt'
            
            if req_path.exists():
                try:
                    with open(req_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                metadata['requirements'].append(line)
                except Exception:
                    pass
            
            return ComponentMetadata(**metadata)
            
        except Exception as e:
            return None
    
    def _extract_ast_value(self, node) -> Any:
        """Extract value from AST node."""
        import ast
        
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
    
    def cleanup_temp_dirs(self):
        """Clean up all temporary directories created during imports."""
        for temp_dir in list(self.temp_dirs):
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                self.temp_dirs.discard(temp_dir)
            except Exception:
                pass  # Ignore cleanup errors
    
    def get_zip_info(self, zip_path: str) -> Dict[str, Any]:
        """
        Get information about a ZIP file without extracting it.
        
        Args:
            zip_path: Path to ZIP file
            
        Returns:
            Dict: ZIP file information
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_list = zip_ref.infolist()
                
                total_size = sum(f.file_size for f in file_list)
                compressed_size = sum(f.compress_size for f in file_list)
                
                python_files = [f.filename for f in file_list if f.filename.endswith('.py')]
                
                return {
                    'file_count': len(file_list),
                    'total_size': total_size,
                    'compressed_size': compressed_size,
                    'compression_ratio': compressed_size / total_size if total_size > 0 else 0,
                    'python_files': python_files,
                    'has_requirements': any('requirements.txt' in f.filename for f in file_list),
                    'has_init': any('__init__.py' in f.filename for f in file_list),
                    'has_main': any('main.py' in f.filename for f in file_list)
                }
                
        except Exception as e:
            return {'error': str(e)}
    
    def __del__(self):
        """Cleanup temporary directories on destruction."""
        self.cleanup_temp_dirs()