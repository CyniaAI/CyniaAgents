"""
Unit tests for the ComponentLoader class.

Tests cover safe component loading, metadata extraction, validation,
and error handling scenarios.
"""

import os
import sys
import tempfile
import shutil
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from unittest import mock
import pytest

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hot_reload.loader import ComponentLoader, LoadResult, ValidationResult
from hot_reload.models import ComponentMetadata, ComponentStatus
from hot_reload.errors import ErrorHandler


class TestComponentLoader:
    """Test cases for ComponentLoader class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = Path(self.temp_dir) / "components"
        self.components_dir.mkdir()
        self.error_handler = Mock(spec=ErrorHandler)
        self.loader = ComponentLoader(str(self.components_dir), self.error_handler)
    
    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def create_test_component_file(self, name: str, content: str = None) -> Path:
        """Create a test component file."""
        if content is None:
            content = f'''
from component_base import BaseComponent

class TestComponent(BaseComponent):
    name = "{name}"
    description = "Test component"
    requirements = ["requests"]
    
    def render(self):
        pass

def get_component():
    return TestComponent()
'''
        
        component_file = self.components_dir / f"{name}.py"
        component_file.write_text(content)
        return component_file
    
    def create_test_component_package(self, name: str, use_init: bool = True) -> Path:
        """Create a test component package."""
        package_dir = self.components_dir / name
        package_dir.mkdir()
        
        main_file = package_dir / ("__init__.py" if use_init else "main.py")
        content = f'''
from component_base import BaseComponent

class TestComponent(BaseComponent):
    name = "{name}"
    description = "Test package component"
    requirements = ["numpy", "pandas"]
    
    def render(self):
        pass

def get_component():
    return TestComponent()
'''
        main_file.write_text(content)
        
        # Add requirements.txt
        req_file = package_dir / "requirements.txt"
        req_file.write_text("requests>=2.25.0\nnumpy>=1.20.0\n")
        
        return package_dir
    
    def create_test_zip(self, component_name: str) -> bytes:
        """Create a test ZIP file containing a component."""
        import io
        
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            content = f'''
from component_base import BaseComponent

class TestComponent(BaseComponent):
    name = "{component_name}"
    description = "Test ZIP component"
    requirements = ["requests"]
    
    def render(self):
        pass

def get_component():
    return TestComponent()
'''
            zip_file.writestr(f"{component_name}.py", content)
        
        return zip_buffer.getvalue()
    
    def test_init(self):
        """Test ComponentLoader initialization."""
        assert self.loader.components_dir == self.components_dir
        assert self.loader.error_handler == self.error_handler
        assert isinstance(self.loader.loaded_modules, dict)
        assert isinstance(self.loader.component_cache, dict)
        assert self.components_dir.exists()
    
    def test_load_component_from_path_file_success(self):
        """Test successful loading of a component file."""
        # Create test component
        component_file = self.create_test_component_file("test_component")
        
        # Mock the module loading to avoid actual imports
        with patch.object(self.loader, '_load_module_safely') as mock_load, \
             patch.object(self.loader, '_validate_loaded_component') as mock_validate:
            
            mock_module = Mock()
            mock_load.return_value = mock_module
            mock_validate.return_value = Mock()
            
            result = self.loader.load_component_from_path(str(component_file))
            
            assert result.success
            assert result.component_name == "test_component"
            assert result.metadata is not None
            assert result.metadata.name == "test_component"
            assert result.metadata.description == "Test component"
            assert "requests" in result.metadata.requirements
            assert result.load_time > 0
    
    def test_load_component_from_path_package_success(self):
        """Test successful loading of a component package."""
        # Create test package
        package_dir = self.create_test_component_package("test_package")
        
        # Mock the module loading
        with patch.object(self.loader, '_load_module_safely') as mock_load, \
             patch.object(self.loader, '_validate_loaded_component') as mock_validate:
            
            mock_module = Mock()
            mock_load.return_value = mock_module
            mock_validate.return_value = Mock()
            
            result = self.loader.load_component_from_path(str(package_dir))
            
            assert result.success
            assert result.component_name == "test_package"
            assert result.metadata is not None
            assert result.metadata.is_package
            assert result.metadata.package_path == str(package_dir)
    
    def test_load_component_from_path_nonexistent(self):
        """Test loading from non-existent path."""
        result = self.loader.load_component_from_path("/nonexistent/path")
        
        assert not result.success
        assert "does not exist" in result.error_message
    
    def test_load_component_from_path_validation_failure(self):
        """Test loading with validation failure."""
        # Create component with syntax error
        component_file = self.create_test_component_file(
            "bad_component", 
            "invalid python syntax here!"
        )
        
        result = self.loader.load_component_from_path(str(component_file))
        
        assert not result.success
        assert "validation failed" in result.error_message.lower()
    
    def test_load_component_from_zip_success(self):
        """Test successful loading from ZIP file."""
        zip_data = self.create_test_zip("zip_component")
        
        with patch.object(self.loader, '_load_module_safely') as mock_load, \
             patch.object(self.loader, '_validate_loaded_component') as mock_validate:
            
            mock_module = Mock()
            mock_load.return_value = mock_module
            mock_validate.return_value = Mock()
            
            result = self.loader.load_component_from_zip(zip_data)
            
            assert result.success
            assert result.component_name == "zip_component"
    
    def test_load_component_from_zip_invalid(self):
        """Test loading from invalid ZIP data."""
        invalid_zip = b"not a zip file"
        
        result = self.loader.load_component_from_zip(invalid_zip)
        
        assert not result.success
        assert "Failed to extract ZIP" in result.error_message
    
    def test_validate_component_structure_file_valid(self):
        """Test validation of valid component file."""
        component_file = self.create_test_component_file("valid_component")
        
        result = self.loader.validate_component_structure(str(component_file))
        
        assert result.is_valid
        assert len(result.errors) == 0
    
    def test_validate_component_structure_file_syntax_error(self):
        """Test validation of file with syntax error."""
        component_file = self.create_test_component_file(
            "syntax_error", 
            "def invalid_syntax(\n    pass"
        )
        
        result = self.loader.validate_component_structure(str(component_file))
        
        assert not result.is_valid
        assert any("syntax error" in error.lower() for error in result.errors)
    
    def test_validate_component_structure_package_valid(self):
        """Test validation of valid component package."""
        package_dir = self.create_test_component_package("valid_package")
        
        result = self.loader.validate_component_structure(str(package_dir))
        
        assert result.is_valid
        assert len(result.errors) == 0
    
    def test_validate_component_structure_package_no_main(self):
        """Test validation of package without main file."""
        package_dir = self.components_dir / "no_main_package"
        package_dir.mkdir()
        
        result = self.loader.validate_component_structure(str(package_dir))
        
        assert not result.is_valid
        assert any("__init__.py or main.py" in error for error in result.errors)
    
    def test_validate_component_structure_nonexistent(self):
        """Test validation of non-existent path."""
        result = self.loader.validate_component_structure("/nonexistent/path")
        
        assert not result.is_valid
        assert any("does not exist" in error for error in result.errors)
    
    def test_extract_component_metadata_file(self):
        """Test metadata extraction from component file."""
        component_file = self.create_test_component_file("metadata_test")
        
        metadata = self.loader.extract_component_metadata(str(component_file))
        
        assert metadata is not None
        assert metadata.name == "metadata_test"
        assert metadata.description == "Test component"
        assert "requests" in metadata.requirements
        assert metadata.file_path == str(component_file)
        assert not metadata.is_package
        assert metadata.checksum != ""
    
    def test_extract_component_metadata_package(self):
        """Test metadata extraction from component package."""
        package_dir = self.create_test_component_package("metadata_package")
        
        metadata = self.loader.extract_component_metadata(str(package_dir))
        
        assert metadata is not None
        assert metadata.name == "metadata_package"
        assert metadata.description == "Test package component"
        assert metadata.is_package
        assert metadata.package_path == str(package_dir)
        # Should include requirements from both class and requirements.txt
        assert "numpy" in metadata.requirements or "pandas" in metadata.requirements
    
    def test_extract_component_metadata_invalid_file(self):
        """Test metadata extraction from invalid file."""
        invalid_file = self.components_dir / "invalid.py"
        invalid_file.write_text("invalid python syntax!")
        
        metadata = self.loader.extract_component_metadata(str(invalid_file))
        
        # Should return None for invalid files
        assert metadata is None
    
    def test_extract_ast_value(self):
        """Test AST value extraction."""
        import ast
        
        # Test string constant
        string_node = ast.Constant(value="test_string")
        assert self.loader._extract_ast_value(string_node) == "test_string"
        
        # Test list
        list_node = ast.List(elts=[ast.Constant(value="item1"), ast.Constant(value="item2")])
        assert self.loader._extract_ast_value(list_node) == ["item1", "item2"]
        
        # Test unsupported node
        name_node = ast.Name(id="variable")
        assert self.loader._extract_ast_value(name_node) is None
    
    def test_read_requirements_file(self):
        """Test reading requirements.txt file."""
        req_file = self.components_dir / "requirements.txt"
        req_file.write_text("requests>=2.25.0\nnumpy\n# comment\n\npandas>=1.0.0\n")
        
        requirements = self.loader._read_requirements_file(str(req_file))
        
        assert "requests>=2.25.0" in requirements
        assert "numpy" in requirements
        assert "pandas>=1.0.0" in requirements
        assert len(requirements) == 3  # Should exclude comment and empty lines
    
    def test_read_requirements_file_nonexistent(self):
        """Test reading non-existent requirements file."""
        requirements = self.loader._read_requirements_file("/nonexistent/requirements.txt")
        
        assert requirements == []
    
    def test_calculate_file_checksum(self):
        """Test file checksum calculation."""
        test_file = self.components_dir / "test.txt"
        test_file.write_text("test content")
        
        checksum1 = self.loader._calculate_file_checksum(str(test_file))
        checksum2 = self.loader._calculate_file_checksum(str(test_file))
        
        assert checksum1 == checksum2
        assert len(checksum1) == 64  # SHA-256 hex length
        
        # Change content and verify checksum changes
        test_file.write_text("different content")
        checksum3 = self.loader._calculate_file_checksum(str(test_file))
        
        assert checksum1 != checksum3
    
    def test_calculate_file_checksum_nonexistent(self):
        """Test checksum calculation for non-existent file."""
        checksum = self.loader._calculate_file_checksum("/nonexistent/file.txt")
        
        assert checksum == ""
    
    def test_is_safe_path(self):
        """Test path safety validation."""
        # Safe paths
        assert self.loader._is_safe_path("component.py")
        assert self.loader._is_safe_path("folder/component.py")
        assert self.loader._is_safe_path("deep/nested/folder/component.py")
        
        # Unsafe paths
        assert not self.loader._is_safe_path("../component.py")
        assert not self.loader._is_safe_path("/absolute/path.py")
        assert not self.loader._is_safe_path("folder/../../../etc/passwd")
        assert not self.loader._is_safe_path("\\windows\\path.py")
    
    def test_validate_zip_contents_valid(self):
        """Test validation of valid ZIP contents."""
        import io
        
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr("component.py", "# Valid Python file")
            zip_file.writestr("requirements.txt", "requests")
        
        zip_buffer.seek(0)
        with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
            result = self.loader._validate_zip_contents(zip_ref)
            
            assert result.success
    
    def test_validate_zip_contents_suspicious_file(self):
        """Test validation of ZIP with suspicious files."""
        import io
        
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr("component.py", "# Valid Python file")
            zip_file.writestr("malicious.exe", "fake executable")
        
        zip_buffer.seek(0)
        with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
            result = self.loader._validate_zip_contents(zip_ref)
            
            assert not result.success
            assert "suspicious file type" in result.error_message.lower()
    
    def test_validate_zip_contents_path_traversal(self):
        """Test validation of ZIP with path traversal attempt."""
        import io
        
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr("../../../etc/passwd", "malicious content")
        
        zip_buffer.seek(0)
        with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
            result = self.loader._validate_zip_contents(zip_ref)
            
            assert not result.success
            assert "unsafe path" in result.error_message.lower()
    
    def test_validate_zip_contents_no_python_files(self):
        """Test validation of ZIP without Python files."""
        import io
        
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr("readme.txt", "No Python files here")
        
        zip_buffer.seek(0)
        with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
            result = self.loader._validate_zip_contents(zip_ref)
            
            assert not result.success
            assert "no python files" in result.error_message.lower()
    
    def test_find_component_in_directory(self):
        """Test finding component in extracted directory."""
        # Create test directory structure
        test_dir = self.components_dir / "extracted"
        test_dir.mkdir()
        
        # Test with Python file in root
        py_file = test_dir / "component.py"
        py_file.write_text("# Python component")
        
        result = self.loader._find_component_in_directory(test_dir)
        assert result == py_file
        
        # Clean up and test with package
        py_file.unlink()
        package_dir = test_dir / "package"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("# Package component")
        
        result = self.loader._find_component_in_directory(test_dir)
        assert result == package_dir
    
    def test_find_component_in_directory_empty(self):
        """Test finding component in empty directory."""
        empty_dir = self.components_dir / "empty"
        empty_dir.mkdir()
        
        result = self.loader._find_component_in_directory(empty_dir)
        assert result is None
    
    def test_get_loaded_component(self):
        """Test getting loaded component."""
        # Add mock component to cache
        mock_module = Mock()
        self.loader.loaded_modules["test_component"] = mock_module
        
        result = self.loader.get_loaded_component("test_component")
        assert result == mock_module
        
        # Test non-existent component
        result = self.loader.get_loaded_component("nonexistent")
        assert result is None
    
    def test_get_component_metadata(self):
        """Test getting component metadata."""
        # Add mock metadata to cache
        mock_metadata = Mock(spec=ComponentMetadata)
        self.loader.component_cache["test_component"] = mock_metadata
        
        result = self.loader.get_component_metadata("test_component")
        assert result == mock_metadata
        
        # Test non-existent component
        result = self.loader.get_component_metadata("nonexistent")
        assert result is None
    
    def test_unload_component(self):
        """Test component unloading."""
        # Add mock data to caches
        mock_module = Mock()
        mock_metadata = Mock(spec=ComponentMetadata)
        
        self.loader.loaded_modules["test_component"] = mock_module
        self.loader.component_cache["test_component"] = mock_metadata
        
        # Mock sys.modules
        with patch.dict(sys.modules, {"components.test_component": mock_module}):
            result = self.loader.unload_component("test_component")
            
            assert result
            assert "test_component" not in self.loader.loaded_modules
            assert "test_component" not in self.loader.component_cache
    
    def test_unload_component_error(self):
        """Test component unloading with error."""
        # Create a mock dictionary that raises an exception on __contains__
        error_dict = Mock()
        error_dict.__contains__ = Mock(side_effect=Exception("Dictionary error"))
        
        # Replace the loaded_modules with our error dict
        self.loader.loaded_modules = error_dict
        
        result = self.loader.unload_component("test_component")
        
        # Should handle error gracefully and return False
        assert not result
        # Should call error handler
        self.error_handler.handle_component_error.assert_called_once_with(
            "test_component", "unload", mock.ANY
        )
    
    def test_list_available_components(self):
        """Test listing available components."""
        # Create test components
        self.create_test_component_file("component1")
        self.create_test_component_file("component2")
        self.create_test_component_package("package1")
        
        # Create __init__.py (should be ignored)
        (self.components_dir / "__init__.py").write_text("")
        
        components = self.loader.list_available_components()
        
        assert "component1" in components
        assert "component2" in components
        assert "package1" in components
        assert "__init__" not in components
        assert len(components) == 3
    
    def test_list_available_components_empty_dir(self):
        """Test listing components in empty directory."""
        # Remove the components directory
        shutil.rmtree(self.components_dir)
        
        components = self.loader.list_available_components()
        
        assert components == []


if __name__ == "__main__":
    pytest.main([__file__])