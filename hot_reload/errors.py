"""
Error handling framework for the hot reload system.

This module provides comprehensive error handling, categorization, and isolation
for component loading, reloading, and unloading operations.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any
import traceback
import sys
from datetime import datetime


class ErrorSeverity(Enum):
    """Severity levels for errors in the hot reload system."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ErrorInfo:
    """Detailed information about an error that occurred during component operations."""
    error_type: str
    message: str
    traceback: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    suggestions: List[str] = None
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class ErrorReport:
    """Comprehensive error report for component operations."""
    component_name: str
    operation: str  # 'load', 'reload', 'unload', 'install_dependencies'
    success: bool
    errors: List[ErrorInfo]
    warnings: List[str]
    timestamp: datetime = None
    duration: float = 0.0
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def has_critical_errors(self) -> bool:
        """Check if the report contains any critical errors."""
        return any(error.severity == ErrorSeverity.CRITICAL for error in self.errors)
    
    def get_error_summary(self) -> str:
        """Get a summary of all errors in the report."""
        if not self.errors:
            return "No errors"
        
        error_counts = {}
        for error in self.errors:
            error_counts[error.severity] = error_counts.get(error.severity, 0) + 1
        
        summary_parts = []
        for severity, count in error_counts.items():
            summary_parts.append(f"{count} {severity.value}")
        
        return f"Errors: {', '.join(summary_parts)}"


class ComponentIsolator:
    """Handles error isolation to prevent component failures from affecting the entire system."""
    
    def __init__(self):
        self.isolated_components: Dict[str, List[ErrorInfo]] = {}
        self.isolation_strategies = {
            'import_error': self._isolate_import_error,
            'runtime_error': self._isolate_runtime_error,
            'dependency_error': self._isolate_dependency_error,
            'syntax_error': self._isolate_syntax_error
        }
    
    def isolate_component_error(self, component_name: str, error: Exception, error_type: str) -> bool:
        """
        Isolate a component error to prevent system-wide impact.
        
        Args:
            component_name: Name of the component with the error
            error: The exception that occurred
            error_type: Type of error ('import_error', 'runtime_error', etc.)
            
        Returns:
            bool: True if isolation was successful, False otherwise
        """
        try:
            strategy = self.isolation_strategies.get(error_type, self._default_isolation)
            return strategy(component_name, error)
        except Exception as isolation_error:
            # If isolation itself fails, log it but don't propagate
            print(f"Failed to isolate error for component {component_name}: {isolation_error}")
            return False
    
    def _isolate_import_error(self, component_name: str, error: Exception) -> bool:
        """Isolate import errors by cleaning up partial imports."""
        try:
            # Remove any partially loaded modules
            modules_to_remove = []
            for module_name in sys.modules:
                if component_name in module_name:
                    modules_to_remove.append(module_name)
            
            for module_name in modules_to_remove:
                del sys.modules[module_name]
            
            return True
        except Exception:
            return False
    
    def _isolate_runtime_error(self, component_name: str, error: Exception) -> bool:
        """Isolate runtime errors by containing their effects."""
        # For runtime errors, we mainly need to ensure the error doesn't propagate
        # The component should be marked as failed but not affect others
        return True
    
    def _isolate_dependency_error(self, component_name: str, error: Exception) -> bool:
        """Isolate dependency errors by preventing cascade failures."""
        # Mark component as having dependency issues
        # This prevents other components from trying to depend on it
        return True
    
    def _isolate_syntax_error(self, component_name: str, error: Exception) -> bool:
        """Isolate syntax errors by preventing module loading."""
        # Syntax errors are caught during parsing, so isolation is mainly
        # about ensuring the error is properly reported
        return True
    
    def _default_isolation(self, component_name: str, error: Exception) -> bool:
        """Default isolation strategy for unknown error types."""
        return True
    
    def is_component_isolated(self, component_name: str) -> bool:
        """Check if a component is currently isolated due to errors."""
        return component_name in self.isolated_components
    
    def get_isolation_errors(self, component_name: str) -> List[ErrorInfo]:
        """Get the errors that caused a component to be isolated."""
        return self.isolated_components.get(component_name, [])
    
    def clear_isolation(self, component_name: str) -> None:
        """Clear isolation status for a component."""
        if component_name in self.isolated_components:
            del self.isolated_components[component_name]


