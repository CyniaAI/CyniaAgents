"""
Comprehensive logging system for component hot reload operations.

This module provides structured logging with context, error tracking,
and log rotation for the hot reload system.
"""

import logging
import logging.handlers
import os
import json
import traceback
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
import sys


class LogLevel(Enum):
    """Log levels for component operations."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogCategory(Enum):
    """Categories of log events."""
    COMPONENT_LOAD = "component_load"
    COMPONENT_RELOAD = "component_reload"
    COMPONENT_UNLOAD = "component_unload"
    DEPENDENCY_INSTALL = "dependency_install"
    ERROR_RECOVERY = "error_recovery"
    PERFORMANCE = "performance"
    SYSTEM = "system"
    USER_ACTION = "user_action"
    FILE_OPERATION = "file_operation"
    SECURITY = "security"


@dataclass
class LogContext:
    """Context information for log entries."""
    component_name: Optional[str] = None
    operation_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    function_name: Optional[str] = None
    thread_id: Optional[str] = None
    process_id: Optional[int] = None
    additional_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class LogEntry:
    """Structured log entry."""
    timestamp: datetime
    level: LogLevel
    category: LogCategory
    message: str
    context: LogContext
    exception_info: Optional[Dict[str, Any]] = None
    stack_trace: Optional[str] = None
    duration: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert log entry to dictionary for serialization."""
        data = {
            'timestamp': self.timestamp.isoformat(),
            'level': self.level.value,
            'category': self.category.value,
            'message': self.message,
            'context': self.context.to_dict()
        }
        
        if self.exception_info:
            data['exception_info'] = self.exception_info
        
        if self.stack_trace:
            data['stack_trace'] = self.stack_trace
        
        if self.duration is not None:
            data['duration'] = self.duration
        
        return data
    
    def to_json(self) -> str:
        """Convert log entry to JSON string."""
        return json.dumps(self.to_dict(), default=str)


class ComponentLogger:
    """Logger for component-specific operations."""
    
    def __init__(self, component_name: str, parent_logger: 'HotReloadLogger'):
        self.component_name = component_name
        self.parent_logger = parent_logger
        self._operation_stack: List[str] = []
        self._operation_start_times: Dict[str, datetime] = {}
    
    def start_operation(self, operation_id: str, operation_type: str, **context):
        """Start tracking an operation."""
        self._operation_stack.append(operation_id)
        self._operation_start_times[operation_id] = datetime.now()
        
        self.info(
            f"Starting {operation_type}",
            category=LogCategory.COMPONENT_LOAD,
            operation_id=operation_id,
            **context
        )
    
    def end_operation(self, operation_id: str, success: bool = True, **context):
        """End tracking an operation."""
        if operation_id in self._operation_start_times:
            duration = (datetime.now() - self._operation_start_times[operation_id]).total_seconds()
            del self._operation_start_times[operation_id]
        else:
            duration = None
        
        if operation_id in self._operation_stack:
            self._operation_stack.remove(operation_id)
        
        level = LogLevel.INFO if success else LogLevel.ERROR
        message = f"Operation completed {'successfully' if success else 'with errors'}"
        
        self._log(
            level=level,
            message=message,
            category=LogCategory.COMPONENT_LOAD,
            operation_id=operation_id,
            duration=duration,
            **context
        )
    
    def debug(self, message: str, category: LogCategory = LogCategory.COMPONENT_LOAD, **context):
        """Log debug message."""
        self._log(LogLevel.DEBUG, message, category, **context)
    
    def info(self, message: str, category: LogCategory = LogCategory.COMPONENT_LOAD, **context):
        """Log info message."""
        self._log(LogLevel.INFO, message, category, **context)
    
    def warning(self, message: str, category: LogCategory = LogCategory.COMPONENT_LOAD, **context):
        """Log warning message."""
        self._log(LogLevel.WARNING, message, category, **context)
    
    def error(self, message: str, category: LogCategory = LogCategory.COMPONENT_LOAD, 
              exception: Optional[Exception] = None, **context):
        """Log error message."""
        exception_info = None
        stack_trace = None
        
        if exception:
            exception_info = {
                'type': type(exception).__name__,
                'message': str(exception),
                'args': exception.args
            }
            stack_trace = traceback.format_exc()
        
        self._log(
            LogLevel.ERROR, message, category, 
            exception_info=exception_info,
            stack_trace=stack_trace,
            **context
        )
    
    def critical(self, message: str, category: LogCategory = LogCategory.COMPONENT_LOAD,
                exception: Optional[Exception] = None, **context):
        """Log critical message."""
        exception_info = None
        stack_trace = None
        
        if exception:
            exception_info = {
                'type': type(exception).__name__,
                'message': str(exception),
                'args': exception.args
            }
            stack_trace = traceback.format_exc()
        
        self._log(
            LogLevel.CRITICAL, message, category,
            exception_info=exception_info,
            stack_trace=stack_trace,
            **context
        )
    
    def _log(self, level: LogLevel, message: str, category: LogCategory,
             operation_id: Optional[str] = None, duration: Optional[float] = None,
             exception_info: Optional[Dict[str, Any]] = None,
             stack_trace: Optional[str] = None, **context):
        """Internal logging method."""
        # Get current operation if not specified
        if operation_id is None and self._operation_stack:
            operation_id = self._operation_stack[-1]
        
        # Create context
        log_context = LogContext(
            component_name=self.component_name,
            operation_id=operation_id,
            thread_id=str(threading.current_thread().ident),
            process_id=os.getpid(),
            additional_data=context
        )
        
        # Add caller information
        frame = sys._getframe(2)  # Go up 2 frames to get the actual caller
        log_context.file_path = frame.f_code.co_filename
        log_context.line_number = frame.f_lineno
        log_context.function_name = frame.f_code.co_name
        
        # Create log entry
        entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            category=category,
            message=message,
            context=log_context,
            exception_info=exception_info,
            stack_trace=stack_trace,
            duration=duration
        )
        
        # Send to parent logger
        self.parent_logger.log_entry(entry)


