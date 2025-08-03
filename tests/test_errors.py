"""
Unit tests for hot reload error handling framework.

This module tests all error handling, categorization, and isolation
functionality in the hot_reload.errors module.
"""

import pytest
import sys
from datetime import datetime
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to import hot_reload modules
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hot_reload.errors import (
    ErrorSeverity, ErrorInfo, ErrorReport, ComponentIsolator, ErrorHandler
)


class TestErrorSeverity:
    """Test cases for ErrorSeverity enum."""
    
    def test_error_severity_values(self):
        """Test ErrorSeverity enum values."""
        assert ErrorSeverity.LOW.value == "low"
        assert ErrorSeverity.MEDIUM.value == "medium"
        assert ErrorSeverity.HIGH.value == "high"
        assert ErrorSeverity.CRITICAL.value == "critical"


class TestErrorInfo:
    """Test cases for ErrorInfo data class."""
    
    def test_error_info_creation(self):
        """Test basic ErrorInfo creation."""
        error_info = ErrorInfo(
            error_type="import_error",
            message="Module not found",
            traceback="Traceback...",
            file_path="/path/to/file.py",
            line_number=42,
            suggestions=["Install module"],
            severity=ErrorSeverity.HIGH
        )
        
        assert error_info.error_type == "import_error"
        assert error_info.message == "Module not found"
        assert error_info.traceback == "Traceback..."
        assert error_info.file_path == "/path/to/file.py"
        assert error_info.line_number == 42
        assert error_info.suggestions == ["Install module"]
        assert error_info.severity == ErrorSeverity.HIGH
        assert isinstance(error_info.timestamp, datetime)
    
    def test_error_info_defaults(self):
        """Test ErrorInfo with default values."""
        error_info = ErrorInfo(
            error_type="runtime_error",
            message="Something went wrong",
            traceback="Traceback..."
        )
        
        assert error_info.suggestions == []
        assert error_info.severity == ErrorSeverity.MEDIUM
        assert error_info.file_path is None
        assert error_info.line_number is None
        assert isinstance(error_info.timestamp, datetime)
    
    def test_error_info_post_init(self):
        """Test ErrorInfo __post_init__ method."""
        # Test with None suggestions
        error_info = ErrorInfo(
            error_type="test",
            message="test",
            traceback="test",
            suggestions=None
        )
        assert error_info.suggestions == []
        
        # Test with None timestamp
        error_info = ErrorInfo(
            error_type="test",
            message="test",
            traceback="test",
            timestamp=None
        )
        assert isinstance(error_info.timestamp, datetime)


class TestErrorReport:
    """Test cases for ErrorReport data class."""
    
    def test_error_report_creation(self):
        """Test basic ErrorReport creation."""
        error_info = ErrorInfo(
            error_type="import_error",
            message="Test error",
            traceback="Test traceback"
        )
        
        report = ErrorReport(
            component_name="test_component",
            operation="load",
            success=False,
            errors=[error_info],
            warnings=["Test warning"],
            duration=1.5
        )
        
        assert report.component_name == "test_component"
        assert report.operation == "load"
        assert report.success is False
        assert len(report.errors) == 1
        assert report.warnings == ["Test warning"]
        assert report.duration == 1.5
        assert isinstance(report.timestamp, datetime)
    
    def test_error_report_defaults(self):
        """Test ErrorReport with default values."""
        report = ErrorReport(
            component_name="test",
            operation="test",
            success=True,
            errors=[],
            warnings=[]
        )
        
        assert isinstance(report.timestamp, datetime)
        assert report.duration == 0.0
    
    def test_has_critical_errors(self):
        """Test has_critical_errors method."""
        # No errors
        report = ErrorReport(
            component_name="test",
            operation="test",
            success=True,
            errors=[],
            warnings=[]
        )
        assert not report.has_critical_errors()
        
        # Non-critical errors
        error_info = ErrorInfo(
            error_type="test",
            message="test",
            traceback="test",
            severity=ErrorSeverity.MEDIUM
        )
        report.errors = [error_info]
        assert not report.has_critical_errors()
        
        # Critical error
        critical_error = ErrorInfo(
            error_type="test",
            message="test",
            traceback="test",
            severity=ErrorSeverity.CRITICAL
        )
        report.errors = [error_info, critical_error]
        assert report.has_critical_errors()
    
    def test_get_error_summary(self):
        """Test get_error_summary method."""
        # No errors
        report = ErrorReport(
            component_name="test",
            operation="test",
            success=True,
            errors=[],
            warnings=[]
        )
        assert report.get_error_summary() == "No errors"
        
        # Multiple errors with different severities
        errors = [
            ErrorInfo("test", "test", "test", severity=ErrorSeverity.LOW),
            ErrorInfo("test", "test", "test", severity=ErrorSeverity.MEDIUM),
            ErrorInfo("test", "test", "test", severity=ErrorSeverity.MEDIUM),
            ErrorInfo("test", "test", "test", severity=ErrorSeverity.HIGH),
            ErrorInfo("test", "test", "test", severity=ErrorSeverity.CRITICAL)
        ]
        report.errors = errors
        
        summary = report.get_error_summary()
        assert "1 low" in summary
        assert "2 medium" in summary
        assert "1 high" in summary
        assert "1 critical" in summary


