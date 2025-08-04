"""
Unit tests for the performance monitoring system.
"""

import pytest
import time
import json
import tempfile
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from hot_reload.performance import (
    PerformanceMonitor, PerformanceMetric, ComponentPerformanceStats,
    PerformanceTimer, MetricType, PerformanceLevel,
    get_performance_monitor, set_performance_monitor,
    record_component_metric, time_component_operation
)


class TestPerformanceMetric:
    """Test PerformanceMetric class."""
    
    def test_create_metric(self):
        """Test creating a performance metric."""
        metric = PerformanceMetric(
            component_name="test_component",
            metric_type=MetricType.LOAD_TIME,
            value=1.5,
            unit="seconds"
        )
        
        assert metric.component_name == "test_component"
        assert metric.metric_type == MetricType.LOAD_TIME
        assert metric.value == 1.5
        assert metric.unit == "seconds"
        assert isinstance(metric.timestamp, datetime)
        assert metric.operation_id is None
        assert metric.context == {}
    
    def test_metric_validation(self):
        """Test metric validation."""
        # Empty component name should raise error
        with pytest.raises(ValueError, match="Component name cannot be empty"):
            PerformanceMetric("", MetricType.LOAD_TIME, 1.0, "seconds")
        
        # Negative value should raise error
        with pytest.raises(ValueError, match="Metric value cannot be negative"):
            PerformanceMetric("test", MetricType.LOAD_TIME, -1.0, "seconds")
    
    def test_metric_serialization(self):
        """Test metric serialization to/from dict."""
        metric = PerformanceMetric(
            component_name="test_component",
            metric_type=MetricType.MEMORY_USAGE,
            value=1024.0,
            unit="bytes",
            operation_id="op_123",
            context={"test": "value"}
        )
        
        # Test to_dict
        data = metric.to_dict()
        assert data['component_name'] == "test_component"
        assert data['metric_type'] == "memory_usage"
        assert data['value'] == 1024.0
        assert data['unit'] == "bytes"
        assert data['operation_id'] == "op_123"
        assert data['context'] == {"test": "value"}
        assert 'timestamp' in data
        
        # Test from_dict
        restored_metric = PerformanceMetric.from_dict(data)
        assert restored_metric.component_name == metric.component_name
        assert restored_metric.metric_type == metric.metric_type
        assert restored_metric.value == metric.value
        assert restored_metric.unit == metric.unit
        assert restored_metric.operation_id == metric.operation_id
        assert restored_metric.context == metric.context


