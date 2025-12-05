"""
Performance monitoring system for component hot reload operations.

This module provides comprehensive performance tracking, metrics collection,
and reporting for component lifecycle operations.
"""

import time
import threading
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from collections import defaultdict, deque
from enum import Enum
import statistics
import json
import os


class MetricType(Enum):
    """Types of performance metrics."""
    LOAD_TIME = "load_time"
    RELOAD_TIME = "reload_time"
    UNLOAD_TIME = "unload_time"
    MEMORY_USAGE = "memory_usage"
    CPU_USAGE = "cpu_usage"
    DEPENDENCY_INSTALL_TIME = "dependency_install_time"
    FILE_SIZE = "file_size"
    MODULE_COUNT = "module_count"


class PerformanceLevel(Enum):
    """Performance levels for categorization."""
    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    POOR = "poor"
    CRITICAL = "critical"


@dataclass
class PerformanceMetric:
    """Individual performance metric data point."""
    component_name: str
    metric_type: MetricType
    value: float
    unit: str
    timestamp: datetime = field(default_factory=datetime.now)
    operation_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Post-initialization validation."""
        if not self.component_name:
            raise ValueError("Component name cannot be empty")
        if self.value < 0:
            raise ValueError("Metric value cannot be negative")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'component_name': self.component_name,
            'metric_type': self.metric_type.value,
            'value': self.value,
            'unit': self.unit,
            'timestamp': self.timestamp.isoformat(),
            'operation_id': self.operation_id,
            'context': self.context
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PerformanceMetric':
        """Create metric from dictionary."""
        data['metric_type'] = MetricType(data['metric_type'])
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


@dataclass
class ComponentPerformanceStats:
    """Aggregated performance statistics for a component."""
    component_name: str
    total_operations: int = 0
    successful_operations: int = 0
    failed_operations: int = 0
    average_load_time: float = 0.0
    average_memory_usage: float = 0.0
    peak_memory_usage: float = 0.0
    total_reload_count: int = 0
    last_operation_time: Optional[datetime] = None
    performance_level: PerformanceLevel = PerformanceLevel.AVERAGE
    metrics_history: List[PerformanceMetric] = field(default_factory=list)
    
    def update_stats(self, metric: PerformanceMetric, success: bool = True):
        """Update statistics with new metric."""
        self.total_operations += 1
        if success:
            self.successful_operations += 1
        else:
            self.failed_operations += 1
        
        self.last_operation_time = metric.timestamp
        self.metrics_history.append(metric)
        
        # Update specific metric averages
        if metric.metric_type == MetricType.LOAD_TIME:
            load_times = [m.value for m in self.metrics_history 
                         if m.metric_type == MetricType.LOAD_TIME]
            self.average_load_time = statistics.mean(load_times)
        
        elif metric.metric_type == MetricType.MEMORY_USAGE:
            memory_values = [m.value for m in self.metrics_history 
                           if m.metric_type == MetricType.MEMORY_USAGE]
            self.average_memory_usage = statistics.mean(memory_values)
            self.peak_memory_usage = max(memory_values)
        
        elif metric.metric_type in [MetricType.RELOAD_TIME]:
            self.total_reload_count += 1
        
        # Update performance level
        self._calculate_performance_level()
    
    def _calculate_performance_level(self):
        """Calculate overall performance level based on metrics."""
        score = 0
        factors = 0
        
        # Load time factor (lower is better)
        if self.average_load_time > 0:
            if self.average_load_time < 0.5:
                score += 5
            elif self.average_load_time < 1.0:
                score += 4
            elif self.average_load_time < 2.0:
                score += 3
            elif self.average_load_time < 5.0:
                score += 2
            else:
                score += 1
            factors += 1
        
        # Memory usage factor (lower is better, in MB)
        if self.average_memory_usage > 0:
            memory_mb = self.average_memory_usage / (1024 * 1024)
            if memory_mb < 10:
                score += 5
            elif memory_mb < 50:
                score += 4
            elif memory_mb < 100:
                score += 3
            elif memory_mb < 200:
                score += 2
            else:
                score += 1
            factors += 1
        
        # Success rate factor
        if self.total_operations > 0:
            success_rate = self.successful_operations / self.total_operations
            if success_rate >= 0.95:
                score += 5
            elif success_rate >= 0.85:
                score += 4
            elif success_rate >= 0.70:
                score += 3
            elif success_rate >= 0.50:
                score += 2
            else:
                score += 1
            factors += 1
        
        # Calculate average score
        if factors > 0:
            avg_score = score / factors
            if avg_score >= 4.5:
                self.performance_level = PerformanceLevel.EXCELLENT
            elif avg_score >= 3.5:
                self.performance_level = PerformanceLevel.GOOD
            elif avg_score >= 2.5:
                self.performance_level = PerformanceLevel.AVERAGE
            elif avg_score >= 1.5:
                self.performance_level = PerformanceLevel.POOR
            else:
                self.performance_level = PerformanceLevel.CRITICAL
    
    def get_success_rate(self) -> float:
        """Get operation success rate."""
        if self.total_operations == 0:
            return 0.0
        return self.successful_operations / self.total_operations
    
    def get_recent_metrics(self, hours: int = 24) -> List[PerformanceMetric]:
        """Get metrics from the last N hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [m for m in self.metrics_history if m.timestamp >= cutoff]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'component_name': self.component_name,
            'total_operations': self.total_operations,
            'successful_operations': self.successful_operations,
            'failed_operations': self.failed_operations,
            'average_load_time': self.average_load_time,
            'average_memory_usage': self.average_memory_usage,
            'peak_memory_usage': self.peak_memory_usage,
            'total_reload_count': self.total_reload_count,
            'last_operation_time': self.last_operation_time.isoformat() if self.last_operation_time else None,
            'performance_level': self.performance_level.value,
            'success_rate': self.get_success_rate(),
            'recent_metrics_count': len(self.get_recent_metrics())
        }


