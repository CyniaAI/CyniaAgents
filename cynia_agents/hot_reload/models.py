"""
Data models and result classes for the hot reload system.

This module provides comprehensive data structures for component metadata,
operation results, and status tracking.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Set
from datetime import datetime
import os


class ComponentStatus(Enum):
    """Status of a component in the hot reload system."""
    UNKNOWN = "unknown"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"
    RELOADING = "reloading"
    UNLOADING = "unloading"
    UNLOADED = "unloaded"
    DISABLED = "disabled"


class DependencyStatus(Enum):
    """Status of component dependencies."""
    UNKNOWN = "unknown"
    CHECKING = "checking"
    SATISFIED = "satisfied"
    MISSING = "missing"
    INSTALLING = "installing"
    FAILED = "failed"
    CONFLICT = "conflict"


class OperationType(Enum):
    """Types of operations that can be performed on components."""
    LOAD = "load"
    RELOAD = "reload"
    UNLOAD = "unload"
    INSTALL_DEPENDENCIES = "install_dependencies"
    DISCOVER = "discover"
    VALIDATE = "validate"


@dataclass
class ComponentMetadata:
    """Comprehensive metadata for a component."""
    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    requirements: List[str] = field(default_factory=list)
    file_path: Optional[str] = None
    module_name: Optional[str] = None
    class_name: Optional[str] = None
    is_package: bool = False
    package_path: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    size_bytes: int = 0
    checksum: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Post-initialization validation and setup."""
        if not self.name:
            raise ValueError("Component name cannot be empty")
        
        # Ensure requirements is a list
        if not isinstance(self.requirements, list):
            self.requirements = []
        
        # Set file size if file_path is provided
        if self.file_path and os.path.exists(self.file_path):
            try:
                self.size_bytes = os.path.getsize(self.file_path)
                self.modified_at = datetime.fromtimestamp(os.path.getmtime(self.file_path))
            except OSError:
                pass
    
    def is_valid(self) -> bool:
        """Check if the component metadata is valid."""
        if not self.name or not self.name.strip():
            return False
        
        if self.file_path and not os.path.exists(self.file_path):
            return False
        
        return True
    
    def get_display_name(self) -> str:
        """Get a user-friendly display name for the component."""
        return self.name.replace('_', ' ').title()
    
    def has_requirements(self) -> bool:
        """Check if the component has any requirements."""
        return bool(self.requirements)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary for serialization."""
        return {
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'author': self.author,
            'requirements': self.requirements,
            'file_path': self.file_path,
            'module_name': self.module_name,
            'class_name': self.class_name,
            'is_package': self.is_package,
            'package_path': self.package_path,
            'created_at': self.created_at.isoformat(),
            'modified_at': self.modified_at.isoformat(),
            'size_bytes': self.size_bytes,
            'checksum': self.checksum,
            'tags': self.tags,
            'config': self.config
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ComponentMetadata':
        """Create metadata from dictionary."""
        # Convert datetime strings back to datetime objects
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if 'modified_at' in data and isinstance(data['modified_at'], str):
            data['modified_at'] = datetime.fromisoformat(data['modified_at'])
        
        return cls(**data)


@dataclass
class DependencyInfo:
    """Information about a component dependency."""
    name: str
    version_spec: str = ""
    status: DependencyStatus = DependencyStatus.UNKNOWN
    installed_version: Optional[str] = None
    error_message: Optional[str] = None
    is_optional: bool = False
    
    def __post_init__(self):
        """Post-initialization validation."""
        if not self.name:
            raise ValueError("Dependency name cannot be empty")
    
    def is_satisfied(self) -> bool:
        """Check if the dependency is satisfied."""
        return self.status == DependencyStatus.SATISFIED
    
    def needs_installation(self) -> bool:
        """Check if the dependency needs to be installed."""
        return self.status in [DependencyStatus.MISSING, DependencyStatus.FAILED]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'version_spec': self.version_spec,
            'status': self.status.value,
            'installed_version': self.installed_version,
            'error_message': self.error_message,
            'is_optional': self.is_optional
        }


@dataclass
class ReloadResult:
    """Result of a component reload operation."""
    component_name: str
    operation: OperationType
    success: bool
    status: ComponentStatus
    previous_status: ComponentStatus
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0
    error_message: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    metadata: Optional[ComponentMetadata] = None
    dependencies: List[DependencyInfo] = field(default_factory=list)
    rollback_available: bool = False
    
    def __post_init__(self):
        """Post-initialization validation."""
        if not self.component_name:
            raise ValueError("Component name cannot be empty")
    
    def is_successful(self) -> bool:
        """Check if the operation was successful."""
        return self.success and self.status not in [ComponentStatus.FAILED, ComponentStatus.UNKNOWN]
    
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return bool(self.warnings)
    
    def get_summary(self) -> str:
        """Get a summary of the reload result."""
        status_text = "succeeded" if self.success else "failed"
        duration_text = f" in {self.duration:.2f}s" if self.duration > 0 else ""
        
        summary = f"{self.operation.value.title()} {status_text}{duration_text}"
        
        if self.error_message:
            summary += f" - {self.error_message}"
        elif self.warnings:
            summary += f" - {len(self.warnings)} warning(s)"
        
        return summary
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'component_name': self.component_name,
            'operation': self.operation.value,
            'success': self.success,
            'status': self.status.value,
            'previous_status': self.previous_status.value,
            'timestamp': self.timestamp.isoformat(),
            'duration': self.duration,
            'error_message': self.error_message,
            'warnings': self.warnings,
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'dependencies': [dep.to_dict() for dep in self.dependencies],
            'rollback_available': self.rollback_available
        }


@dataclass
class InstallationResult:
    """Result of a dependency installation operation."""
    component_name: str
    dependencies: List[DependencyInfo]
    success: bool
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0
    installed_packages: List[str] = field(default_factory=list)
    failed_packages: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    installation_log: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Post-initialization validation."""
        if not self.component_name:
            raise ValueError("Component name cannot be empty")
        
        if not isinstance(self.dependencies, list):
            self.dependencies = []
    
    def is_successful(self) -> bool:
        """Check if the installation was successful."""
        return self.success and not self.failed_packages
    
    def get_installed_count(self) -> int:
        """Get the number of successfully installed packages."""
        return len(self.installed_packages)
    
    def get_failed_count(self) -> int:
        """Get the number of failed package installations."""
        return len(self.failed_packages)
    
    def get_summary(self) -> str:
        """Get a summary of the installation result."""
        if self.success:
            if self.installed_packages:
                return f"Installed {len(self.installed_packages)} package(s) successfully"
            else:
                return "All dependencies already satisfied"
        else:
            failed_count = len(self.failed_packages)
            return f"Failed to install {failed_count} package(s)"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'component_name': self.component_name,
            'dependencies': [dep.to_dict() for dep in self.dependencies],
            'success': self.success,
            'timestamp': self.timestamp.isoformat(),
            'duration': self.duration,
            'installed_packages': self.installed_packages,
            'failed_packages': self.failed_packages,
            'error_message': self.error_message,
            'installation_log': self.installation_log
        }