class TestComponentPerformanceStats:
    """Test ComponentPerformanceStats class."""
    
    def test_create_stats(self):
        """Test creating component performance stats."""
        stats = ComponentPerformanceStats("test_component")
        
        assert stats.component_name == "test_component"
        assert stats.total_operations == 0
        assert stats.successful_operations == 0
        assert stats.failed_operations == 0
        assert stats.average_load_time == 0.0
        assert stats.average_memory_usage == 0.0
        assert stats.peak_memory_usage == 0.0
        assert stats.total_reload_count == 0
        assert stats.last_operation_time is None
        assert stats.performance_level == PerformanceLevel.AVERAGE
        assert stats.metrics_history == []
    
    def test_update_stats_with_load_time(self):
        """Test updating stats with load time metrics."""
        stats = ComponentPerformanceStats("test_component")
        
        # Add first load time metric
        metric1 = PerformanceMetric("test_component", MetricType.LOAD_TIME, 1.0, "seconds")
        stats.update_stats(metric1, success=True)
        
        assert stats.total_operations == 1
        assert stats.successful_operations == 1
        assert stats.failed_operations == 0
        assert stats.average_load_time == 1.0
        assert stats.last_operation_time == metric1.timestamp
        assert len(stats.metrics_history) == 1
        
        # Add second load time metric
        metric2 = PerformanceMetric("test_component", MetricType.LOAD_TIME, 3.0, "seconds")
        stats.update_stats(metric2, success=True)
        
        assert stats.total_operations == 2
        assert stats.successful_operations == 2
        assert stats.average_load_time == 2.0  # (1.0 + 3.0) / 2
    
    def test_update_stats_with_memory_usage(self):
        """Test updating stats with memory usage metrics."""
        stats = ComponentPerformanceStats("test_component")
        
        # Add memory usage metrics
        metric1 = PerformanceMetric("test_component", MetricType.MEMORY_USAGE, 1024.0, "bytes")
        stats.update_stats(metric1, success=True)
        
        assert stats.average_memory_usage == 1024.0
        assert stats.peak_memory_usage == 1024.0
        
        metric2 = PerformanceMetric("test_component", MetricType.MEMORY_USAGE, 2048.0, "bytes")
        stats.update_stats(metric2, success=True)
        
        assert stats.average_memory_usage == 1536.0  # (1024 + 2048) / 2
        assert stats.peak_memory_usage == 2048.0
    
    def test_update_stats_with_failures(self):
        """Test updating stats with failed operations."""
        stats = ComponentPerformanceStats("test_component")
        
        metric = PerformanceMetric("test_component", MetricType.LOAD_TIME, 1.0, "seconds")
        stats.update_stats(metric, success=False)
        
        assert stats.total_operations == 1
        assert stats.successful_operations == 0
        assert stats.failed_operations == 1
    
    def test_performance_level_calculation(self):
        """Test performance level calculation."""
        stats = ComponentPerformanceStats("test_component")
        
        # Add excellent performance metrics
        load_metric = PerformanceMetric("test_component", MetricType.LOAD_TIME, 0.1, "seconds")
        memory_metric = PerformanceMetric("test_component", MetricType.MEMORY_USAGE, 1024*1024, "bytes")  # 1MB
        
        stats.update_stats(load_metric, success=True)
        stats.update_stats(memory_metric, success=True)
        
        # Should be excellent due to fast load time, low memory, and 100% success rate
        assert stats.performance_level == PerformanceLevel.EXCELLENT
    
    def test_get_success_rate(self):
        """Test success rate calculation."""
        stats = ComponentPerformanceStats("test_component")
        
        # No operations
        assert stats.get_success_rate() == 0.0
        
        # Add successful operations
        metric1 = PerformanceMetric("test_component", MetricType.LOAD_TIME, 1.0, "seconds")
        stats.update_stats(metric1, success=True)
        assert stats.get_success_rate() == 1.0
        
        # Add failed operation
        metric2 = PerformanceMetric("test_component", MetricType.LOAD_TIME, 2.0, "seconds")
        stats.update_stats(metric2, success=False)
        assert stats.get_success_rate() == 0.5
    
    def test_get_recent_metrics(self):
        """Test getting recent metrics."""
        stats = ComponentPerformanceStats("test_component")
        
        # Add old metric
        old_metric = PerformanceMetric("test_component", MetricType.LOAD_TIME, 1.0, "seconds")
        old_metric.timestamp = datetime.now() - timedelta(hours=25)
        stats.metrics_history.append(old_metric)
        
        # Add recent metric
        recent_metric = PerformanceMetric("test_component", MetricType.LOAD_TIME, 2.0, "seconds")
        stats.metrics_history.append(recent_metric)
        
        recent_metrics = stats.get_recent_metrics(hours=24)
        assert len(recent_metrics) == 1
        assert recent_metrics[0] == recent_metric
    
    def test_stats_serialization(self):
        """Test stats serialization to dict."""
        stats = ComponentPerformanceStats("test_component")
        metric = PerformanceMetric("test_component", MetricType.LOAD_TIME, 1.0, "seconds")
        stats.update_stats(metric, success=True)
        
        data = stats.to_dict()
        assert data['component_name'] == "test_component"
        assert data['total_operations'] == 1
        assert data['successful_operations'] == 1
        assert data['failed_operations'] == 0
        assert data['average_load_time'] == 1.0
        assert data['performance_level'] == stats.performance_level.value
        assert data['success_rate'] == 1.0