class HotReloadLogger:
    """Main logging system for hot reload operations."""
    
    def __init__(self, log_dir: str = "logs", max_log_size: int = 10 * 1024 * 1024,
                 backup_count: int = 5, log_level: LogLevel = LogLevel.INFO):
        self.log_dir = Path(log_dir)
        self.max_log_size = max_log_size
        self.backup_count = backup_count
        self.log_level = log_level
        
        # Create log directory
        self.log_dir.mkdir(exist_ok=True)
        
        # Component loggers
        self.component_loggers: Dict[str, ComponentLogger] = {}
        
        # Log storage
        self.log_entries: List[LogEntry] = []
        self.max_memory_entries = 1000
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Setup file logging
        self._setup_file_logging()
        
        # Setup console logging
        self._setup_console_logging()
        
        # Log rotation timer
        self._setup_log_rotation()
    
    def _setup_file_logging(self):
        """Setup file logging with rotation."""
        # JSON structured log file
        json_log_file = self.log_dir / "hot_reload.json"
        self.json_handler = logging.handlers.RotatingFileHandler(
            json_log_file,
            maxBytes=self.max_log_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        
        # Text log file
        text_log_file = self.log_dir / "hot_reload.log"
        self.text_handler = logging.handlers.RotatingFileHandler(
            text_log_file,
            maxBytes=self.max_log_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        
        # Setup formatters
        text_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.text_handler.setFormatter(text_formatter)
        
        # Setup Python logger
        self.python_logger = logging.getLogger('hot_reload')
        self.python_logger.setLevel(getattr(logging, self.log_level.value))
        self.python_logger.addHandler(self.text_handler)
        
        # Prevent duplicate logs
        self.python_logger.propagate = False
    
    def _setup_console_logging(self):
        """Setup console logging."""
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        self.python_logger.addHandler(console_handler)
    
    def _setup_log_rotation(self):
        """Setup automatic log rotation."""
        # This could be enhanced with a timer for time-based rotation
        pass
    
    def get_component_logger(self, component_name: str) -> ComponentLogger:
        """Get or create a logger for a specific component."""
        with self._lock:
            if component_name not in self.component_loggers:
                self.component_loggers[component_name] = ComponentLogger(component_name, self)
            return self.component_loggers[component_name]
    
    def log_entry(self, entry: LogEntry):
        """Log an entry to all configured outputs."""
        with self._lock:
            # Add to memory storage
            self.log_entries.append(entry)
            if len(self.log_entries) > self.max_memory_entries:
                self.log_entries = self.log_entries[-self.max_memory_entries:]
            
            # Log to JSON file (with better error handling)
            try:
                json_file = self.log_dir / "hot_reload.json"
                with open(json_file, "a", encoding='utf-8') as f:
                    f.write(entry.to_json() + "\n")
                    f.flush()  # Ensure data is written
            except (OSError, IOError, PermissionError):
                pass  # Don't let logging errors break the application
            
            # Log to Python logger (which handles text file and console)
            python_level = getattr(logging, entry.level.value)
            message = f"[{entry.category.value}] {entry.message}"
            
            if entry.context.component_name:
                message = f"[{entry.context.component_name}] {message}"
            
            if entry.exception_info:
                message += f" - {entry.exception_info['type']}: {entry.exception_info['message']}"
            
            self.python_logger.log(python_level, message)
    
    def get_recent_entries(self, hours: int = 24, component_name: Optional[str] = None,
                          category: Optional[LogCategory] = None,
                          level: Optional[LogLevel] = None) -> List[LogEntry]:
        """Get recent log entries with optional filtering."""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        with self._lock:
            entries = [e for e in self.log_entries if e.timestamp >= cutoff]
            
            if component_name:
                entries = [e for e in entries if e.context.component_name == component_name]
            
            if category:
                entries = [e for e in entries if e.category == category]
            
            if level:
                entries = [e for e in entries if e.level == level]
            
            return entries
    
    def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get summary of errors in the specified time period."""
        entries = self.get_recent_entries(hours)
        error_entries = [e for e in entries if e.level in [LogLevel.ERROR, LogLevel.CRITICAL]]
        
        # Group by component
        component_errors = {}
        for entry in error_entries:
            comp_name = entry.context.component_name or "system"
            if comp_name not in component_errors:
                component_errors[comp_name] = []
            component_errors[comp_name].append(entry)
        
        # Group by category
        category_errors = {}
        for entry in error_entries:
            cat = entry.category.value
            if cat not in category_errors:
                category_errors[cat] = 0
            category_errors[cat] += 1
        
        return {
            'total_errors': len(error_entries),
            'component_errors': {k: len(v) for k, v in component_errors.items()},
            'category_errors': category_errors,
            'recent_errors': [e.to_dict() for e in error_entries[-10:]]  # Last 10 errors
        }
    
    def export_logs(self, file_path: str, hours: int = 24, 
                   component_name: Optional[str] = None):
        """Export logs to a file."""
        entries = self.get_recent_entries(hours, component_name)
        
        export_data = {
            'export_timestamp': datetime.now().isoformat(),
            'time_range_hours': hours,
            'component_filter': component_name,
            'total_entries': len(entries),
            'entries': [e.to_dict() for e in entries]
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, default=str)
    
    def clear_logs(self, older_than_hours: Optional[int] = None):
        """Clear logs from memory and optionally from files."""
        with self._lock:
            if older_than_hours:
                cutoff = datetime.now() - timedelta(hours=older_than_hours)
                self.log_entries = [e for e in self.log_entries if e.timestamp >= cutoff]
            else:
                self.log_entries.clear()
    
    def set_log_level(self, level: LogLevel):
        """Set the logging level."""
        self.log_level = level
        self.python_logger.setLevel(getattr(logging, level.value))
    
    def get_log_stats(self) -> Dict[str, Any]:
        """Get logging statistics."""
        with self._lock:
            total_entries = len(self.log_entries)
            
            # Count by level
            level_counts = {}
            for entry in self.log_entries:
                level = entry.level.value
                level_counts[level] = level_counts.get(level, 0) + 1
            
            # Count by category
            category_counts = {}
            for entry in self.log_entries:
                category = entry.category.value
                category_counts[category] = category_counts.get(category, 0) + 1
            
            # Count by component
            component_counts = {}
            for entry in self.log_entries:
                component = entry.context.component_name or "system"
                component_counts[component] = component_counts.get(component, 0) + 1
            
            return {
                'total_entries': total_entries,
                'level_counts': level_counts,
                'category_counts': category_counts,
                'component_counts': component_counts,
                'memory_usage_entries': total_entries,
                'max_memory_entries': self.max_memory_entries
            }


# Global logger instance
_global_logger: Optional[HotReloadLogger] = None


def get_hot_reload_logger() -> HotReloadLogger:
    """Get the global hot reload logger instance."""
    global _global_logger
    if _global_logger is None:
        _global_logger = HotReloadLogger()
    return _global_logger


def set_hot_reload_logger(logger: HotReloadLogger):
    """Set the global hot reload logger instance."""
    global _global_logger
    _global_logger = logger


def get_component_logger(component_name: str) -> ComponentLogger:
    """Get a component logger using the global logger."""
    logger = get_hot_reload_logger()
    return logger.get_component_logger(component_name)


def log_component_event(component_name: str, level: LogLevel, message: str,
                       category: LogCategory = LogCategory.COMPONENT_LOAD,
                       exception: Optional[Exception] = None, **context):
    """Convenience function to log a component event."""
    component_logger = get_component_logger(component_name)
    
    if level == LogLevel.DEBUG:
        component_logger.debug(message, category, **context)
    elif level == LogLevel.INFO:
        component_logger.info(message, category, **context)
    elif level == LogLevel.WARNING:
        component_logger.warning(message, category, **context)
    elif level == LogLevel.ERROR:
        component_logger.error(message, category, exception, **context)
    elif level == LogLevel.CRITICAL:
        component_logger.critical(message, category, exception, **context)


class LoggingContextManager:
    """Context manager for logging operations with automatic start/end."""
    
    def __init__(self, component_name: str, operation_type: str, 
                 operation_id: Optional[str] = None, **context):
        self.component_logger = get_component_logger(component_name)
        self.operation_type = operation_type
        self.operation_id = operation_id or f"{operation_type}_{datetime.now().timestamp()}"
        self.context = context
        self.success = True
    
    def __enter__(self):
        """Start the operation logging."""
        self.component_logger.start_operation(
            self.operation_id, self.operation_type, **self.context
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """End the operation logging."""
        if exc_type is not None:
            self.success = False
            self.context['exception'] = str(exc_val)
        
        self.component_logger.end_operation(
            self.operation_id, self.success, **self.context
        )
    
    def mark_failure(self, reason: str = ""):
        """Mark the operation as failed."""
        self.success = False
        if reason:
            self.context['failure_reason'] = reason


def log_operation(component_name: str, operation_type: str, 
                 operation_id: Optional[str] = None, **context) -> LoggingContextManager:
    """Create a logging context manager for an operation."""
    return LoggingContextManager(component_name, operation_type, operation_id, **context)