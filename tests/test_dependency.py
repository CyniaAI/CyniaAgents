"""
Unit tests for the dependency management system.

Tests cover requirement parsing, dependency checking, and validation logic.
"""

import unittest
from unittest.mock import Mock, patch, mock_open, MagicMock
import tempfile
import os
import subprocess
import threading
import time
from pathlib import Path

from hot_reload.dependency import (
    RequirementParser, DependencyManager, ParsedRequirement, PipInstaller,
    InstallationProgress, InstallationStatus
)
from hot_reload.models import ComponentMetadata, DependencyInfo, DependencyStatus


class TestParsedRequirement(unittest.TestCase):
    """Test the ParsedRequirement data class."""
    
    def test_simple_requirement_string(self):
        """Test converting simple requirement back to string."""
        req = ParsedRequirement(
            name="requests",
            version_specs=[(">=", "2.0.0")],
            extras=set()
        )
        self.assertEqual(str(req), "requests>=2.0.0")
    
    def test_requirement_with_extras(self):
        """Test requirement with extras."""
        req = ParsedRequirement(
            name="requests",
            version_specs=[(">=", "2.0.0")],
            extras={"security", "socks"}
        )
        result = str(req)
        self.assertIn("requests[", result)
        self.assertIn("security", result)
        self.assertIn("socks", result)
    
    def test_requirement_with_markers(self):
        """Test requirement with markers."""
        req = ParsedRequirement(
            name="requests",
            version_specs=[(">=", "2.0.0")],
            extras=set(),
            markers='python_version >= "3.6"'
        )
        self.assertEqual(str(req), 'requests>=2.0.0; python_version >= "3.6"')