class TestPerformanceTimer:
    """Test PerformanceTimer class."""
    
    def test_timer_context_manager(self):
        """Test timer as context manager."""
        monitor = PerformanceMonitor()
        
        with PerformanceTimer("test_component", MetricType.LOAD_TIME, monitor) as timer:
            time.sleep(0.01)  # Small delay
        
        # Check that metric was recorded
        stats = monitor.get_component_stats("test_component")
        assert stats is not None
        assert stats.total_operations >= 1  # At least timing metric
        assert stats.average_load_time > 0
    
    def test_timer_with_exception(self):
        """Test timer behavior when exception occurs."""
        monitor = PerformanceMonitor()
        
        try:
            with PerformanceTimer("test_component", MetricType.LOAD_TIME, monitor) as timer:
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # Check that metric was still recorded but marked as failed
        stats = monitor.get_component_stats("test_component")
        assert stats is not None
        assert stats.failed_operations > 0
    
    def test_timer_mark_failure(self):
        """Test manually marking timer as failed."""
        monitor = PerformanceMonitor()
        
        with PerformanceTimer("test_component", MetricType.LOAD_TIME, monitor) as timer:
            timer.mark_failure()
        
        stats = monitor.get_component_stats("test_component")
        assert stats is not None
        assert stats.failed_operations > 0
    
    def test_timer_memory_tracking(self):
        """Test timer memory usage tracking."""
        # Create a mock psutil module
        mock_psutil = MagicMock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 1024 * 1024  # 1MB
        mock_psutil.Process.return_value.memory_info.return_value = mock_memory_info
        
        # Patch both the module and availability flag
        with patch('hot_reload.performance.PSUTIL_AVAILABLE', True), \
             patch('hot_reload.performance.psutil', mock_psutil):
            
            monitor = PerformanceMonitor()
            
            with PerformanceTimer("test_component", MetricType.LOAD_TIME, monitor):
                # Change memory usage during operation
                mock_memory_info.rss = 2 * 1024 * 1024  # 2MB
            
            # Should have recorded both timing and memory metrics
            stats = monitor.get_component_stats("test_component")
            assert stats is not None
            assert stats.total_operations == 2  # timing + memory
    
    @patch('hot_reload.performance.PSUTIL_AVAILABLE', False)
    def test_timer_without_psutil(self):
        """Test timer behavior when psutil is not available."""
        monitor = PerformanceMonitor()
        
        with PerformanceTimer("test_component", MetricType.LOAD_TIME, monitor):
            time.sleep(0.01)
        
        # Should have recorded only timing metric, no memory metric
        stats = monitor.get_component_stats("test_component")
        assert stats is not None
        assert stats.total_operations == 1  # only timing


