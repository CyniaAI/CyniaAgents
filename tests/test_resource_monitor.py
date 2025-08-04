"""
Unit tests for the resource monitoring system.
"""

import pytest
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from hot_reload.resource_monitor import (
    ResourceMonitor, ComponentResourceTracker, ResourceSnapshot, ResourceThresholds,
    ResourceAlert, ResourceType, AlertLevel, ResourceMonitoringContext,
    get_resource_monitor, set_resource_monitor, monitor_component_resources,
    record_component_usage, track_component_object, monitor_component_context
)


class TestResourceSnapshot:
    """Test ResourceSnapshot class."""
    
    def test_create_snapshot(self):
        """Test creating a resource snapshot."""
        timestamp = datetime.now()
        snapshot = ResourceSnapshot(
            timestamp=timestamp,
            component_name="test_component",
            memory_rss=1024 * 1024,  # 1MB
            cpu_percent=25.5,
            num_threads=5
        )
        
        assert snapshot.timestamp == timestamp
        assert snapshot.component_name == "test_component"
        assert snapshot.memory_rss == 1024 * 1024
        assert snapshot.cpu_percent == 25.5
        assert snapshot.num_threads == 5
    
    def test_snapshot_to_dict(self):
        """Test converting snapshot to dictionary."""
        timestamp = datetime.now()
        snapshot = ResourceSnapshot(
            timestamp=timestamp,
            component_name="test_component",
            memory_rss=1024 * 1024,
            cpu_percent=25.5
        )
        
        data = snapshot.to_dict()
        assert data['timestamp'] == timestamp.isoformat()
        assert data['component_name'] == "test_component"
        assert data['memory_rss'] == 1024 * 1024
        assert data['cpu_percent'] == 25.5


class TestResourceThresholds:
    """Test ResourceThresholds class."""
    
    def test_default_thresholds(self):
        """Test default threshold values."""
        thresholds = ResourceThresholds()
        
        assert thresholds.memory_mb_warning == 100.0
        assert thresholds.memory_mb_critical == 500.0
        assert thresholds.cpu_percent_warning == 50.0
        assert thresholds.cpu_percent_critical == 80.0
    
    def test_memory_rss_check(self):
        """Test memory RSS threshold checking."""
        thresholds = ResourceThresholds()
        
        # Below warning threshold
        assert thresholds.check_memory_rss(50 * 1024 * 1024) is None  # 50MB
        
        # Warning threshold
        assert thresholds.check_memory_rss(150 * 1024 * 1024) == AlertLevel.WARNING  # 150MB
        
        # Critical threshold
        assert thresholds.check_memory_rss(600 * 1024 * 1024) == AlertLevel.CRITICAL  # 600MB
    
    def test_cpu_percent_check(self):
        """Test CPU percentage threshold checking."""
        thresholds = ResourceThresholds()
        
        # Below warning threshold
        assert thresholds.check_cpu_percent(30.0) is None
        
        # Warning threshold
        assert thresholds.check_cpu_percent(60.0) == AlertLevel.WARNING
        
        # Critical threshold
        assert thresholds.check_cpu_percent(90.0) == AlertLevel.CRITICAL
    
    def test_file_handles_check(self):
        """Test file handles threshold checking."""
        thresholds = ResourceThresholds()
        
        # Below warning threshold
        assert thresholds.check_file_handles(50) is None
        
        # Warning threshold
        assert thresholds.check_file_handles(150) == AlertLevel.WARNING
        
        # Critical threshold
        assert thresholds.check_file_handles(600) == AlertLevel.CRITICAL


