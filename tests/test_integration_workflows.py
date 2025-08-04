"""
Integration tests for hot reload workflows.

This module tests end-to-end workflows including hot reload operations,
dependency installation, ZIP import workflows, and performance regression tests.
"""

import pytest
import sys
import tempfile
import os
import time
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

# Add the parent directory to the path to import hot_reload modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from hot_reload.models import ComponentStatus
from hot_reload.cache import ModuleCache
from hot_reload.dependency import DependencyManager
from hot_reload.loader import ComponentLoader
from hot_reload.hot_reload_manager import HotReloadManager
from hot_reload.errors import ErrorHandler


class TestEndToEndHotReloadWorkflows:
    """Test complete end-to-end hot reload workflows."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        os.makedirs(self.components_dir, exist_ok=True)
        
        # Initialize core components
        self.error_handler = ErrorHandler()
        self.module_cache = ModuleCache()
        
        # Initialize managers
        self.hot_reload_manager = HotReloadManager(self.components_dir)
        self.dependency_manager = DependencyManager()
        self.component_loader = ComponentLoader(self.components_dir, self.error_handler)
    
    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.module_cache.clear_cache()
    
    def create_test_component(self, name: str, content: str = None):
        """Create a test component with proper structure."""
        component_dir = os.path.join(self.components_dir, name)
        os.makedirs(component_dir, exist_ok=True)
        
        # Create __init__.py file (required for package structure)
        init_file = os.path.join(component_dir, "__init__.py")
        with open(init_file, 'w') as f:
            f.write("# Component package initialization\n")
        
        if content is None:
            content = f'''
"""Test component {name}."""

def get_info():
    return {{
        "name": "{name}",
        "description": "Test component",
        "version": "1.0.0"
    }}

COMPONENT_INFO = get_info()
'''
        
        # Create main component file
        component_file = os.path.join(component_dir, f"{name}.py")
        with open(component_file, 'w') as f:
            f.write(content)
        
        return component_dir, component_file
    
    def test_complete_component_lifecycle(self):
        """Test complete component lifecycle: load -> reload -> unload."""
        component_name = "lifecycle_test"
        
        # Create test component
        component_dir, component_file = self.create_test_component(component_name)
        
        # Load component
        load_result = self.component_loader.load_component_from_path(component_dir)
        assert load_result.success, f"Load failed: {load_result.error_message}"
        assert load_result.component_name == component_name
        
        # Verify component is loaded
        status = self.hot_reload_manager.get_component_status(component_name)
        assert status == ComponentStatus.LOADED
        
        # Modify and reload component
        modified_content = f'''
"""Modified test component {component_name}."""

def get_info():
    return {{
        "name": "{component_name}",
        "description": "Modified test component",
        "version": "2.0.0"
    }}

COMPONENT_INFO = get_info()
'''
        
        with open(component_file, 'w') as f:
            f.write(modified_content)
        
        # Reload component
        reload_result = self.hot_reload_manager.hot_reload_component(component_name)
        assert reload_result.success, f"Reload failed: {reload_result.errors}"
        assert reload_result.component_name == component_name
        assert reload_result.new_version == "2.0.0"
        
        # Unload component
        unload_result = self.hot_reload_manager.unload_component(component_name)
        assert unload_result.success, f"Unload failed: {unload_result.errors}"
        
        # Verify component is unloaded
        status = self.hot_reload_manager.get_component_status(component_name)
        assert status == ComponentStatus.UNLOADED
    
    def test_hot_reload_with_dependencies(self):
        """Test hot reload workflow with dependency management."""
        component_name = "dependency_test"
        
        # Create component with dependencies
        content = '''
"""Component with dependencies."""
import json

def get_info():
    return {
        "name": "dependency_test",
        "description": "Component with dependencies",
        "version": "1.0.0"
    }

def process_json(data):
    return json.dumps(data)

COMPONENT_INFO = get_info()
'''
        
        component_dir, component_file = self.create_test_component(component_name, content)
        
        # Create requirements.txt
        req_file = os.path.join(component_dir, "requirements.txt")
        with open(req_file, 'w') as f:
            f.write("requests>=2.25.0")
        
        # Mock pip installation
        with patch.object(self.dependency_manager, 'install_dependencies') as mock_install:
            mock_install.return_value = Mock(
                success=True,
                installed_packages=["requests"],
                failed_packages=[],
                installation_log="Successfully installed requests",
                duration=2.5
            )
            
            # Load component
            load_result = self.component_loader.load_component_from_path(component_dir)
            
            # Verify component loaded successfully
            assert load_result.success, f"Load failed: {load_result.error_message}"
            assert load_result.component_name == component_name
    
    def test_concurrent_hot_reload_operations(self):
        """Test concurrent hot reload operations."""
        import threading
        
        component_names = ["concurrent_1", "concurrent_2", "concurrent_3"]
        
        # Create multiple components
        for name in component_names:
            self.create_test_component(name)
        
        # Load all components concurrently
        def load_component(name):
            component_dir = os.path.join(self.components_dir, name)
            return self.component_loader.load_component_from_path(component_dir)
        
        threads = []
        results = {}
        
        for name in component_names:
            thread = threading.Thread(
                target=lambda n=name: results.update({n: load_component(n)})
            )
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify all components loaded successfully
        for name in component_names:
            assert name in results
            assert results[name].success, f"Load failed for {name}: {results[name].error_message}"
            
            status = self.hot_reload_manager.get_component_status(name)
            assert status == ComponentStatus.LOADED
    
    def test_hot_reload_error_recovery(self):
        """Test hot reload error recovery workflow."""
        component_name = "error_recovery_test"
        
        # Create valid component
        component_dir, component_file = self.create_test_component(component_name)
        
        # Load component successfully
        load_result = self.component_loader.load_component_from_path(component_dir)
        assert load_result.success
        
        # Introduce syntax error
        invalid_content = '''
"""Invalid component with syntax error."""

def get_info():
    return {
        "name": "error_recovery_test"
        "description": "Invalid component"  # Missing comma - syntax error
        "version": "1.0.0"
    }
'''
        
        with open(component_file, 'w') as f:
            f.write(invalid_content)
        
        # Attempt reload (should fail but not crash)
        reload_result = self.hot_reload_manager.hot_reload_component(component_name)
        assert not reload_result.success
        assert len(reload_result.errors) > 0
        
        # Verify original component is still available
        status = self.hot_reload_manager.get_component_status(component_name)
        assert status == ComponentStatus.LOADED  # Should maintain previous version
        
        # Fix the component
        fixed_content = '''
"""Fixed component."""

def get_info():
    return {
        "name": "error_recovery_test",
        "description": "Fixed component",
        "version": "1.1.0"
    }

COMPONENT_INFO = get_info()
'''
        
        with open(component_file, 'w') as f:
            f.write(fixed_content)
        
        # Reload should now succeed
        reload_result = self.hot_reload_manager.hot_reload_component(component_name)
        assert reload_result.success
        assert reload_result.new_version == "1.1.0"


class TestDependencyInstallationWorkflows:
    """Test dependency installation workflows."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        os.makedirs(self.components_dir, exist_ok=True)
        
        self.error_handler = ErrorHandler()
        self.dependency_manager = DependencyManager()
        self.component_loader = ComponentLoader(self.components_dir, self.error_handler)
    
    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def create_test_component(self, name: str, content: str = None, requirements: list = None):
        """Create a test component with proper structure."""
        component_dir = os.path.join(self.components_dir, name)
        os.makedirs(component_dir, exist_ok=True)
        
        # Create __init__.py file
        init_file = os.path.join(component_dir, "__init__.py")
        with open(init_file, 'w') as f:
            f.write("# Component package initialization\n")
        
        if content is None:
            content = f'''
"""Test component {name}."""

def get_info():
    return {{
        "name": "{name}",
        "description": "Test component",
        "version": "1.0.0"
    }}

COMPONENT_INFO = get_info()
'''
        
        # Create main component file
        component_file = os.path.join(component_dir, f"{name}.py")
        with open(component_file, 'w') as f:
            f.write(content)
        
        # Create requirements.txt if specified
        if requirements:
            req_file = os.path.join(component_dir, "requirements.txt")
            with open(req_file, 'w') as f:
                f.write('\n'.join(requirements))
        
        return component_dir, component_file
    
    def test_automatic_dependency_detection_and_installation(self):
        """Test automatic dependency detection and installation workflow."""
        component_name = "auto_deps_test"
        
        # Create component with dependencies
        content = '''
"""Component with dependencies."""
import json

def get_info():
    return {
        "name": "auto_deps_test",
        "description": "Component with auto-detected dependencies",
        "version": "1.0.0"
    }

def process_data(data):
    return json.dumps(data)

COMPONENT_INFO = get_info()
'''
        
        requirements = ["requests>=2.25.0", "pyyaml>=5.4.0"]
        component_dir, _ = self.create_test_component(component_name, content, requirements)
        
        # Mock dependency checking and installation
        with patch.object(self.dependency_manager, 'check_dependencies') as mock_check, \
             patch.object(self.dependency_manager, 'install_dependencies') as mock_install:
            
            # Mock missing dependencies
            mock_check.return_value = Mock(
                missing_packages=["requests", "pyyaml"],
                satisfied_packages=[],
                conflicts=[]
            )
            
            # Mock successful installation
            mock_install.return_value = Mock(
                success=True,
                installed_packages=["requests", "pyyaml"],
                failed_packages=[],
                installation_log="All packages installed successfully",
                duration=15.2
            )
            
            # Load component
            load_result = self.component_loader.load_component_from_path(component_dir)
            
            # Verify component loaded successfully
            assert load_result.success, f"Load failed: {load_result.error_message}"
    
    def test_dependency_installation_with_failures(self):
        """Test dependency installation workflow with partial failures."""
        component_name = "partial_deps_test"
        
        content = '''
"""Component with problematic dependencies."""
import json

def get_info():
    return {
        "name": "partial_deps_test",
        "description": "Component with partial dependency failures",
        "version": "1.0.0"
    }

COMPONENT_INFO = get_info()
'''
        
        requirements = ["requests>=2.25.0", "nonexistent-package>=1.0.0"]
        component_dir, _ = self.create_test_component(component_name, content, requirements)
        
        # Mock partial installation failure
        with patch.object(self.dependency_manager, 'install_dependencies') as mock_install:
            mock_install.return_value = Mock(
                success=False,
                installed_packages=["requests"],
                failed_packages=["nonexistent-package"],
                installation_log="Failed to install nonexistent-package",
                duration=8.3,
                errors=[Mock(message="Package not found", severity="ERROR")]
            )
            
            # Load component
            load_result = self.component_loader.load_component_from_path(component_dir)
            
            # Should handle partial failure gracefully
            assert not load_result.success
            assert len(load_result.errors) > 0