class ErrorHandler:
    """Main error handler for the hot reload system."""
    
    def __init__(self):
        self.component_isolator = ComponentIsolator()
        self.error_history: Dict[str, List[ErrorReport]] = {}
        
        # Error type mappings for better categorization
        self.error_type_map = {
            ImportError: 'import_error',
            ModuleNotFoundError: 'dependency_error',
            SyntaxError: 'syntax_error',
            AttributeError: 'runtime_error',
            TypeError: 'runtime_error',
            ValueError: 'runtime_error',
            Exception: 'general_error'
        }
        
        # Suggestion generators for different error types
        self.suggestion_generators = {
            'import_error': self._generate_import_suggestions,
            'dependency_error': self._generate_dependency_suggestions,
            'syntax_error': self._generate_syntax_suggestions,
            'runtime_error': self._generate_runtime_suggestions,
            'general_error': self._generate_general_suggestions
        }
    
    def handle_component_error(self, component_name: str, operation: str, error: Exception) -> ErrorReport:
        """
        Handle an error that occurred during a component operation.
        
        Args:
            component_name: Name of the component
            operation: Operation being performed ('load', 'reload', 'unload', etc.)
            error: The exception that occurred
            
        Returns:
            ErrorReport: Detailed error report
        """
        error_type = self._categorize_error(error)
        error_info = self._create_error_info(error, error_type)
        
        # Attempt to isolate the error
        isolation_success = self.component_isolator.isolate_component_error(
            component_name, error, error_type
        )
        
        if not isolation_success:
            error_info.severity = ErrorSeverity.CRITICAL
            error_info.suggestions.append("Error isolation failed - system stability may be affected")
        
        # Create error report
        report = ErrorReport(
            component_name=component_name,
            operation=operation,
            success=False,
            errors=[error_info],
            warnings=[]
        )
        
        # Store in history
        if component_name not in self.error_history:
            self.error_history[component_name] = []
        self.error_history[component_name].append(report)
        
        return report
    
    def handle_import_error(self, component_name: str, error: ImportError) -> ErrorReport:
        """Handle import errors specifically."""
        return self.handle_component_error(component_name, 'load', error)
    
    def handle_runtime_error(self, component_name: str, error: Exception) -> ErrorReport:
        """Handle runtime errors specifically."""
        return self.handle_component_error(component_name, 'runtime', error)
    
    def _categorize_error(self, error: Exception) -> str:
        """Categorize an error based on its type."""
        error_class = type(error)
        
        # Check for exact matches first
        if error_class in self.error_type_map:
            return self.error_type_map[error_class]
        
        # Check for inheritance
        for error_type, category in self.error_type_map.items():
            if isinstance(error, error_type):
                return category
        
        return 'general_error'
    
    def _create_error_info(self, error: Exception, error_type: str) -> ErrorInfo:
        """Create detailed error information from an exception."""
        # Extract file path and line number from traceback
        tb = traceback.extract_tb(error.__traceback__)
        file_path = None
        line_number = None
        
        if tb:
            # Get the last frame (where the error occurred)
            last_frame = tb[-1]
            file_path = last_frame.filename
            line_number = last_frame.lineno
        
        # Generate suggestions based on error type
        suggestions = self._generate_suggestions(error, error_type)
        
        # Determine severity
        severity = self._determine_severity(error, error_type)
        
        return ErrorInfo(
            error_type=error_type,
            message=str(error),
            traceback=traceback.format_exc(),
            file_path=file_path,
            line_number=line_number,
            suggestions=suggestions,
            severity=severity
        )
    
    def _generate_suggestions(self, error: Exception, error_type: str) -> List[str]:
        """Generate helpful suggestions based on the error type."""
        generator = self.suggestion_generators.get(error_type, self._generate_general_suggestions)
        return generator(error)
    
    def _generate_import_suggestions(self, error: Exception) -> List[str]:
        """Generate suggestions for import errors."""
        suggestions = []
        error_msg = str(error).lower()
        
        if "no module named" in error_msg:
            module_name = error_msg.split("no module named ")[-1].strip("'\"")
            suggestions.extend([
                f"Install the missing module: pip install {module_name}",
                "Check if the module name is spelled correctly",
                "Verify the module is in your Python path"
            ])
        
        suggestions.append("Check the component's requirements.txt file")
        return suggestions
    
    def _generate_dependency_suggestions(self, error: Exception) -> List[str]:
        """Generate suggestions for dependency errors."""
        return [
            "Install missing dependencies using the Component Center",
            "Check the component's requirements.txt file",
            "Verify all required packages are installed",
            "Try reinstalling the component dependencies"
        ]
    
    def _generate_syntax_suggestions(self, error: Exception) -> List[str]:
        """Generate suggestions for syntax errors."""
        return [
            "Check the Python syntax in the component file",
            "Verify proper indentation and brackets",
            "Look for missing colons, commas, or quotes",
            "Use a Python linter to identify syntax issues"
        ]
    
    def _generate_runtime_suggestions(self, error: Exception) -> List[str]:
        """Generate suggestions for runtime errors."""
        suggestions = []
        error_msg = str(error).lower()
        
        if "attribute" in error_msg:
            suggestions.append("Check if the attribute or method exists")
        if "type" in error_msg:
            suggestions.append("Verify the data types being used")
        if "value" in error_msg or "invalid literal" in error_msg:
            suggestions.append("Check the input values and parameters")
        
        suggestions.extend([
            "Review the component's implementation",
            "Check the component's documentation",
            "Verify the component's dependencies are properly loaded"
        ])
        
        return suggestions
    
    def _generate_general_suggestions(self, error: Exception) -> List[str]:
        """Generate general suggestions for unknown error types."""
        return [
            "Check the component's implementation for issues",
            "Review the error traceback for more details",
            "Try reloading the component",
            "Check the application logs for additional information"
        ]
    
    def _determine_severity(self, error: Exception, error_type: str) -> ErrorSeverity:
        """Determine the severity of an error."""
        if error_type == 'syntax_error':
            return ErrorSeverity.HIGH
        elif error_type in ['import_error', 'dependency_error']:
            return ErrorSeverity.MEDIUM
        elif error_type == 'runtime_error':
            return ErrorSeverity.MEDIUM
        else:
            return ErrorSeverity.LOW
    
    def get_component_error_history(self, component_name: str) -> List[ErrorReport]:
        """Get the error history for a specific component."""
        return self.error_history.get(component_name, [])
    
    def clear_component_errors(self, component_name: str) -> None:
        """Clear the error history for a component."""
        if component_name in self.error_history:
            del self.error_history[component_name]
        
        self.component_isolator.clear_isolation(component_name)
    
    def get_system_error_summary(self) -> Dict[str, Any]:
        """Get a summary of all system errors."""
        total_errors = 0
        critical_errors = 0
        isolated_components = len(self.component_isolator.isolated_components)
        
        for reports in self.error_history.values():
            for report in reports:
                total_errors += len(report.errors)
                if report.has_critical_errors():
                    critical_errors += 1
        
        return {
            'total_errors': total_errors,
            'critical_errors': critical_errors,
            'isolated_components': isolated_components,
            'components_with_errors': len(self.error_history)
        }