class TestResourceAlert:
    """Test ResourceAlert class."""
    
    def test_create_alert(self):
        """Test creating a resource alert."""
        timestamp = datetime.now()
        alert = ResourceAlert(
            timestamp=timestamp,
            component_name="test_component",
            resource_type=ResourceType.MEMORY,
            alert_level=AlertLevel.WARNING,
            current_value=150.0,
            threshold_value=100.0,
            message="Memory usage exceeds warning threshold"
        )
        
        assert alert.timestamp == timestamp
        assert alert.component_name == "test_component"
        assert alert.resource_type == ResourceType.MEMORY
        assert alert.alert_level == AlertLevel.WARNING
        assert alert.current_value == 150.0
        assert alert.threshold_value == 100.0
    
    def test_alert_to_dict(self):
        """Test converting alert to dictionary."""
        timestamp = datetime.now()
        alert = ResourceAlert(
            timestamp=timestamp,
            component_name="test_component",
            resource_type=ResourceType.CPU,
            alert_level=AlertLevel.CRITICAL,
            current_value=85.0,
            threshold_value=80.0,
            message="CPU usage critical"
        )
        
        data = alert.to_dict()
        assert data['timestamp'] == timestamp.isoformat()
        assert data['component_name'] == "test_component"
        assert data['resource_type'] == "cpu"
        assert data['alert_level'] == "critical"
        assert data['current_value'] == 85.0
        assert data['threshold_value'] == 80.0
        assert data['message'] == "CPU usage critical"


class TestComponentResourceTracker:
    """Test ComponentResourceTracker class."""
    
    def test_create_tracker(self):
        """Test creating a component resource tracker."""
        tracker = ComponentResourceTracker("test_component")
        
        assert tracker.component_name == "test_component"
        assert len(tracker.snapshots) == 0
        assert tracker.peak_memory >= 0
        assert tracker.peak_cpu >= 0.0
        assert tracker.start_snapshot is not None
    
    def test_record_snapshot(self):
        """Test recording resource snapshots."""
        tracker = ComponentResourceTracker("test_component")
        
        # Record a snapshot
        snapshot = tracker.record_snapshot()
        
        assert snapshot is not None
        assert snapshot.component_name == "test_component"
        assert len(tracker.snapshots) == 1
        assert tracker.snapshots[0] == snapshot
    
    def test_memory_delta_calculation(self):
        """Test memory delta calculation."""
        tracker = ComponentResourceTracker("test_component")
        
        # Mock the start snapshot
        start_memory = 100 * 1024 * 1024  # 100MB
        tracker.start_snapshot = ResourceSnapshot(
            timestamp=datetime.now(),
            component_name="test_component",
            memory_rss=start_memory
        )
        
        # Add a current snapshot
        current_memory = 150 * 1024 * 1024  # 150MB
        current_snapshot = ResourceSnapshot(
            timestamp=datetime.now(),
            component_name="test_component",
            memory_rss=current_memory
        )
        tracker.snapshots.append(current_snapshot)
        
        # Check delta
        delta = tracker.get_memory_delta()
        assert delta == 50 * 1024 * 1024  # 50MB increase
    
    def test_average_cpu_calculation(self):
        """Test average CPU calculation."""
        tracker = ComponentResourceTracker("test_component")
        
        # Add snapshots with different CPU values
        now = datetime.now()
        for i, cpu_value in enumerate([10.0, 20.0, 30.0, 40.0]):
            snapshot = ResourceSnapshot(
                timestamp=now - timedelta(minutes=i),
                component_name="test_component",
                cpu_percent=cpu_value
            )
            tracker.snapshots.append(snapshot)
        
        # Calculate average
        avg_cpu = tracker.get_average_cpu(minutes=10)
        assert avg_cpu == 25.0  # (10 + 20 + 30 + 40) / 4
    
    def test_resource_summary(self):
        """Test getting resource summary."""
        tracker = ComponentResourceTracker("test_component")
        
        # Add a snapshot
        snapshot = ResourceSnapshot(
            timestamp=datetime.now(),
            component_name="test_component",
            memory_rss=100 * 1024 * 1024,  # 100MB
            cpu_percent=25.0,
            num_threads=5
        )
        tracker.snapshots.append(snapshot)
        tracker.peak_memory = 120 * 1024 * 1024  # 120MB
        tracker.peak_cpu = 30.0
        
        summary = tracker.get_resource_summary()
        
        assert summary['component_name'] == "test_component"
        assert summary['current_memory_mb'] == 100.0
        assert summary['peak_memory_mb'] == 120.0
        assert summary['current_cpu_percent'] == 25.0
        assert summary['peak_cpu_percent'] == 30.0
        assert summary['current_threads'] == 5
        assert summary['snapshots_count'] == 1
    
    def test_object_reference_tracking(self):
        """Test tracking object references."""
        tracker = ComponentResourceTracker("test_component")
        
        # Test with objects that support weak references
        class TestObject:
            def __init__(self, name):
                self.name = name
        
        obj1 = TestObject("object1")
        obj2 = TestObject("object2")
        
        tracker.add_object_reference(obj1)
        tracker.add_object_reference(obj2)
        
        # Check that references are tracked
        summary = tracker.get_resource_summary()
        assert summary['tracked_objects'] == 2
        
        # Delete one object and force garbage collection
        del obj1
        import gc
        gc.collect()
        
        # Should now track only the remaining object
        summary = tracker.get_resource_summary()
        assert summary['tracked_objects'] == 1
        
        # Test with objects that don't support weak references (like dict)
        dict_obj = {"test": "dict"}
        tracker.add_object_reference(dict_obj)
        
        # Should increase count
        summary = tracker.get_resource_summary()
        assert summary['tracked_objects'] == 2  # 1 weak ref + 1 non-weak ref


