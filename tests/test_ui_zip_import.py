"""
Unit tests for ZIP import UI components.

Tests the ZipImportUI class functionality including:
- ZIP file upload interface
- File validation
- Import progress tracking
- Error handling
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import threading
import time
import sys
import io
import zipfile

# Mock streamlit before importing
sys.modules['streamlit'] = Mock()

# Import the UI components
from ui_components import ZipImportUI
from hot_reload.models import ComponentMetadata, ReloadResult, ComponentStatus
from component_manager import ComponentManager


class TestZipImportUI(unittest.TestCase):
    """Test cases for ZipImportUI."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_component_manager = Mock()
        
        # Mock the component_loader attribute
        self.mock_component_manager.component_loader = Mock()
        self.mock_component_manager.component_loader.load_component_from_zip = Mock()
        self.mock_component_manager.discover_components = Mock()
        
        self.ui = ZipImportUI(self.mock_component_manager)
        
        # Mock Streamlit functions
        self.st_patcher = patch('ui_components.st')
        self.st_mock = self.st_patcher.start()
        
        # Configure st mock methods
        self.st_mock.subheader = Mock()
        self.st_mock.file_uploader = Mock(return_value=None)
        self.st_mock.info = Mock()
        self.st_mock.success = Mock()
        self.st_mock.error = Mock()
        self.st_mock.button = Mock(return_value=False)
        self.st_mock.code = Mock()
        self.st_mock.progress = Mock()
        self.st_mock.rerun = Mock()
        self.st_mock.markdown = Mock()
        self.st_mock.write = Mock()
        
        # Mock expander as context manager
        mock_expander = Mock()
        mock_expander.__enter__ = Mock(return_value=mock_expander)
        mock_expander.__exit__ = Mock(return_value=None)
        self.st_mock.expander = Mock(return_value=mock_expander)
    
    def tearDown(self):
        """Clean up after tests."""
        self.st_patcher.stop()
    
    def test_render_zip_import_interface_no_file(self):
        """Test rendering ZIP import interface with no file uploaded."""
        # Setup
        self.st_mock.file_uploader.return_value = None
        
        # Execute
        self.ui.render_zip_import_interface()
        
        # Verify
        self.st_mock.subheader.assert_called_once_with("📁 Import Component from ZIP")
        self.st_mock.file_uploader.assert_called_once()
    
    def test_render_zip_import_interface_with_file(self):
        """Test rendering ZIP import interface with uploaded file."""
        # Setup
        mock_file = Mock()
        mock_file.name = "test_component.zip"
        mock_file.read.return_value = b"fake zip content"
        self.st_mock.file_uploader.return_value = mock_file
        
        # Mock validation to return valid
        with patch.object(self.ui, '_validate_zip_file') as mock_validate:
            mock_validate.return_value = {
                'valid': True,
                'python_files': ['component.py'],
                'total_files': 2,
                'total_size': 1024
            }
            
            with patch.object(self.ui, '_show_zip_contents') as mock_show:
                # Execute
                self.ui.render_zip_import_interface()
                
                # Verify
                mock_validate.assert_called_once()
                mock_show.assert_called_once()
                self.st_mock.success.assert_called_with("✅ ZIP file is valid!")
    
    def test_validate_zip_file_valid(self):
        """Test ZIP file validation with valid file."""
        # Create a valid ZIP file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr('component.py', 'print("Hello World")')
            zip_file.writestr('requirements.txt', 'requests>=2.0.0')
        
        zip_content = zip_buffer.getvalue()
        
        # Execute
        result = self.ui._validate_zip_file(zip_content, "test.zip")
        
        # Verify
        self.assertTrue(result['valid'])
        self.assertIn('component.py', result['python_files'])
        self.assertEqual(result['total_files'], 2)
    
    def test_validate_zip_file_no_python_files(self):
        """Test ZIP file validation with no Python files."""
        # Create a ZIP file without Python files
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr('readme.txt', 'This is a readme')
        
        zip_content = zip_buffer.getvalue()
        
        # Execute
        result = self.ui._validate_zip_file(zip_content, "test.zip")
        
        # Verify
        self.assertFalse(result['valid'])
        self.assertEqual(result['error'], "No Python files found in ZIP")
    
    def test_validate_zip_file_malicious_path(self):
        """Test ZIP file validation with malicious paths."""
        # Create a ZIP file with malicious path
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr('../../../malicious.py', 'print("Malicious code")')
        
        zip_content = zip_buffer.getvalue()
        
        # Execute
        result = self.ui._validate_zip_file(zip_content, "test.zip")
        
        # Verify
        self.assertFalse(result['valid'])
        self.assertIn("malicious path", result['error'])
    
    def test_validate_zip_file_too_large(self):
        """Test ZIP file validation with file too large."""
        # Create a large ZIP file (mock the file size check)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr('component.py', 'print("Hello World")')
        
        zip_content = zip_buffer.getvalue()
        
        # Mock the file size to be too large
        with patch('zipfile.ZipFile') as mock_zip:
            mock_file_info = Mock()
            mock_file_info.filename = 'component.py'
            mock_file_info.file_size = 200 * 1024 * 1024  # 200MB
            
            mock_zip_instance = Mock()
            mock_zip_instance.filelist = [mock_file_info]
            mock_zip_instance.namelist.return_value = ['component.py']
            mock_zip.return_value.__enter__.return_value = mock_zip_instance
            
            # Execute
            result = self.ui._validate_zip_file(zip_content, "test.zip")
            
            # Verify
            self.assertFalse(result['valid'])
            self.assertIn("too large", result['error'])
    
    def test_validate_zip_file_bad_zip(self):
        """Test ZIP file validation with corrupted ZIP."""
        # Create invalid ZIP content
        zip_content = b"This is not a ZIP file"
        
        # Execute
        result = self.ui._validate_zip_file(zip_content, "test.zip")
        
        # Verify
        self.assertFalse(result['valid'])
        self.assertEqual(result['error'], "Invalid ZIP file format")
    
    def test_show_zip_contents(self):
        """Test showing ZIP file contents."""
        # Create a ZIP file with various file types
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr('component.py', 'print("Hello World")')
            zip_file.writestr('requirements.txt', 'requests>=2.0.0')
            zip_file.writestr('README.md', '# Component Documentation')
            zip_file.writestr('utils/', '')  # Directory
        
        zip_content = zip_buffer.getvalue()
        
        # Execute
        self.ui._show_zip_contents(zip_content, "test.zip")
        
        # Verify
        self.st_mock.markdown.assert_called_with("**ZIP Contents:**")
        # Should have called write for each file
        self.assertTrue(self.st_mock.write.called)
    
    def test_start_zip_import_success(self):
        """Test starting ZIP import process successfully."""
        # Setup
        zip_content = b"fake zip content"
        filename = "test_component.zip"
        
        # Mock successful import result
        mock_metadata = ComponentMetadata(
            name="test_component",
            description="Test component",
            version="1.0.0"
        )
        
        mock_result = ReloadResult(
            component_name="test_component",
            operation=None,
            success=True,
            status=ComponentStatus.LOADED,
            previous_status=ComponentStatus.UNKNOWN,
            metadata=mock_metadata
        )
        
        self.mock_component_manager.component_loader.load_component_from_zip.return_value = mock_result
        
        # Execute
        self.ui._start_zip_import(zip_content, filename)
        
        # Verify initial state
        self.assertTrue(len(self.ui._import_progress) > 0)
        self.assertTrue(len(self.ui._import_logs) > 0)
        
        # Wait for thread to complete
        time.sleep(0.1)
    
    def test_start_zip_import_failure(self):
        """Test starting ZIP import process with failure."""
        # Setup
        zip_content = b"fake zip content"
        filename = "invalid_component.zip"
        
        # Mock failed import result
        mock_result = ReloadResult(
            component_name="invalid_component",
            operation=None,
            success=False,
            status=ComponentStatus.FAILED,
            previous_status=ComponentStatus.UNKNOWN,
            error_message="Invalid component structure"
        )
        
        self.mock_component_manager.component_loader.load_component_from_zip.return_value = mock_result
        
        # Execute
        self.ui._start_zip_import(zip_content, filename)
        
        # Verify initial state
        self.assertTrue(len(self.ui._import_progress) > 0)
        self.assertTrue(len(self.ui._import_logs) > 0)
    
    def test_render_import_progress(self):
        """Test rendering import progress indicators."""
        # Setup
        import_id = "import_123"
        self.ui._import_progress[import_id] = {
            'filename': 'test_component.zip',
            'progress': 75,
            'status': 'Extracting files...',
            'component_name': 'test_component'
        }
        
        # Execute
        self.ui._render_import_progress()
        
        # Verify
        self.st_mock.markdown.assert_called_with("#### Import Progress")
        self.st_mock.write.assert_called()
        self.st_mock.progress.assert_called_with(0.75)  # 75% progress
    
    def test_render_import_logs(self):
        """Test rendering import logs."""
        # Setup
        import_id = "import_123"
        self.ui._import_logs[import_id] = [
            "[10:30:15] Starting import...",
            "[10:30:16] Extracting ZIP file...",
            "[10:30:20] ✅ Component imported successfully"
        ]
        self.ui._import_progress[import_id] = {'filename': 'test_component.zip'}
        
        # Mock expander
        mock_expander = Mock()
        self.st_mock.expander.return_value.__enter__ = Mock(return_value=mock_expander)
        self.st_mock.expander.return_value.__exit__ = Mock(return_value=None)
        
        # Execute
        self.ui._render_import_logs()
        
        # Verify
        self.st_mock.expander.assert_called_with("📋 Import Logs", expanded=False)
    
    def test_update_import_progress(self):
        """Test updating import progress."""
        # Setup
        import_id = "import_123"
        self.ui._import_progress[import_id] = {
            'progress': 0,
            'status': 'Starting...'
        }
        
        # Execute
        self.ui._update_import_progress(import_id, 50, "Processing...")
        
        # Verify
        self.assertEqual(self.ui._import_progress[import_id]['progress'], 50)
        self.assertEqual(self.ui._import_progress[import_id]['status'], "Processing...")
    
    def test_add_import_log(self):
        """Test adding import log messages."""
        # Setup
        import_id = "import_123"
        message = "Test import log message"
        
        # Execute
        self.ui._add_import_log(import_id, message)
        
        # Verify
        self.assertIn(import_id, self.ui._import_logs)
        self.assertEqual(len(self.ui._import_logs[import_id]), 1)
        self.assertIn(message, self.ui._import_logs[import_id][0])
    
    def test_handle_zip_upload_invalid_file(self):
        """Test handling ZIP upload with invalid file."""
        # Setup
        mock_file = Mock()
        mock_file.name = "invalid.zip"
        mock_file.read.return_value = b"invalid zip content"
        
        # Mock validation to return invalid
        with patch.object(self.ui, '_validate_zip_file') as mock_validate:
            mock_validate.return_value = {
                'valid': False,
                'error': 'Invalid ZIP file format'
            }
            
            # Execute
            self.ui._handle_zip_upload(mock_file)
            
            # Verify
            self.st_mock.error.assert_called_with("❌ Invalid ZIP file: Invalid ZIP file format")
    
    def test_render_instructions(self):
        """Test rendering ZIP import instructions."""
        # Execute
        self.ui.render_zip_import_interface()
        
        # Verify that expander for instructions is created
        # (The exact verification depends on the implementation details)
        self.st_mock.expander.assert_called()


if __name__ == '__main__':
    unittest.main()