class TestComponentIsolator:
    """Test cases for ComponentIsolator class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.isolator = ComponentIsolator()
    
    def test_isolator_initialization(self):
        """Test ComponentIsolator initialization."""
        assert self.isolator.isolated_components == {}
        assert len(self.isolator.isolation_strategies) == 4
        assert 'import_error' in self.isolator.isolation_strategies
        assert 'runtime_error' in self.isolator.isolation_strategies
        assert 'dependency_error' in self.isolator.isolation_strategies
        assert 'syntax_error' in self.isolator.isolation_strategies
    
    def test_isolate_import_error(self):
        """Test isolation of import errors."""
        # Mock sys.modules
        original_modules = sys.modules.copy()
        sys.modules['test_component.module'] = MagicMock()
        sys.modules['test_component.submodule'] = MagicMock()
        sys.modules['other_module'] = MagicMock()
        
        try:
            error = ImportError("Test import error")
            result = self.isolator._isolate_import_error("test_component", error)
            
            assert result is True
            assert 'test_component.module' not in sys.modules
            assert 'test_component.submodule' not in sys.modules
            assert 'other_module' in sys.modules  # Should not be removed
        finally:
            # Restore original modules
            sys.modules.clear()
            sys.modules.update(original_modules)
    
    def test_isolate_runtime_error(self):
        """Test isolation of runtime errors."""
        error = RuntimeError("Test runtime error")
        result = self.isolator._isolate_runtime_error("test_component", error)
        assert result is True
    
    def test_isolate_dependency_error(self):
        """Test isolation of dependency errors."""
        error = ModuleNotFoundError("Test dependency error")
        result = self.isolator._isolate_dependency_error("test_component", error)
        assert result is True
    
    def test_isolate_syntax_error(self):
        """Test isolation of syntax errors."""
        error = SyntaxError("Test syntax error")
        result = self.isolator._isolate_syntax_error("test_component", error)
        assert result is True
    
    def test_default_isolation(self):
        """Test default isolation strategy."""
        error = ValueError("Test error")
        result = self.isolator._default_isolation("test_component", error)
        assert result is True
    
    def test_isolate_component_error_success(self):
        """Test successful component error isolation."""
        error = ImportError("Test error")
        result = self.isolator.isolate_component_error("test_component", error, "import_error")
        assert result is True
    
    def test_isolate_component_error_unknown_type(self):
        """Test isolation with unknown error type."""
        error = ValueError("Test error")
        result = self.isolator.isolate_component_error("test_component", error, "unknown_error")
        assert result is True  # Should use default strategy
    
    def test_isolate_component_error_failure(self):
        """Test isolation failure handling."""
        # Mock a strategy that raises an exception
        def failing_strategy(component_name, error):
            raise Exception("Isolation failed")
        
        self.isolator.isolation_strategies['test_error'] = failing_strategy
        
        with patch('builtins.print') as mock_print:
            error = ValueError("Test error")
            result = self.isolator.isolate_component_error("test_component", error, "test_error")
            
            assert result is False
            mock_print.assert_called_once()
            assert "Failed to isolate error" in mock_print.call_args[0][0]
    
    def test_is_component_isolated(self):
        """Test component isolation status checking."""
        assert not self.isolator.is_component_isolated("test_component")
        
        self.isolator.isolated_components["test_component"] = []
        assert self.isolator.is_component_isolated("test_component")
    
    def test_get_isolation_errors(self):
        """Test getting isolation errors for a component."""
        # Component not isolated
        errors = self.isolator.get_isolation_errors("test_component")
        assert errors == []
        
        # Component isolated with errors
        error_info = ErrorInfo("test", "test", "test")
        self.isolator.isolated_components["test_component"] = [error_info]
        
        errors = self.isolator.get_isolation_errors("test_component")
        assert len(errors) == 1
        assert errors[0] == error_info
    
    def test_clear_isolation(self):
        """Test clearing component isolation."""
        # Add isolated component
        self.isolator.isolated_components["test_component"] = []
        assert self.isolator.is_component_isolated("test_component")
        
        # Clear isolation
        self.isolator.clear_isolation("test_component")
        assert not self.isolator.is_component_isolated("test_component")
        
        # Clear non-existent component (should not raise error)
        self.isolator.clear_isolation("non_existent")


class TestErrorHandler:
    """Test cases for ErrorHandler class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.handler = ErrorHandler()
    
    def test_handler_initialization(self):
        """Test ErrorHandler initialization."""
        assert isinstance(self.handler.component_isolator, ComponentIsolator)
        assert self.handler.error_history == {}
        assert len(self.handler.error_type_map) > 0
        assert len(self.handler.suggestion_generators) > 0
    
    def test_categorize_error(self):
        """Test error categorization."""
        # Test exact matches
        assert self.handler._categorize_error(ImportError()) == 'import_error'
        assert self.handler._categorize_error(ModuleNotFoundError()) == 'dependency_error'
        assert self.handler._categorize_error(SyntaxError()) == 'syntax_error'
        assert self.handler._categorize_error(AttributeError()) == 'runtime_error'
        assert self.handler._categorize_error(TypeError()) == 'runtime_error'
        assert self.handler._categorize_error(ValueError()) == 'runtime_error'
        
        # Test inheritance
        class CustomError(ImportError):
            pass
        
        assert self.handler._categorize_error(CustomError()) == 'import_error'
        
        # Test unknown error
        class UnknownError(BaseException):
            pass
        
        assert self.handler._categorize_error(UnknownError()) == 'general_error'
    
    def test_determine_severity(self):
        """Test error severity determination."""
        assert self.handler._determine_severity(SyntaxError(), 'syntax_error') == ErrorSeverity.HIGH
        assert self.handler._determine_severity(ImportError(), 'import_error') == ErrorSeverity.MEDIUM
        assert self.handler._determine_severity(ModuleNotFoundError(), 'dependency_error') == ErrorSeverity.MEDIUM
        assert self.handler._determine_severity(RuntimeError(), 'runtime_error') == ErrorSeverity.MEDIUM
        assert self.handler._determine_severity(Exception(), 'general_error') == ErrorSeverity.LOW
    
    def test_create_error_info(self):
        """Test error info creation from exception."""
        try:
            raise ValueError("Test error")
        except ValueError as e:
            error_info = self.handler._create_error_info(e, 'runtime_error')
            
            assert error_info.error_type == 'runtime_error'
            assert error_info.message == "Test error"
            assert "ValueError: Test error" in error_info.traceback
            assert error_info.severity == ErrorSeverity.MEDIUM
            assert len(error_info.suggestions) > 0
    
    def test_generate_import_suggestions(self):
        """Test import error suggestions."""
        error = ImportError("No module named 'missing_module'")
        suggestions = self.handler._generate_import_suggestions(error)
        
        assert len(suggestions) > 0
        assert any("pip install missing_module" in s for s in suggestions)
        assert any("spelled correctly" in s for s in suggestions)
    
    def test_generate_dependency_suggestions(self):
        """Test dependency error suggestions."""
        error = ModuleNotFoundError("Test error")
        suggestions = self.handler._generate_dependency_suggestions(error)
        
        assert len(suggestions) > 0
        assert any("Component Center" in s for s in suggestions)
        assert any("requirements.txt" in s for s in suggestions)
    
    def test_generate_syntax_suggestions(self):
        """Test syntax error suggestions."""
        error = SyntaxError("Test error")
        suggestions = self.handler._generate_syntax_suggestions(error)
        
        assert len(suggestions) > 0
        assert any("syntax" in s for s in suggestions)
        assert any("indentation" in s for s in suggestions)
    
    def test_generate_runtime_suggestions(self):
        """Test runtime error suggestions."""
        # Test attribute error
        error = AttributeError("'str' object has no attribute 'missing'")
        suggestions = self.handler._generate_runtime_suggestions(error)
        assert any("attribute" in s for s in suggestions)
        
        # Test type error
        error = TypeError("unsupported operand type(s)")
        suggestions = self.handler._generate_runtime_suggestions(error)
        assert any("data types" in s for s in suggestions)
        
        # Test value error
        error = ValueError("invalid literal for int()")
        suggestions = self.handler._generate_runtime_suggestions(error)
        assert any("input values" in s for s in suggestions)
    
    def test_generate_general_suggestions(self):
        """Test general error suggestions."""
        error = Exception("Unknown error")
        suggestions = self.handler._generate_general_suggestions(error)
        
        assert len(suggestions) > 0
        assert any("implementation" in s for s in suggestions)
        assert any("traceback" in s for s in suggestions)
    
    def test_handle_component_error(self):
        """Test component error handling."""
        error = ImportError("Test import error")
        
        with patch.object(self.handler.component_isolator, 'isolate_component_error', return_value=True):
            report = self.handler.handle_component_error("test_component", "load", error)
            
            assert report.component_name == "test_component"
            assert report.operation == "load"
            assert report.success is False
            assert len(report.errors) == 1
            assert report.errors[0].error_type == 'import_error'
            assert report.errors[0].severity != ErrorSeverity.CRITICAL
    
    def test_handle_component_error_isolation_failure(self):
        """Test component error handling when isolation fails."""
        error = ImportError("Test import error")
        
        with patch.object(self.handler.component_isolator, 'isolate_component_error', return_value=False):
            report = self.handler.handle_component_error("test_component", "load", error)
            
            assert report.errors[0].severity == ErrorSeverity.CRITICAL
            assert any("isolation failed" in s for s in report.errors[0].suggestions)
    
    def test_handle_import_error(self):
        """Test specific import error handling."""
        error = ImportError("Test import error")
        report = self.handler.handle_import_error("test_component", error)
        
        assert report.operation == "load"
        assert report.errors[0].error_type == 'import_error'
    
    def test_handle_runtime_error(self):
        """Test specific runtime error handling."""
        error = AttributeError("Test runtime error")  # AttributeError is mapped to runtime_error
        report = self.handler.handle_runtime_error("test_component", error)
        
        assert report.operation == "runtime"
        assert report.errors[0].error_type == 'runtime_error'
    
    def test_error_history_management(self):
        """Test error history management."""
        # Initially no history
        assert self.handler.get_component_error_history("test_component") == []
        
        # Add error
        error = ImportError("Test error")
        report = self.handler.handle_component_error("test_component", "load", error)
        
        # Check history
        history = self.handler.get_component_error_history("test_component")
        assert len(history) == 1
        assert history[0] == report
        
        # Add another error
        error2 = RuntimeError("Another error")
        report2 = self.handler.handle_component_error("test_component", "runtime", error2)
        
        history = self.handler.get_component_error_history("test_component")
        assert len(history) == 2
        
        # Clear history
        self.handler.clear_component_errors("test_component")
        assert self.handler.get_component_error_history("test_component") == []
    
    def test_clear_component_errors(self):
        """Test clearing component errors."""
        # Add error and isolation
        error = ImportError("Test error")
        self.handler.handle_component_error("test_component", "load", error)
        self.handler.component_isolator.isolated_components["test_component"] = []
        
        # Verify they exist
        assert len(self.handler.get_component_error_history("test_component")) > 0
        assert self.handler.component_isolator.is_component_isolated("test_component")
        
        # Clear errors
        self.handler.clear_component_errors("test_component")
        
        # Verify they're cleared
        assert self.handler.get_component_error_history("test_component") == []
        assert not self.handler.component_isolator.is_component_isolated("test_component")
    
    def test_get_system_error_summary(self):
        """Test system error summary."""
        # Initially no errors
        summary = self.handler.get_system_error_summary()
        assert summary['total_errors'] == 0
        assert summary['critical_errors'] == 0
        assert summary['isolated_components'] == 0
        assert summary['components_with_errors'] == 0
        
        # Add some errors
        error1 = ImportError("Error 1")
        error2 = SyntaxError("Error 2")
        
        with patch.object(self.handler.component_isolator, 'isolate_component_error', return_value=False):
            # This will create critical errors
            self.handler.handle_component_error("component1", "load", error1)
            self.handler.handle_component_error("component2", "load", error2)
        
        # Add isolated component
        self.handler.component_isolator.isolated_components["component3"] = []
        
        summary = self.handler.get_system_error_summary()
        assert summary['total_errors'] == 2
        assert summary['critical_errors'] == 2  # Both should be critical due to isolation failure
        assert summary['isolated_components'] == 1
        assert summary['components_with_errors'] == 2