class TestRequirementParser(unittest.TestCase):
    """Test the RequirementParser class."""
    
    def setUp(self):
        self.parser = RequirementParser()
    
    def test_parse_simple_requirement(self):
        """Test parsing a simple requirement string."""
        req = self.parser.parse_requirement_string("requests>=2.0.0")
        
        self.assertIsNotNone(req)
        self.assertEqual(req.name, "requests")
        self.assertEqual(req.version_specs, [(">=", "2.0.0")])
        self.assertEqual(req.extras, set())
    
    def test_parse_requirement_with_extras(self):
        """Test parsing requirement with extras."""
        req = self.parser.parse_requirement_string("requests[security,socks]>=2.0.0")
        
        self.assertIsNotNone(req)
        self.assertEqual(req.name, "requests")
        self.assertEqual(req.extras, {"security", "socks"})
    
    def test_parse_requirement_with_multiple_versions(self):
        """Test parsing requirement with multiple version constraints."""
        req = self.parser.parse_requirement_string("Django>=3.0,<4.0")
        
        self.assertIsNotNone(req)
        self.assertEqual(req.name, "Django")
        self.assertIn((">=", "3.0"), req.version_specs)
        self.assertIn(("<", "4.0"), req.version_specs)
    
    def test_parse_requirement_with_markers(self):
        """Test parsing requirement with markers."""
        req = self.parser.parse_requirement_string('requests>=2.0.0; python_version >= "3.6"')
        
        self.assertIsNotNone(req)
        self.assertEqual(req.name, "requests")
        self.assertIsNotNone(req.markers)
    
    def test_parse_invalid_requirement(self):
        """Test parsing invalid requirement returns None."""
        req = self.parser.parse_requirement_string("invalid requirement string !!!")
        self.assertIsNone(req)
    
    def test_parse_empty_requirement(self):
        """Test parsing empty requirement returns None."""
        req = self.parser.parse_requirement_string("")
        self.assertIsNone(req)
        
        req = self.parser.parse_requirement_string("   ")
        self.assertIsNone(req)
    
    def test_parse_requirements_file(self):
        """Test parsing a requirements.txt file."""
        requirements_content = """
# This is a comment
requests>=2.0.0
Django>=3.0,<4.0
numpy==1.21.0
# Another comment

flask[async]>=1.0.0
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(requirements_content)
            temp_file_name = f.name
        
        try:
            requirements = self.parser.parse_requirements_file(temp_file_name)
            
            self.assertEqual(len(requirements), 4)
            
            # Check specific requirements
            req_names = [req.name for req in requirements]
            self.assertIn("requests", req_names)
            self.assertIn("Django", req_names)
            self.assertIn("numpy", req_names)
            self.assertIn("flask", req_names)
            
            # Check flask has extras
            flask_req = next(req for req in requirements if req.name == "flask")
            self.assertIn("async", flask_req.extras)
            
        finally:
            try:
                os.unlink(temp_file_name)
            except (OSError, PermissionError):
                pass  # Ignore cleanup errors on Windows
    
    def test_parse_requirements_file_not_found(self):
        """Test parsing non-existent requirements file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.parser.parse_requirements_file("non_existent_file.txt")
    
    def test_parse_component_requirements(self):
        """Test parsing requirements from component metadata."""
        metadata = ComponentMetadata(
            name="test_component",
            requirements=["requests>=2.0.0", "numpy==1.21.0", "flask[async]"]
        )
        
        requirements = self.parser.parse_component_requirements(metadata)
        
        self.assertEqual(len(requirements), 3)
        req_names = [req.name for req in requirements]
        self.assertIn("requests", req_names)
        self.assertIn("numpy", req_names)
        self.assertIn("flask", req_names)
    
    def test_extract_requirements_from_file(self):
        """Test extracting requirements from Python file imports."""
        python_content = """
import os
import sys
import requests
from numpy import array
from flask import Flask
import json
from datetime import datetime
import custom_module
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(python_content)
            temp_file_name = f.name
        
        try:
            requirements = self.parser.extract_requirements_from_file(temp_file_name)
            
            # Should include third-party modules but not stdlib
            self.assertIn("requests", requirements)
            self.assertIn("numpy", requirements)
            self.assertIn("flask", requirements)
            self.assertIn("custom_module", requirements)
            
            # Should not include stdlib modules
            self.assertNotIn("os", requirements)
            self.assertNotIn("sys", requirements)
            self.assertNotIn("json", requirements)
            self.assertNotIn("datetime", requirements)
            
        finally:
            try:
                os.unlink(temp_file_name)
            except (OSError, PermissionError):
                pass  # Ignore cleanup errors on Windows
    
    def test_is_stdlib_module(self):
        """Test stdlib module detection."""
        # Test known stdlib modules
        self.assertTrue(self.parser._is_stdlib_module("os"))
        self.assertTrue(self.parser._is_stdlib_module("sys"))
        self.assertTrue(self.parser._is_stdlib_module("json"))
        self.assertTrue(self.parser._is_stdlib_module("datetime"))
        
        # Test non-stdlib modules
        self.assertFalse(self.parser._is_stdlib_module("requests"))
        self.assertFalse(self.parser._is_stdlib_module("numpy"))
        self.assertFalse(self.parser._is_stdlib_module("flask"))


class TestDependencyManager(unittest.TestCase):
    """Test the DependencyManager class."""
    
    def setUp(self):
        self.manager = DependencyManager()
    
    @patch('hot_reload.dependency.pkg_resources.get_distribution')
    def test_check_dependencies_satisfied(self, mock_get_dist):
        """Test checking dependencies that are satisfied."""
        # Mock installed package
        mock_dist = Mock()
        mock_dist.version = "2.25.1"
        mock_get_dist.return_value = mock_dist
        
        requirements = ["requests>=2.0.0"]
        dependencies = self.manager.check_dependencies(requirements)
        
        self.assertEqual(len(dependencies), 1)
        dep = dependencies[0]
        self.assertEqual(dep.name, "requests")
        self.assertEqual(dep.status, DependencyStatus.SATISFIED)
        self.assertEqual(dep.installed_version, "2.25.1")
    
    @patch('hot_reload.dependency.pkg_resources.get_distribution')
    def test_check_dependencies_missing(self, mock_get_dist):
        """Test checking dependencies that are missing."""
        # Mock package not found
        from pkg_resources import DistributionNotFound
        mock_get_dist.side_effect = DistributionNotFound("Package not found")
        
        requirements = ["nonexistent-package>=1.0.0"]
        dependencies = self.manager.check_dependencies(requirements)
        
        self.assertEqual(len(dependencies), 1)
        dep = dependencies[0]
        self.assertEqual(dep.name, "nonexistent-package")
        self.assertEqual(dep.status, DependencyStatus.MISSING)
        self.assertIsNone(dep.installed_version)
    
    @patch('hot_reload.dependency.pkg_resources.get_distribution')
    def test_check_dependencies_version_conflict(self, mock_get_dist):
        """Test checking dependencies with version conflicts."""
        # Mock installed package with wrong version
        mock_dist = Mock()
        mock_dist.version = "1.5.0"
        mock_get_dist.return_value = mock_dist
        
        requirements = ["requests>=2.0.0"]
        dependencies = self.manager.check_dependencies(requirements)
        
        self.assertEqual(len(dependencies), 1)
        dep = dependencies[0]
        self.assertEqual(dep.name, "requests")
        self.assertEqual(dep.status, DependencyStatus.CONFLICT)
        self.assertEqual(dep.installed_version, "1.5.0")
        self.assertIn("doesn't satisfy", dep.error_message)
    
    def test_check_component_dependencies(self):
        """Test checking dependencies for a component."""
        metadata = ComponentMetadata(
            name="test_component",
            requirements=["requests>=2.0.0", "numpy==1.21.0"]
        )
        
        with patch.object(self.manager, 'check_dependencies') as mock_check:
            mock_check.return_value = [
                DependencyInfo(name="requests", status=DependencyStatus.SATISFIED),
                DependencyInfo(name="numpy", status=DependencyStatus.MISSING)
            ]
            
            dependencies = self.manager.check_component_dependencies(metadata)
            
            mock_check.assert_called_once_with(metadata.requirements)
            self.assertEqual(len(dependencies), 2)
    
    @patch('hot_reload.dependency.pkg_resources.get_distribution')
    def test_get_missing_dependencies(self, mock_get_dist):
        """Test getting list of missing dependencies."""
        def side_effect(package_name):
            if package_name == "requests":
                mock_dist = Mock()
                mock_dist.version = "2.25.1"
                return mock_dist
            else:
                from pkg_resources import DistributionNotFound
                raise DistributionNotFound("Package not found")
        
        mock_get_dist.side_effect = side_effect
        
        requirements = ["requests>=2.0.0", "nonexistent-package>=1.0.0"]
        missing = self.manager.get_missing_dependencies(requirements)
        
        self.assertEqual(len(missing), 1)
        self.assertIn("nonexistent-package", missing[0])
    
    @patch('hot_reload.dependency.pkg_resources.get_distribution')
    def test_validate_dependencies_all_satisfied(self, mock_get_dist):
        """Test validating dependencies when all are satisfied."""
        mock_dist = Mock()
        mock_dist.version = "2.25.1"
        mock_get_dist.return_value = mock_dist
        
        requirements = ["requests>=2.0.0"]
        is_valid, issues = self.manager.validate_dependencies(requirements)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    @patch('hot_reload.dependency.pkg_resources.get_distribution')
    def test_validate_dependencies_with_issues(self, mock_get_dist):
        """Test validating dependencies with issues."""
        def side_effect(package_name):
            if package_name == "requests":
                mock_dist = Mock()
                mock_dist.version = "1.5.0"  # Wrong version
                return mock_dist
            else:
                from pkg_resources import DistributionNotFound
                raise DistributionNotFound("Package not found")
        
        mock_get_dist.side_effect = side_effect
        
        requirements = ["requests>=2.0.0", "nonexistent-package>=1.0.0"]
        is_valid, issues = self.manager.validate_dependencies(requirements)
        
        self.assertFalse(is_valid)
        self.assertEqual(len(issues), 2)
        self.assertTrue(any("Version conflict" in issue for issue in issues))
        self.assertTrue(any("Missing dependency" in issue for issue in issues))
    
    def test_check_version_constraints(self):
        """Test version constraint checking."""
        # Test various version operators
        self.assertTrue(self.manager._check_version_constraints("2.25.1", [(">=", "2.0.0")]))
        self.assertTrue(self.manager._check_version_constraints("2.25.1", [("==", "2.25.1")]))
        self.assertTrue(self.manager._check_version_constraints("2.25.1", [("!=", "2.25.0")]))
        self.assertTrue(self.manager._check_version_constraints("2.25.1", [("<", "3.0.0")]))
        self.assertTrue(self.manager._check_version_constraints("2.25.1", [("<=", "2.25.1")]))
        
        # Test failing constraints
        self.assertFalse(self.manager._check_version_constraints("1.5.0", [(">=", "2.0.0")]))
        self.assertFalse(self.manager._check_version_constraints("2.25.1", [("==", "2.25.0")]))
        self.assertFalse(self.manager._check_version_constraints("2.25.1", [("!=", "2.25.1")]))
        self.assertFalse(self.manager._check_version_constraints("3.0.0", [("<", "2.0.0")]))
        self.assertFalse(self.manager._check_version_constraints("2.25.2", [("<=", "2.25.1")]))
    
    def test_compare_versions(self):
        """Test version comparison logic."""
        from packaging.version import Version
        
        v1 = Version("2.25.1")
        v2 = Version("2.0.0")
        v3 = Version("3.0.0")
        
        # Test all operators
        self.assertTrue(self.manager._compare_versions(v1, ">=", v2))
        self.assertTrue(self.manager._compare_versions(v1, ">", v2))
        self.assertFalse(self.manager._compare_versions(v1, "<", v2))
        self.assertFalse(self.manager._compare_versions(v1, "<=", v2))
        self.assertTrue(self.manager._compare_versions(v1, "==", v1))
        self.assertTrue(self.manager._compare_versions(v1, "!=", v2))
        
        # Test compatible release operator
        self.assertTrue(self.manager._compare_versions(Version("2.1.0"), "~=", Version("2.0.0")))
        self.assertFalse(self.manager._compare_versions(Version("3.0.0"), "~=", Version("2.0.0")))
    
    def test_clear_cache(self):
        """Test clearing the package cache."""
        # Add something to cache
        self.manager._package_cache["test"] = "1.0.0"
        self.assertEqual(len(self.manager._package_cache), 1)
        
        # Clear cache
        self.manager.clear_cache()
        self.assertEqual(len(self.manager._package_cache), 0)
    
    @patch('hot_reload.dependency.pkg_resources.get_distribution')
    def test_get_dependency_graph(self, mock_get_dist):
        """Test building dependency graph."""
        # Mock package with dependencies
        mock_dist = Mock()
        mock_dist.version = "2.25.1"
        mock_req1 = Mock()
        mock_req1.__str__ = Mock(return_value="urllib3 >=1.21.1")
        mock_req2 = Mock()
        mock_req2.__str__ = Mock(return_value="certifi >=2017.4.17")
        mock_dist.requires.return_value = [mock_req1, mock_req2]
        mock_get_dist.return_value = mock_dist
        
        requirements = ["requests>=2.0.0"]
        graph = self.manager.get_dependency_graph(requirements)
        
        self.assertIn("requests", graph)
        self.assertIn("urllib3", graph["requests"])
        self.assertIn("certifi", graph["requests"])
    
    def test_detect_circular_dependencies(self):
        """Test detecting circular dependencies."""
        # Mock a simple circular dependency scenario
        with patch.object(self.manager, 'get_dependency_graph') as mock_graph:
            # A depends on B, B depends on A
            mock_graph.return_value = {
                "package_a": ["package_b"],
                "package_b": ["package_a"]
            }
            
            requirements = ["package_a", "package_b"]
            cycles = self.manager.detect_circular_dependencies(requirements)
            
            # Should detect the circular dependency
            self.assertTrue(len(cycles) > 0)


class TestInstallationProgress(unittest.TestCase):
    """Test the InstallationProgress data class."""
    
    def test_progress_percentage(self):
        """Test progress percentage calculation."""
        progress = InstallationProgress(
            install_id="test",
            status=InstallationStatus.RUNNING,
            packages_total=10,
            packages_completed=3
        )
        
        self.assertEqual(progress.progress_percentage, 30.0)
    
    def test_progress_percentage_zero_total(self):
        """Test progress percentage with zero total packages."""
        progress = InstallationProgress(
            install_id="test",
            status=InstallationStatus.RUNNING,
            packages_total=0,
            packages_completed=0
        )
        
        self.assertEqual(progress.progress_percentage, 0.0)
    
    def test_is_complete(self):
        """Test completion status checking."""
        progress = InstallationProgress(
            install_id="test",
            status=InstallationStatus.RUNNING
        )
        self.assertFalse(progress.is_complete())
        
        progress.status = InstallationStatus.COMPLETED
        self.assertTrue(progress.is_complete())
        
        progress.status = InstallationStatus.FAILED
        self.assertTrue(progress.is_complete())
        
        progress.status = InstallationStatus.CANCELLED
        self.assertTrue(progress.is_complete())


class TestPipInstaller(unittest.TestCase):
    """Test the PipInstaller class."""
    
    def setUp(self):
        self.installer = PipInstaller()
    
    @patch('subprocess.run')
    def test_install_single_package_success(self, mock_run):
        """Test successful installation of a single package."""
        # Mock successful subprocess call
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed test-package-1.0.0"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        success, logs = self.installer._install_single_package("test-package==1.0.0")
        
        self.assertTrue(success)
        self.assertIn("Successfully installed test-package-1.0.0", logs)
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_install_single_package_failure(self, mock_run):
        """Test failed installation of a single package."""
        # Mock failed subprocess call
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "ERROR: Could not find a version that satisfies the requirement"
        mock_run.return_value = mock_result
        
        success, logs = self.installer._install_single_package("nonexistent-package")
        
        self.assertFalse(success)
        self.assertIn("Installation failed with return code: 1", logs)
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_install_single_package_timeout(self, mock_run):
        """Test installation timeout handling."""
        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired("pip", 300)
        
        success, logs = self.installer._install_single_package("slow-package")
        
        self.assertFalse(success)
        # Check that timeout message is in any of the log lines
        timeout_found = any("timed out after 5 minutes" in log for log in logs)
        self.assertTrue(timeout_found, f"Timeout message not found in logs: {logs}")
    
    @patch.object(PipInstaller, '_install_single_package')
    def test_install_packages_success(self, mock_install_single):
        """Test successful installation of multiple packages."""
        # Mock successful single package installations
        mock_install_single.side_effect = [
            (True, ["Successfully installed package1"]),
            (True, ["Successfully installed package2"])
        ]
        
        packages = ["package1==1.0.0", "package2==2.0.0"]
        result = self.installer.install_packages(packages, "test_component")
        
        self.assertTrue(result.success)
        self.assertEqual(len(result.installed_packages), 2)
        self.assertEqual(len(result.failed_packages), 0)
        self.assertEqual(result.component_name, "test_component")
    
    @patch.object(PipInstaller, '_install_single_package')
    def test_install_packages_partial_failure(self, mock_install_single):
        """Test installation with some packages failing."""
        # Mock mixed success/failure
        mock_install_single.side_effect = [
            (True, ["Successfully installed package1"]),
            (False, ["Failed to install package2"])
        ]
        
        packages = ["package1==1.0.0", "package2==2.0.0"]
        result = self.installer.install_packages(packages, "test_component")
        
        self.assertFalse(result.success)
        self.assertEqual(len(result.installed_packages), 1)
        self.assertEqual(len(result.failed_packages), 1)
        self.assertIn("package1==1.0.0", result.installed_packages)
        self.assertIn("package2==2.0.0", result.failed_packages)
    
    def test_get_installation_progress(self):
        """Test getting installation progress."""
        # Create a mock progress
        install_id = "test-install"
        progress = InstallationProgress(
            install_id=install_id,
            status=InstallationStatus.RUNNING
        )
        
        self.installer.active_installations[install_id] = progress
        
        retrieved_progress = self.installer.get_installation_progress(install_id)
        self.assertIsNotNone(retrieved_progress)
        self.assertEqual(retrieved_progress.install_id, install_id)
        
        # Test non-existent installation
        non_existent = self.installer.get_installation_progress("non-existent")
        self.assertIsNone(non_existent)
    
    def test_cancel_installation(self):
        """Test cancelling an installation."""
        # Create a running installation
        install_id = "test-install"
        progress = InstallationProgress(
            install_id=install_id,
            status=InstallationStatus.RUNNING
        )
        
        self.installer.active_installations[install_id] = progress
        
        # Cancel the installation
        success = self.installer.cancel_installation(install_id)
        self.assertTrue(success)
        self.assertEqual(progress.status, InstallationStatus.CANCELLED)
        
        # Try to cancel non-existent installation
        success = self.installer.cancel_installation("non-existent")
        self.assertFalse(success)
    
    def test_progress_callbacks(self):
        """Test progress callback functionality."""
        callback_called = []
        
        def test_callback(progress):
            callback_called.append(progress)
        
        # Add callback
        self.installer.add_progress_callback(test_callback)
        
        # Create and update progress
        install_id = "test-install"
        progress = InstallationProgress(
            install_id=install_id,
            status=InstallationStatus.RUNNING
        )
        
        self.installer.active_installations[install_id] = progress
        self.installer._update_progress(install_id, current_step="Testing callback")
        
        # Check callback was called
        self.assertEqual(len(callback_called), 1)
        self.assertEqual(callback_called[0].install_id, install_id)
        
        # Remove callback
        self.installer.remove_progress_callback(test_callback)
        self.installer._update_progress(install_id, current_step="Testing callback removal")
        
        # Should still be 1 (callback not called again)
        self.assertEqual(len(callback_called), 1)
    
    @patch('importlib.import_module')
    def test_validate_installation_success(self, mock_import):
        """Test successful installation validation."""
        # Mock successful imports
        mock_import.return_value = Mock()
        
        packages = ["package1", "package2"]
        success, issues = self.installer.validate_installation(packages)
        
        self.assertTrue(success)
        self.assertEqual(len(issues), 0)
        self.assertEqual(mock_import.call_count, 2)
    
    @patch('importlib.import_module')
    @patch('hot_reload.dependency.pkg_resources.get_distribution')
    def test_validate_installation_failure(self, mock_get_dist, mock_import):
        """Test installation validation with failures."""
        # Mock import failure
        mock_import.side_effect = ImportError("No module named 'package1'")
        
        # Mock pkg_resources failure
        from pkg_resources import DistributionNotFound
        mock_get_dist.side_effect = DistributionNotFound("Package not found")
        
        packages = ["package1"]
        success, issues = self.installer.validate_installation(packages)
        
        self.assertFalse(success)
        self.assertEqual(len(issues), 1)
        self.assertIn("not found after installation", issues[0])
    
    @patch('subprocess.run')
    def test_get_pip_version(self, mock_run):
        """Test getting pip version."""
        # Mock successful version check
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "pip 21.3.1 from /path/to/pip"
        mock_run.return_value = mock_result
        
        version = self.installer.get_pip_version()
        self.assertEqual(version, "pip 21.3.1 from /path/to/pip")
        
        # Mock failure
        mock_result.returncode = 1
        version = self.installer.get_pip_version()
        self.assertIsNone(version)
    
    @patch('subprocess.run')
    def test_upgrade_pip(self, mock_run):
        """Test pip upgrade functionality."""
        # Mock successful upgrade
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully upgraded pip"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        success, logs = self.installer.upgrade_pip()
        
        self.assertTrue(success)
        self.assertIn("Successfully upgraded pip", logs)


class TestDependencyManagerWithPipInstaller(unittest.TestCase):
    """Test DependencyManager integration with PipInstaller."""
    
    def setUp(self):
        self.manager = DependencyManager()
    
    @patch.object(DependencyManager, 'check_dependencies')
    @patch.object(PipInstaller, 'install_packages')
    def test_install_dependencies_all_satisfied(self, mock_install, mock_check):
        """Test installing dependencies when all are already satisfied."""
        # Mock all dependencies satisfied
        mock_check.return_value = [
            DependencyInfo(name="requests", status=DependencyStatus.SATISFIED)
        ]
        
        requirements = ["requests>=2.0.0"]
        result = self.manager.install_dependencies(requirements, "test_component")
        
        self.assertTrue(result.success)
        self.assertEqual(len(result.installed_packages), 0)
        self.assertIn("already satisfied", result.installation_log[0])
        
        # Should not call pip installer
        mock_install.assert_not_called()
    
    @patch.object(DependencyManager, 'check_dependencies')
    @patch.object(PipInstaller, 'install_packages')
    @patch.object(PipInstaller, 'validate_installation')
    def test_install_dependencies_with_missing(self, mock_validate, mock_install, mock_check):
        """Test installing missing dependencies."""
        # Mock some dependencies missing
        mock_check.return_value = [
            DependencyInfo(name="requests", status=DependencyStatus.MISSING, version_spec="requests>=2.0.0")
        ]
        
        # Mock successful installation
        from hot_reload.models import InstallationResult
        mock_install.return_value = InstallationResult(
            component_name="test_component",
            dependencies=[],
            success=True,
            installed_packages=["requests>=2.0.0"],
            failed_packages=[],
            installation_log=["Successfully installed requests"]
        )
        
        # Mock successful validation
        mock_validate.return_value = (True, [])
        
        requirements = ["requests>=2.0.0"]
        result = self.manager.install_dependencies(requirements, "test_component")
        
        self.assertTrue(result.success)
        self.assertEqual(len(result.installed_packages), 1)
        
        # Should call pip installer
        mock_install.assert_called_once()
        mock_validate.assert_called_once()
    
    def test_progress_callback_integration(self):
        """Test progress callback integration."""
        callback_called = []
        
        def test_callback(progress):
            callback_called.append(progress)
        
        # Add callback through manager
        self.manager.add_progress_callback(test_callback)
        
        # Verify callback was added to pip installer
        self.assertIn(test_callback, self.manager.pip_installer.progress_callbacks)
        
        # Remove callback
        self.manager.remove_progress_callback(test_callback)
        self.assertNotIn(test_callback, self.manager.pip_installer.progress_callbacks)


class TestDependencyValidation(unittest.TestCase):
    """Test dependency validation system."""
    
    def setUp(self):
        self.manager = DependencyManager()
    
    @patch.object(DependencyManager, 'check_dependencies')
    @patch('importlib.import_module')
    def test_validate_post_installation_success(self, mock_import, mock_check):
        """Test successful post-installation validation."""
        # Mock all dependencies satisfied
        mock_check.return_value = [
            DependencyInfo(name="requests", status=DependencyStatus.SATISFIED)
        ]
        
        # Mock successful imports
        mock_import.return_value = Mock()
        
        requirements = ["requests>=2.0.0"]
        success, issues, deps = self.manager.validate_post_installation(requirements, "test_component")
        
        self.assertTrue(success)
        self.assertEqual(len(issues), 0)
        self.assertEqual(len(deps), 1)
    
    @patch.object(DependencyManager, 'check_dependencies')
    @patch('importlib.import_module')
    def test_validate_post_installation_with_issues(self, mock_import, mock_check):
        """Test post-installation validation with issues."""
        # Mock some dependencies still missing
        mock_check.return_value = [
            DependencyInfo(name="requests", status=DependencyStatus.MISSING),
            DependencyInfo(name="numpy", status=DependencyStatus.SATISFIED)
        ]
        
        # Mock import failure for numpy
        def import_side_effect(module_name):
            if module_name == "numpy":
                raise ImportError("No module named 'numpy'")
            return Mock()
        
        mock_import.side_effect = import_side_effect
        
        requirements = ["requests>=2.0.0", "numpy>=1.0.0"]
        success, issues, deps = self.manager.validate_post_installation(requirements, "test_component")
        
        self.assertFalse(success)
        self.assertTrue(len(issues) > 0)
        self.assertTrue(any("still missing" in issue for issue in issues))
        self.assertTrue(any("Cannot import numpy" in issue for issue in issues))
    
    def test_detect_version_conflicts(self):
        """Test version conflict detection."""
        # Create conflicting requirements
        requirements = [
            "Django>=3.0,<4.0",
            "Django>=2.0,<3.0"  # Conflicting version range
        ]
        
        conflicts = self.manager.detect_version_conflicts(requirements)
        
        # Should detect conflict for Django
        self.assertTrue(len(conflicts) > 0)
        django_conflict = next((c for c in conflicts if c['package'] == 'Django'), None)
        self.assertIsNotNone(django_conflict)
        self.assertEqual(len(django_conflict['conflicting_requirements']), 2)
    
    def test_detect_version_conflicts_no_conflict(self):
        """Test version conflict detection with no conflicts."""
        requirements = [
            "requests>=2.0.0",
            "numpy>=1.0.0"
        ]
        
        conflicts = self.manager.detect_version_conflicts(requirements)
        
        # Should not detect any conflicts
        self.assertEqual(len(conflicts), 0)
    
    @patch.object(DependencyManager, 'get_dependency_graph')
    def test_detect_circular_dependencies_with_cycle(self, mock_graph):
        """Test circular dependency detection with actual cycles."""
        # Mock a circular dependency graph
        mock_graph.return_value = {
            "package_a": ["package_b"],
            "package_b": ["package_c"],
            "package_c": ["package_a"]  # Creates a cycle
        }
        
        requirements = ["package_a", "package_b", "package_c"]
        cycles = self.manager.detect_circular_dependencies(requirements)
        
        # Should detect the circular dependency
        self.assertTrue(len(cycles) > 0)
        # Check that the cycle contains all three packages
        cycle = cycles[0]
        self.assertIn("package_a", cycle)
        self.assertIn("package_b", cycle)
        self.assertIn("package_c", cycle)
    
    @patch.object(DependencyManager, 'get_dependency_graph')
    def test_detect_circular_dependencies_no_cycle(self, mock_graph):
        """Test circular dependency detection with no cycles."""
        # Mock a non-circular dependency graph
        mock_graph.return_value = {
            "package_a": ["package_b"],
            "package_b": ["package_c"],
            "package_c": []  # No cycle
        }
        
        requirements = ["package_a", "package_b", "package_c"]
        cycles = self.manager.detect_circular_dependencies(requirements)
        
        # Should not detect any cycles
        self.assertEqual(len(cycles), 0)
    
    @patch.object(DependencyManager, 'check_dependencies')
    @patch.object(DependencyManager, 'detect_version_conflicts')
    @patch.object(DependencyManager, 'detect_circular_dependencies')
    @patch.object(DependencyManager, '_validate_imports')
    def test_create_dependency_validation_report(self, mock_validate_imports, mock_circular, mock_conflicts, mock_check):
        """Test comprehensive dependency validation report creation."""
        # Mock various validation results
        mock_check.return_value = [
            DependencyInfo(name="requests", status=DependencyStatus.SATISFIED),
            DependencyInfo(name="numpy", status=DependencyStatus.MISSING)
        ]
        
        mock_conflicts.return_value = [
            {'package': 'Django', 'conflicting_requirements': ['Django>=3.0', 'Django<3.0']}
        ]
        
        mock_circular.return_value = [
            ['package_a', 'package_b', 'package_a']
        ]
        
        mock_validate_imports.return_value = [
            "Cannot import requests despite being installed"
        ]
        
        requirements = ["requests>=2.0.0", "numpy>=1.0.0", "Django>=3.0"]
        report = self.manager.create_dependency_validation_report(requirements, "test_component")
        
        # Check report structure
        self.assertEqual(report['component_name'], "test_component")
        self.assertEqual(report['requirements_count'], 3)
        self.assertEqual(len(report['dependency_status']), 2)
        self.assertEqual(len(report['missing_dependencies']), 1)
        self.assertEqual(len(report['version_conflicts']), 1)
        self.assertEqual(len(report['circular_dependencies']), 1)
        self.assertEqual(len(report['import_issues']), 1)
        self.assertEqual(report['overall_status'], 'missing_dependencies')
        self.assertTrue(len(report['recommendations']) > 0)
    
    @patch.object(DependencyManager, 'check_dependencies')
    def test_create_dependency_validation_report_all_satisfied(self, mock_check):
        """Test validation report when all dependencies are satisfied."""
        # Mock all dependencies satisfied
        mock_check.return_value = [
            DependencyInfo(name="requests", status=DependencyStatus.SATISFIED)
        ]
        
        requirements = ["requests>=2.0.0"]
        report = self.manager.create_dependency_validation_report(requirements, "test_component")
        
        # Should show satisfied status
        self.assertEqual(report['overall_status'], 'satisfied')
        self.assertEqual(len(report['missing_dependencies']), 0)
        self.assertEqual(len(report['version_conflicts']), 0)
        self.assertEqual(len(report['circular_dependencies']), 0)
        self.assertIn("All dependencies are satisfied", report['recommendations'])


class TestIntegrationWorkflow(unittest.TestCase):
    """Test complete dependency workflow integration."""
    
    def setUp(self):
        self.manager = DependencyManager()
    
    def test_dependency_manager_integration(self):
        """Test that DependencyManager integrates properly with PipInstaller."""
        # Test that the manager has the expected components
        self.assertIsInstance(self.manager.pip_installer, PipInstaller)
        self.assertIsInstance(self.manager.requirement_parser, RequirementParser)
        
        # Test that progress callbacks work
        callback_called = []
        
        def test_callback(progress):
            callback_called.append(progress)
        
        self.manager.add_progress_callback(test_callback)
        self.assertIn(test_callback, self.manager.pip_installer.progress_callbacks)
        
        self.manager.remove_progress_callback(test_callback)
        self.assertNotIn(test_callback, self.manager.pip_installer.progress_callbacks)
    
    def test_validation_report_integration(self):
        """Test that validation report includes all necessary components."""
        requirements = ["requests>=2.0.0", "numpy>=1.0.0"]
        
        # Create a validation report
        report = self.manager.create_dependency_validation_report(requirements, "test_component")
        
        # Verify report structure
        self.assertIn('component_name', report)
        self.assertIn('timestamp', report)
        self.assertIn('requirements_count', report)
        self.assertIn('dependency_status', report)
        self.assertIn('missing_dependencies', report)
        self.assertIn('version_conflicts', report)
        self.assertIn('circular_dependencies', report)
        self.assertIn('import_issues', report)
        self.assertIn('overall_status', report)
        self.assertIn('recommendations', report)
        
        self.assertEqual(report['component_name'], "test_component")
        self.assertEqual(report['requirements_count'], 2)
        self.assertIsInstance(report['dependency_status'], list)
        self.assertIsInstance(report['recommendations'], list)
    
    @patch.object(DependencyManager, 'check_dependencies')
    def test_workflow_methods_exist(self, mock_check):
        """Test that all workflow methods exist and can be called."""
        # Mock basic dependency info
        mock_check.return_value = [
            DependencyInfo(name="requests", status=DependencyStatus.SATISFIED)
        ]
        
        requirements = ["requests>=2.0.0"]
        
        # Test that all workflow methods exist and can be called
        
        # 1. Check dependencies
        deps = self.manager.check_dependencies(requirements)
        self.assertIsInstance(deps, list)
        
        # 2. Get missing dependencies
        missing = self.manager.get_missing_dependencies(requirements)
        self.assertIsInstance(missing, list)
        
        # 3. Validate dependencies
        is_valid, issues = self.manager.validate_dependencies(requirements)
        self.assertIsInstance(is_valid, bool)
        self.assertIsInstance(issues, list)
        
        # 4. Detect version conflicts
        conflicts = self.manager.detect_version_conflicts(requirements)
        self.assertIsInstance(conflicts, list)
        
        # 5. Detect circular dependencies
        cycles = self.manager.detect_circular_dependencies(requirements)
        self.assertIsInstance(cycles, list)
        
        # 6. Create validation report
        report = self.manager.create_dependency_validation_report(requirements)
        self.assertIsInstance(report, dict)
        
        # 7. Get active installations
        active = self.manager.get_active_installations()
        self.assertIsInstance(active, list)


if __name__ == '__main__':
    unittest.main()