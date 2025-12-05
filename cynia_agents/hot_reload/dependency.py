"""
Dependency management system for the hot reload framework.

This module provides automatic dependency detection, installation, and validation
for components in the hot reload system.
"""

import re
import importlib
import importlib.util
import subprocess
import sys
import threading
import time
import uuid
from typing import List, Dict, Optional, Tuple, Set, Callable, Any
from dataclasses import dataclass, field
from pathlib import Path
import pkg_resources
from packaging import requirements as pkg_requirements
from packaging.version import Version, InvalidVersion
from datetime import datetime
from enum import Enum

from .models import DependencyInfo, DependencyStatus, InstallationResult, ComponentMetadata
from .errors import ErrorHandler, ErrorInfo, ErrorSeverity


class InstallationStatus(Enum):
    """Status of a pip installation operation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class InstallationProgress:
    """Progress information for a pip installation."""
    install_id: str
    status: InstallationStatus
    current_package: Optional[str] = None
    packages_total: int = 0
    packages_completed: int = 0
    current_step: str = ""
    log_lines: List[str] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    
    @property
    def progress_percentage(self) -> float:
        """Get progress as percentage (0-100)."""
        if self.packages_total == 0:
            return 0.0
        return (self.packages_completed / self.packages_total) * 100
    
    @property
    def duration(self) -> float:
        """Get duration in seconds."""
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()
    
    def is_complete(self) -> bool:
        """Check if installation is complete."""
        return self.status in [InstallationStatus.COMPLETED, InstallationStatus.FAILED, InstallationStatus.CANCELLED]


@dataclass
class ParsedRequirement:
    """A parsed requirement with name, version specs, and extras."""
    name: str
    version_specs: List[Tuple[str, str]]  # [(operator, version), ...]
    extras: Set[str]
    markers: Optional[str] = None
    is_optional: bool = False
    
    def __str__(self) -> str:
        """Convert back to requirement string format."""
        req_str = self.name
        
        if self.extras:
            req_str += f"[{','.join(sorted(self.extras))}]"
        
        if self.version_specs:
            version_part = ','.join(f"{op}{ver}" for op, ver in self.version_specs)
            req_str += f"{version_part}"
        
        if self.markers:
            req_str += f"; {self.markers}"
        
        return req_str


class RequirementParser:
    """Parser for requirements.txt files and component metadata requirements."""
    
    def __init__(self):
        self.error_handler = ErrorHandler()
        
        # Common requirement patterns
        self.requirement_pattern = re.compile(
            r'^([a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9])'  # package name
            r'(?:\[([^\]]+)\])?'  # optional extras
            r'([><=!~\s]*[0-9][^;]*)?'  # version specs
            r'(?:;\s*(.+))?$'  # markers
        )
        
        # Version operators
        self.version_operators = ['==', '>=', '<=', '>', '<', '!=', '~=']
    
    def parse_requirements_file(self, file_path: str) -> List[ParsedRequirement]:
        """
        Parse a requirements.txt file.
        
        Args:
            file_path: Path to the requirements.txt file
            
        Returns:
            List[ParsedRequirement]: List of parsed requirements
            
        Raises:
            FileNotFoundError: If the requirements file doesn't exist
            ValueError: If parsing fails
        """
        requirements = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise FileNotFoundError(f"Requirements file not found: {file_path}")
        except Exception as e:
            raise ValueError(f"Failed to read requirements file: {e}")
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # Skip -r, -e, and other pip options for now
            if line.startswith('-'):
                continue
            
            try:
                req = self.parse_requirement_string(line)
                if req:
                    requirements.append(req)
            except Exception as e:
                raise ValueError(f"Failed to parse requirement on line {line_num}: {line} - {e}")
        
        return requirements
    
    def parse_requirement_string(self, req_string: str) -> Optional[ParsedRequirement]:
        """
        Parse a single requirement string.
        
        Args:
            req_string: The requirement string to parse
            
        Returns:
            Optional[ParsedRequirement]: Parsed requirement or None if invalid
        """
        req_string = req_string.strip()
        if not req_string:
            return None
        
        # Try using packaging library first (more robust)
        try:
            parsed = pkg_requirements.Requirement(req_string)
            
            # Extract version specs
            version_specs = []
            if parsed.specifier:
                for spec in parsed.specifier:
                    version_specs.append((spec.operator, spec.version))
            
            return ParsedRequirement(
                name=parsed.name,
                version_specs=version_specs,
                extras=set(parsed.extras),
                markers=str(parsed.marker) if parsed.marker else None
            )
        
        except Exception:
            # Fall back to regex parsing
            return self._parse_with_regex(req_string)
    
    def _parse_with_regex(self, req_string: str) -> Optional[ParsedRequirement]:
        """Parse requirement string using regex as fallback."""
        match = self.requirement_pattern.match(req_string)
        if not match:
            return None
        
        name, extras_str, version_str, markers = match.groups()
        
        # Parse extras
        extras = set()
        if extras_str:
            extras = {extra.strip() for extra in extras_str.split(',')}
        
        # Parse version specifications
        version_specs = []
        if version_str:
            version_str = version_str.strip()
            # Split by comma for multiple version specs
            for spec in version_str.split(','):
                spec = spec.strip()
                if spec:
                    # Find the operator
                    for op in sorted(self.version_operators, key=len, reverse=True):
                        if spec.startswith(op):
                            version = spec[len(op):].strip()
                            if version:
                                version_specs.append((op, version))
                            break
        
        return ParsedRequirement(
            name=name,
            version_specs=version_specs,
            extras=extras,
            markers=markers
        )
    
    def parse_component_requirements(self, metadata: ComponentMetadata) -> List[ParsedRequirement]:
        """
        Parse requirements from component metadata.
        
        Args:
            metadata: Component metadata containing requirements
            
        Returns:
            List[ParsedRequirement]: List of parsed requirements
        """
        requirements = []
        
        for req_string in metadata.requirements:
            try:
                req = self.parse_requirement_string(req_string)
                if req:
                    requirements.append(req)
            except Exception as e:
                # Log the error but continue with other requirements
                print(f"Warning: Failed to parse requirement '{req_string}': {e}")
        
        return requirements
    
    def extract_requirements_from_file(self, file_path: str) -> List[str]:
        """
        Extract requirements from a Python file by looking for imports.
        
        Args:
            file_path: Path to the Python file
            
        Returns:
            List[str]: List of potential requirements (module names)
        """
        requirements = set()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return []
        
        # Find import statements
        import_patterns = [
            r'^import\s+([a-zA-Z_][a-zA-Z0-9_]*)',
            r'^from\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+import',
        ]
        
        for pattern in import_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            for match in matches:
                # Skip standard library modules (basic check)
                if not self._is_stdlib_module(match):
                    requirements.add(match)
        
        return list(requirements)
    
    def _is_stdlib_module(self, module_name: str) -> bool:
        """Check if a module is part of the standard library."""
        stdlib_modules = {
            'os', 'sys', 'json', 'datetime', 'time', 'random', 'math',
            'collections', 'itertools', 'functools', 'operator', 'typing',
            'pathlib', 'urllib', 'http', 'email', 'html', 'xml', 'csv',
            'sqlite3', 'logging', 'unittest', 'threading', 'multiprocessing',
            'subprocess', 'shutil', 'tempfile', 'glob', 'fnmatch', 'linecache',
            'pickle', 'copyreg', 'copy', 'pprint', 'reprlib', 'enum', 'numbers',
            'cmath', 'decimal', 'fractions', 'statistics', 'array', 'weakref',
            'types', 'gc', 'inspect', 'site', 'importlib', 'pkgutil', 'modulefinder',
            'runpy', 'ast', 'symtable', 'symbol', 'token', 'keyword', 'tokenize',
            'tabnanny', 'pyclbr', 'py_compile', 'compileall', 'dis', 'pickletools'
        }
        
        return module_name in stdlib_modules


class PipInstaller:
    """Handles pip package installation with progress tracking and logging."""
    
    def __init__(self):
        self.error_handler = ErrorHandler()
        self.active_installations: Dict[str, InstallationProgress] = {}
        self.installation_lock = threading.Lock()
        
        # Progress callback functions
        self.progress_callbacks: List[Callable[[InstallationProgress], None]] = []
    
    def install_packages(self, packages: List[str], component_name: str = "unknown") -> InstallationResult:
        """
        Install a list of packages using pip.
        
        Args:
            packages: List of package requirement strings
            component_name: Name of the component requesting installation
            
        Returns:
            InstallationResult: Result of the installation operation
        """
        install_id = str(uuid.uuid4())
        
        # Initialize progress tracking
        progress = InstallationProgress(
            install_id=install_id,
            status=InstallationStatus.PENDING,
            packages_total=len(packages)
        )
        
        with self.installation_lock:
            self.active_installations[install_id] = progress
        
        try:
            # Update status to running
            self._update_progress(install_id, status=InstallationStatus.RUNNING)
            
            installed_packages = []
            failed_packages = []
            all_logs = []
            
            for i, package in enumerate(packages):
                self._update_progress(
                    install_id,
                    current_package=package,
                    packages_completed=i,
                    current_step=f"Installing {package}"
                )
                
                try:
                    success, logs = self._install_single_package(package)
                    all_logs.extend(logs)
                    
                    if success:
                        installed_packages.append(package)
                        self._update_progress(
                            install_id,
                            packages_completed=i + 1,
                            current_step=f"Successfully installed {package}"
                        )
                    else:
                        failed_packages.append(package)
                        self._update_progress(
                            install_id,
                            current_step=f"Failed to install {package}"
                        )
                
                except Exception as e:
                    failed_packages.append(package)
                    error_msg = f"Error installing {package}: {e}"
                    all_logs.append(error_msg)
                    self._update_progress(
                        install_id,
                        current_step=error_msg
                    )
            
            # Determine overall success
            success = len(failed_packages) == 0
            
            # Update final status
            final_status = InstallationStatus.COMPLETED if success else InstallationStatus.FAILED
            self._update_progress(
                install_id,
                status=final_status,
                packages_completed=len(packages),
                current_step="Installation complete"
            )
            
            # Create result
            result = InstallationResult(
                component_name=component_name,
                dependencies=[],  # Will be populated by caller
                success=success,
                duration=progress.duration,
                installed_packages=installed_packages,
                failed_packages=failed_packages,
                error_message=f"Failed to install {len(failed_packages)} package(s)" if failed_packages else None,
                installation_log=all_logs
            )
            
            return result
            
        except Exception as e:
            # Handle unexpected errors
            self._update_progress(
                install_id,
                status=InstallationStatus.FAILED,
                error_message=str(e)
            )
            
            return InstallationResult(
                component_name=component_name,
                dependencies=[],
                success=False,
                duration=progress.duration,
                installed_packages=[],
                failed_packages=packages,
                error_message=f"Installation failed: {e}",
                installation_log=[str(e)]
            )
        
        finally:
            # Clean up progress tracking after a delay
            threading.Timer(300.0, self._cleanup_installation, args=[install_id]).start()
    
    def _install_single_package(self, package: str) -> Tuple[bool, List[str]]:
        """
        Install a single package using pip.
        
        Args:
            package: Package requirement string
            
        Returns:
            Tuple[bool, List[str]]: (success, log_lines)
        """
        logs = []
        
        try:
            # Build pip command
            cmd = [sys.executable, "-m", "pip", "install", package, "--no-cache-dir"]
            
            # Add additional flags for better output
            cmd.extend(["--progress-bar", "off", "--quiet"])
            
            logs.append(f"Running: {' '.join(cmd)}")
            
            # Execute pip command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            # Capture output
            if result.stdout:
                logs.extend(result.stdout.strip().split('\n'))
            if result.stderr:
                logs.extend(result.stderr.strip().split('\n'))
            
            # Check if installation was successful
            success = result.returncode == 0
            
            if not success:
                logs.append(f"Installation failed with return code: {result.returncode}")
            
            return success, logs
            
        except subprocess.TimeoutExpired:
            error_msg = f"Installation of {package} timed out after 5 minutes"
            logs.append(error_msg)
            return False, logs
            
        except Exception as e:
            error_msg = f"Unexpected error installing {package}: {e}"
            logs.append(error_msg)
            return False, logs
    
    def get_installation_progress(self, install_id: str) -> Optional[InstallationProgress]:
        """
        Get the progress of an installation.
        
        Args:
            install_id: ID of the installation
            
        Returns:
            Optional[InstallationProgress]: Progress information or None if not found
        """
        with self.installation_lock:
            return self.active_installations.get(install_id)
    
    def cancel_installation(self, install_id: str) -> bool:
        """
        Cancel an ongoing installation.
        
        Args:
            install_id: ID of the installation to cancel
            
        Returns:
            bool: True if cancellation was successful
        """
        with self.installation_lock:
            progress = self.active_installations.get(install_id)
            if progress and progress.status == InstallationStatus.RUNNING:
                progress.status = InstallationStatus.CANCELLED
                progress.end_time = datetime.now()
                progress.current_step = "Installation cancelled"
                self._notify_progress_callbacks(progress)
                return True
        return False
    
    def get_active_installations(self) -> List[InstallationProgress]:
        """Get list of all active installations."""
        with self.installation_lock:
            return [progress for progress in self.active_installations.values() 
                   if not progress.is_complete()]
    
    def add_progress_callback(self, callback: Callable[[InstallationProgress], None]):
        """Add a callback function to be called on progress updates."""
        self.progress_callbacks.append(callback)
    
    def remove_progress_callback(self, callback: Callable[[InstallationProgress], None]):
        """Remove a progress callback function."""
        if callback in self.progress_callbacks:
            self.progress_callbacks.remove(callback)
    
    def _update_progress(self, install_id: str, **kwargs):
        """Update progress information and notify callbacks."""
        with self.installation_lock:
            progress = self.active_installations.get(install_id)
            if not progress:
                return
            
            # Update progress fields
            for key, value in kwargs.items():
                if hasattr(progress, key):
                    setattr(progress, key, value)
            
            # Set end time if status is final
            if progress.status in [InstallationStatus.COMPLETED, InstallationStatus.FAILED, InstallationStatus.CANCELLED]:
                progress.end_time = datetime.now()
            
            # Add log entry if current_step is provided
            if 'current_step' in kwargs and kwargs['current_step']:
                timestamp = datetime.now().strftime("%H:%M:%S")
                progress.log_lines.append(f"[{timestamp}] {kwargs['current_step']}")
        
        # Notify callbacks
        self._notify_progress_callbacks(progress)
    
    def _notify_progress_callbacks(self, progress: InstallationProgress):
        """Notify all registered progress callbacks."""
        for callback in self.progress_callbacks:
            try:
                callback(progress)
            except Exception as e:
                # Don't let callback errors break the installation
                print(f"Error in progress callback: {e}")
    
    def _cleanup_installation(self, install_id: str):
        """Clean up completed installation from active list."""
        with self.installation_lock:
            if install_id in self.active_installations:
                progress = self.active_installations[install_id]
                if progress.is_complete():
                    del self.active_installations[install_id]
    
    def validate_installation(self, packages: List[str]) -> Tuple[bool, List[str]]:
        """
        Validate that packages were installed successfully.
        
        Args:
            packages: List of package names to validate
            
        Returns:
            Tuple[bool, List[str]]: (all_valid, list_of_issues)
        """
        issues = []
        
        for package in packages:
            try:
                # Try to import the package
                importlib.import_module(package)
            except ImportError:
                try:
                    # Try with pkg_resources
                    pkg_resources.get_distribution(package)
                except pkg_resources.DistributionNotFound:
                    issues.append(f"Package {package} not found after installation")
                except Exception as e:
                    issues.append(f"Error validating {package}: {e}")
            except Exception as e:
                issues.append(f"Error importing {package}: {e}")
        
        return len(issues) == 0, issues
    
    def get_pip_version(self) -> Optional[str]:
        """Get the version of pip being used."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None
    
    def upgrade_pip(self) -> Tuple[bool, List[str]]:
        """
        Upgrade pip to the latest version.
        
        Returns:
            Tuple[bool, List[str]]: (success, log_lines)
        """
        try:
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "pip"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            logs = []
            if result.stdout:
                logs.extend(result.stdout.strip().split('\n'))
            if result.stderr:
                logs.extend(result.stderr.strip().split('\n'))
            
            return result.returncode == 0, logs
            
        except Exception as e:
            return False, [f"Error upgrading pip: {e}"]