@dataclass
class ComponentState:
    """Current state of a component in the system."""
    name: str
    status: ComponentStatus
    metadata: Optional[ComponentMetadata] = None
    dependencies: List[DependencyInfo] = field(default_factory=list)
    last_loaded: Optional[datetime] = None
    last_modified: Optional[datetime] = None
    load_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    is_enabled: bool = True
    module_references: Set[str] = field(default_factory=set)
    
    def __post_init__(self):
        """Post-initialization validation."""
        if not self.name:
            raise ValueError("Component name cannot be empty")
        
        # Ensure module_references is a set
        if not isinstance(self.module_references, set):
            self.module_references = set(self.module_references) if self.module_references else set()
    
    def is_loaded(self) -> bool:
        """Check if the component is currently loaded."""
        return self.status == ComponentStatus.LOADED
    
    def is_failed(self) -> bool:
        """Check if the component is in a failed state."""
        return self.status == ComponentStatus.FAILED
    
    def has_errors(self) -> bool:
        """Check if the component has any errors."""
        return self.error_count > 0 or self.last_error is not None
    
    def needs_dependencies(self) -> bool:
        """Check if the component has unsatisfied dependencies."""
        return any(not dep.is_satisfied() for dep in self.dependencies)
    
    def get_unsatisfied_dependencies(self) -> List[DependencyInfo]:
        """Get list of unsatisfied dependencies."""
        return [dep for dep in self.dependencies if not dep.is_satisfied()]
    
    def update_status(self, new_status: ComponentStatus, error_message: Optional[str] = None):
        """Update the component status."""
        self.status = new_status
        
        if new_status == ComponentStatus.LOADED:
            self.last_loaded = datetime.now()
            self.load_count += 1
        elif new_status == ComponentStatus.FAILED:
            self.error_count += 1
            if error_message:
                self.last_error = error_message
    
    def add_module_reference(self, module_name: str):
        """Add a module reference."""
        self.module_references.add(module_name)
    
    def remove_module_reference(self, module_name: str):
        """Remove a module reference."""
        self.module_references.discard(module_name)
    
    def clear_module_references(self):
        """Clear all module references."""
        self.module_references.clear()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'status': self.status.value,
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'dependencies': [dep.to_dict() for dep in self.dependencies],
            'last_loaded': self.last_loaded.isoformat() if self.last_loaded else None,
            'last_modified': self.last_modified.isoformat() if self.last_modified else None,
            'load_count': self.load_count,
            'error_count': self.error_count,
            'last_error': self.last_error,
            'is_enabled': self.is_enabled,
            'module_references': list(self.module_references)
        }