class TestPerformanceMonitor:
    """Test PerformanceMonitor class."""
    
    def test_create_monitor(self):
        """Test creating a performance monitor."""
        monitor = PerformanceMonitor()
        
        assert monitor.max_metrics_per_component == 1000
        assert monitor.component_stats == {}
        assert len(monitor.global_metrics) == 0
        assert monitor.is_monitoring_active()
    
    def test_record_metric(self):
        """Test recording a metric."""
        monitor = PerformanceMonitor()
        
        metric = monitor.record_metric(
            component_name="test_component",
            metric_type=MetricType.LOAD_TIME,
            value=1.5,
            unit="seconds",
            operation_id="op_123",
            context={"test": "value"}
        )
        
        assert metric is not None
        assert metric.component_name == "test_component"
        assert metric.metric_type == MetricType.LOAD_TIME
        assert metric.value == 1.5
        
        # Check component stats were updated
        stats = monitor.get_component_stats("test_component")
        assert stats is not None
        assert stats.total_operations == 1
        assert stats.successful_operations == 1
        
        # Check global metrics
        global_metrics = monitor.get_global_metrics()
        assert len(global_metrics) == 1
        assert global_metrics[0] == metric
    
    def test_record_metric_when_monitoring_disabled(self):
        """Test recording metric when monitoring is disabled."""
        monitor = PerformanceMonitor()
        monitor.stop_monitoring()
        
        metric = monitor.record_metric(
            component_name="test_component",
            metric_type=MetricType.LOAD_TIME,
            value=1.5,
            unit="seconds"
        )
        
        assert metric is None
        assert len(monitor.component_stats) == 0
        assert len(monitor.global_metrics) == 0
    
    def test_start_timer(self):
        """Test starting a performance timer."""
        monitor = PerformanceMonitor()
        
        timer = monitor.start_timer("test_component", MetricType.LOAD_TIME, "op_123")
        
        assert isinstance(timer, PerformanceTimer)
        assert timer.component_name == "test_component"
        assert timer.metric_type == MetricType.LOAD_TIME
        assert timer.operation_id == "op_123"
        assert timer.monitor == monitor
    
    def test_get_metrics_by_type(self):
        """Test getting metrics by type."""
        monitor = PerformanceMonitor()
        
        # Record different types of metrics
        monitor.record_metric("comp1", MetricType.LOAD_TIME, 1.0, "seconds")
        monitor.record_metric("comp1", MetricType.MEMORY_USAGE, 1024, "bytes")
        monitor.record_metric("comp2", MetricType.LOAD_TIME, 2.0, "seconds")
        
        # Get load time metrics
        load_metrics = monitor.get_metrics_by_type(MetricType.LOAD_TIME)
        assert len(load_metrics) == 2
        
        # Get load time metrics for specific component
        comp1_load_metrics = monitor.get_metrics_by_type(MetricType.LOAD_TIME, "comp1")
        assert len(comp1_load_metrics) == 1
        assert comp1_load_metrics[0].value == 1.0
        
        # Get memory metrics
        memory_metrics = monitor.get_metrics_by_type(MetricType.MEMORY_USAGE)
        assert len(memory_metrics) == 1
    
    def test_get_performance_summary(self):
        """Test getting performance summary."""
        monitor = PerformanceMonitor()
        
        # Record some metrics
        monitor.record_metric("comp1", MetricType.LOAD_TIME, 1.0, "seconds")
        monitor.record_metric("comp1", MetricType.MEMORY_USAGE, 1024, "bytes")
        monitor.record_metric("comp2", MetricType.LOAD_TIME, 2.0, "seconds", context={'success': False})
        
        summary = monitor.get_performance_summary()
        
        assert summary['total_components'] == 2
        assert summary['total_operations'] == 3
        assert summary['success_rate'] == 2/3  # 2 successful out of 3
        assert summary['average_load_time'] == 1.5  # (1.0 + 2.0) / 2
        assert summary['monitoring_active'] is True
        assert summary['total_metrics'] == 3
    
    def test_metric_callbacks(self):
        """Test metric callbacks."""
        monitor = PerformanceMonitor()
        callback_called = []
        
        def test_callback(metric):
            callback_called.append(metric)
        
        # Add callback
        monitor.add_metric_callback(MetricType.LOAD_TIME, test_callback)
        
        # Record metric
        metric = monitor.record_metric("test", MetricType.LOAD_TIME, 1.0, "seconds")
        
        assert len(callback_called) == 1
        assert callback_called[0] == metric
        
        # Remove callback
        monitor.remove_metric_callback(MetricType.LOAD_TIME, test_callback)
        
        # Record another metric
        monitor.record_metric("test", MetricType.LOAD_TIME, 2.0, "seconds")
        
        # Callback should not be called again
        assert len(callback_called) == 1
    
    def test_thresholds(self):
        """Test performance thresholds."""
        monitor = PerformanceMonitor()
        
        # Set custom threshold
        monitor.set_threshold(MetricType.LOAD_TIME, warning=1.0, critical=2.0)
        
        assert monitor.thresholds[MetricType.LOAD_TIME]['warning'] == 1.0
        assert monitor.thresholds[MetricType.LOAD_TIME]['critical'] == 2.0
    
    def test_clear_stats(self):
        """Test clearing statistics."""
        monitor = PerformanceMonitor()
        
        # Record some metrics
        monitor.record_metric("comp1", MetricType.LOAD_TIME, 1.0, "seconds")
        monitor.record_metric("comp2", MetricType.LOAD_TIME, 2.0, "seconds")
        
        assert len(monitor.component_stats) == 2
        assert len(monitor.global_metrics) == 2
        
        # Clear specific component
        monitor.clear_component_stats("comp1")
        assert len(monitor.component_stats) == 1
        assert "comp1" not in monitor.component_stats
        
        # Clear all stats
        monitor.clear_all_stats()
        assert len(monitor.component_stats) == 0
        assert len(monitor.global_metrics) == 0
    
    def test_export_metrics(self):
        """Test exporting metrics to file."""
        monitor = PerformanceMonitor()
        
        # Record some metrics
        monitor.record_metric("test_component", MetricType.LOAD_TIME, 1.0, "seconds")
        monitor.record_metric("test_component", MetricType.MEMORY_USAGE, 1024, "bytes")
        
        # Export to temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name
        
        try:
            monitor.export_metrics(temp_path)
            
            # Read and verify exported data
            with open(temp_path, 'r') as f:
                data = json.load(f)
            
            assert 'summary' in data
            assert 'component_stats' in data
            assert 'global_metrics' in data
            assert 'test_component' in data['component_stats']
            assert len(data['global_metrics']) == 2
            
        finally:
            os.unlink(temp_path)
    
    def test_export_component_metrics(self):
        """Test exporting metrics for specific component."""
        monitor = PerformanceMonitor()
        
        # Record metrics for different components
        monitor.record_metric("comp1", MetricType.LOAD_TIME, 1.0, "seconds")
        monitor.record_metric("comp2", MetricType.LOAD_TIME, 2.0, "seconds")
        
        # Export specific component
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name
        
        try:
            monitor.export_metrics(temp_path, component_name="comp1")
            
            # Read and verify exported data
            with open(temp_path, 'r') as f:
                data = json.load(f)
            
            assert 'component_stats' in data
            assert 'metrics' in data
            assert data['component_stats']['component_name'] == "comp1"
            
        finally:
            os.unlink(temp_path)
    
    def test_monitoring_control(self):
        """Test starting and stopping monitoring."""
        monitor = PerformanceMonitor()
        
        assert monitor.is_monitoring_active()
        
        # Stop monitoring
        monitor.stop_monitoring()
        assert not monitor.is_monitoring_active()
        
        # Start monitoring
        monitor.start_monitoring()
        assert monitor.is_monitoring_active()