class PerformanceTimer:
    """Context manager for timing operations."""
    
    def __init__(self, component_name: str, metric_type: MetricType, 
                 monitor: 'PerformanceMonitor', operation_id: Optional[str] = None):
        self.component_name = component_name
        self.metric_type = metric_type
        self.monitor = monitor
        self.operation_id = operation_id
        self.start_time = None
        self.start_memory = None
        self.success = True
    
    def __enter__(self):
        """Start timing."""
        self.start_time = time.time()
        self.start_memory = self._get_memory_usage()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """End timing and record metric."""
        if self.start_time is not None:
            duration = time.time() - self.start_time
            # Check if manually marked as failure or if exception occurred
            if not self.success:
                success = False
            else:
                success = exc_type is None
            
            # Record timing metric
            self.monitor.record_metric(
                component_name=self.component_name,
                metric_type=self.metric_type,
                value=duration,
                unit="seconds",
                operation_id=self.operation_id,
                context={'success': success}
            )
            
            # Record memory usage if available
            if self.start_memory is not None:
                current_memory = self._get_memory_usage()
                if current_memory is not None:
                    memory_delta = current_memory - self.start_memory
                    self.monitor.record_metric(
                        component_name=self.component_name,
                        metric_type=MetricType.MEMORY_USAGE,
                        value=memory_delta,
                        unit="bytes",
                        operation_id=self.operation_id,
                        context={'operation': self.metric_type.value, 'success': success}
                    )
    
    def _get_memory_usage(self) -> Optional[float]:
        """Get current memory usage."""
        if not PSUTIL_AVAILABLE:
            return None
        
        try:
            process = psutil.Process()
            return process.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
    
    def mark_failure(self):
        """Mark the operation as failed."""
        self.success = False