class TestErrorHandlerIntegration:
    """Integration tests for error handling system."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.handler = ErrorHandler()
    
    def test_full_error_handling_workflow(self):
        """Test complete error handling workflow."""
        # Simulate a component with multiple types of errors
        component_name = "problematic_component"
        
        # Import error
        import_error = ImportError("No module named 'missing_dep'")
        import_report = self.handler.handle_component_error(component_name, "load", import_error)
        
        # Runtime error
        runtime_error = AttributeError("'NoneType' object has no attribute 'method'")
        runtime_report = self.handler.handle_component_error(component_name, "runtime", runtime_error)
        
        # Check error history
        history = self.handler.get_component_error_history(component_name)
        assert len(history) == 2
        
        # Check system summary
        summary = self.handler.get_system_error_summary()
        assert summary['total_errors'] == 2
        assert summary['components_with_errors'] == 1
        
        # Verify error types and suggestions
        assert import_report.errors[0].error_type == 'import_error'
        assert runtime_report.errors[0].error_type == 'runtime_error'
        
        assert len(import_report.errors[0].suggestions) > 0
        assert len(runtime_report.errors[0].suggestions) > 0
        
        # Clear errors
        self.handler.clear_component_errors(component_name)
        
        # Verify cleanup
        assert len(self.handler.get_component_error_history(component_name)) == 0
        summary = self.handler.get_system_error_summary()
        assert summary['components_with_errors'] == 0
    
    def test_error_isolation_integration(self):
        """Test error isolation integration."""
        component_name = "test_component"
        
        # Test successful isolation
        with patch.object(self.handler.component_isolator, 'isolate_component_error', return_value=True):
            error = ImportError("Test error")
            report = self.handler.handle_component_error(component_name, "load", error)
            
            assert not report.has_critical_errors()
            assert not any("isolation failed" in s for s in report.errors[0].suggestions)
        
        # Test failed isolation
        with patch.object(self.handler.component_isolator, 'isolate_component_error', return_value=False):
            error = ImportError("Test error")
            report = self.handler.handle_component_error(component_name, "load", error)
            
            assert report.has_critical_errors()
            assert any("isolation failed" in s for s in report.errors[0].suggestions)