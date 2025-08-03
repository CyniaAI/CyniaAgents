"""
Unit tests for the hot reload error handling framework.
"""

import unittest
from unittest.mock import Mock, patch
import sys
from datetime import datetime

from hot_reload.errors import (
    ErrorSeverity, ErrorInfo, ErrorReport, ComponentIsolator, ErrorHandler
)


class TestErrorInfo(unittest.TestCase):
    """Test cases for ErrorInfo dataclass."""
    
    def test_error_info_creation(self):
        """Test basic ErrorInfo creation."""
        error_info = ErrorInfo(
            error_type="import_error",
            message="Module not found",
            traceback="Traceback...",
            file_path="/path/to/file.py",
            line_number=42
        )
        
        self.assertEqual(error_info.error_type, "import_error")
        self.assertEqual(error_info.message, "Module not found")
        self.assertEqual(error_info.file_path, "/path/to/file.py")
        self.assertEqual(error_info.line_number, 42)
        self.assertEqual(error_info.severity, ErrorSeverity.MEDIUM)
        self.assertIsInstance(error_info.timestamp, datetime)
        self.assertEqual(error_info.suggestions, [])
    
    def test_error_info_with_suggestions(self):
        """Test ErrorInfo with suggestions."""
        suggestions = ["Install missing module", "Check spelling"]
        error_info = ErrorInfo(
            error_type="import_error",
            message="Module not found",
            traceback="Traceback...",
            suggestions=suggestions
        )
        
        self.assertEqual(error_info.suggestions, suggestions)


class TestErrorReport(unittest.TestCase):
    """Test cases for ErrorReport dataclass."""
    
    def test_error_report_creation(self):
        """Test basic ErrorReport creation."""
        error_info = ErrorInfo(
            error_type="import_error",
            message="Test error",
            traceback="Traceback..."
        )
        
        report = ErrorReport(
            component_name="test_component",
            operation="load",
            success=False,
            errors=[error_info],
            warnings=["Test warning"]
        )
        
        self.assertEqual(report.component_name, "test_component")
        self.assertEqual(report.operation, "load")
        self.assertFalse(report.success)
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(report.warnings, ["Test warning"])
        self.assertIsInstance(report.timestamp, datetime)
    
    def test_has_critical_errors(self):
        """Test critical error detection."""
        critical_error = ErrorInfo(
            error_type="critical_error",
            message="Critical error",
            traceback="Traceback...",
            severity=ErrorSeverity.CRITICAL
        )
        
        normal_error = ErrorInfo(
            error_type="normal_error",
            message="Normal error",
            traceback="Traceback...",
            severity=ErrorSeverity.MEDIUM
        )
        
        # Report with critical error
        report_critical = ErrorReport(
            component_name="test",
            operation="load",
            success=False,
            errors=[critical_error, normal_error],
            warnings=[]
        )
        
        # Report without critical error
        report_normal = ErrorReport(
            component_name="test",
            operation="load",
            success=False,
            errors=[normal_error],
            warnings=[]
        )
        
        self.assertTrue(report_critical.has_critical_errors())
        self.assertFalse(report_normal.has_critical_errors())
    
    def test_get_error_summary(self):
        """Test error summary generation."""
        errors = [
            ErrorInfo("error1", "msg1", "tb1", severity=ErrorSeverity.HIGH),
            ErrorInfo("error2", "msg2", "tb2", severity=ErrorSeverity.HIGH),
            ErrorInfo("error3", "msg3", "tb3", severity=ErrorSeverity.MEDIUM),
        ]
        
        report = ErrorReport(
            component_name="test",
            operation="load",
            success=False,
            errors=errors,
            warnings=[]
        )
        
        summary = report.get_error_summary()
        self.assertIn("2 high", summary)
        self.assertIn("1 medium", summary)
        
        # Test empty errors
        empty_report = ErrorReport(
            component_name="test",
            operation="load",
            success=True,
            errors=[],
            warnings=[]
        )
        
        self.assertEqual(empty_report.get_error_summary(), "No errors")