class PerformanceMonitor:
    """Main performance monitoring system."""
    
    def __init__(self, max_metrics_per_component: int = 1000):
        self.max_metrics_per_component = max_metrics_per_component
        self.component_stats: Dict[str, ComponentPerformanceStats] = {}
        self.global_metrics: deque = deque(maxlen=10000)
        self.metric_callbacks: Dict[MetricType, List[Callable]] = defaultdict(list)
        self._lock = threading.RLock()
        self._monitoring_active = True
        
        # Performance thresholds
        self.thresholds = {
            MetricType.LOAD_TIME: {'warning': 2.0, 'critical': 5.0},
            MetricType.RELOAD_TIME: {'warning': 1.0, 'critical': 3.0},
            MetricType.MEMORY_USAGE: {'warning': 100 * 1024 * 1024, 'critical': 500 * 1024 * 1024},  # MB
            MetricType.DEPENDENCY_INSTALL_TIME: {'warning': 30.0, 'critical': 120.0}
        }
    
    def record_metric(self, component_name: str, metric_type: MetricType, 
                     value: float, unit: str, operation_id: Optional[str] = None,
                     context: Optional[Dict[str, Any]] = None) -> PerformanceMetric:
        """Record a performance metric."""
        if not self._monitoring_active:
            return None
        
        metric = PerformanceMetric(
            component_name=component_name,
            metric_type=metric_type,
            value=value,
            unit=unit,
            operation_id=operation_id,
            context=context or {}
        )
        
        with self._lock:
            # Update component stats
            if component_name not in self.component_stats:
                self.component_stats[component_name] = ComponentPerformanceStats(component_name)
            
            stats = self.component_stats[component_name]
            success = context.get('success', True) if context else True
            stats.update_stats(metric, success)
            
            # Limit metrics history per component
            if len(stats.metrics_history) > self.max_metrics_per_component:
                stats.metrics_history = stats.metrics_history[-self.max_metrics_per_component:]
            
            # Add to global metrics
            self.global_metrics.append(metric)
            
            # Check thresholds and trigger callbacks
            self._check_thresholds(metric)
            self._trigger_callbacks(metric)
        
        return metric
    
    def start_timer(self, component_name: str, metric_type: MetricType, 
                   operation_id: Optional[str] = None) -> PerformanceTimer:
        """Start a performance timer."""
        return PerformanceTimer(component_name, metric_type, self, operation_id)
    
    def get_component_stats(self, component_name: str) -> Optional[ComponentPerformanceStats]:
        """Get performance statistics for a component."""
        with self._lock:
            return self.component_stats.get(component_name)
    
    def get_all_component_stats(self) -> Dict[str, ComponentPerformanceStats]:
        """Get performance statistics for all components."""
        with self._lock:
            return self.component_stats.copy()
    
    def get_global_metrics(self, limit: Optional[int] = None) -> List[PerformanceMetric]:
        """Get global metrics."""
        with self._lock:
            metrics = list(self.global_metrics)
            if limit:
                return metrics[-limit:]
            return metrics
    
    def get_metrics_by_type(self, metric_type: MetricType, 
                           component_name: Optional[str] = None,
                           hours: int = 24) -> List[PerformanceMetric]:
        """Get metrics by type and optionally by component."""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        with self._lock:
            metrics = []
            if component_name:
                stats = self.component_stats.get(component_name)
                if stats:
                    metrics = [m for m in stats.metrics_history 
                             if m.metric_type == metric_type and m.timestamp >= cutoff]
            else:
                metrics = [m for m in self.global_metrics 
                          if m.metric_type == metric_type and m.timestamp >= cutoff]
            
            return metrics
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get overall performance summary."""
        with self._lock:
            total_components = len(self.component_stats)
            total_operations = sum(stats.total_operations for stats in self.component_stats.values())
            total_successful = sum(stats.successful_operations for stats in self.component_stats.values())
            
            # Calculate average metrics
            load_times = []
            memory_usage = []
            
            for stats in self.component_stats.values():
                if stats.average_load_time > 0:
                    load_times.append(stats.average_load_time)
                if stats.average_memory_usage > 0:
                    memory_usage.append(stats.average_memory_usage)
            
            # Performance level distribution
            level_counts = defaultdict(int)
            for stats in self.component_stats.values():
                level_counts[stats.performance_level.value] += 1
            
            return {
                'total_components': total_components,
                'total_operations': total_operations,
                'success_rate': total_successful / total_operations if total_operations > 0 else 0.0,
                'average_load_time': statistics.mean(load_times) if load_times else 0.0,
                'average_memory_usage': statistics.mean(memory_usage) if memory_usage else 0.0,
                'performance_levels': dict(level_counts),
                'monitoring_active': self._monitoring_active,
                'total_metrics': len(self.global_metrics)
            }
    
    def add_metric_callback(self, metric_type: MetricType, callback: Callable[[PerformanceMetric], None]):
        """Add a callback for when specific metrics are recorded."""
        with self._lock:
            self.metric_callbacks[metric_type].append(callback)
    
    def remove_metric_callback(self, metric_type: MetricType, callback: Callable):
        """Remove a metric callback."""
        with self._lock:
            if callback in self.metric_callbacks[metric_type]:
                self.metric_callbacks[metric_type].remove(callback)
    
    def set_threshold(self, metric_type: MetricType, warning: float, critical: float):
        """Set performance thresholds for a metric type."""
        with self._lock:
            self.thresholds[metric_type] = {'warning': warning, 'critical': critical}
    
    def clear_component_stats(self, component_name: str):
        """Clear statistics for a specific component."""
        with self._lock:
            if component_name in self.component_stats:
                del self.component_stats[component_name]
    
    def clear_all_stats(self):
        """Clear all performance statistics."""
        with self._lock:
            self.component_stats.clear()
            self.global_metrics.clear()
    
    def export_metrics(self, file_path: str, component_name: Optional[str] = None):
        """Export metrics to JSON file."""
        with self._lock:
            if component_name:
                stats = self.component_stats.get(component_name)
                if stats:
                    data = {
                        'component_stats': stats.to_dict(),
                        'metrics': [m.to_dict() for m in stats.metrics_history]
                    }
                else:
                    data = {'error': f'Component {component_name} not found'}
            else:
                data = {
                    'summary': self.get_performance_summary(),
                    'component_stats': {name: stats.to_dict() 
                                      for name, stats in self.component_stats.items()},
                    'global_metrics': [m.to_dict() for m in self.global_metrics]
                }
            
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
    
    def start_monitoring(self):
        """Start performance monitoring."""
        with self._lock:
            self._monitoring_active = True
    
    def stop_monitoring(self):
        """Stop performance monitoring."""
        with self._lock:
            self._monitoring_active = False
    
    def is_monitoring_active(self) -> bool:
        """Check if monitoring is active."""
        return self._monitoring_active
    
    def _check_thresholds(self, metric: PerformanceMetric):
        """Check if metric exceeds thresholds."""
        thresholds = self.thresholds.get(metric.metric_type)
        if not thresholds:
            return
        
        if metric.value >= thresholds['critical']:
            # Trigger critical threshold callback if registered
            for callback in self.metric_callbacks.get('critical_threshold', []):
                try:
                    callback(metric, 'critical')
                except Exception:
                    pass  # Don't let callback errors break monitoring
        
        elif metric.value >= thresholds['warning']:
            # Trigger warning threshold callback if registered
            for callback in self.metric_callbacks.get('warning_threshold', []):
                try:
                    callback(metric, 'warning')
                except Exception:
                    pass
    
    def _trigger_callbacks(self, metric: PerformanceMetric):
        """Trigger registered callbacks for the metric type."""
        for callback in self.metric_callbacks.get(metric.metric_type, []):
            try:
                callback(metric)
            except Exception:
                pass  # Don't let callback errors break monitoring


# Global performance monitor instance
_global_monitor: Optional[PerformanceMonitor] = None


def get_performance_monitor() -> PerformanceMonitor:
    """Get the global performance monitor instance."""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = PerformanceMonitor()
    return _global_monitor


def set_performance_monitor(monitor: PerformanceMonitor):
    """Set the global performance monitor instance."""
    global _global_monitor
    _global_monitor = monitor


def record_component_metric(component_name: str, metric_type: MetricType, 
                          value: float, unit: str, **kwargs) -> PerformanceMetric:
    """Convenience function to record a metric using the global monitor."""
    monitor = get_performance_monitor()
    return monitor.record_metric(component_name, metric_type, value, unit, **kwargs)


def time_component_operation(component_name: str, metric_type: MetricType, 
                           operation_id: Optional[str] = None) -> PerformanceTimer:
    """Convenience function to time an operation using the global monitor."""
    monitor = get_performance_monitor()
    return monitor.start_timer(component_name, metric_type, operation_id)