class TestResourceMonitor:
    """Test ResourceMonitor class."""
    
    def test_create_monitor(self):
        """Test creating a resource monitor."""
        monitor = ResourceMonitor(monitoring_interval=1.0)
        
        assert monitor.monitoring_interval == 1.0
        assert len(monitor.component_trackers) == 0
        assert isinstance(monitor.thresholds, ResourceThresholds)
        assert len(monitor.alerts) == 0
        assert not monitor._monitoring_active
    
    def test_register_component(self):
        """Test registering components for monitoring."""
        monitor = ResourceMonitor()
        
        # Register a component
        tracker = monitor.register_component("test_component")
        
        assert isinstance(tracker, ComponentResourceTracker)
        assert tracker.component_name == "test_component"
        assert "test_component" in monitor.component_trackers
        
        # Register same component again should return same tracker
        tracker2 = monitor.register_component("test_component")
        assert tracker is tracker2
    
    def test_unregister_component(self):
        """Test unregistering components."""
        monitor = ResourceMonitor()
        
        # Register and then unregister
        monitor.register_component("test_component")
        assert "test_component" in monitor.component_trackers
        
        monitor.unregister_component("test_component")
        assert "test_component" not in monitor.component_trackers
    
    def test_record_component_snapshot(self):
        """Test recording component snapshots."""
        monitor = ResourceMonitor()
        
        # Register component
        monitor.register_component("test_component")
        
        # Record snapshot
        snapshot = monitor.record_component_snapshot("test_component")
        
        assert snapshot is not None
        assert snapshot.component_name == "test_component"
        
        # Check that tracker has the snapshot
        tracker = monitor.component_trackers["test_component"]
        assert len(tracker.snapshots) == 1
    
    def test_threshold_checking(self):
        """Test threshold checking and alert generation."""
        monitor = ResourceMonitor()
        
        # Set low thresholds for testing
        monitor.thresholds.memory_mb_warning = 1.0  # 1MB
        monitor.thresholds.memory_mb_critical = 2.0  # 2MB
        
        # Create a snapshot that exceeds thresholds
        snapshot = ResourceSnapshot(
            timestamp=datetime.now(),
            component_name="test_component",
            memory_rss=3 * 1024 * 1024  # 3MB
        )
        
        # Check thresholds
        monitor._check_thresholds(snapshot)
        
        # Should have generated alerts
        assert len(monitor.alerts) > 0
        
        # Check alert details
        memory_alerts = [a for a in monitor.alerts if a.resource_type == ResourceType.MEMORY]
        assert len(memory_alerts) > 0
        
        critical_alerts = [a for a in memory_alerts if a.alert_level == AlertLevel.CRITICAL]
        assert len(critical_alerts) > 0
    
    def test_alert_callbacks(self):
        """Test alert callback functionality."""
        monitor = ResourceMonitor()
        callback_called = []
        
        def test_callback(alert):
            callback_called.append(alert)
        
        # Add callback
        monitor.add_alert_callback(test_callback)
        
        # Set low threshold and trigger alert
        monitor.thresholds.cpu_percent_warning = 1.0
        
        snapshot = ResourceSnapshot(
            timestamp=datetime.now(),
            component_name="test_component",
            cpu_percent=5.0
        )
        
        monitor._check_thresholds(snapshot)
        
        # Callback should have been called
        assert len(callback_called) > 0
        assert callback_called[0].resource_type == ResourceType.CPU
        
        # Remove callback
        monitor.remove_alert_callback(test_callback)
        callback_called.clear()
        
        # Trigger another alert
        monitor._check_thresholds(snapshot)
        
        # Callback should not be called
        assert len(callback_called) == 0
    
    def test_get_component_summary(self):
        """Test getting component summary."""
        monitor = ResourceMonitor()
        
        # Register component and record snapshot
        monitor.register_component("test_component")
        monitor.record_component_snapshot("test_component")
        
        # Get summary
        summary = monitor.get_component_summary("test_component")
        
        assert summary is not None
        assert summary['component_name'] == "test_component"
        assert 'current_memory_mb' in summary
        assert 'current_cpu_percent' in summary
        
        # Test non-existent component
        summary = monitor.get_component_summary("non_existent")
        assert summary is None
    
    def test_get_all_component_summaries(self):
        """Test getting all component summaries."""
        monitor = ResourceMonitor()
        
        # Register multiple components
        monitor.register_component("component1")
        monitor.register_component("component2")
        
        # Record snapshots
        monitor.record_component_snapshot("component1")
        monitor.record_component_snapshot("component2")
        
        # Get all summaries
        summaries = monitor.get_all_component_summaries()
        
        assert len(summaries) == 2
        assert "component1" in summaries
        assert "component2" in summaries
        assert summaries["component1"]['component_name'] == "component1"
        assert summaries["component2"]['component_name'] == "component2"
    
    def test_get_system_summary(self):
        """Test getting system summary."""
        monitor = ResourceMonitor()
        
        # Register components and record snapshots
        monitor.register_component("component1")
        monitor.register_component("component2")
        monitor.record_component_snapshot("component1")
        monitor.record_component_snapshot("component2")
        
        # Get system summary
        summary = monitor.get_system_summary()
        
        assert summary['component_count'] == 2
        assert 'total_memory_mb' in summary
        assert 'average_cpu_percent' in summary
        assert 'monitoring_active' in summary
        assert summary['monitoring_active'] == False  # Not started yet
    
    def test_get_recent_alerts(self):
        """Test getting recent alerts."""
        monitor = ResourceMonitor()
        
        # Create alerts with different timestamps
        now = datetime.now()
        old_alert = ResourceAlert(
            timestamp=now - timedelta(hours=25),  # Older than 24 hours
            component_name="component1",
            resource_type=ResourceType.MEMORY,
            alert_level=AlertLevel.WARNING,
            current_value=100.0,
            threshold_value=80.0,
            message="Old alert"
        )
        
        recent_alert = ResourceAlert(
            timestamp=now - timedelta(hours=1),  # Recent
            component_name="component2",
            resource_type=ResourceType.CPU,
            alert_level=AlertLevel.CRITICAL,
            current_value=90.0,
            threshold_value=80.0,
            message="Recent alert"
        )
        
        monitor.alerts.extend([old_alert, recent_alert])
        
        # Get recent alerts (last 24 hours)
        recent_alerts = monitor.get_recent_alerts(hours=24)
        assert len(recent_alerts) == 1
        assert recent_alerts[0].message == "Recent alert"
        
        # Filter by component
        component_alerts = monitor.get_recent_alerts(hours=48, component_name="component1")
        assert len(component_alerts) == 1
        assert component_alerts[0].component_name == "component1"
        
        # Filter by alert level
        critical_alerts = monitor.get_recent_alerts(hours=48, alert_level=AlertLevel.CRITICAL)
        assert len(critical_alerts) == 1
        assert critical_alerts[0].alert_level == AlertLevel.CRITICAL
    
    def test_monitoring_start_stop(self):
        """Test starting and stopping monitoring."""
        monitor = ResourceMonitor(monitoring_interval=0.1)  # Fast interval for testing
        
        assert not monitor._monitoring_active
        
        # Start monitoring
        monitor.start_monitoring()
        assert monitor._monitoring_active
        assert monitor._monitoring_thread is not None
        
        # Let it run briefly
        time.sleep(0.2)
        
        # Stop monitoring
        monitor.stop_monitoring()
        assert not monitor._monitoring_active
        
        # Starting again should work
        monitor.start_monitoring()
        assert monitor._monitoring_active
        
        # Cleanup
        monitor.stop_monitoring()
    
    def test_force_garbage_collection(self):
        """Test forcing garbage collection."""
        monitor = ResourceMonitor()
        
        # Create some objects
        objects = [{"test": i} for i in range(100)]
        
        # Force garbage collection
        gc_stats = monitor.force_garbage_collection()
        
        assert 'collected_objects' in gc_stats
        assert 'total_objects' in gc_stats
        assert gc_stats['total_objects'] > 0
    
    def test_cleanup_component_resources(self):
        """Test cleaning up component resources."""
        monitor = ResourceMonitor()
        
        # Register component and add objects
        tracker = monitor.register_component("test_component")
        test_obj = {"test": "object"}
        tracker.add_object_reference(test_obj)
        
        # Record some snapshots
        monitor.record_component_snapshot("test_component")
        
        # Cleanup resources
        cleanup_result = monitor.cleanup_component_resources("test_component")
        
        assert cleanup_result is not None
        assert cleanup_result['component_name'] == "test_component"
        assert 'final_memory_mb' in cleanup_result
        assert 'memory_delta_mb' in cleanup_result
        assert 'peak_memory_mb' in cleanup_result
        assert 'snapshots_recorded' in cleanup_result


