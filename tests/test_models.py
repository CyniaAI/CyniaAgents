"""
Unit tests for hot reload data models and validation.

This module tests all data classes, enums, and validation functions
in the hot_reload.models module.
"""

import pytest
import os
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

from hot_reload.models import (
    ComponentStatus, DependencyStatus, OperationType,
    ComponentMetadata, DependencyInfo, ReloadResult, InstallationResult,
    ComponentState, ValidationError,
    validate_component_name, validate_requirements_list, validate_file_path
)


class TestEnums:
    """Test cases for enum classes."""
    
    def test_component_status_values(self):
        """Test ComponentStatus enum values."""
        assert ComponentStatus.UNKNOWN.value == "unknown"
        assert ComponentStatus.LOADING.value == "loading"
        assert ComponentStatus.LOADED.value == "loaded"
        assert ComponentStatus.FAILED.value == "failed"
        assert ComponentStatus.RELOADING.value == "reloading"
        assert ComponentStatus.UNLOADING.value == "unloading"
        assert ComponentStatus.UNLOADED.value == "unloaded"
        assert ComponentStatus.DISABLED.value == "disabled"
    
    def test_dependency_status_values(self):
        """Test DependencyStatus enum values."""
        assert DependencyStatus.UNKNOWN.value == "unknown"
        assert DependencyStatus.CHECKING.value == "checking"
        assert DependencyStatus.SATISFIED.value == "satisfied"
        assert DependencyStatus.MISSING.value == "missing"
        assert DependencyStatus.INSTALLING.value == "installing"
        assert DependencyStatus.FAILED.value == "failed"
        assert DependencyStatus.CONFLICT.value == "conflict"
    
    def test_operation_type_values(self):
        """Test OperationType enum values."""
        assert OperationType.LOAD.value == "load"
        assert OperationType.RELOAD.value == "reload"
        assert OperationType.UNLOAD.value == "unload"
        assert OperationType.INSTALL_DEPENDENCIES.value == "install_dependencies"
        assert OperationType.DISCOVER.value == "discover"
        assert OperationType.VALIDATE.value == "validate"


