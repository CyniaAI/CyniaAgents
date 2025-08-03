"""
Enhanced UI components for component management with hot reload functionality.

This module provides UI components for:
- Dependency installation with progress tracking
- ZIP import interface with drag-and-drop
- Component management controls
- Real-time status updates
"""

try:
    import streamlit as st
except ImportError:
    # For testing purposes when streamlit is not available
    st = None

import time
import threading
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
import io
import zipfile
import os

from hot_reload.models import (
    ComponentStatus, DependencyStatus, InstallationResult, 
    ReloadResult, ComponentMetadata, DependencyInfo
)
from component_manager import ComponentManager


class DependencyInstallationUI:
    """UI component for dependency installation with progress tracking."""
    
    def __init__(self, component_manager: ComponentManager):
        self.component_manager = component_manager
        self._installation_progress = {}
        self._installation_logs = {}
        
    def render_dependency_installation_interface(self, component_name: str) -> None:
        """
        Render the dependency installation interface for a component.
        
        Args:
            component_name: Name of the component
        """
        st.subheader(f"📦 Dependencies for {component_name}")
        
        # Get component dependencies
        dependencies = self.component_manager.get_component_dependencies(component_name)
        
        if not dependencies:
            st.info("This component has no dependencies.")
            return
        
        # Check current dependency status
        dependency_info = self.component_manager.dependency_manager.check_dependencies(dependencies)
        
        # Display dependency status
        self._render_dependency_status(component_name, dependency_info)
        
        # Show installation interface if needed
        missing_deps = [dep for dep in dependency_info if not dep.is_satisfied()]
        if missing_deps:
            self._render_installation_controls(component_name, missing_deps)
        
        # Show installation progress if active
        if component_name in self._installation_progress:
            self._render_installation_progress(component_name)
        
        # Show installation logs
        if component_name in self._installation_logs:
            self._render_installation_logs(component_name)
    
    def _render_dependency_status(self, component_name: str, dependency_info: List[DependencyInfo]) -> None:
        """Render the current status of dependencies."""
        st.markdown("#### Current Status")
        
        for dep in dependency_info:
            col1, col2, col3 = st.columns([3, 2, 2])
            
            with col1:
                st.write(f"**{dep.name}**")
                if dep.version_spec:
                    st.caption(f"Required: {dep.version_spec}")
            
            with col2:
                if dep.is_satisfied():
                    st.success("✅ Installed")
                    if dep.installed_version:
                        st.caption(f"Version: {dep.installed_version}")
                else:
                    st.error("❌ Missing")
            
            with col3:
                status_color = {
                    DependencyStatus.SATISFIED: "green",
                    DependencyStatus.MISSING: "red",
                    DependencyStatus.INSTALLING: "orange",
                    DependencyStatus.FAILED: "red",
                    DependencyStatus.CONFLICT: "orange"
                }.get(dep.status, "gray")
                
                st.markdown(f"<span style='color: {status_color}'>●</span> {dep.status.value.title()}", 
                           unsafe_allow_html=True)
    
    def _render_installation_controls(self, component_name: str, missing_deps: List[DependencyInfo]) -> None:
        """Render installation controls for missing dependencies."""
        st.markdown("#### Installation")
        
        # Show what will be installed
        dep_names = [dep.name for dep in missing_deps]
        st.info(f"Missing packages: {', '.join(dep_names)}")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            if st.button(f"🔧 Install Dependencies", key=f"install_{component_name}", type="primary"):
                self._start_installation(component_name, dep_names)
        
        with col2:
            if st.button(f"📋 Copy pip command", key=f"copy_{component_name}"):
                pip_command = f"pip install {' '.join(dep_names)}"
                st.code(pip_command, language="bash")
                st.success("Command copied to display!")
    
    def _render_installation_progress(self, component_name: str) -> None:
        """Render installation progress indicators."""
        progress_info = self._installation_progress.get(component_name, {})
        
        if not progress_info:
            return
        
        st.markdown("#### Installation Progress")
        
        # Overall progress bar
        overall_progress = progress_info.get('overall_progress', 0)
        st.progress(overall_progress / 100.0)
        
        # Current operation
        current_op = progress_info.get('current_operation', 'Installing...')
        st.info(f"🔄 {current_op}")
        
        # Package-specific progress
        package_progress = progress_info.get('package_progress', {})
        if package_progress:
            st.markdown("**Package Progress:**")
            for package, progress in package_progress.items():
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.write(package)
                with col2:
                    if progress == 100:
                        st.success("✅ Done")
                    elif progress > 0:
                        st.info(f"{progress}%")
                    else:
                        st.info("⏳ Waiting")
    
    def _render_installation_logs(self, component_name: str) -> None:
        """Render installation logs."""
        logs = self._installation_logs.get(component_name, [])
        
        if not logs:
            return
        
        with st.expander("📋 Installation Logs", expanded=False):
            log_text = "\n".join(logs)
            st.code(log_text, language="text")
    
    def _start_installation(self, component_name: str, packages: List[str]) -> None:
        """Start the installation process in a separate thread."""
        # Initialize progress tracking
        self._installation_progress[component_name] = {
            'overall_progress': 0,
            'current_operation': 'Starting installation...',
            'package_progress': {pkg: 0 for pkg in packages}
        }
        self._installation_logs[component_name] = []
        
        # Start installation in background thread
        def install_worker():
            try:
                # Update progress
                self._update_progress(component_name, 10, "Preparing installation...")
                
                # Perform installation
                result = self.component_manager.install_dependencies(component_name, packages)
                
                # Update progress based on result
                if result.success:
                    self._update_progress(component_name, 100, "Installation completed successfully!")
                    
                    # Update package progress
                    for pkg in packages:
                        self._installation_progress[component_name]['package_progress'][pkg] = 100
                    
                    # Add success log
                    self._add_log(component_name, f"✅ Successfully installed: {', '.join(result.installed_packages)}")
                    
                    # Trigger UI refresh
                    st.rerun()
                else:
                    self._update_progress(component_name, 0, f"Installation failed: {result.error_message}")
                    self._add_log(component_name, f"❌ Installation failed: {result.error_message}")
                
                # Add installation logs
                for log_line in result.installation_log:
                    self._add_log(component_name, log_line)
                
            except Exception as e:
                self._update_progress(component_name, 0, f"Installation error: {str(e)}")
                self._add_log(component_name, f"❌ Error: {str(e)}")
            
            finally:
                # Clean up progress after a delay
                time.sleep(5)
                if component_name in self._installation_progress:
                    del self._installation_progress[component_name]
        
        # Start the worker thread
        thread = threading.Thread(target=install_worker, daemon=True)
        thread.start()
        
        # Trigger immediate UI refresh to show progress
        st.rerun()
    
    def _update_progress(self, component_name: str, progress: int, operation: str) -> None:
        """Update installation progress."""
        if component_name in self._installation_progress:
            self._installation_progress[component_name]['overall_progress'] = progress
            self._installation_progress[component_name]['current_operation'] = operation
    
    def _add_log(self, component_name: str, message: str) -> None:
        """Add a log message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        
        if component_name not in self._installation_logs:
            self._installation_logs[component_name] = []
        
        self._installation_logs[component_name].append(log_entry)
        
        # Keep only last 100 log entries
        if len(self._installation_logs[component_name]) > 100:
            self._installation_logs[component_name] = self._installation_logs[component_name][-100:]


class ZipImportUI:
    """UI component for ZIP import with drag-and-drop functionality."""
    
    def __init__(self, component_manager: ComponentManager):
        self.component_manager = component_manager
        self._import_progress = {}
        self._import_logs = {}
    
    def render_zip_import_interface(self) -> None:
        """Render the ZIP import interface."""
        st.subheader("📁 Import Component from ZIP")
        
        # File upload interface
        uploaded_file = st.file_uploader(
            "Choose a ZIP file containing a component",
            type=['zip'],
            help="Upload a ZIP file containing a component with its code and metadata"
        )
        
        if uploaded_file is not None:
            self._handle_zip_upload(uploaded_file)
        
        # Show import progress if active
        if self._import_progress:
            self._render_import_progress()
        
        # Show import logs
        if self._import_logs:
            self._render_import_logs()
        
        # Instructions
        with st.expander("📖 ZIP Import Instructions", expanded=False):
            st.markdown("""
            **ZIP File Structure:**
            
            Your ZIP file should contain:
            - Component Python files (`.py`)
            - Optional `requirements.txt` for dependencies
            - Optional `README.md` for documentation
            
            **Example structure:**
            ```
            my_component.zip
            ├── my_component.py          # Main component file
            ├── requirements.txt         # Dependencies (optional)
            └── README.md               # Documentation (optional)
            ```
            
            **Or for package components:**
            ```
            my_package.zip
            ├── my_package/
            │   ├── __init__.py         # Package init
            │   ├── main.py            # Main component
            │   └── utils.py           # Helper modules
            ├── requirements.txt        # Dependencies (optional)
            └── README.md              # Documentation (optional)
            ```
            """)
    
    def _handle_zip_upload(self, uploaded_file) -> None:
        """Handle ZIP file upload and validation."""
        try:
            # Read ZIP file content
            zip_content = uploaded_file.read()
            
            # Validate ZIP file
            validation_result = self._validate_zip_file(zip_content, uploaded_file.name)
            
            if not validation_result['valid']:
                st.error(f"❌ Invalid ZIP file: {validation_result['error']}")
                return
            
            # Show ZIP contents
            st.success("✅ ZIP file is valid!")
            self._show_zip_contents(zip_content, uploaded_file.name)
            
            # Import button
            if st.button("🚀 Import Component", type="primary"):
                self._start_zip_import(zip_content, uploaded_file.name)
                
        except Exception as e:
            st.error(f"❌ Error processing ZIP file: {str(e)}")
    
    def _validate_zip_file(self, zip_content: bytes, filename: str) -> Dict[str, Any]:
        """Validate ZIP file structure and contents."""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_content), 'r') as zip_file:
                # Check for malicious paths
                for file_info in zip_file.filelist:
                    if '..' in file_info.filename or file_info.filename.startswith('/'):
                        return {
                            'valid': False,
                            'error': f"Potentially malicious path detected: {file_info.filename}"
                        }
                
                # Check for Python files
                python_files = [f for f in zip_file.namelist() if f.endswith('.py')]
                if not python_files:
                    return {
                        'valid': False,
                        'error': "No Python files found in ZIP"
                    }
                
                # Check file sizes (prevent zip bombs)
                total_size = sum(file_info.file_size for file_info in zip_file.filelist)
                if total_size > 100 * 1024 * 1024:  # 100MB limit
                    return {
                        'valid': False,
                        'error': "ZIP file too large (max 100MB)"
                    }
                
                return {
                    'valid': True,
                    'python_files': python_files,
                    'total_files': len(zip_file.namelist()),
                    'total_size': total_size
                }
                
        except zipfile.BadZipFile:
            return {
                'valid': False,
                'error': "Invalid ZIP file format"
            }
        except Exception as e:
            return {
                'valid': False,
                'error': f"Validation error: {str(e)}"
            }
    
    def _show_zip_contents(self, zip_content: bytes, filename: str) -> None:
        """Show ZIP file contents preview."""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_content), 'r') as zip_file:
                st.markdown("**ZIP Contents:**")
                
                files = zip_file.namelist()
                for file_path in sorted(files):
                    file_info = zip_file.getinfo(file_path)
                    size_kb = file_info.file_size / 1024
                    
                    # File type icon
                    if file_path.endswith('.py'):
                        icon = "🐍"
                    elif file_path.endswith('.txt'):
                        icon = "📄"
                    elif file_path.endswith('.md'):
                        icon = "📝"
                    elif file_path.endswith('/'):
                        icon = "📁"
                    else:
                        icon = "📄"
                    
                    st.write(f"{icon} `{file_path}` ({size_kb:.1f} KB)")
                
        except Exception as e:
            st.error(f"Error reading ZIP contents: {str(e)}")
    
    def _start_zip_import(self, zip_content: bytes, filename: str) -> None:
        """Start ZIP import process."""
        # Initialize progress tracking
        import_id = f"import_{int(time.time())}"
        self._import_progress[import_id] = {
            'filename': filename,
            'progress': 0,
            'status': 'Starting import...',
            'component_name': None
        }
        self._import_logs[import_id] = []
        
        def import_worker():
            try:
                # Update progress
                self._update_import_progress(import_id, 10, "Extracting ZIP file...")
                
                # Use component loader to import from ZIP
                result = self.component_manager.component_loader.load_component_from_zip(zip_content)
                
                if result.success:
                    self._update_import_progress(import_id, 80, "Component loaded successfully!")
                    self._add_import_log(import_id, f"✅ Successfully imported component: {result.metadata.name}")
                    
                    # Update component name
                    self._import_progress[import_id]['component_name'] = result.metadata.name
                    
                    # Refresh component discovery
                    self.component_manager.discover_components()
                    
                    self._update_import_progress(import_id, 100, "Import completed!")
                    
                    # Trigger UI refresh
                    st.rerun()
                else:
                    self._update_import_progress(import_id, 0, f"Import failed: {result.error_message}")
                    self._add_import_log(import_id, f"❌ Import failed: {result.error_message}")
                
            except Exception as e:
                self._update_import_progress(import_id, 0, f"Import error: {str(e)}")
                self._add_import_log(import_id, f"❌ Error: {str(e)}")
            
            finally:
                # Clean up progress after delay
                time.sleep(10)
                if import_id in self._import_progress:
                    del self._import_progress[import_id]
                if import_id in self._import_logs:
                    del self._import_logs[import_id]
        
        # Start worker thread
        thread = threading.Thread(target=import_worker, daemon=True)
        thread.start()
        
        # Trigger immediate UI refresh
        st.rerun()
    
    def _render_import_progress(self) -> None:
        """Render import progress indicators."""
        st.markdown("#### Import Progress")
        
        for import_id, progress_info in self._import_progress.items():
            with st.container():
                st.write(f"**{progress_info['filename']}**")
                
                # Progress bar
                progress = progress_info.get('progress', 0)
                st.progress(progress / 100.0)
                
                # Status
                status = progress_info.get('status', 'Processing...')
                if progress == 100:
                    st.success(f"✅ {status}")
                elif progress == 0 and 'failed' in status.lower():
                    st.error(f"❌ {status}")
                else:
                    st.info(f"🔄 {status}")
                
                st.markdown("---")
    
    def _render_import_logs(self) -> None:
        """Render import logs."""
        if not self._import_logs:
            return
        
        with st.expander("📋 Import Logs", expanded=False):
            for import_id, logs in self._import_logs.items():
                if logs:
                    st.markdown(f"**{self._import_progress.get(import_id, {}).get('filename', import_id)}**")
                    log_text = "\n".join(logs)
                    st.code(log_text, language="text")
    
    def _update_import_progress(self, import_id: str, progress: int, status: str) -> None:
        """Update import progress."""
        if import_id in self._import_progress:
            self._import_progress[import_id]['progress'] = progress
            self._import_progress[import_id]['status'] = status
    
    def _add_import_log(self, import_id: str, message: str) -> None:
        """Add import log message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        
        if import_id not in self._import_logs:
            self._import_logs[import_id] = []
        
        self._import_logs[import_id].append(log_entry)


