"""
Version compatibility checker for components.
"""
import re
from typing import Optional, Set, Union
from packaging import version
from log_writer import logger


class VersionRange:
    """Represents a version range with optional min and max bounds."""
    
    def __init__(self, min_version: Optional[str] = None, max_version: Optional[str] = None, 
                 include_min: bool = True, include_max: bool = True):
        """
        Initialize a version range.
        
        Args:
            min_version: Minimum version (None for no lower bound)
            max_version: Maximum version (None for no upper bound)
            include_min: Whether to include the minimum version
            include_max: Whether to include the maximum version
        """
        self.min_version = version.parse(min_version) if min_version else None
        self.max_version = version.parse(max_version) if max_version else None
        self.include_min = include_min
        self.include_max = include_max
    
    def contains(self, target_version: str) -> bool:
        """Check if a version is within this range."""
        try:
            target = version.parse(target_version)
            
            # Check lower bound
            if self.min_version is not None:
                if self.include_min:
                    if target < self.min_version:
                        return False
                else:
                    if target <= self.min_version:
                        return False
            
            # Check upper bound
            if self.max_version is not None:
                if self.include_max:
                    if target > self.max_version:
                        return False
                else:
                    if target >= self.max_version:
                        return False
            
            return True
        except Exception as e:
            logger(f"Error parsing version {target_version}: {e}")
            return False
    
    def __str__(self):
        if self.min_version is None and self.max_version is None:
            return "any version"
        elif self.min_version is None:
            op = "<=" if self.include_max else "<"
            return f"{op} {self.max_version}"
        elif self.max_version is None:
            op = ">=" if self.include_min else ">"
            return f"{op} {self.min_version}"
        else:
            min_op = ">=" if self.include_min else ">"
            max_op = "<=" if self.include_max else "<"
            return f"{min_op} {self.min_version}, {max_op} {self.max_version}"


class VersionSet:
    """Represents a set of version ranges."""
    
    def __init__(self, ranges: Optional[list] = None):
        """
        Initialize a version set.
        
        Args:
            ranges: List of VersionRange objects or version specification strings
        """
        self.ranges = []
        if ranges:
            for r in ranges:
                if isinstance(r, VersionRange):
                    self.ranges.append(r)
                elif isinstance(r, str):
                    self.ranges.extend(self._parse_version_spec(r))
                elif isinstance(r, dict):
                    self.ranges.append(self._parse_range_dict(r))
    
    def _parse_version_spec(self, spec: str) -> list:
        """Parse a version specification string into VersionRange objects."""
        ranges = []
        
        # Handle comma-separated ranges - these should be combined into a single range
        parts = [part.strip() for part in spec.split(',') if part.strip()]
        
        if len(parts) == 1:
            # Single constraint
            part = parts[0]
            match = re.match(r'^(>=|<=|>|<|==)\s*(.+)$', part)
            if match:
                op, ver = match.groups()
                if op == '>=':
                    ranges.append(VersionRange(min_version=ver, include_min=True))
                elif op == '>':
                    ranges.append(VersionRange(min_version=ver, include_min=False))
                elif op == '<=':
                    ranges.append(VersionRange(max_version=ver, include_max=True))
                elif op == '<':
                    ranges.append(VersionRange(max_version=ver, include_max=False))
                elif op == '==':
                    ranges.append(VersionRange(min_version=ver, max_version=ver, 
                                             include_min=True, include_max=True))
            else:
                # Assume exact version match
                ranges.append(VersionRange(min_version=part, max_version=part,
                                         include_min=True, include_max=True))
        else:
            # Multiple constraints - combine into single range
            min_version = None
            max_version = None
            include_min = True
            include_max = True
            
            for part in parts:
                match = re.match(r'^(>=|<=|>|<|==)\s*(.+)$', part)
                if match:
                    op, ver = match.groups()
                    if op in ['>=', '>']:
                        min_version = ver
                        include_min = (op == '>=')
                    elif op in ['<=', '<']:
                        max_version = ver
                        include_max = (op == '<=')
                    elif op == '==':
                        min_version = max_version = ver
                        include_min = include_max = True
            
            ranges.append(VersionRange(min_version, max_version, include_min, include_max))
        
        return ranges
    
    def _parse_range_dict(self, range_dict: dict) -> VersionRange:
        """Parse a range dictionary into a VersionRange object."""
        return VersionRange(
            min_version=range_dict.get('min_version'),
            max_version=range_dict.get('max_version'),
            include_min=range_dict.get('include_min', True),
            include_max=range_dict.get('include_max', True)
        )
    
    def contains(self, target_version: str) -> bool:
        """Check if a version is within any of the ranges in this set."""
        if not self.ranges:
            return True  # Empty set means all versions are supported
        
        return any(r.contains(target_version) for r in self.ranges)
    
    def __str__(self):
        if not self.ranges:
            return "any version"
        return " OR ".join(str(r) for r in self.ranges)


class VersionChecker:
    """Utility class for checking version compatibility."""
    
    @staticmethod
    def parse_supported_versions(supported_versions) -> VersionSet:
        """
        Parse supported versions specification into a VersionSet.
        
        Args:
            supported_versions: Can be:
                - None: All versions supported
                - str: Version specification string (e.g., ">=1.0.0,<=2.0.0")
                - list: List of version specs or range dicts
                - dict: Single range dict with min_version/max_version
        
        Returns:
            VersionSet: Parsed version set
        """
        if supported_versions is None:
            return VersionSet()  # All versions supported
        
        if isinstance(supported_versions, str):
            return VersionSet([supported_versions])
        
        if isinstance(supported_versions, list):
            return VersionSet(supported_versions)
        
        if isinstance(supported_versions, dict):
            return VersionSet([supported_versions])
        
        logger(f"Unknown supported_versions format: {type(supported_versions)}")
        return VersionSet()  # Default to all versions supported
    
    @staticmethod
    def is_version_supported(component_supported_versions, framework_version: str) -> bool:
        """
        Check if a framework version is supported by a component.
        
        Args:
            component_supported_versions: Component's supported versions specification
            framework_version: Current framework version
            
        Returns:
            bool: True if version is supported
        """
        try:
            version_set = VersionChecker.parse_supported_versions(component_supported_versions)
            return version_set.contains(framework_version)
        except Exception as e:
            logger(f"Error checking version compatibility: {e}")
            return True  # Default to supported on error
    
    @staticmethod
    def get_version_compatibility_message(component_name: str, component_supported_versions, 
                                        framework_version: str) -> str:
        """
        Get a human-readable message about version compatibility.
        
        Args:
            component_name: Name of the component
            component_supported_versions: Component's supported versions specification
            framework_version: Current framework version
            
        Returns:
            str: Compatibility message
        """
        try:
            version_set = VersionChecker.parse_supported_versions(component_supported_versions)
            
            if version_set.contains(framework_version):
                return f"Component '{component_name}' is compatible with framework version {framework_version}"
            else:
                return (f"Component '{component_name}' requires framework version {version_set}, "
                       f"but current version is {framework_version}")
        except Exception as e:
            logger(f"Error generating compatibility message: {e}")
            return f"Unable to determine version compatibility for component '{component_name}'"