class TestComponentIsolator(unittest.TestCase):
    """Test cases for ComponentIsolator."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.isolator = ComponentIsolator()
    
    def test_isolate_import_error(self):
        """Test import error isolation."""
        # Mock sys.modules
        with patch.dict(sys.modules, {'test_component.submodule': Mock()}):
            error = ImportError("No module named 'missing_module'")
            result = self.isolator.isolate_component_error(
                "test_component", error, "import_error"
            )
            self.assertTrue(result)
    
    def test_isolate_runtime_error(self):
        """Test runtime error isolation."""
        error = RuntimeError("Runtime error occurred")
        result = self.isolator.isolate_component_error(
            "test_component", error, "runtime_error"
        )
        self.assertTrue(result)
    
    def test_isolate_dependency_error(self):
        """Test dependency error isolation."""
        error = ModuleNotFoundError("No module named 'dependency'")
        result = self.isolator.isolate_component_error(
            "test_component", error, "dependency_error"
        )
        self.assertTrue(result)
    
    def test_isolate_syntax_error(self):
        """Test syntax error isolation."""
        error = SyntaxError("Invalid syntax")
        result = self.isolator.isolate_component_error(
            "test_component", error, "syntax_error"
        )
        self.assertTrue(result)
    
    def test_isolation_status(self):
        """Test isolation status tracking."""
        component_name = "test_component"
        
        # Initially not isolated
        self.assertFalse(self.isolator.is_component_isolated(component_name))
        
        # Clear isolation (should not fail even if not isolated)
        self.isolator.clear_isolation(component_name)
        self.assertFalse(self.isolator.is_component_isolated(component_name))


class TestErrorHandler(unittest.TestCase):
    """Test cases for ErrorHandler."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.handler = ErrorHandler()
    
    def test_categorize_error(self):
        """Test error categorization."""
        # Test specific error types
        self.assertEqual(
            self.handler._categorize_error(ImportError()), "import_error"
        )
        self.assertEqual(
            self.handler._categorize_error(ModuleNotFoundError()), "dependency_error"
        )
        self.assertEqual(
            self.handler._categorize_error(SyntaxError()), "syntax_error"
        )
        self.assertEqual(
            self.handler._categorize_error(AttributeError()), "runtime_error"
        )
        self.assertEqual(
            self.handler._categorize_error(ValueError()), "runtime_error"
        )
        
        # Test unknown error type
        class CustomError(Exception):
            pass
        
        self.assertEqual(
            self.handler._categorize_error(CustomError()), "general_error"
        )
    
    def test_handle_component_error(self):
        """Test component error handling."""
        error = ImportError("No module named 'test_module'")
        report = self.handler.handle_component_error(
            "test_component", "load", error
        )
        
        self.assertEqual(report.component_name, "test_component")
        self.assertEqual(report.operation, "load")
        self.assertFalse(report.success)
        self.assertEqual(len(report.errors), 1)
        
        error_info = report.errors[0]
        self.assertEqual(error_info.error_type, "import_error")
        self.assertEqual(error_info.message, "No module named 'test_module'")
        self.assertIsNotNone(error_info.traceback)
        self.assertTrue(len(error_info.suggestions) > 0)
    
    def test_handle_import_error(self):
        """Test specific import error handling."""
        error = ImportError("No module named 'missing_module'")
        report = self.handler.handle_import_error("test_component", error)
        
        self.assertEqual(report.operation, "load")
        self.assertEqual(report.errors[0].error_type, "import_error")
    
    def test_handle_runtime_error(self):
        """Test specific runtime error handling."""
        error = AttributeError("'NoneType' object has no attribute 'test'")
        report = self.handler.handle_runtime_error("test_component", error)
        
        self.assertEqual(report.operation, "runtime")
        self.assertEqual(report.errors[0].error_type, "runtime_error")
    
    def test_generate_import_suggestions(self):
        """Test import error suggestion generation."""
        error = ImportError("No module named 'missing_module'")
        suggestions = self.handler._generate_import_suggestions(error)
        
        self.assertTrue(any("pip install" in s for s in suggestions))
        self.assertTrue(any("requirements.txt" in s for s in suggestions))
    
    def test_generate_dependency_suggestions(self):
        """Test dependency error suggestion generation."""
        error = ModuleNotFoundError("No module named 'dependency'")
        suggestions = self.handler._generate_dependency_suggestions(error)
        
        self.assertTrue(any("Component Center" in s for s in suggestions))
        self.assertTrue(any("requirements.txt" in s for s in suggestions))
    
    def test_generate_syntax_suggestions(self):
        """Test syntax error suggestion generation."""
        error = SyntaxError("Invalid syntax")
        suggestions = self.handler._generate_syntax_suggestions(error)
        
        self.assertTrue(any("syntax" in s for s in suggestions))
        self.assertTrue(any("linter" in s for s in suggestions))
    
    def test_generate_runtime_suggestions(self):
        """Test runtime error suggestion generation."""
        # Test attribute error
        attr_error = AttributeError("'NoneType' object has no attribute 'test'")
        suggestions = self.handler._generate_runtime_suggestions(attr_error)
        self.assertTrue(any("attribute" in s for s in suggestions))
        
        # Test type error
        type_error = TypeError("unsupported operand type(s)")
        suggestions = self.handler._generate_runtime_suggestions(type_error)
        self.assertTrue(any("data types" in s for s in suggestions))
        
        # Test value error
        value_error = ValueError("invalid literal")
        suggestions = self.handler._generate_runtime_suggestions(value_error)
        self.assertTrue(any("input values" in s for s in suggestions))
    
    def test_determine_severity(self):
        """Test error severity determination."""
        self.assertEqual(
            self.handler._determine_severity(SyntaxError(), "syntax_error"),
            ErrorSeverity.HIGH
        )
        self.assertEqual(
            self.handler._determine_severity(ImportError(), "import_error"),
            ErrorSeverity.MEDIUM
        )
        self.assertEqual(
            self.handler._determine_severity(ModuleNotFoundError(), "dependency_error"),
            ErrorSeverity.MEDIUM
        )
        self.assertEqual(
            self.handler._determine_severity(RuntimeError(), "runtime_error"),
            ErrorSeverity.MEDIUM
        )
        self.assertEqual(
            self.handler._determine_severity(Exception(), "general_error"),
            ErrorSeverity.LOW
        )
    
    def test_error_history(self):
        """Test error history management."""
        component_name = "test_component"
        error = ImportError("Test error")
        
        # Initially no history
        history = self.handler.get_component_error_history(component_name)
        self.assertEqual(len(history), 0)
        
        # Handle an error
        report = self.handler.handle_component_error(component_name, "load", error)
        
        # Check history
        history = self.handler.get_component_error_history(component_name)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0], report)
        
        # Clear history
        self.handler.clear_component_errors(component_name)
        history = self.handler.get_component_error_history(component_name)
        self.assertEqual(len(history), 0)
    
    def test_system_error_summary(self):
        """Test system error summary generation."""
        # Initially no errors
        summary = self.handler.get_system_error_summary()
        self.assertEqual(summary['total_errors'], 0)
        self.assertEqual(summary['critical_errors'], 0)
        self.assertEqual(summary['components_with_errors'], 0)
        
        # Add some errors
        error1 = ImportError("Error 1")
        error2 = SyntaxError("Error 2")
        
        self.handler.handle_component_error("comp1", "load", error1)
        self.handler.handle_component_error("comp2", "load", error2)
        
        summary = self.handler.get_system_error_summary()
        self.assertEqual(summary['total_errors'], 2)
        self.assertEqual(summary['components_with_errors'], 2)


if __name__ == '__main__':
    unittest.main()