class TestResourceMonitoringContext:
    """Test ResourceMonitoringContext class."""
    
    def test_context_manager(self):
        """Test resource monitoring context manager."""
        monitor = ResourceMonitor()
        set_resource_monitor(monitor)
        
        with ResourceMonitoringContext("test_component") as tracker:
            assert isinstance(tracker, ComponentResourceTracker)
            assert tracker.component_name == "test_component"
            assert "test_component" in monitor.component_trackers
        
        # After context, component should still be registered
        # (cleanup happens but doesn't unregister)
        assert "test_component" in monitor.component_trackers
    
    def test_context_manager_with_exception(self):
        """Test context manager when exception occurs."""
        monitor = ResourceMonitor()
        set_resource_monitor(monitor)
        
        try:
            with ResourceMonitoringContext("test_component") as tracker:
                assert isinstance(tracker, ComponentResourceTracker)
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # Component should still be registered
        assert "test_component" in monitor.component_trackers


class TestGlobalFunctions:
    """Test global convenience functions."""
    
    def test_get_set_resource_monitor(self):
        """Test getting and setting global resource monitor."""
        # Reset global monitor
        set_resource_monitor(None)
        
        monitor1 = get_resource_monitor()
        monitor2 = get_resource_monitor()
        
        # Should return same instance
        assert monitor1 is monitor2
        assert isinstance(monitor1, ResourceMonitor)
        
        # Set custom monitor
        custom_monitor = ResourceMonitor()
        set_resource_monitor(custom_monitor)
        
        retrieved_monitor = get_resource_monitor()
        assert retrieved_monitor is custom_monitor
    
    def test_monitor_component_resources(self):
        """Test monitoring component resources."""
        # Reset global monitor
        set_resource_monitor(ResourceMonitor())
        
        tracker = monitor_component_resources("test_component")
        assert isinstance(tracker, ComponentResourceTracker)
        assert tracker.component_name == "test_component"
        
        # Verify it was registered in global monitor
        monitor = get_resource_monitor()
        assert "test_component" in monitor.component_trackers
    
    def test_record_component_usage(self):
        """Test recording component usage."""
        # Reset global monitor
        set_resource_monitor(ResourceMonitor())
        
        # Register component first
        monitor_component_resources("test_component")
        
        # Record usage
        snapshot = record_component_usage("test_component")
        assert snapshot is not None
        assert snapshot.component_name == "test_component"
        
        # Verify it was recorded in global monitor
        monitor = get_resource_monitor()
        tracker = monitor.component_trackers["test_component"]
        assert len(tracker.snapshots) == 1
    
    def test_track_component_object(self):
        """Test tracking component objects."""
        # Reset global monitor
        set_resource_monitor(ResourceMonitor())
        
        # Register component
        monitor_component_resources("test_component")
        
        # Track object that supports weak references
        class TestObject:
            def __init__(self, name):
                self.name = name
        
        test_obj = TestObject("test")
        track_component_object("test_component", test_obj)
        
        # Verify object is tracked
        monitor = get_resource_monitor()
        tracker = monitor.component_trackers["test_component"]
        summary = tracker.get_resource_summary()
        assert summary['tracked_objects'] == 1
        
        # Keep reference to prevent garbage collection during test
        assert test_obj is not None
    
    def test_monitor_component_context(self):
        """Test monitor component context function."""
        # Reset global monitor
        set_resource_monitor(ResourceMonitor())
        
        context = monitor_component_context("test_component")
        assert isinstance(context, ResourceMonitoringContext)
        assert context.component_name == "test_component"
        
        # Use context
        with context as tracker:
            assert isinstance(tracker, ComponentResourceTracker)
            assert tracker.component_name == "test_component"