class ValidationError(Exception):
    """Exception raised when data model validation fails."""
    
    def __init__(self, message: str, field: Optional[str] = None, value: Any = None):
        super().__init__(message)
        self.field = field
        self.value = value


def validate_component_name(name: str) -> bool:
    """
    Validate a component name.
    
    Args:
        name: The component name to validate
        
    Returns:
        bool: True if valid, False otherwise
        
    Raises:
        ValidationError: If validation fails with details
    """
    if not name:
        raise ValidationError("Component name cannot be empty", "name", name)
    
    if not isinstance(name, str):
        raise ValidationError("Component name must be a string", "name", name)
    
    if not name.strip():
        raise ValidationError("Component name cannot be only whitespace", "name", name)
    
    # Check for invalid characters
    invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for char in invalid_chars:
        if char in name:
            raise ValidationError(f"Component name cannot contain '{char}'", "name", name)
    
    # Check length
    if len(name) > 100:
        raise ValidationError("Component name cannot exceed 100 characters", "name", name)
    
    return True


def validate_requirements_list(requirements: List[str]) -> bool:
    """
    Validate a list of requirements.
    
    Args:
        requirements: List of requirement strings
        
    Returns:
        bool: True if valid, False otherwise
        
    Raises:
        ValidationError: If validation fails with details
    """
    if not isinstance(requirements, list):
        raise ValidationError("Requirements must be a list", "requirements", requirements)
    
    for i, req in enumerate(requirements):
        if not isinstance(req, str):
            raise ValidationError(f"Requirement at index {i} must be a string", "requirements", req)
        
        if not req.strip():
            raise ValidationError(f"Requirement at index {i} cannot be empty", "requirements", req)
    
    return True


def validate_file_path(file_path: str) -> bool:
    """
    Validate a file path.
    
    Args:
        file_path: The file path to validate
        
    Returns:
        bool: True if valid, False otherwise
        
    Raises:
        ValidationError: If validation fails with details
    """
    if not isinstance(file_path, str):
        raise ValidationError("File path must be a string", "file_path", file_path)
    
    if not file_path.strip():
        raise ValidationError("File path cannot be empty", "file_path", file_path)
    
    # Check if path exists
    if not os.path.exists(file_path):
        raise ValidationError("File path does not exist", "file_path", file_path)
    
    # Check if it's a file (not a directory)
    if not os.path.isfile(file_path):
        raise ValidationError("Path must point to a file", "file_path", file_path)
    
    return True