class DependencyManager:
    """Main dependency manager for component requirements."""
    
    def __init__(self):
        self.requirement_parser = RequirementParser()
        self.pip_installer = PipInstaller()
        self.error_handler = ErrorHandler()
        self._package_cache: Dict[str, Optional[str]] = {}  # Cache for installed packages
    
    def check_dependencies(self, requirements: List[str]) -> List[DependencyInfo]:
        """
        Check the status of a list of requirements.
        
        Args:
            requirements: List of requirement strings
            
        Returns:
            List[DependencyInfo]: Status information for each dependency
        """
        dependency_info = []
        
        for req_string in requirements:
            try:
                parsed_req = self.requirement_parser.parse_requirement_string(req_string)
                if not parsed_req:
                    dependency_info.append(DependencyInfo(
                        name=req_string,
                        status=DependencyStatus.FAILED,
                        error_message="Failed to parse requirement"
                    ))
                    continue
                
                # Check if the package is installed
                status, installed_version, error_msg = self._check_single_dependency(parsed_req)
                
                dependency_info.append(DependencyInfo(
                    name=parsed_req.name,
                    version_spec=str(parsed_req),
                    status=status,
                    installed_version=installed_version,
                    error_message=error_msg
                ))
                
            except Exception as e:
                dependency_info.append(DependencyInfo(
                    name=req_string,
                    status=DependencyStatus.FAILED,
                    error_message=f"Error checking dependency: {e}"
                ))
        
        return dependency_info
    
    def check_component_dependencies(self, metadata: ComponentMetadata) -> List[DependencyInfo]:
        """
        Check dependencies for a specific component.
        
        Args:
            metadata: Component metadata containing requirements
            
        Returns:
            List[DependencyInfo]: Status information for each dependency
        """
        return self.check_dependencies(metadata.requirements)
    
    def get_missing_dependencies(self, requirements: List[str]) -> List[str]:
        """
        Get a list of missing dependencies.
        
        Args:
            requirements: List of requirement strings
            
        Returns:
            List[str]: List of missing requirement strings
        """
        missing = []
        dependency_info = self.check_dependencies(requirements)
        
        for dep in dependency_info:
            if dep.status in [DependencyStatus.MISSING, DependencyStatus.FAILED]:
                missing.append(dep.version_spec or dep.name)
        
        return missing
    
    def validate_dependencies(self, requirements: List[str]) -> Tuple[bool, List[str]]:
        """
        Validate that all dependencies are satisfied.
        
        Args:
            requirements: List of requirement strings
            
        Returns:
            Tuple[bool, List[str]]: (all_satisfied, list_of_issues)
        """
        issues = []
        dependency_info = self.check_dependencies(requirements)
        
        for dep in dependency_info:
            if dep.status == DependencyStatus.MISSING:
                issues.append(f"Missing dependency: {dep.name}")
            elif dep.status == DependencyStatus.CONFLICT:
                issues.append(f"Version conflict for {dep.name}: {dep.error_message}")
            elif dep.status == DependencyStatus.FAILED:
                issues.append(f"Failed to check {dep.name}: {dep.error_message}")
        
        return len(issues) == 0, issues
    
    def _check_single_dependency(self, parsed_req: ParsedRequirement) -> Tuple[DependencyStatus, Optional[str], Optional[str]]:
        """
        Check a single parsed requirement.
        
        Returns:
            Tuple[DependencyStatus, installed_version, error_message]
        """
        package_name = parsed_req.name
        
        # Check cache first
        if package_name in self._package_cache:
            cached_version = self._package_cache[package_name]
            if cached_version is None:
                return DependencyStatus.MISSING, None, f"Package {package_name} not found"
        else:
            # Try to get installed version
            try:
                installed_version = self._get_installed_version(package_name)
                self._package_cache[package_name] = installed_version
            except Exception as e:
                self._package_cache[package_name] = None
                return DependencyStatus.MISSING, None, str(e)
        
        installed_version = self._package_cache[package_name]
        
        # If no version constraints, just check if it's installed
        if not parsed_req.version_specs:
            if installed_version:
                return DependencyStatus.SATISFIED, installed_version, None
            else:
                return DependencyStatus.MISSING, None, f"Package {package_name} not installed"
        
        # Check version constraints
        try:
            if self._check_version_constraints(installed_version, parsed_req.version_specs):
                return DependencyStatus.SATISFIED, installed_version, None
            else:
                constraint_str = ','.join(f"{op}{ver}" for op, ver in parsed_req.version_specs)
                return DependencyStatus.CONFLICT, installed_version, \
                       f"Installed version {installed_version} doesn't satisfy {constraint_str}"
        
        except Exception as e:
            return DependencyStatus.FAILED, installed_version, f"Version check failed: {e}"
    
    def _get_installed_version(self, package_name: str) -> Optional[str]:
        """Get the installed version of a package."""
        try:
            # Try using pkg_resources first
            distribution = pkg_resources.get_distribution(package_name)
            return distribution.version
        except pkg_resources.DistributionNotFound:
            pass
        
        try:
            # Try using importlib.metadata (Python 3.8+)
            import importlib.metadata as metadata
            return metadata.version(package_name)
        except (ImportError, metadata.PackageNotFoundError):
            pass
        
        try:
            # Try importing the module and checking for __version__
            module = importlib.import_module(package_name)
            if hasattr(module, '__version__'):
                return module.__version__
        except ImportError:
            pass
        
        raise Exception(f"Package {package_name} not found")
    
    def _check_version_constraints(self, installed_version: str, version_specs: List[Tuple[str, str]]) -> bool:
        """Check if installed version satisfies version constraints."""
        try:
            installed = Version(installed_version)
        except InvalidVersion:
            # If we can't parse the installed version, assume it's satisfied
            return True
        
        for operator, version_str in version_specs:
            try:
                required = Version(version_str)
            except InvalidVersion:
                # If we can't parse the required version, skip this constraint
                continue
            
            if not self._compare_versions(installed, operator, required):
                return False
        
        return True
    
    def _compare_versions(self, installed: Version, operator: str, required: Version) -> bool:
        """Compare two versions using the given operator."""
        if operator == '==':
            return installed == required
        elif operator == '!=':
            return installed != required
        elif operator == '>':
            return installed > required
        elif operator == '>=':
            return installed >= required
        elif operator == '<':
            return installed < required
        elif operator == '<=':
            return installed <= required
        elif operator == '~=':
            # Compatible release operator
            return installed >= required and installed.major == required.major
        else:
            # Unknown operator, assume satisfied
            return True
    
    def clear_cache(self):
        """Clear the package cache."""
        self._package_cache.clear()
    
    def get_dependency_graph(self, requirements: List[str]) -> Dict[str, List[str]]:
        """
        Build a dependency graph for the given requirements.
        
        Args:
            requirements: List of requirement strings
            
        Returns:
            Dict[str, List[str]]: Dependency graph mapping package names to their dependencies
        """
        graph = {}
        
        for req_string in requirements:
            parsed_req = self.requirement_parser.parse_requirement_string(req_string)
            if not parsed_req:
                continue
            
            package_name = parsed_req.name
            
            # Get dependencies of this package
            try:
                package_deps = self._get_package_dependencies(package_name)
                graph[package_name] = package_deps
            except Exception:
                graph[package_name] = []
        
        return graph
    
    def _get_package_dependencies(self, package_name: str) -> List[str]:
        """Get the dependencies of a specific package."""
        try:
            distribution = pkg_resources.get_distribution(package_name)
            return [str(req).split()[0] for req in distribution.requires()]
        except Exception:
            return []
    
    def install_dependencies(self, requirements: List[str], component_name: str = "unknown") -> InstallationResult:
        """
        Install missing dependencies for a component.
        
        Args:
            requirements: List of requirement strings
            component_name: Name of the component requesting installation
            
        Returns:
            InstallationResult: Result of the installation operation
        """
        # First check which dependencies are missing
        dependency_info = self.check_dependencies(requirements)
        missing_packages = []
        
        for dep in dependency_info:
            if dep.status in [DependencyStatus.MISSING, DependencyStatus.FAILED]:
                missing_packages.append(dep.version_spec or dep.name)
        
        if not missing_packages:
            # All dependencies are already satisfied
            return InstallationResult(
                component_name=component_name,
                dependencies=dependency_info,
                success=True,
                duration=0.0,
                installed_packages=[],
                failed_packages=[],
                error_message=None,
                installation_log=["All dependencies already satisfied"]
            )
        
        # Install missing packages
        result = self.pip_installer.install_packages(missing_packages, component_name)
        
        # Update result with dependency info
        result.dependencies = dependency_info
        
        # Clear cache to force re-check of installed packages
        self.clear_cache()
        
        # Validate installation
        if result.success:
            validation_success, validation_issues = self.pip_installer.validate_installation(
                [dep.name for dep in dependency_info if dep.status == DependencyStatus.MISSING]
            )
            
            if not validation_success:
                result.success = False
                result.error_message = f"Installation validation failed: {'; '.join(validation_issues)}"
                result.installation_log.extend(validation_issues)
        
        return result
    
    def get_installation_progress(self, install_id: str) -> Optional[InstallationProgress]:
        """Get the progress of an installation."""
        return self.pip_installer.get_installation_progress(install_id)
    
    def cancel_installation(self, install_id: str) -> bool:
        """Cancel an ongoing installation."""
        return self.pip_installer.cancel_installation(install_id)
    
    def get_active_installations(self) -> List[InstallationProgress]:
        """Get list of all active installations."""
        return self.pip_installer.get_active_installations()
    
    def add_progress_callback(self, callback: Callable[[InstallationProgress], None]):
        """Add a callback function to be called on installation progress updates."""
        self.pip_installer.add_progress_callback(callback)
    
    def remove_progress_callback(self, callback: Callable[[InstallationProgress], None]):
        """Remove a progress callback function."""
        self.pip_installer.remove_progress_callback(callback)
    
    def validate_post_installation(self, requirements: List[str], component_name: str = "unknown") -> Tuple[bool, List[str], List[DependencyInfo]]:
        """
        Validate dependencies after installation.
        
        Args:
            requirements: List of requirement strings
            component_name: Name of the component
            
        Returns:
            Tuple[bool, List[str], List[DependencyInfo]]: (success, issues, updated_dependency_info)
        """
        issues = []
        
        # Clear cache to get fresh dependency status
        self.clear_cache()
        
        # Re-check all dependencies
        dependency_info = self.check_dependencies(requirements)
        
        # Check for remaining issues
        for dep in dependency_info:
            if dep.status == DependencyStatus.MISSING:
                issues.append(f"Dependency {dep.name} is still missing after installation")
            elif dep.status == DependencyStatus.CONFLICT:
                issues.append(f"Version conflict for {dep.name}: {dep.error_message}")
            elif dep.status == DependencyStatus.FAILED:
                issues.append(f"Failed to validate {dep.name}: {dep.error_message}")
        
        # Check for import issues
        import_issues = self._validate_imports(dependency_info)
        issues.extend(import_issues)
        
        return len(issues) == 0, issues, dependency_info
    
    def _validate_imports(self, dependency_info: List[DependencyInfo]) -> List[str]:
        """
        Validate that dependencies can be imported.
        
        Args:
            dependency_info: List of dependency information
            
        Returns:
            List[str]: List of import issues
        """
        issues = []
        
        for dep in dependency_info:
            if dep.status == DependencyStatus.SATISFIED:
                try:
                    # Try to import the package
                    importlib.import_module(dep.name)
                except ImportError as e:
                    issues.append(f"Cannot import {dep.name} despite being installed: {e}")
                except Exception as e:
                    issues.append(f"Error importing {dep.name}: {e}")
        
        return issues
    
    def detect_version_conflicts(self, requirements: List[str]) -> List[Dict[str, Any]]:
        """
        Detect version conflicts between requirements.
        
        Args:
            requirements: List of requirement strings
            
        Returns:
            List[Dict[str, Any]]: List of conflict information
        """
        conflicts = []
        parsed_requirements = []
        
        # Parse all requirements
        for req_string in requirements:
            parsed_req = self.requirement_parser.parse_requirement_string(req_string)
            if parsed_req:
                parsed_requirements.append(parsed_req)
        
        # Group by package name
        package_requirements = {}
        for req in parsed_requirements:
            if req.name not in package_requirements:
                package_requirements[req.name] = []
            package_requirements[req.name].append(req)
        
        # Check for conflicts within each package
        for package_name, reqs in package_requirements.items():
            if len(reqs) > 1:
                # Multiple requirements for the same package
                conflict_info = self._analyze_version_conflict(package_name, reqs)
                if conflict_info:
                    conflicts.append(conflict_info)
        
        return conflicts
    
    def _analyze_version_conflict(self, package_name: str, requirements: List[ParsedRequirement]) -> Optional[Dict[str, Any]]:
        """
        Analyze version conflicts for a specific package.
        
        Args:
            package_name: Name of the package
            requirements: List of requirements for this package
            
        Returns:
            Optional[Dict[str, Any]]: Conflict information or None if no conflict
        """
        # Collect all version constraints
        all_constraints = []
        for req in requirements:
            all_constraints.extend(req.version_specs)
        
        if not all_constraints:
            return None  # No version constraints, no conflict
        
        # Try to find a version that satisfies all constraints
        try:
            # Get the currently installed version
            installed_version = self._get_installed_version(package_name)
            
            # Check if installed version satisfies all constraints
            satisfies_all = True
            failing_constraints = []
            
            for operator, version_str in all_constraints:
                try:
                    required = Version(version_str)
                    installed = Version(installed_version)
                    
                    if not self._compare_versions(installed, operator, required):
                        satisfies_all = False
                        failing_constraints.append(f"{operator}{version_str}")
                
                except InvalidVersion:
                    continue
            
            if not satisfies_all:
                return {
                    'package': package_name,
                    'installed_version': installed_version,
                    'conflicting_requirements': [str(req) for req in requirements],
                    'failing_constraints': failing_constraints,
                    'resolution_suggestion': self._suggest_conflict_resolution(package_name, requirements)
                }
        
        except Exception:
            # If we can't get installed version, assume potential conflict
            return {
                'package': package_name,
                'installed_version': None,
                'conflicting_requirements': [str(req) for req in requirements],
                'failing_constraints': [],
                'resolution_suggestion': f"Install {package_name} to resolve conflicts"
            }
        
        return None
    
    def _suggest_conflict_resolution(self, package_name: str, requirements: List[ParsedRequirement]) -> str:
        """
        Suggest a resolution for version conflicts.
        
        Args:
            package_name: Name of the conflicting package
            requirements: List of conflicting requirements
            
        Returns:
            str: Resolution suggestion
        """
        # Find the most restrictive version requirement
        min_versions = []
        max_versions = []
        
        for req in requirements:
            for operator, version_str in req.version_specs:
                try:
                    version = Version(version_str)
                    if operator in ['>=', '>']:
                        min_versions.append((version, operator))
                    elif operator in ['<=', '<']:
                        max_versions.append((version, operator))
                    elif operator == '==':
                        return f"Install {package_name}=={version_str} (exact version required)"
                except InvalidVersion:
                    continue
        
        suggestions = []
        
        if min_versions:
            highest_min = max(min_versions, key=lambda x: x[0])
            suggestions.append(f"minimum version {highest_min[1]}{highest_min[0]}")
        
        if max_versions:
            lowest_max = min(max_versions, key=lambda x: x[0])
            suggestions.append(f"maximum version {lowest_max[1]}{lowest_max[0]}")
        
        if suggestions:
            return f"Install {package_name} with {' and '.join(suggestions)}"
        else:
            return f"Review requirements for {package_name} and choose compatible versions"
    
    def detect_circular_dependencies(self, requirements: List[str]) -> List[List[str]]:
        """
        Detect circular dependencies in the requirement list.
        
        Args:
            requirements: List of requirement strings
            
        Returns:
            List[List[str]]: List of circular dependency chains
        """
        graph = self.get_dependency_graph(requirements)
        cycles = []
        visited = set()
        rec_stack = set()
        
        def dfs(node: str, path: List[str]) -> None:
            if node in rec_stack:
                # Found a cycle
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle)
                return
            
            if node in visited:
                return
            
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in graph.get(node, []):
                dfs(neighbor, path + [node])
            
            rec_stack.remove(node)
        
        for package in graph:
            if package not in visited:
                dfs(package, [])
        
        return cycles
    
    def create_dependency_validation_report(self, requirements: List[str], component_name: str = "unknown") -> Dict[str, Any]:
        """
        Create a comprehensive dependency validation report.
        
        Args:
            requirements: List of requirement strings
            component_name: Name of the component
            
        Returns:
            Dict[str, Any]: Comprehensive validation report
        """
        report = {
            'component_name': component_name,
            'timestamp': datetime.now().isoformat(),
            'requirements_count': len(requirements),
            'dependency_status': [],
            'missing_dependencies': [],
            'version_conflicts': [],
            'circular_dependencies': [],
            'import_issues': [],
            'overall_status': 'unknown',
            'recommendations': []
        }
        
        try:
            # Check dependency status
            dependency_info = self.check_dependencies(requirements)
            report['dependency_status'] = [dep.to_dict() for dep in dependency_info]
            
            # Find missing dependencies
            missing = [dep for dep in dependency_info if dep.status == DependencyStatus.MISSING]
            report['missing_dependencies'] = [dep.name for dep in missing]
            
            # Detect version conflicts
            conflicts = self.detect_version_conflicts(requirements)
            report['version_conflicts'] = conflicts
            
            # Detect circular dependencies
            cycles = self.detect_circular_dependencies(requirements)
            report['circular_dependencies'] = cycles
            
            # Check import issues
            import_issues = self._validate_imports(dependency_info)
            report['import_issues'] = import_issues
            
            # Determine overall status
            if missing or conflicts or cycles or import_issues:
                if missing:
                    report['overall_status'] = 'missing_dependencies'
                elif conflicts:
                    report['overall_status'] = 'version_conflicts'
                elif cycles:
                    report['overall_status'] = 'circular_dependencies'
                else:
                    report['overall_status'] = 'import_issues'
            else:
                report['overall_status'] = 'satisfied'
            
            # Generate recommendations
            recommendations = []
            
            if missing:
                recommendations.append(f"Install {len(missing)} missing dependencies")
            
            if conflicts:
                recommendations.append(f"Resolve {len(conflicts)} version conflicts")
            
            if cycles:
                recommendations.append(f"Address {len(cycles)} circular dependency chains")
            
            if import_issues:
                recommendations.append(f"Fix {len(import_issues)} import issues")
            
            if not recommendations:
                recommendations.append("All dependencies are satisfied")
            
            report['recommendations'] = recommendations
            
        except Exception as e:
            report['overall_status'] = 'validation_error'
            report['error'] = str(e)
            report['recommendations'] = ['Fix validation errors before proceeding']
        
        return report