class TestIntegration:
    """Integration tests for resource monitoring."""
    
    def test_full_monitoring_workflow(self):
        """Test complete monitoring workflow."""
        monitor = ResourceMonitor(monitoring_interval=0.1)
        
        # Register components
        tracker1 = monitor.register_component("component1")
        tracker2 = monitor.register_component("component2")
        
        # Add some objects to track (use objects that support weak references)
        class TestObject:
            def __init__(self, data):
                self.data = data
        
        obj1 = TestObject("component1_data")
        obj2 = TestObject("component2_data")
        tracker1.add_object_reference(obj1)
        tracker2.add_object_reference(obj2)
        
        # Record snapshots
        snapshot1 = monitor.record_component_snapshot("component1")
        snapshot2 = monitor.record_component_snapshot("component2")
        
        assert snapshot1 is not None
        assert snapshot2 is not None
        
        # Get summaries
        summary1 = monitor.get_component_summary("component1")
        summary2 = monitor.get_component_summary("component2")
        
        assert summary1['component_name'] == "component1"
        assert summary2['component_name'] == "component2"
        assert summary1['tracked_objects'] == 1
        assert summary2['tracked_objects'] == 1
        
        # Keep references to prevent garbage collection during test
        assert obj1 is not None
        assert obj2 is not None
        
        # Get system summary
        system_summary = monitor.get_system_summary()
        assert system_summary['component_count'] == 2
        
        # Test monitoring
        monitor.start_monitoring()
        time.sleep(0.3)  # Let it collect some data
        monitor.stop_monitoring()
        
        # Should have more snapshots now
        assert len(tracker1.snapshots) > 1
        assert len(tracker2.snapshots) > 1
        
        # Cleanup
        cleanup1 = monitor.cleanup_component_resources("component1")
        cleanup2 = monitor.cleanup_component_resources("component2")
        
        assert cleanup1['component_name'] == "component1"
        assert cleanup2['component_name'] == "component2"
    
    def test_alert_generation_workflow(self):
        """Test alert generation workflow."""
        monitor = ResourceMonitor()
        
        # Set very low thresholds
        monitor.thresholds.memory_mb_warning = 0.1  # 0.1MB
        monitor.thresholds.memory_mb_critical = 0.2  # 0.2MB
        monitor.thresholds.cpu_percent_warning = 1.0  # 1%
        monitor.thresholds.cpu_percent_critical = 2.0  # 2%
        
        # Track alerts
        alerts_received = []
        
        def alert_callback(alert):
            alerts_received.append(alert)
        
        monitor.add_alert_callback(alert_callback)
        
        # Create a mock snapshot that will trigger alerts
        snapshot = ResourceSnapshot(
            timestamp=datetime.now(),
            component_name="test_component",
            memory_rss=5 * 1024 * 1024,  # 5MB - should trigger critical alert
            cpu_percent=10.0  # 10% - should trigger critical alert
        )
        
        # Manually trigger threshold checking
        monitor._check_thresholds(snapshot)
        
        # Should have received alerts
        assert len(alerts_received) > 0
        
        # Check alert types
        memory_alerts = [a for a in alerts_received if a.resource_type == ResourceType.MEMORY]
        assert len(memory_alerts) > 0
        
        cpu_alerts = [a for a in alerts_received if a.resource_type == ResourceType.CPU]
        assert len(cpu_alerts) > 0
        
        # Get recent alerts
        recent_alerts = monitor.get_recent_alerts(hours=1)
        assert len(recent_alerts) > 0


if __name__ == "__main__":
    pytest.main([__file__])