class TestComponentMetadata:
    """Test cases for ComponentMetadata data class."""
    
    def test_basic_creation(self):
        """Test basic ComponentMetadata creation."""
        metadata = ComponentMetadata(
            name="test_component",
            description="A test component",
            version="1.0.0",
            author="Test Author"
        )
        
        assert metadata.name == "test_component"
        assert metadata.description == "A test component"
        assert metadata.version == "1.0.0"
        assert metadata.author == "Test Author"
        assert metadata.requirements == []
        assert isinstance(metadata.created_at, datetime)
        assert isinstance(metadata.modified_at, datetime)
    
    def test_creation_with_requirements(self):
        """Test ComponentMetadata creation with requirements."""
        requirements = ["requests>=2.25.0", "numpy"]
        metadata = ComponentMetadata(
            name="test_component",
            requirements=requirements
        )
        
        assert metadata.requirements == requirements
    
    def test_creation_with_file_path(self):
        """Test ComponentMetadata creation with file path."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("# Test component")
            temp_path = f.name
        
        try:
            metadata = ComponentMetadata(
                name="test_component",
                file_path=temp_path
            )
            
            assert metadata.file_path == temp_path
            assert metadata.size_bytes > 0
            assert isinstance(metadata.modified_at, datetime)
        finally:
            os.unlink(temp_path)
    
    def test_empty_name_validation(self):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="Component name cannot be empty"):
            ComponentMetadata(name="")
    
    def test_is_valid(self):
        """Test metadata validation."""
        # Valid metadata
        valid_metadata = ComponentMetadata(name="test_component")
        assert valid_metadata.is_valid()
        
        # Invalid metadata - empty name (create object and then modify)
        invalid_metadata = ComponentMetadata(name="test_component")
        invalid_metadata.name = ""  # Modify after creation
        assert not invalid_metadata.is_valid()
        
        # Invalid metadata - non-existent file
        invalid_file_metadata = ComponentMetadata(
            name="test_component",
            file_path="/non/existent/path.py"
        )
        assert not invalid_file_metadata.is_valid()
    
    def test_get_display_name(self):
        """Test display name generation."""
        metadata = ComponentMetadata(name="test_component_name")
        assert metadata.get_display_name() == "Test Component Name"
    
    def test_has_requirements(self):
        """Test requirements checking."""
        # No requirements
        metadata_no_req = ComponentMetadata(name="test")
        assert not metadata_no_req.has_requirements()
        
        # With requirements
        metadata_with_req = ComponentMetadata(
            name="test",
            requirements=["requests"]
        )
        assert metadata_with_req.has_requirements()
    
    def test_to_dict_and_from_dict(self):
        """Test serialization and deserialization."""
        original = ComponentMetadata(
            name="test_component",
            description="Test description",
            version="2.0.0",
            requirements=["requests", "numpy"],
            tags=["test", "example"]
        )
        
        # Convert to dict
        data = original.to_dict()
        assert isinstance(data, dict)
        assert data['name'] == "test_component"
        assert data['version'] == "2.0.0"
        assert data['requirements'] == ["requests", "numpy"]
        
        # Convert back from dict
        restored = ComponentMetadata.from_dict(data)
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.version == original.version
        assert restored.requirements == original.requirements
        assert restored.tags == original.tags


class TestDependencyInfo:
    """Test cases for DependencyInfo data class."""
    
    def test_basic_creation(self):
        """Test basic DependencyInfo creation."""
        dep = DependencyInfo(
            name="requests",
            version_spec=">=2.25.0",
            status=DependencyStatus.SATISFIED
        )
        
        assert dep.name == "requests"
        assert dep.version_spec == ">=2.25.0"
        assert dep.status == DependencyStatus.SATISFIED
        assert not dep.is_optional
    
    def test_empty_name_validation(self):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="Dependency name cannot be empty"):
            DependencyInfo(name="")
    
    def test_is_satisfied(self):
        """Test satisfaction checking."""
        satisfied_dep = DependencyInfo(
            name="requests",
            status=DependencyStatus.SATISFIED
        )
        assert satisfied_dep.is_satisfied()
        
        missing_dep = DependencyInfo(
            name="missing_package",
            status=DependencyStatus.MISSING
        )
        assert not missing_dep.is_satisfied()
    
    def test_needs_installation(self):
        """Test installation need checking."""
        missing_dep = DependencyInfo(
            name="missing_package",
            status=DependencyStatus.MISSING
        )
        assert missing_dep.needs_installation()
        
        failed_dep = DependencyInfo(
            name="failed_package",
            status=DependencyStatus.FAILED
        )
        assert failed_dep.needs_installation()
        
        satisfied_dep = DependencyInfo(
            name="satisfied_package",
            status=DependencyStatus.SATISFIED
        )
        assert not satisfied_dep.needs_installation()
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        dep = DependencyInfo(
            name="requests",
            version_spec=">=2.25.0",
            status=DependencyStatus.SATISFIED,
            installed_version="2.26.0",
            is_optional=True
        )
        
        data = dep.to_dict()
        assert data['name'] == "requests"
        assert data['version_spec'] == ">=2.25.0"
        assert data['status'] == "satisfied"
        assert data['installed_version'] == "2.26.0"
        assert data['is_optional'] is True


class TestReloadResult:
    """Test cases for ReloadResult data class."""
    
    def test_basic_creation(self):
        """Test basic ReloadResult creation."""
        result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNLOADED
        )
        
        assert result.component_name == "test_component"
        assert result.operation == OperationType.RELOAD
        assert result.success is True
        assert result.status == ComponentStatus.LOADED
        assert result.previous_status == ComponentStatus.UNLOADED
        assert isinstance(result.timestamp, datetime)
    
    def test_empty_component_name_validation(self):
        """Test that empty component name raises ValueError."""
        with pytest.raises(ValueError, match="Component name cannot be empty"):
            ReloadResult(
                component_name="",
                operation=OperationType.LOAD,
                success=True,
                status=ComponentStatus.LOADED,
                previous_status=ComponentStatus.UNKNOWN
            )
    
    def test_is_successful(self):
        """Test success checking."""
        successful_result = ReloadResult(
            component_name="test",
            operation=OperationType.LOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNKNOWN
        )
        assert successful_result.is_successful()
        
        failed_result = ReloadResult(
            component_name="test",
            operation=OperationType.LOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.UNKNOWN
        )
        assert not failed_result.is_successful()
        
        # Success=True but failed status
        mixed_result = ReloadResult(
            component_name="test",
            operation=OperationType.LOAD,
            success=True,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.UNKNOWN
        )
        assert not mixed_result.is_successful()
    
    def test_has_warnings(self):
        """Test warning detection."""
        result_no_warnings = ReloadResult(
            component_name="test",
            operation=OperationType.LOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNKNOWN
        )
        assert not result_no_warnings.has_warnings()
        
        result_with_warnings = ReloadResult(
            component_name="test",
            operation=OperationType.LOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNKNOWN,
            warnings=["Warning 1", "Warning 2"]
        )
        assert result_with_warnings.has_warnings()
    
    def test_get_summary(self):
        """Test summary generation."""
        # Successful operation
        success_result = ReloadResult(
            component_name="test",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNKNOWN,
            duration=1.5
        )
        summary = success_result.get_summary()
        assert "Reload succeeded" in summary
        assert "1.50s" in summary
        
        # Failed operation with error
        failed_result = ReloadResult(
            component_name="test",
            operation=OperationType.LOAD,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.UNKNOWN,
            error_message="Import failed"
        )
        summary = failed_result.get_summary()
        assert "Load failed" in summary
        assert "Import failed" in summary
        
        # Operation with warnings
        warning_result = ReloadResult(
            component_name="test",
            operation=OperationType.LOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNKNOWN,
            warnings=["Warning 1", "Warning 2"]
        )
        summary = warning_result.get_summary()
        assert "Load succeeded" in summary
        assert "2 warning(s)" in summary
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        metadata = ComponentMetadata(name="test_component")
        dependencies = [DependencyInfo(name="requests")]
        
        result = ReloadResult(
            component_name="test_component",
            operation=OperationType.RELOAD,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNLOADED,
            duration=2.5,
            warnings=["Test warning"],
            metadata=metadata,
            dependencies=dependencies
        )
        
        data = result.to_dict()
        assert data['component_name'] == "test_component"
        assert data['operation'] == "reload"
        assert data['success'] is True
        assert data['status'] == "loaded"
        assert data['previous_status'] == "unloaded"
        assert data['duration'] == 2.5
        assert data['warnings'] == ["Test warning"]
        assert data['metadata'] is not None
        assert len(data['dependencies']) == 1


class TestInstallationResult:
    """Test cases for InstallationResult data class."""
    
    def test_basic_creation(self):
        """Test basic InstallationResult creation."""
        dependencies = [DependencyInfo(name="requests")]
        result = InstallationResult(
            component_name="test_component",
            dependencies=dependencies,
            success=True
        )
        
        assert result.component_name == "test_component"
        assert result.dependencies == dependencies
        assert result.success is True
        assert isinstance(result.timestamp, datetime)
    
    def test_empty_component_name_validation(self):
        """Test that empty component name raises ValueError."""
        with pytest.raises(ValueError, match="Component name cannot be empty"):
            InstallationResult(
                component_name="",
                dependencies=[],
                success=True
            )
    
    def test_is_successful(self):
        """Test success checking."""
        # Successful with no failed packages
        success_result = InstallationResult(
            component_name="test",
            dependencies=[],
            success=True,
            installed_packages=["requests"],
            failed_packages=[]
        )
        assert success_result.is_successful()
        
        # Success=True but has failed packages
        mixed_result = InstallationResult(
            component_name="test",
            dependencies=[],
            success=True,
            failed_packages=["missing_package"]
        )
        assert not mixed_result.is_successful()
        
        # Failed result
        failed_result = InstallationResult(
            component_name="test",
            dependencies=[],
            success=False
        )
        assert not failed_result.is_successful()
    
    def test_get_counts(self):
        """Test package count methods."""
        result = InstallationResult(
            component_name="test",
            dependencies=[],
            success=True,
            installed_packages=["requests", "numpy"],
            failed_packages=["missing_package"]
        )
        
        assert result.get_installed_count() == 2
        assert result.get_failed_count() == 1
    
    def test_get_summary(self):
        """Test summary generation."""
        # Successful installation
        success_result = InstallationResult(
            component_name="test",
            dependencies=[],
            success=True,
            installed_packages=["requests", "numpy"]
        )
        summary = success_result.get_summary()
        assert "Installed 2 package(s) successfully" in summary
        
        # No packages to install
        no_install_result = InstallationResult(
            component_name="test",
            dependencies=[],
            success=True,
            installed_packages=[]
        )
        summary = no_install_result.get_summary()
        assert "All dependencies already satisfied" in summary
        
        # Failed installation
        failed_result = InstallationResult(
            component_name="test",
            dependencies=[],
            success=False,
            failed_packages=["missing1", "missing2"]
        )
        summary = failed_result.get_summary()
        assert "Failed to install 2 package(s)" in summary
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        dependencies = [DependencyInfo(name="requests")]
        result = InstallationResult(
            component_name="test_component",
            dependencies=dependencies,
            success=True,
            duration=5.0,
            installed_packages=["requests"],
            installation_log=["Installing requests..."]
        )
        
        data = result.to_dict()
        assert data['component_name'] == "test_component"
        assert data['success'] is True
        assert data['duration'] == 5.0
        assert data['installed_packages'] == ["requests"]
        assert data['installation_log'] == ["Installing requests..."]
        assert len(data['dependencies']) == 1


class TestComponentState:
    """Test cases for ComponentState data class."""
    
    def test_basic_creation(self):
        """Test basic ComponentState creation."""
        state = ComponentState(
            name="test_component",
            status=ComponentStatus.LOADED
        )
        
        assert state.name == "test_component"
        assert state.status == ComponentStatus.LOADED
        assert state.dependencies == []
        assert state.load_count == 0
        assert state.error_count == 0
        assert state.is_enabled is True
        assert isinstance(state.module_references, set)
    
    def test_empty_name_validation(self):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="Component name cannot be empty"):
            ComponentState(name="", status=ComponentStatus.UNKNOWN)
    
    def test_status_checks(self):
        """Test status checking methods."""
        loaded_state = ComponentState(
            name="test",
            status=ComponentStatus.LOADED
        )
        assert loaded_state.is_loaded()
        assert not loaded_state.is_failed()
        
        failed_state = ComponentState(
            name="test",
            status=ComponentStatus.FAILED
        )
        assert not failed_state.is_loaded()
        assert failed_state.is_failed()
    
    def test_error_tracking(self):
        """Test error tracking methods."""
        state = ComponentState(
            name="test",
            status=ComponentStatus.LOADED
        )
        
        # Initially no errors
        assert not state.has_errors()
        
        # Add error count
        state.error_count = 1
        assert state.has_errors()
        
        # Reset and add error message
        state.error_count = 0
        state.last_error = "Test error"
        assert state.has_errors()
    
    def test_dependency_management(self):
        """Test dependency management methods."""
        satisfied_dep = DependencyInfo(
            name="requests",
            status=DependencyStatus.SATISFIED
        )
        missing_dep = DependencyInfo(
            name="missing",
            status=DependencyStatus.MISSING
        )
        
        state = ComponentState(
            name="test",
            status=ComponentStatus.LOADED,
            dependencies=[satisfied_dep, missing_dep]
        )
        
        assert state.needs_dependencies()
        unsatisfied = state.get_unsatisfied_dependencies()
        assert len(unsatisfied) == 1
        assert unsatisfied[0].name == "missing"
        
        # Test with all satisfied dependencies
        state_satisfied = ComponentState(
            name="test",
            status=ComponentStatus.LOADED,
            dependencies=[satisfied_dep]
        )
        assert not state_satisfied.needs_dependencies()
    
    def test_update_status(self):
        """Test status update method."""
        state = ComponentState(
            name="test",
            status=ComponentStatus.UNKNOWN
        )
        
        # Update to loaded
        state.update_status(ComponentStatus.LOADED)
        assert state.status == ComponentStatus.LOADED
        assert state.load_count == 1
        assert state.last_loaded is not None
        
        # Update to failed with error
        state.update_status(ComponentStatus.FAILED, "Test error")
        assert state.status == ComponentStatus.FAILED
        assert state.error_count == 1
        assert state.last_error == "Test error"
    
    def test_module_reference_management(self):
        """Test module reference management."""
        state = ComponentState(
            name="test",
            status=ComponentStatus.LOADED
        )
        
        # Add references
        state.add_module_reference("test.module1")
        state.add_module_reference("test.module2")
        assert len(state.module_references) == 2
        assert "test.module1" in state.module_references
        
        # Remove reference
        state.remove_module_reference("test.module1")
        assert len(state.module_references) == 1
        assert "test.module1" not in state.module_references
        
        # Clear all references
        state.clear_module_references()
        assert len(state.module_references) == 0
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        metadata = ComponentMetadata(name="test_component")
        dependencies = [DependencyInfo(name="requests")]
        
        state = ComponentState(
            name="test_component",
            status=ComponentStatus.LOADED,
            metadata=metadata,
            dependencies=dependencies,
            load_count=3,
            error_count=1,
            last_error="Previous error"
        )
        state.add_module_reference("test.module")
        
        data = state.to_dict()
        assert data['name'] == "test_component"
        assert data['status'] == "loaded"
        assert data['metadata'] is not None
        assert len(data['dependencies']) == 1
        assert data['load_count'] == 3
        assert data['error_count'] == 1
        assert data['last_error'] == "Previous error"
        assert "test.module" in data['module_references']


class TestValidationFunctions:
    """Test cases for validation functions."""
    
    def test_validate_component_name(self):
        """Test component name validation."""
        # Valid names
        assert validate_component_name("test_component")
        assert validate_component_name("TestComponent")
        assert validate_component_name("test-component")
        assert validate_component_name("test123")
        
        # Invalid names
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_component_name("")
        
        with pytest.raises(ValidationError, match="must be a string"):
            validate_component_name(123)
        
        with pytest.raises(ValidationError, match="cannot be only whitespace"):
            validate_component_name("   ")
        
        with pytest.raises(ValidationError, match="cannot contain"):
            validate_component_name("test/component")
        
        with pytest.raises(ValidationError, match="cannot exceed 100 characters"):
            validate_component_name("a" * 101)
    
    def test_validate_requirements_list(self):
        """Test requirements list validation."""
        # Valid requirements
        assert validate_requirements_list([])
        assert validate_requirements_list(["requests", "numpy>=1.0"])
        
        # Invalid requirements
        with pytest.raises(ValidationError, match="must be a list"):
            validate_requirements_list("not a list")
        
        with pytest.raises(ValidationError, match="must be a string"):
            validate_requirements_list([123])
        
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_requirements_list([""])
    
    def test_validate_file_path(self):
        """Test file path validation."""
        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_path = f.name
        
        try:
            # Valid file path
            assert validate_file_path(temp_path)
            
            # Invalid path - not a string
            with pytest.raises(ValidationError, match="must be a string"):
                validate_file_path(123)
            
            # Invalid path - empty
            with pytest.raises(ValidationError, match="cannot be empty"):
                validate_file_path("")
            
            # Invalid path - doesn't exist
            with pytest.raises(ValidationError, match="does not exist"):
                validate_file_path("/non/existent/path.py")
            
            # Invalid path - is a directory
            temp_dir = tempfile.mkdtemp()
            try:
                with pytest.raises(ValidationError, match="must point to a file"):
                    validate_file_path(temp_dir)
            finally:
                os.rmdir(temp_dir)
        
        finally:
            os.unlink(temp_path)


class TestValidationError:
    """Test cases for ValidationError exception."""
    
    def test_basic_creation(self):
        """Test basic ValidationError creation."""
        error = ValidationError("Test message")
        assert str(error) == "Test message"
        assert error.field is None
        assert error.value is None
    
    def test_creation_with_field_and_value(self):
        """Test ValidationError creation with field and value."""
        error = ValidationError("Test message", field="test_field", value="test_value")
        assert str(error) == "Test message"
        assert error.field == "test_field"
        assert error.value == "test_value"