class TestZipImportWorkflows:
    """Test ZIP import workflows."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        os.makedirs(self.components_dir, exist_ok=True)
        
        from hot_reload.zip_importer import ZipImporter
        self.zip_importer = ZipImporter()
        self.component_loader = ComponentLoader(self.components_dir)
    
    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def create_test_zip(self, component_name: str, content: str = None):
        """Create a test ZIP file containing a component."""
        import zipfile
        import io
        import json
        
        zip_buffer = io.BytesIO()
        
        if content is None:
            content = f'''
"""Test component {component_name} from ZIP."""

def get_info():
    return {{
        "name": "{component_name}",
        "description": "Test component from ZIP import",
        "version": "1.0.0"
    }}

COMPONENT_INFO = get_info()
'''
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add __init__.py file
            zip_file.writestr(f"{component_name}/__init__.py", "# Component package initialization\n")
            
            # Add component file
            zip_file.writestr(f"{component_name}/{component_name}.py", content)
            
            # Add metadata
            metadata = {
                "name": component_name,
                "description": "Test component from ZIP",
                "version": "1.0.0",
                "author": "Test Suite"
            }
            zip_file.writestr(f"{component_name}/metadata.json", json.dumps(metadata, indent=2))
        
        zip_buffer.seek(0)
        return zip_buffer.getvalue()
    
    def test_complete_zip_import_workflow(self):
        """Test complete ZIP import workflow."""
        component_name = "zip_import_test"
        
        # Create test ZIP
        zip_data = self.create_test_zip(component_name)
        
        # Import ZIP
        import_result = self.zip_importer.import_component_zip(
            zip_data, 
            self.components_dir
        )
        
        assert import_result.success, f"Import failed: {import_result.errors}"
        assert import_result.component_name == component_name
        
        # Verify component was extracted
        component_dir = os.path.join(self.components_dir, component_name)
        assert os.path.exists(component_dir)
        assert os.path.exists(os.path.join(component_dir, f"{component_name}.py"))
        assert os.path.exists(os.path.join(component_dir, "__init__.py"))
        
        # Load the imported component
        load_result = self.component_loader.load_component_from_path(component_dir)
        assert load_result.success, f"Load failed: {load_result.error_message}"
        assert load_result.component_name == component_name
    
    def test_malicious_zip_protection(self):
        """Test protection against malicious ZIP files."""
        import zipfile
        import io
        
        # Create malicious ZIP with path traversal
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Attempt path traversal
            zip_file.writestr("../../../malicious.py", "print('Malicious code')")
            zip_file.writestr("component/../../../another_malicious.py", "print('More malicious code')")
        
        zip_buffer.seek(0)
        malicious_zip = zip_buffer.getvalue()
        
        # Import should fail with security error
        import_result = self.zip_importer.import_component_zip(
            malicious_zip, 
            self.components_dir
        )
        
        assert not import_result.success
        assert any("security" in str(error).lower() or "path" in str(error).lower() 
                  for error in import_result.errors)
        
        # Verify no malicious files were created
        parent_dir = os.path.dirname(self.components_dir)
        assert not os.path.exists(os.path.join(parent_dir, "malicious.py"))


class TestPerformanceRegressionWorkflows:
    """Test performance regression workflows."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.components_dir = os.path.join(self.temp_dir, "components")
        os.makedirs(self.components_dir, exist_ok=True)
        
        self.component_loader = ComponentLoader(self.components_dir)
        self.hot_reload_manager = HotReloadManager(self.components_dir)
    
    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def create_test_component(self, name: str):
        """Create a test component with proper structure."""
        component_dir = os.path.join(self.components_dir, name)
        os.makedirs(component_dir, exist_ok=True)
        
        # Create __init__.py file
        init_file = os.path.join(component_dir, "__init__.py")
        with open(init_file, 'w') as f:
            f.write("# Component package initialization\n")
        
        component_file = os.path.join(component_dir, f"{name}.py")
        content = f'''
"""Performance test component {name}."""

def get_info():
    return {{
        "name": "{name}",
        "description": "Performance test component",
        "version": "1.0.0"
    }}

COMPONENT_INFO = get_info()
'''
        
        with open(component_file, 'w') as f:
            f.write(content)
        
        return component_dir, component_file
    
    def test_component_loading_performance(self):
        """Test component loading performance benchmarks."""
        component_count = 10
        max_load_time_per_component = 1.0  # seconds
        
        # Create multiple test components
        component_names = [f"perf_test_{i}" for i in range(component_count)]
        for name in component_names:
            self.create_test_component(name)
        
        # Measure loading performance
        start_time = time.time()
        load_results = []
        
        for name in component_names:
            component_dir = os.path.join(self.components_dir, name)
            component_start = time.time()
            
            load_result = self.component_loader.load_component_from_path(component_dir)
            
            component_time = time.time() - component_start
            load_results.append({
                'name': name,
                'success': load_result.success,
                'load_time': component_time
            })
        
        total_time = time.time() - start_time
        
        # Verify performance benchmarks
        assert total_time < component_count * max_load_time_per_component
        
        # Verify all components loaded successfully
        successful_loads = [r for r in load_results if r['success']]
        assert len(successful_loads) == component_count
        
        # Check individual component load times
        for result in load_results:
            assert result['load_time'] < max_load_time_per_component
    
    def test_hot_reload_performance(self):
        """Test hot reload performance benchmarks."""
        component_name = "reload_perf_test"
        max_reload_time = 2.0  # seconds
        
        # Create and load component
        component_dir, component_file = self.create_test_component(component_name)
        load_result = self.component_loader.load_component_from_path(component_dir)
        assert load_result.success
        
        # Perform multiple reloads and measure performance
        reload_times = []
        
        for i in range(5):
            # Modify component
            modified_content = f'''
"""Modified component iteration {i}."""

def get_info():
    return {{
        "name": "{component_name}",
        "description": "Performance test component iteration {i}",
        "version": "1.{i}.0"
    }}

COMPONENT_INFO = get_info()
'''
            
            with open(component_file, 'w') as f:
                f.write(modified_content)
            
            # Measure reload time
            start_time = time.time()
            reload_result = self.hot_reload_manager.hot_reload_component(component_name)
            reload_time = time.time() - start_time
            
            reload_times.append(reload_time)
            
            assert reload_result.success
            assert reload_time < max_reload_time
        
        # Verify consistent performance
        avg_reload_time = sum(reload_times) / len(reload_times)
        assert avg_reload_time < max_reload_time * 0.8  # Should be well under limit


if __name__ == "__main__":
    pytest.main([__file__, "-v"])