class TestGlobalFunctions:
    """Test global convenience functions."""
    
    def test_get_performance_monitor(self):
        """Test getting global performance monitor."""
        # Reset global monitor
        set_performance_monitor(None)
        
        monitor1 = get_performance_monitor()
        monitor2 = get_performance_monitor()
        
        # Should return same instance
        assert monitor1 is monitor2
        assert isinstance(monitor1, PerformanceMonitor)
    
    def test_set_performance_monitor(self):
        """Test setting global performance monitor."""
        custom_monitor = PerformanceMonitor()
        set_performance_monitor(custom_monitor)
        
        retrieved_monitor = get_performance_monitor()
        assert retrieved_monitor is custom_monitor
    
    def test_record_component_metric(self):
        """Test convenience function for recording metrics."""
        # Reset global monitor
        set_performance_monitor(PerformanceMonitor())
        
        metric = record_component_metric(
            component_name="test_component",
            metric_type=MetricType.LOAD_TIME,
            value=1.5,
            unit="seconds",
            operation_id="op_123"
        )
        
        assert metric is not None
        assert metric.component_name == "test_component"
        assert metric.value == 1.5
        
        # Verify it was recorded in global monitor
        monitor = get_performance_monitor()
        stats = monitor.get_component_stats("test_component")
        assert stats is not None
        assert stats.total_operations == 1
    
    def test_time_component_operation(self):
        """Test convenience function for timing operations."""
        # Reset global monitor
        set_performance_monitor(PerformanceMonitor())
        
        timer = time_component_operation(
            component_name="test_component",
            metric_type=MetricType.LOAD_TIME,
            operation_id="op_123"
        )
        
        assert isinstance(timer, PerformanceTimer)
        assert timer.component_name == "test_component"
        assert timer.metric_type == MetricType.LOAD_TIME
        assert timer.operation_id == "op_123"


class TestPerformanceIntegration:
    """Integration tests for performance monitoring."""
    
    def test_full_monitoring_workflow(self):
        """Test complete monitoring workflow."""
        monitor = PerformanceMonitor()
        
        # Simulate component loading with timing
        with monitor.start_timer("test_component", MetricType.LOAD_TIME, "load_op_1"):
            time.sleep(0.01)
            
            # Record memory usage during load
            monitor.record_metric(
                "test_component", 
                MetricType.MEMORY_USAGE, 
                1024 * 1024, 
                "bytes",
                operation_id="load_op_1"
            )
        
        # Simulate component reload
        with monitor.start_timer("test_component", MetricType.RELOAD_TIME, "reload_op_1"):
            time.sleep(0.005)
        
        # Verify stats
        stats = monitor.get_component_stats("test_component")
        assert stats is not None
        assert stats.total_operations >= 3  # load timing + memory + reload timing
        assert stats.average_load_time > 0
        assert stats.total_reload_count >= 1
        
        # Verify global metrics
        global_metrics = monitor.get_global_metrics()
        assert len(global_metrics) >= 3
        
        # Verify performance summary
        summary = monitor.get_performance_summary()
        assert summary['total_components'] == 1
        assert summary['total_operations'] >= 3
        assert summary['success_rate'] > 0
    
    def test_multiple_components_monitoring(self):
        """Test monitoring multiple components."""
        monitor = PerformanceMonitor()
        
        # Monitor different components
        components = ["comp1", "comp2", "comp3"]
        
        for comp in components:
            with monitor.start_timer(comp, MetricType.LOAD_TIME):
                time.sleep(0.001)
            
            monitor.record_metric(comp, MetricType.MEMORY_USAGE, 1024 * 1024, "bytes")
        
        # Verify all components are tracked
        assert len(monitor.component_stats) == 3
        
        for comp in components:
            stats = monitor.get_component_stats(comp)
            assert stats is not None
            assert stats.total_operations >= 2
        
        # Verify summary
        summary = monitor.get_performance_summary()
        assert summary['total_components'] == 3
        assert summary['total_operations'] >= 6


if __name__ == "__main__":
    pytest.main([__file__])