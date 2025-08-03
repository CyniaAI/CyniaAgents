"""
Resource usage monitoring system for component hot reload operations.

This module provides comprehensive resource tracking including memory usage,
CPU usage, file handles, and system resource monitoring per component.
"""

import os
import gc
import sys
import time
import threading
import tracemalloc
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Set
from collections import defaultdict, deque
from enum import Enum
import weakref

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False


class ResourceType(Enum):
    """Types of resources to monitor."""
    MEMORY = "memory"
    CPU = "cpu"
    FILE_HANDLES = "file_handles"
    THREADS = "threads"
    NETWORK_CONNECTIONS = "network_connections"
    DISK_IO = "disk_io"
    NETWORK_IO = "network_io"


class AlertLevel(Enum):
    """Alert levels for resource usage."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class ResourceSnapshot:
    """Snapshot of resource usage at a point in time."""
    timestamp: datetime
    component_name: str
    memory_rss: int = 0  # Resident Set Size in bytes
    memory_vms: int = 0  # Virtual Memory Size in bytes
    memory_percent: float = 0.0  # Memory usage as percentage of total
    cpu_percent: float = 0.0  # CPU usage percentage
    num_threads: int = 0  # Number of threads
    num_file_handles: int = 0  # Number of open file handles
    num_network_connections: int = 0  # Number of network connections
    disk_read_bytes: int = 0  # Disk read bytes
    disk_write_bytes: int = 0  # Disk write bytes
    network_sent_bytes: int = 0  # Network sent bytes
    network_recv_bytes: int = 0  # Network received bytes
    python_objects: int = 0  # Number of Python objects
    gc_collections: int = 0  # Number of garbage collections
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'component_name': self.component_name,
            'memory_rss': self.memory_rss,
            'memory_vms': self.memory_vms,
            'memory_percent': self.memory_percent,
            'cpu_percent': self.cpu_percent,
            'num_threads': self.num_threads,
            'num_file_handles': self.num_file_handles,
            'num_network_connections': self.num_network_connections,
            'disk_read_bytes': self.disk_read_bytes,
            'disk_write_bytes': self.disk_write_bytes,
            'network_sent_bytes': self.network_sent_bytes,
            'network_recv_bytes': self.network_recv_bytes,
            'python_objects': self.python_objects,
            'gc_collections': self.gc_collections
        }


@dataclass
class ResourceThresholds:
    """Thresholds for resource usage alerts."""
    memory_mb_warning: float = 100.0  # MB
    memory_mb_critical: float = 500.0  # MB
    memory_percent_warning: float = 10.0  # %
    memory_percent_critical: float = 25.0  # %
    cpu_percent_warning: float = 50.0  # %
    cpu_percent_critical: float = 80.0  # %
    file_handles_warning: int = 100
    file_handles_critical: int = 500
    threads_warning: int = 10
    threads_critical: int = 50
    
    def check_memory_rss(self, memory_bytes: int) -> Optional[AlertLevel]:
        """Check memory RSS against thresholds."""
        memory_mb = memory_bytes / (1024 * 1024)
        if memory_mb >= self.memory_mb_critical:
            return AlertLevel.CRITICAL
        elif memory_mb >= self.memory_mb_warning:
            return AlertLevel.WARNING
        return None
    
    def check_memory_percent(self, memory_percent: float) -> Optional[AlertLevel]:
        """Check memory percentage against thresholds."""
        if memory_percent >= self.memory_percent_critical:
            return AlertLevel.CRITICAL
        elif memory_percent >= self.memory_percent_warning:
            return AlertLevel.WARNING
        return None
    
    def check_cpu_percent(self, cpu_percent: float) -> Optional[AlertLevel]:
        """Check CPU percentage against thresholds."""
        if cpu_percent >= self.cpu_percent_critical:
            return AlertLevel.CRITICAL
        elif cpu_percent >= self.cpu_percent_warning:
            return AlertLevel.WARNING
        return None
    
    def check_file_handles(self, num_handles: int) -> Optional[AlertLevel]:
        """Check file handles against thresholds."""
        if num_handles >= self.file_handles_critical:
            return AlertLevel.CRITICAL
        elif num_handles >= self.file_handles_warning:
            return AlertLevel.WARNING
        return None
    
    def check_threads(self, num_threads: int) -> Optional[AlertLevel]:
        """Check thread count against thresholds."""
        if num_threads >= self.threads_critical:
            return AlertLevel.CRITICAL
        elif num_threads >= self.threads_warning:
            return AlertLevel.WARNING
        return None


@dataclass
class ResourceAlert:
    """Resource usage alert."""
    timestamp: datetime
    component_name: str
    resource_type: ResourceType
    alert_level: AlertLevel
    current_value: float
    threshold_value: float
    message: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'component_name': self.component_name,
            'resource_type': self.resource_type.value,
            'alert_level': self.alert_level.value,
            'current_value': self.current_value,
            'threshold_value': self.threshold_value,
            'message': self.message
        }


class ComponentResourceTracker:
    """Tracks resource usage for a specific component."""
    
    def __init__(self, component_name: str):
        self.component_name = component_name
        self.snapshots: deque = deque(maxlen=1000)  # Keep last 1000 snapshots
        self.start_snapshot: Optional[ResourceSnapshot] = None
        self.peak_memory: int = 0
        self.peak_cpu: float = 0.0
        self.total_cpu_time: float = 0.0
        self.last_cpu_time: float = 0.0
        self.object_refs: Set[weakref.ref] = set()
        self.gc_start_count = sum(gc.get_count())
        
        # Track component-specific objects
        self._track_initial_state()
    
    def _track_initial_state(self):
        """Track initial resource state."""
        self.start_snapshot = self._take_snapshot()
        if self.start_snapshot:
            self.peak_memory = self.start_snapshot.memory_rss
            self.peak_cpu = self.start_snapshot.cpu_percent
    
    def _take_snapshot(self) -> Optional[ResourceSnapshot]:
        """Take a resource usage snapshot."""
        try:
            snapshot = ResourceSnapshot(
                timestamp=datetime.now(),
                component_name=self.component_name
            )
            
            if PSUTIL_AVAILABLE:
                process = psutil.Process()
                
                # Memory information
                memory_info = process.memory_info()
                snapshot.memory_rss = memory_info.rss
                snapshot.memory_vms = memory_info.vms
                snapshot.memory_percent = process.memory_percent()
                
                # CPU information
                snapshot.cpu_percent = process.cpu_percent()
                
                # Thread information
                snapshot.num_threads = process.num_threads()
                
                # File handles
                try:
                    snapshot.num_file_handles = process.num_fds() if hasattr(process, 'num_fds') else len(process.open_files())
                except (psutil.AccessDenied, AttributeError):
                    snapshot.num_file_handles = 0
                
                # Network connections
                try:
                    snapshot.num_network_connections = len(process.connections())
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    snapshot.num_network_connections = 0
                
                # I/O information
                try:
                    io_counters = process.io_counters()
                    snapshot.disk_read_bytes = io_counters.read_bytes
                    snapshot.disk_write_bytes = io_counters.write_bytes
                except (psutil.AccessDenied, AttributeError):
                    pass
            
            # Python-specific information
            snapshot.python_objects = len(gc.get_objects())
            snapshot.gc_collections = sum(gc.get_count()) - self.gc_start_count
            
            return snapshot
            
        except Exception:
            return None
    
    def record_snapshot(self) -> Optional[ResourceSnapshot]:
        """Record a new resource snapshot."""
        snapshot = self._take_snapshot()
        if snapshot:
            self.snapshots.append(snapshot)
            
            # Update peaks
            if snapshot.memory_rss > self.peak_memory:
                self.peak_memory = snapshot.memory_rss
            
            if snapshot.cpu_percent > self.peak_cpu:
                self.peak_cpu = snapshot.cpu_percent
            
            # Update CPU time
            if self.last_cpu_time > 0:
                self.total_cpu_time += snapshot.cpu_percent
            self.last_cpu_time = snapshot.cpu_percent
        
        return snapshot
    
    def add_object_reference(self, obj: Any):
        """Add a weak reference to track component objects."""
        try:
            ref = weakref.ref(obj)
            self.object_refs.add(ref)
        except TypeError:
            # Object doesn't support weak references (like dict, list, etc.)
            # Store a simple counter instead
            if not hasattr(self, '_non_weakref_objects'):
                self._non_weakref_objects = 0
            self._non_weakref_objects += 1
    
    def get_current_memory_usage(self) -> int:
        """Get current memory usage in bytes."""
        if self.snapshots:
            return self.snapshots[-1].memory_rss
        return 0
    
    def get_memory_delta(self) -> int:
        """Get memory usage delta from start."""
        if self.start_snapshot and self.snapshots:
            return self.snapshots[-1].memory_rss - self.start_snapshot.memory_rss
        return 0
    
    def get_average_cpu(self, minutes: int = 5) -> float:
        """Get average CPU usage over the last N minutes."""
        if not self.snapshots:
            return 0.0
        
        cutoff = datetime.now() - timedelta(minutes=minutes)
        recent_snapshots = [s for s in self.snapshots if s.timestamp >= cutoff]
        
        if not recent_snapshots:
            return 0.0
        
        return sum(s.cpu_percent for s in recent_snapshots) / len(recent_snapshots)
    
    def get_resource_summary(self) -> Dict[str, Any]:
        """Get resource usage summary."""
        current_snapshot = self.snapshots[-1] if self.snapshots else None
        
        # Count live object references
        live_refs = []
        dead_refs = []
        for ref in self.object_refs:
            obj = ref()
            if obj is not None:
                live_refs.append(ref)
            else:
                dead_refs.append(ref)
        
        # Clean up dead references
        for dead_ref in dead_refs:
            self.object_refs.discard(dead_ref)
        
        # Add non-weakref objects count
        non_weakref_count = getattr(self, '_non_weakref_objects', 0)
        
        return {
            'component_name': self.component_name,
            'current_memory_mb': current_snapshot.memory_rss / (1024 * 1024) if current_snapshot else 0,
            'peak_memory_mb': self.peak_memory / (1024 * 1024),
            'memory_delta_mb': self.get_memory_delta() / (1024 * 1024),
            'current_cpu_percent': current_snapshot.cpu_percent if current_snapshot else 0,
            'peak_cpu_percent': self.peak_cpu,
            'average_cpu_5min': self.get_average_cpu(5),
            'current_threads': current_snapshot.num_threads if current_snapshot else 0,
            'current_file_handles': current_snapshot.num_file_handles if current_snapshot else 0,
            'python_objects': current_snapshot.python_objects if current_snapshot else 0,
            'gc_collections': current_snapshot.gc_collections if current_snapshot else 0,
            'snapshots_count': len(self.snapshots),
            'tracked_objects': len(live_refs) + non_weakref_count
        }


class ResourceMonitor:
    """Main resource monitoring system."""
    
    def __init__(self, monitoring_interval: float = 5.0):
        self.monitoring_interval = monitoring_interval
        self.component_trackers: Dict[str, ComponentResourceTracker] = {}
        self.thresholds = ResourceThresholds()
        self.alerts: deque = deque(maxlen=1000)
        self.alert_callbacks: List[Callable[[ResourceAlert], None]] = []
        
        # Monitoring control
        self._monitoring_active = False
        self._monitoring_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Thread safety
        self._lock = threading.RLock()
        
        # System baseline
        self._system_baseline: Optional[ResourceSnapshot] = None
        self._take_system_baseline()
    
    def _take_system_baseline(self):
        """Take a baseline measurement of system resources."""
        try:
            self._system_baseline = ResourceSnapshot(
                timestamp=datetime.now(),
                component_name="system_baseline"
            )
            
            if PSUTIL_AVAILABLE:
                process = psutil.Process()
                memory_info = process.memory_info()
                self._system_baseline.memory_rss = memory_info.rss
                self._system_baseline.memory_vms = memory_info.vms
                self._system_baseline.memory_percent = process.memory_percent()
                self._system_baseline.cpu_percent = process.cpu_percent()
                self._system_baseline.num_threads = process.num_threads()
                
                try:
                    self._system_baseline.num_file_handles = process.num_fds() if hasattr(process, 'num_fds') else len(process.open_files())
                except (psutil.AccessDenied, AttributeError):
                    pass
            
            self._system_baseline.python_objects = len(gc.get_objects())
            
        except Exception:
            self._system_baseline = None
    
    def register_component(self, component_name: str) -> ComponentResourceTracker:
        """Register a component for resource monitoring."""
        with self._lock:
            if component_name not in self.component_trackers:
                self.component_trackers[component_name] = ComponentResourceTracker(component_name)
            return self.component_trackers[component_name]
    
    def unregister_component(self, component_name: str):
        """Unregister a component from monitoring."""
        with self._lock:
            if component_name in self.component_trackers:
                del self.component_trackers[component_name]
    
    def record_component_snapshot(self, component_name: str) -> Optional[ResourceSnapshot]:
        """Record a resource snapshot for a component."""
        with self._lock:
            tracker = self.component_trackers.get(component_name)
            if tracker:
                snapshot = tracker.record_snapshot()
                if snapshot:
                    self._check_thresholds(snapshot)
                return snapshot
            return None
    
    def add_component_object(self, component_name: str, obj: Any):
        """Add an object reference for component tracking."""
        with self._lock:
            tracker = self.component_trackers.get(component_name)
            if tracker:
                tracker.add_object_reference(obj)
    
    def _check_thresholds(self, snapshot: ResourceSnapshot):
        """Check resource usage against thresholds and generate alerts."""
        alerts = []
        
        # Check memory RSS
        alert_level = self.thresholds.check_memory_rss(snapshot.memory_rss)
        if alert_level:
            alerts.append(ResourceAlert(
                timestamp=snapshot.timestamp,
                component_name=snapshot.component_name,
                resource_type=ResourceType.MEMORY,
                alert_level=alert_level,
                current_value=snapshot.memory_rss / (1024 * 1024),  # MB
                threshold_value=self.thresholds.memory_mb_critical if alert_level == AlertLevel.CRITICAL else self.thresholds.memory_mb_warning,
                message=f"Memory usage {snapshot.memory_rss / (1024 * 1024):.1f} MB exceeds {alert_level.value} threshold"
            ))
        
        # Check memory percentage
        alert_level = self.thresholds.check_memory_percent(snapshot.memory_percent)
        if alert_level:
            alerts.append(ResourceAlert(
                timestamp=snapshot.timestamp,
                component_name=snapshot.component_name,
                resource_type=ResourceType.MEMORY,
                alert_level=alert_level,
                current_value=snapshot.memory_percent,
                threshold_value=self.thresholds.memory_percent_critical if alert_level == AlertLevel.CRITICAL else self.thresholds.memory_percent_warning,
                message=f"Memory usage {snapshot.memory_percent:.1f}% exceeds {alert_level.value} threshold"
            ))
        
        # Check CPU usage
        alert_level = self.thresholds.check_cpu_percent(snapshot.cpu_percent)
        if alert_level:
            alerts.append(ResourceAlert(
                timestamp=snapshot.timestamp,
                component_name=snapshot.component_name,
                resource_type=ResourceType.CPU,
                alert_level=alert_level,
                current_value=snapshot.cpu_percent,
                threshold_value=self.thresholds.cpu_percent_critical if alert_level == AlertLevel.CRITICAL else self.thresholds.cpu_percent_warning,
                message=f"CPU usage {snapshot.cpu_percent:.1f}% exceeds {alert_level.value} threshold"
            ))
        
        # Check file handles
        alert_level = self.thresholds.check_file_handles(snapshot.num_file_handles)
        if alert_level:
            alerts.append(ResourceAlert(
                timestamp=snapshot.timestamp,
                component_name=snapshot.component_name,
                resource_type=ResourceType.FILE_HANDLES,
                alert_level=alert_level,
                current_value=snapshot.num_file_handles,
                threshold_value=self.thresholds.file_handles_critical if alert_level == AlertLevel.CRITICAL else self.thresholds.file_handles_warning,
                message=f"File handles {snapshot.num_file_handles} exceeds {alert_level.value} threshold"
            ))
        
        # Check thread count
        alert_level = self.thresholds.check_threads(snapshot.num_threads)
        if alert_level:
            alerts.append(ResourceAlert(
                timestamp=snapshot.timestamp,
                component_name=snapshot.component_name,
                resource_type=ResourceType.THREADS,
                alert_level=alert_level,
                current_value=snapshot.num_threads,
                threshold_value=self.thresholds.threads_critical if alert_level == AlertLevel.CRITICAL else self.thresholds.threads_warning,
                message=f"Thread count {snapshot.num_threads} exceeds {alert_level.value} threshold"
            ))
        
        # Store alerts and trigger callbacks
        for alert in alerts:
            self.alerts.append(alert)
            for callback in self.alert_callbacks:
                try:
                    callback(alert)
                except Exception:
                    pass  # Don't let callback errors break monitoring
    
    def start_monitoring(self):
        """Start continuous resource monitoring."""
        with self._lock:
            if self._monitoring_active:
                return
            
            self._monitoring_active = True
            self._stop_event.clear()
            self._monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
            self._monitoring_thread.start()
    
    def stop_monitoring(self):
        """Stop continuous resource monitoring."""
        with self._lock:
            if not self._monitoring_active:
                return
            
            self._monitoring_active = False
            self._stop_event.set()
            
            if self._monitoring_thread:
                self._monitoring_thread.join(timeout=5.0)
                self._monitoring_thread = None
    
    def _monitoring_loop(self):
        """Main monitoring loop."""
        while self._monitoring_active and not self._stop_event.is_set():
            try:
                # Record snapshots for all registered components
                with self._lock:
                    for component_name in list(self.component_trackers.keys()):
                        self.record_component_snapshot(component_name)
                
                # Wait for next interval
                self._stop_event.wait(self.monitoring_interval)
                
            except Exception:
                # Don't let monitoring errors break the loop
                time.sleep(1.0)
    
    def get_component_summary(self, component_name: str) -> Optional[Dict[str, Any]]:
        """Get resource summary for a component."""
        with self._lock:
            tracker = self.component_trackers.get(component_name)
            if tracker:
                return tracker.get_resource_summary()
            return None
    
    def get_all_component_summaries(self) -> Dict[str, Dict[str, Any]]:
        """Get resource summaries for all components."""
        with self._lock:
            return {
                name: tracker.get_resource_summary()
                for name, tracker in self.component_trackers.items()
            }
    
    def get_system_summary(self) -> Dict[str, Any]:
        """Get overall system resource summary."""
        with self._lock:
            total_memory = 0
            total_cpu = 0.0
            total_threads = 0
            total_file_handles = 0
            total_objects = 0
            component_count = len(self.component_trackers)
            
            for tracker in self.component_trackers.values():
                if tracker.snapshots:
                    latest = tracker.snapshots[-1]
                    total_memory += latest.memory_rss
                    total_cpu += latest.cpu_percent
                    total_threads += latest.num_threads
                    total_file_handles += latest.num_file_handles
                    total_objects += latest.python_objects
            
            baseline_memory = self._system_baseline.memory_rss if self._system_baseline else 0
            baseline_objects = self._system_baseline.python_objects if self._system_baseline else 0
            
            return {
                'component_count': component_count,
                'total_memory_mb': total_memory / (1024 * 1024),
                'memory_delta_mb': (total_memory - baseline_memory) / (1024 * 1024),
                'average_cpu_percent': total_cpu / component_count if component_count > 0 else 0,
                'total_threads': total_threads,
                'total_file_handles': total_file_handles,
                'total_python_objects': total_objects,
                'objects_delta': total_objects - baseline_objects,
                'monitoring_active': self._monitoring_active,
                'monitoring_interval': self.monitoring_interval,
                'alert_count': len(self.alerts)
            }
    
    def get_recent_alerts(self, hours: int = 24, 
                         component_name: Optional[str] = None,
                         alert_level: Optional[AlertLevel] = None) -> List[ResourceAlert]:
        """Get recent resource alerts."""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        with self._lock:
            alerts = [alert for alert in self.alerts if alert.timestamp >= cutoff]
            
            if component_name:
                alerts = [alert for alert in alerts if alert.component_name == component_name]
            
            if alert_level:
                alerts = [alert for alert in alerts if alert.alert_level == alert_level]
            
            return alerts
    
    def add_alert_callback(self, callback: Callable[[ResourceAlert], None]):
        """Add a callback for resource alerts."""
        with self._lock:
            self.alert_callbacks.append(callback)
    
    def remove_alert_callback(self, callback: Callable[[ResourceAlert], None]):
        """Remove an alert callback."""
        with self._lock:
            if callback in self.alert_callbacks:
                self.alert_callbacks.remove(callback)
    
    def set_thresholds(self, thresholds: ResourceThresholds):
        """Set resource usage thresholds."""
        with self._lock:
            self.thresholds = thresholds
    
    def force_garbage_collection(self):
        """Force garbage collection and return statistics."""
        collected_counts = gc.collect()
        
        return {
            'collected_objects': collected_counts,
            'total_objects': len(gc.get_objects()),
            'gc_stats': gc.get_stats() if hasattr(gc, 'get_stats') else None
        }
    
    def cleanup_component_resources(self, component_name: str):
        """Clean up resources for a component."""
        with self._lock:
            tracker = self.component_trackers.get(component_name)
            if tracker:
                # Clear object references
                tracker.object_refs.clear()
                
                # Force garbage collection
                self.force_garbage_collection()
                
                # Take final snapshot
                final_snapshot = tracker.record_snapshot()
                
                return {
                    'component_name': component_name,
                    'final_memory_mb': final_snapshot.memory_rss / (1024 * 1024) if final_snapshot else 0,
                    'memory_delta_mb': tracker.get_memory_delta() / (1024 * 1024),
                    'peak_memory_mb': tracker.peak_memory / (1024 * 1024),
                    'snapshots_recorded': len(tracker.snapshots)
                }
            
            return None


# Global resource monitor instance
_global_resource_monitor: Optional[ResourceMonitor] = None


def get_resource_monitor() -> ResourceMonitor:
    """Get the global resource monitor instance."""
    global _global_resource_monitor
    if _global_resource_monitor is None:
        _global_resource_monitor = ResourceMonitor()
    return _global_resource_monitor


def set_resource_monitor(monitor: ResourceMonitor):
    """Set the global resource monitor instance."""
    global _global_resource_monitor
    _global_resource_monitor = monitor


def monitor_component_resources(component_name: str) -> ComponentResourceTracker:
    """Register a component for resource monitoring."""
    monitor = get_resource_monitor()
    return monitor.register_component(component_name)


def record_component_usage(component_name: str) -> Optional[ResourceSnapshot]:
    """Record resource usage for a component."""
    monitor = get_resource_monitor()
    return monitor.record_component_snapshot(component_name)


def track_component_object(component_name: str, obj: Any):
    """Track an object for a component."""
    monitor = get_resource_monitor()
    monitor.add_component_object(component_name, obj)


class ResourceMonitoringContext:
    """Context manager for monitoring component resources."""
    
    def __init__(self, component_name: str, auto_cleanup: bool = True):
        self.component_name = component_name
        self.auto_cleanup = auto_cleanup
        self.monitor = get_resource_monitor()
        self.tracker: Optional[ComponentResourceTracker] = None
    
    def __enter__(self):
        """Start resource monitoring."""
        self.tracker = self.monitor.register_component(self.component_name)
        return self.tracker
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """End resource monitoring."""
        if self.auto_cleanup:
            self.monitor.cleanup_component_resources(self.component_name)


def monitor_component_context(component_name: str, auto_cleanup: bool = True) -> ResourceMonitoringContext:
    """Create a resource monitoring context manager."""
    return ResourceMonitoringContext(component_name, auto_cleanup)