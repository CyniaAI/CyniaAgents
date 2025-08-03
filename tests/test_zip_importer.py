"""
Unit tests for the ZipImporter class.

Tests cover ZIP file validation, secure extraction, malicious content detection,
and component metadata extraction.
"""

import os
import sys
import tempfile
import shutil
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hot_reload.zip_importer import ZipImporter, ZipValidationResult, ZipImportResult
from hot_reload.models import ComponentMetadata
from hot_reload.errors import ErrorHandler


class TestZipImporter:
    """Test cases for ZipImporter class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.error_handler = Mock(spec=ErrorHandler)
        self.importer = ZipImporter(self.error_handler)
    
    def teardown_method(self):
        """Clean up test fixtures."""
        self.importer.cleanup_temp_dirs()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def create_test_zip(self, filename: str, files: dict) -> str:
        """
        Create a test ZIP file with specified files.
        
        Args:
            filename: Name of the ZIP file
            files: Dictionary of filename -> content
            
        Returns:
            str: Path to created ZIP file
        """
        zip_path = os.path.join(self.temp_dir, filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zip_file:
            for file_path, content in files.items():
                zip_file.writestr(file_path, content)
        
        return zip_path
    
    def create_valid_component_zip(self, component_name: str = "test_component") -> str:
        """Create a ZIP file with a valid component."""
        files = {
            f"{component_name}.py": f'''
from component_base import BaseComponent

class TestComponent(BaseComponent):
    name = "{component_name}"
    description = "Test component from ZIP"
    requirements = ["requests", "numpy"]
    
    def render(self):
        pass

def get_component():
    return TestComponent()
''',
            "requirements.txt": "requests>=2.25.0\nnumpy>=1.20.0\n"
        }
        
        return self.create_test_zip(f"{component_name}.zip", files)
    
    def create_package_component_zip(self, package_name: str = "test_package") -> str:
        """Create a ZIP file with a package component."""
        files = {
            f"{package_name}/__init__.py": f'''
from component_base import BaseComponent

class TestPackageComponent(BaseComponent):
    name = "{package_name}"
    description = "Test package component"
    requirements = ["pandas"]
    
    def render(self):
        pass

def get_component():
    return TestPackageComponent()
''',
            f"{package_name}/requirements.txt": "pandas>=1.0.0\n",
            f"{package_name}/helper.py": "# Helper module\n"
        }
        
        return self.create_test_zip(f"{package_name}.zip", files)
    
    def test_init(self):
        """Test ZipImporter initialization."""
        assert self.importer.error_handler == self.error_handler
        assert isinstance(self.importer.temp_dirs, set)
        assert len(self.importer.temp_dirs) == 0
    
    def test_init_default_error_handler(self):
        """Test ZipImporter initialization with default error handler."""
        importer = ZipImporter()
        assert isinstance(importer.error_handler, ErrorHandler)
    
    def test_import_from_file_valid_component(self):
        """Test importing a valid component from ZIP file."""
        zip_path = self.create_valid_component_zip("valid_component")
        
        result = self.importer.import_from_file(zip_path)
        
        assert result.success
        assert result.component_name == "valid_component"
        assert result.extracted_path is not None
        assert result.metadata is not None
        assert result.metadata.name == "valid_component"
        assert "requests" in result.metadata.requirements
        assert result.import_time > 0
    
    def test_import_from_file_package_component(self):
        """Test importing a package component from ZIP file."""
        zip_path = self.create_package_component_zip("test_package")
        
        result = self.importer.import_from_file(zip_path)
        
        assert result.success
        assert result.component_name == "test_package"
        assert result.metadata is not None
        assert result.metadata.is_package
        assert "pandas" in result.metadata.requirements
    
    def test_import_from_file_nonexistent(self):
        """Test importing from non-existent ZIP file."""
        result = self.importer.import_from_file("/nonexistent/file.zip")
        
        assert not result.success
        assert "does not exist" in result.error_message
    
    def test_import_from_file_invalid_zip(self):
        """Test importing from invalid ZIP file."""
        # Create a non-ZIP file
        invalid_zip = os.path.join(self.temp_dir, "invalid.zip")
        with open(invalid_zip, 'w') as f:
            f.write("not a zip file")
        
        result = self.importer.import_from_file(invalid_zip)
        
        assert not result.success
        assert "validation failed" in result.error_message.lower()
    
    def test_import_from_bytes_valid(self):
        """Test importing from ZIP bytes."""
        zip_path = self.create_valid_component_zip("bytes_component")
        
        with open(zip_path, 'rb') as f:
            zip_data = f.read()
        
        result = self.importer.import_from_bytes(zip_data)
        
        assert result.success
        assert result.component_name == "bytes_component"
    
    def test_import_from_bytes_invalid(self):
        """Test importing from invalid ZIP bytes."""
        invalid_data = b"not a zip file"
        
        result = self.importer.import_from_bytes(invalid_data)
        
        assert not result.success
        assert "ZIP validation failed" in result.error_message or "Failed to process ZIP data" in result.error_message
    
    def test_validate_zip_file_valid(self):
        """Test validation of valid ZIP file."""
        zip_path = self.create_valid_component_zip("valid_test")
        
        result = self.importer.validate_zip_file(zip_path)
        
        assert result.is_valid
        assert len(result.errors) == 0
        assert len(result.python_files) > 0
        assert "valid_test.py" in result.python_files
    
    def test_validate_zip_file_no_python_files(self):
        """Test validation of ZIP with no Python files."""
        files = {
            "readme.txt": "This is a readme file",
            "config.json": '{"setting": "value"}'
        }
        zip_path = self.create_test_zip("no_python.zip", files)
        
        result = self.importer.validate_zip_file(zip_path)
        
        assert not result.is_valid
        assert any("no python files" in error.lower() for error in result.errors)
    
    def test_validate_zip_file_suspicious_files(self):
        """Test validation of ZIP with suspicious files."""
        files = {
            "component.py": "# Valid Python file",
            "malicious.exe": "fake executable",
            "script.bat": "echo malicious"
        }
        zip_path = self.create_test_zip("suspicious.zip", files)
        
        result = self.importer.validate_zip_file(zip_path)
        
        assert not result.is_valid
        assert len(result.suspicious_files) == 2
        assert "malicious.exe" in result.suspicious_files
        assert "script.bat" in result.suspicious_files
    
    def test_validate_zip_file_path_traversal(self):
        """Test validation of ZIP with path traversal attempts."""
        files = {
            "component.py": "# Valid Python file",
            "../../../etc/passwd": "malicious content",
            "..\\windows\\system32\\evil.dll": "windows path traversal"
        }
        zip_path = self.create_test_zip("traversal.zip", files)
        
        result = self.importer.validate_zip_file(zip_path)
        
        assert not result.is_valid
        assert any("unsafe path" in error.lower() for error in result.errors)
    
    def test_validate_zip_file_too_many_files(self):
        """Test validation of ZIP with too many files."""
        # Create ZIP with files exceeding the limit
        files = {}
        for i in range(ZipImporter.MAX_FILE_COUNT + 10):
            files[f"file_{i}.py"] = f"# File {i}"
        
        zip_path = self.create_test_zip("too_many.zip", files)
        
        result = self.importer.validate_zip_file(zip_path)
        
        assert not result.is_valid
        assert any("too many files" in error.lower() for error in result.errors)
    
    def test_validate_zip_file_file_too_large(self):
        """Test validation of ZIP with oversized file."""
        # Create a large content string
        large_content = "x" * (ZipImporter.MAX_FILE_SIZE + 1000)
        files = {
            "component.py": "# Valid Python file",
            "large_file.py": large_content
        }
        zip_path = self.create_test_zip("large_file.zip", files)
        
        result = self.importer.validate_zip_file(zip_path)
        
        assert not result.is_valid
        assert any("file too large" in error.lower() for error in result.errors)
    
    def test_validate_zip_file_invalid_format(self):
        """Test validation of invalid ZIP file."""
        # Create a non-ZIP file
        invalid_zip = os.path.join(self.temp_dir, "invalid.zip")
        with open(invalid_zip, 'w') as f:
            f.write("not a zip file")
        
        result = self.importer.validate_zip_file(invalid_zip)
        
        assert not result.is_valid
        assert any("invalid zip file" in error.lower() for error in result.errors)
    
    def test_is_safe_path_valid_paths(self):
        """Test path safety validation for valid paths."""
        safe_paths = [
            "component.py",
            "package/component.py",
            "deep/nested/folder/file.py",
            "requirements.txt"
        ]
        
        for path in safe_paths:
            assert self.importer._is_safe_path(path), f"Path should be safe: {path}"
    
    def test_is_safe_path_unsafe_paths(self):
        """Test path safety validation for unsafe paths."""
        unsafe_paths = [
            "../component.py",
            "/absolute/path.py",
            "folder/../../../etc/passwd",
            "..\\windows\\system32\\file.dll",
            "C:\\windows\\system32\\file.exe",
            "folder/../../file.py"
        ]
        
        for path in unsafe_paths:
            assert not self.importer._is_safe_path(path), f"Path should be unsafe: {path}"
    
    def test_find_main_component_python_file(self):
        """Test finding main component when it's a Python file."""
        # Create test directory structure
        test_dir = Path(self.temp_dir) / "extracted"
        test_dir.mkdir()
        
        # Create Python files
        (test_dir / "component.py").write_text("# Component file")
        (test_dir / "helper.py").write_text("# Helper file")
        
        result = self.importer._find_main_component(test_dir)
        
        assert result is not None
        assert result.name == "component.py"
    
    def test_find_main_component_package(self):
        """Test finding main component when it's a package."""
        # Create test directory structure
        test_dir = Path(self.temp_dir) / "extracted"
        test_dir.mkdir()
        
        package_dir = test_dir / "test_package"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("# Package init")
        
        result = self.importer._find_main_component(test_dir)
        
        assert result is not None
        assert result.name == "test_package"
        assert result.is_dir()
    
    def test_find_main_component_none_found(self):
        """Test finding main component when none exists."""
        # Create test directory with no Python files
        test_dir = Path(self.temp_dir) / "extracted"
        test_dir.mkdir()
        
        (test_dir / "readme.txt").write_text("No Python files here")
        
        result = self.importer._find_main_component(test_dir)
        
        assert result is None
    
    def test_extract_component_metadata_file(self):
        """Test extracting metadata from component file."""
        # Create component file
        component_file = Path(self.temp_dir) / "test_component.py"
        component_file.write_text('''
from component_base import BaseComponent

class TestComponent(BaseComponent):
    name = "metadata_test"
    description = "Test component for metadata"
    requirements = ["requests", "numpy"]
    
    def render(self):
        pass
''')
        
        metadata = self.importer._extract_component_metadata(component_file)
        
        assert metadata is not None
        assert metadata.name == "metadata_test"
        assert metadata.description == "Test component for metadata"
        assert "requests" in metadata.requirements
        assert "numpy" in metadata.requirements
        assert not metadata.is_package
    
    def test_extract_component_metadata_package(self):
        """Test extracting metadata from component package."""
        # Create package structure
        package_dir = Path(self.temp_dir) / "test_package"
        package_dir.mkdir()
        
        init_file = package_dir / "__init__.py"
        init_file.write_text('''
from component_base import BaseComponent

class TestPackageComponent(BaseComponent):
    name = "package_test"
    description = "Test package component"
    requirements = ["pandas"]
    
    def render(self):
        pass
''')
        
        req_file = package_dir / "requirements.txt"
        req_file.write_text("matplotlib>=3.0.0\n")
        
        metadata = self.importer._extract_component_metadata(package_dir)
        
        assert metadata is not None
        assert metadata.name == "package_test"
        assert metadata.is_package
        assert "pandas" in metadata.requirements
        assert "matplotlib>=3.0.0" in metadata.requirements
    
    def test_extract_component_metadata_invalid(self):
        """Test extracting metadata from invalid file."""
        # Create invalid Python file
        invalid_file = Path(self.temp_dir) / "invalid.py"
        invalid_file.write_text("invalid python syntax!")
        
        metadata = self.importer._extract_component_metadata(invalid_file)
        
        assert metadata is None
    
    def test_extract_ast_value(self):
        """Test AST value extraction."""
        import ast
        
        # Test string constant
        string_node = ast.Constant(value="test_string")
        assert self.importer._extract_ast_value(string_node) == "test_string"
        
        # Test list
        list_node = ast.List(elts=[ast.Constant(value="item1"), ast.Constant(value="item2")])
        assert self.importer._extract_ast_value(list_node) == ["item1", "item2"]
        
        # Test unsupported node
        name_node = ast.Name(id="variable")
        assert self.importer._extract_ast_value(name_node) is None
    
    def test_get_zip_info(self):
        """Test getting ZIP file information."""
        zip_path = self.create_valid_component_zip("info_test")
        
        info = self.importer.get_zip_info(zip_path)
        
        assert 'file_count' in info
        assert 'total_size' in info
        assert 'python_files' in info
        assert info['file_count'] == 2  # component.py + requirements.txt
        assert len(info['python_files']) == 1
        assert info['has_requirements']
    
    def test_get_zip_info_invalid_file(self):
        """Test getting info from invalid ZIP file."""
        invalid_zip = os.path.join(self.temp_dir, "invalid.zip")
        with open(invalid_zip, 'w') as f:
            f.write("not a zip file")
        
        info = self.importer.get_zip_info(invalid_zip)
        
        assert 'error' in info
    
    def test_cleanup_temp_dirs(self):
        """Test cleanup of temporary directories."""
        # Create some temporary directories
        temp_dir1 = tempfile.mkdtemp(prefix="test_cleanup_")
        temp_dir2 = tempfile.mkdtemp(prefix="test_cleanup_")
        
        self.importer.temp_dirs.add(temp_dir1)
        self.importer.temp_dirs.add(temp_dir2)
        
        # Verify directories exist
        assert os.path.exists(temp_dir1)
        assert os.path.exists(temp_dir2)
        
        # Cleanup
        self.importer.cleanup_temp_dirs()
        
        # Verify directories are removed
        assert not os.path.exists(temp_dir1)
        assert not os.path.exists(temp_dir2)
        assert len(self.importer.temp_dirs) == 0
    
    def test_extract_to_specific_directory(self):
        """Test extracting to a specific directory."""
        zip_path = self.create_valid_component_zip("extract_test")
        extract_dir = os.path.join(self.temp_dir, "custom_extract")
        
        result = self.importer.import_from_file(zip_path, extract_dir)
        
        assert result.success
        assert os.path.exists(extract_dir)
        assert extract_dir in result.extracted_path
    
    def test_security_file_permissions(self):
        """Test that extracted files have safe permissions."""
        zip_path = self.create_valid_component_zip("permissions_test")
        
        result = self.importer.import_from_file(zip_path)
        
        assert result.success
        
        # Check that the extracted Python file has safe permissions
        extracted_file = Path(result.extracted_path)
        if extracted_file.is_file():
            # On Unix systems, check that execute bit is not set
            if hasattr(os, 'stat'):
                import stat
                file_mode = os.stat(extracted_file).st_mode
                # Should not have execute permissions
                assert not (file_mode & stat.S_IXUSR)
    
    def test_multiple_imports_temp_cleanup(self):
        """Test that multiple imports properly manage temporary directories."""
        # Perform multiple imports
        for i in range(3):
            zip_path = self.create_valid_component_zip(f"multi_test_{i}")
            result = self.importer.import_from_file(zip_path)
            assert result.success
        
        # Should have created temporary directories
        assert len(self.importer.temp_dirs) == 3
        
        # Cleanup should remove all
        self.importer.cleanup_temp_dirs()
        assert len(self.importer.temp_dirs) == 0


if __name__ == "__main__":
    pytest.main([__file__])