class ComponentManagementUI:
    """UI component for component management controls."""
    
    def __init__(self, component_manager: ComponentManager):
        self.component_manager = component_manager
        self._operation_progress = {}
        self._operation_logs = {}
    
    def render_component_card(self, component_name: str, component) -> None:
        """
        Render an enhanced component card with management controls.
        
        Args:
            component_name: Name of the component
            component: Component instance
        """
        # Get component status and metadata
        status = self.component_manager.get_component_status(component_name)
        metadata = self.component_manager.get_component_metadata(component_name)
        
        # Determine card styling based on status
        status_colors = {
            ComponentStatus.LOADED: "#28a745",
            ComponentStatus.FAILED: "#dc3545",
            ComponentStatus.LOADING: "#ffc107",
            ComponentStatus.RELOADING: "#17a2b8",
            ComponentStatus.UNLOADING: "#6c757d",
            ComponentStatus.UNLOADED: "#6c757d",
            ComponentStatus.DISABLED: "#6c757d",
            ComponentStatus.UNKNOWN: "#6c757d"
        }
        
        status_color = status_colors.get(status, "#6c757d")
        
        # Check dependencies
        dependencies = self.component_manager.get_component_dependencies(component_name)
        missing_deps = self.component_manager.missing_requirements(dependencies)
        has_missing_deps = bool(missing_deps)
        
        # Determine if component can be enabled
        can_enable = not has_missing_deps and status not in [ComponentStatus.FAILED, ComponentStatus.UNKNOWN]
        
        # Component card container
        with st.container():
            # Card header with status indicator
            col1, col2, col3 = st.columns([6, 2, 2])
            
            with col1:
                # Component title with status indicator
                st.markdown(f"""
                <div style="display: flex; align-items: center; margin-bottom: 8px;">
                    <div style="width: 12px; height: 12px; border-radius: 50%; background-color: {status_color}; margin-right: 10px;"></div>
                    <h3 style="margin: 0; color: {'#ffffff' if can_enable else '#999999'};">{component_name}</h3>
                </div>
                """, unsafe_allow_html=True)
                
                # Component description
                description = getattr(component, 'description', 'No description available')
                if metadata and metadata.description:
                    description = metadata.description
                
                st.markdown(f"<p style='color: {'#ffffff' if can_enable else '#cccccc'}; margin: 0;'>{description}</p>", 
                           unsafe_allow_html=True)
                
                # Status and metadata info
                status_text = status.value.replace('_', ' ').title()
                st.caption(f"Status: {status_text}")
                
                if metadata:
                    if metadata.version:
                        st.caption(f"Version: {metadata.version}")
                    if metadata.author:
                        st.caption(f"Author: {metadata.author}")
            
            with col2:
                # Component management controls
                self._render_component_controls(component_name, component, status, can_enable)
            
            with col3:
                # Enable/disable toggle
                original_enabled = component_name in self.component_manager.enabled
                
                if has_missing_deps:
                    st.toggle("Enable", value=False, key=f"toggle_{component_name}", 
                             disabled=True, help="Cannot enable: missing dependencies")
                else:
                    enabled = st.toggle("Enable", value=original_enabled, key=f"toggle_{component_name}")
                    
                    # Handle toggle changes
                    if enabled != original_enabled:
                        if enabled:
                            if component_name not in self.component_manager.enabled:
                                self.component_manager.enabled.append(component_name)
                        else:
                            if component_name in self.component_manager.enabled:
                                self.component_manager.enabled.remove(component_name)
                        
                        self.component_manager.save_config()
                        st.rerun()
            
            # Dependency information
            if dependencies:
                self._render_dependency_info(component_name, dependencies, missing_deps)
            
            # Error information
            if status == ComponentStatus.FAILED:
                self._render_error_info(component_name)
            
            # Operation progress
            if component_name in self._operation_progress:
                self._render_operation_progress(component_name)
            
            st.markdown("---")
    
    def _render_component_controls(self, component_name: str, component, status: ComponentStatus, can_enable: bool) -> None:
        """Render component management control buttons."""
        # Install dependencies button (only keep this functionality)
        dependencies = self.component_manager.get_component_dependencies(component_name)
        missing_deps = self.component_manager.missing_requirements(dependencies)
        
        if missing_deps:
            if st.button("🔧", key=f"install_deps_{component_name}", 
                        help="Install dependencies", use_container_width=True):
                self._start_component_operation(component_name, "install_dependencies")
    
    def _render_dependency_info(self, component_name: str, dependencies: List[str], missing_deps: List[str]) -> None:
        """Render dependency information."""
        if missing_deps:
            st.error(f"⚠️ Missing dependencies: {', '.join(missing_deps)}")
            
            with st.expander("🔧 Dependency Actions", expanded=False):
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("Install All", key=f"install_all_{component_name}"):
                        self._start_component_operation(component_name, "install_dependencies")
                
                with col2:
                    pip_command = f"pip install {' '.join(missing_deps)}"
                    st.code(pip_command, language="bash")
        else:
            if dependencies:
                st.success(f"✅ All {len(dependencies)} dependencies satisfied")
    
    def _render_error_info(self, component_name: str) -> None:
        """Render error information and suggestions."""
        # Try to get error details from hot reload manager
        try:
            # This would need to be implemented in the hot reload manager
            # For now, show generic error info
            st.error("❌ Component failed to load")
            
            with st.expander("🔍 Error Details & Suggestions", expanded=False):
                st.markdown("**Common solutions:**")
                st.markdown("- Check for syntax errors in the component code")
                st.markdown("- Ensure all required dependencies are installed")
                st.markdown("- Verify the component inherits from BaseComponent")
                st.markdown("- Check the component has a get_component() function")
                
                # Show reload suggestion
                if st.button("🔄 Try Reload", key=f"error_reload_{component_name}"):
                    self._start_component_operation(component_name, "reload")
                    
        except Exception as e:
            st.error(f"Error getting error details: {str(e)}")
    
    def _render_operation_progress(self, component_name: str) -> None:
        """Render operation progress indicators."""
        progress_info = self._operation_progress.get(component_name, {})
        
        if not progress_info:
            return
        
        operation = progress_info.get('operation', 'Processing')
        progress = progress_info.get('progress', 0)
        status = progress_info.get('status', 'Working...')
        
        st.info(f"🔄 {operation.title()}: {status}")
        
        if progress > 0:
            st.progress(progress / 100.0)
    
    def _show_component_details(self, component_name: str, component) -> None:
        """Show detailed component information in a modal-like expander."""
        with st.expander(f"📋 Details for {component_name}", expanded=True):
            metadata = self.component_manager.get_component_metadata(component_name)
            status = self.component_manager.get_component_status(component_name)
            
            # Basic information
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Basic Information**")
                st.write(f"Name: {component_name}")
                st.write(f"Status: {status.value.replace('_', ' ').title()}")
                
                if metadata:
                    st.write(f"Version: {metadata.version}")
                    st.write(f"Author: {metadata.author}")
                    if metadata.file_path:
                        st.write(f"File: {metadata.file_path}")
            
            with col2:
                st.markdown("**Dependencies**")
                dependencies = self.component_manager.get_component_dependencies(component_name)
                
                if dependencies:
                    for dep in dependencies:
                        try:
                            __import__(dep)
                            st.success(f"✅ {dep}")
                        except ImportError:
                            st.error(f"❌ {dep}")
                else:
                    st.info("No dependencies")
            
            # Description
            if metadata and metadata.description:
                st.markdown("**Description**")
                st.write(metadata.description)
            
            # File information
            if metadata and metadata.file_path and os.path.exists(metadata.file_path):
                st.markdown("**File Information**")
                file_stats = os.stat(metadata.file_path)
                st.write(f"Size: {file_stats.st_size} bytes")
                st.write(f"Modified: {datetime.fromtimestamp(file_stats.st_mtime)}")
    
    def _start_component_operation(self, component_name: str, operation: str) -> None:
        """Start a component operation in the background."""
        # Initialize progress tracking
        self._operation_progress[component_name] = {
            'operation': operation,
            'progress': 0,
            'status': f'Starting {operation}...'
        }
        
        if component_name not in self._operation_logs:
            self._operation_logs[component_name] = []
        
        def operation_worker():
            try:
                if operation == "install_dependencies":
                    self._update_operation_progress(component_name, 20, "Installing dependencies...")
                    dependencies = self.component_manager.get_component_dependencies(component_name)
                    result = self.component_manager.install_dependencies(component_name, dependencies)
                    
                    if result.success:
                        self._update_operation_progress(component_name, 100, "Dependencies installed!")
                        self._add_operation_log(component_name, f"✅ Dependencies installed: {', '.join(result.installed_packages)}")
                    else:
                        self._update_operation_progress(component_name, 0, f"Installation failed: {result.error_message}")
                        self._add_operation_log(component_name, f"❌ Installation failed: {result.error_message}")
                
                # Trigger UI refresh
                st.rerun()
                
            except Exception as e:
                self._update_operation_progress(component_name, 0, f"Operation error: {str(e)}")
                self._add_operation_log(component_name, f"❌ Error: {str(e)}")
            
            finally:
                # Clean up progress after delay
                time.sleep(3)
                if component_name in self._operation_progress:
                    del self._operation_progress[component_name]
        
        # Start worker thread
        thread = threading.Thread(target=operation_worker, daemon=True)
        thread.start()
        
        # Trigger immediate UI refresh
        st.rerun()
    
    def _update_operation_progress(self, component_name: str, progress: int, status: str) -> None:
        """Update operation progress."""
        if component_name in self._operation_progress:
            self._operation_progress[component_name]['progress'] = progress
            self._operation_progress[component_name]['status'] = status
    
    def _add_operation_log(self, component_name: str, message: str) -> None:
        """Add operation log message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        
        if component_name not in self._operation_logs:
            self._operation_logs[component_name] = []
        
        self._operation_logs[component_name].append(log_entry)
        
        # Keep only last 50 log entries
        if len(self._operation_logs[component_name]) > 50:
            self._operation_logs[component_name] = self._operation_logs[component_name][-50:]


class RealTimeStatusUI:
    """UI component for real-time status updates and notifications."""
    
    def __init__(self, component_manager: ComponentManager):
        self.component_manager = component_manager
        self._status_cache = {}
        self._notifications = []
        self._last_update = datetime.now()
    
    def render_status_dashboard(self) -> None:
        """Render real-time status dashboard."""
        st.subheader("📊 Component Status Dashboard")
        
        # Get current status of all components
        current_statuses = self.component_manager.get_all_component_statuses()
        
        # Check for status changes
        self._check_status_changes(current_statuses)
        
        # Status summary
        self._render_status_summary(current_statuses)
        
        # Component status grid
        self._render_status_grid(current_statuses)
        
        # Notifications
        self._render_notifications()
        
        # Auto-refresh indicator
        self._render_refresh_indicator()
    
    def _render_status_summary(self, statuses: Dict[str, ComponentStatus]) -> None:
        """Render status summary metrics."""
        # Count components by status
        status_counts = {}
        for status in statuses.values():
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Display metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            loaded_count = status_counts.get(ComponentStatus.LOADED, 0)
            st.metric("✅ Loaded", loaded_count)
        
        with col2:
            failed_count = status_counts.get(ComponentStatus.FAILED, 0)
            st.metric("❌ Failed", failed_count)
        
        with col3:
            loading_count = (status_counts.get(ComponentStatus.LOADING, 0) + 
                           status_counts.get(ComponentStatus.RELOADING, 0))
            st.metric("🔄 Processing", loading_count)
        
        with col4:
            total_count = len(statuses)
            st.metric("📦 Total", total_count)
    
    def _render_status_grid(self, statuses: Dict[str, ComponentStatus]) -> None:
        """Render component status in a grid layout."""
        if not statuses:
            st.info("No components found.")
            return
        
        # Group components by status
        status_groups = {}
        for component_name, status in statuses.items():
            if status not in status_groups:
                status_groups[status] = []
            status_groups[status].append(component_name)
        
        # Render each status group
        for status, components in status_groups.items():
            status_color = {
                ComponentStatus.LOADED: "green",
                ComponentStatus.FAILED: "red",
                ComponentStatus.LOADING: "orange",
                ComponentStatus.RELOADING: "blue",
                ComponentStatus.UNLOADING: "gray",
                ComponentStatus.UNLOADED: "gray",
                ComponentStatus.DISABLED: "gray",
                ComponentStatus.UNKNOWN: "gray"
            }.get(status, "gray")
            
            status_text = status.value.replace('_', ' ').title()
            
            with st.expander(f"{status_text} ({len(components)})", expanded=True):
                # Display components in columns
                cols = st.columns(min(3, len(components)))
                
                for i, component_name in enumerate(components):
                    col_idx = i % len(cols)
                    
                    with cols[col_idx]:
                        st.markdown(f"""
                        <div style="
                            padding: 10px;
                            border-left: 4px solid {status_color};
                            background-color: rgba(255,255,255,0.05);
                            margin: 5px 0;
                            border-radius: 4px;
                        ">
                            <strong>{component_name}</strong><br>
                            <small style="color: {status_color};">●</small> {status_text}
                        </div>
                        """, unsafe_allow_html=True)
    
    def _render_notifications(self) -> None:
        """Render recent notifications."""
        if not self._notifications:
            return
        
        st.subheader("🔔 Recent Notifications")
        
        # Show last 5 notifications
        recent_notifications = self._notifications[-5:]
        
        for notification in reversed(recent_notifications):
            timestamp = notification['timestamp'].strftime("%H:%M:%S")
            message = notification['message']
            notification_type = notification['type']
            
            if notification_type == 'success':
                st.success(f"[{timestamp}] {message}")
            elif notification_type == 'error':
                st.error(f"[{timestamp}] {message}")
            elif notification_type == 'warning':
                st.warning(f"[{timestamp}] {message}")
            else:
                st.info(f"[{timestamp}] {message}")
    
    def _render_refresh_indicator(self) -> None:
        """Render auto-refresh indicator."""
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            last_update_str = self._last_update.strftime("%H:%M:%S")
            st.caption(f"Last updated: {last_update_str}")
        
        with col2:
            if st.button("🔄 Refresh Now"):
                st.rerun()
        
        with col3:
            # Auto-refresh toggle
            auto_refresh = st.checkbox("Auto-refresh", value=True)
            
            if auto_refresh:
                # Auto-refresh every 5 seconds
                time.sleep(5)
                st.rerun()
    
    def _check_status_changes(self, current_statuses: Dict[str, ComponentStatus]) -> None:
        """Check for status changes and generate notifications."""
        for component_name, current_status in current_statuses.items():
            previous_status = self._status_cache.get(component_name)
            
            if previous_status and previous_status != current_status:
                # Status changed - generate notification
                self._add_notification(
                    f"Component '{component_name}' status changed: {previous_status.value} → {current_status.value}",
                    self._get_notification_type(current_status)
                )
        
        # Update status cache
        self._status_cache = current_statuses.copy()
        self._last_update = datetime.now()
    
    def _get_notification_type(self, status: ComponentStatus) -> str:
        """Get notification type based on component status."""
        if status == ComponentStatus.LOADED:
            return 'success'
        elif status == ComponentStatus.FAILED:
            return 'error'
        elif status in [ComponentStatus.LOADING, ComponentStatus.RELOADING]:
            return 'info'
        else:
            return 'warning'
    
    def _add_notification(self, message: str, notification_type: str = 'info') -> None:
        """Add a notification."""
        notification = {
            'message': message,
            'type': notification_type,
            'timestamp': datetime.now()
        }
        
        self._notifications.append(notification)
        
        # Keep only last 20 notifications
        if len(self._notifications) > 20:
            self._notifications = self._notifications[-20:]


# Utility functions for UI components
def get_status_color(status: ComponentStatus) -> str:
    """Get color for component status."""
    colors = {
        ComponentStatus.LOADED: "#28a745",
        ComponentStatus.FAILED: "#dc3545",
        ComponentStatus.LOADING: "#ffc107",
        ComponentStatus.RELOADING: "#17a2b8",
        ComponentStatus.UNLOADING: "#6c757d",
        ComponentStatus.UNLOADED: "#6c757d",
        ComponentStatus.DISABLED: "#6c757d",
        ComponentStatus.UNKNOWN: "#6c757d"
    }
    return colors.get(status, "#6c757d")


def get_status_icon(status: ComponentStatus) -> str:
    """Get icon for component status."""
    icons = {
        ComponentStatus.LOADED: "✅",
        ComponentStatus.FAILED: "❌",
        ComponentStatus.LOADING: "⏳",
        ComponentStatus.RELOADING: "🔄",
        ComponentStatus.UNLOADING: "⏹️",
        ComponentStatus.UNLOADED: "⏸️",
        ComponentStatus.DISABLED: "🚫",
        ComponentStatus.UNKNOWN: "❓"
    }
    return icons.get(status, "❓")


def format_duration(seconds: float) -> str:
    """Format duration in a human-readable way."""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        return f"{minutes}m {remaining_seconds:.1f}s"


def format_file_size(size_bytes: int) -> str:
    """Format file size in a human-readable way."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"