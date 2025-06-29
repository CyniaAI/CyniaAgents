import importlib
import importlib.util
import ast
import json
import os
import pkgutil
import sys

from log_writer import logger

from component_base import BaseComponent, PlaceholderComponent


class ComponentManager:
    def __init__(self, components_dir="components", config_path="components.json"):
        self.components_dir = components_dir
        self.config_path = config_path
        self.available = {}
        self.enabled = []
        self.load_config()
        self.discover_components()

    @staticmethod
    def missing_requirements(requirements: list[str]) -> list[str]:
        """Return a list of packages that are not installed."""
        missing = []
        for req in requirements:
            try:
                importlib.import_module(req)
            except ImportError:
                missing.append(req)
        return missing

    @staticmethod
    def _read_requirements_file(req_path: str) -> list[str]:
        """Return package names listed in a requirements.txt file."""
        requirements: list[str] = []
        if os.path.isfile(req_path):
            try:
                with open(req_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            requirements.append(line)
            except Exception as e:
                logger(f"Failed to read requirements from {req_path}: {e}")
        return requirements

    @staticmethod
    def _extract_metadata(path: str, req_file: str | None = None) -> dict:
        """Parse component file for class metadata without importing."""
        meta: dict = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
        except Exception as e:
            logger(f"Failed to parse {path} for metadata: {e}")
            return meta

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "BaseComponent":
                        for stmt in node.body:
                            if (
                                isinstance(stmt, ast.Assign)
                                and len(stmt.targets) == 1
                                and isinstance(stmt.targets[0], ast.Name)
                            ):
                                key = stmt.targets[0].id
                                if key in {"name", "description"} and isinstance(
                                    stmt.value, (ast.Str, ast.Constant)
                                ):
                                    meta[key] = (
                                        stmt.value.s
                                        if hasattr(stmt.value, "s")
                                        else stmt.value.value
                                    )
                                elif key == "requirements" and isinstance(
                                    stmt.value, (ast.List, ast.Tuple)
                                ):
                                    reqs = []
                                    for elt in stmt.value.elts:
                                        if isinstance(elt, (ast.Str, ast.Constant)):
                                            reqs.append(
                                                elt.s if hasattr(elt, "s") else elt.value
                                            )
                                    meta[key] = reqs
                        break

        # Append requirements.txt content if provided
        if req_file:
            meta.setdefault("requirements", [])
            meta["requirements"] += ComponentManager._read_requirements_file(req_file)

        return meta

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.enabled = data.get("enabled", [])
        else:
            self.enabled = []

    def save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"enabled": self.enabled}, f, indent=2)

    def discover_components(self):
        self.available = {}
        if not os.path.isdir(self.components_dir):
            return
        package_name = self.components_dir.replace(os.sep, ".")
        # Discover regular modules and packages first
        for _, name, ispkg in pkgutil.iter_modules([self.components_dir]):
            if ispkg:
                module_path = os.path.join(self.components_dir, name, "__init__.py")
                req_path = os.path.join(self.components_dir, name, "requirements.txt")
            else:
                module_path = os.path.join(self.components_dir, f"{name}.py")
                req_path = None
            try:
                module = importlib.import_module(f"{package_name}.{name}")
            except Exception as e:
                logger(f"Failed to import module {name}: {e}")
                meta = (
                    self._extract_metadata(module_path, req_path)
                    if os.path.isfile(module_path)
                    else {}
                )
                reqs = meta.get("requirements")
                if reqs is None and req_path:
                    reqs = self._read_requirements_file(req_path)
                comp = PlaceholderComponent(
                    meta.get("name", name),
                    meta.get("description", ""),
                    reqs or [],
                )
                self.available[comp.name] = comp
                continue

            if hasattr(module, "get_component"):
                try:
                    comp = module.get_component()
                    if isinstance(comp, BaseComponent):
                        self.available[comp.name] = comp
                except Exception as e:
                    logger(f"Failed to load component from module {name}: {e}")

        # Also support components stored in a directory without __init__.py
        for entry in os.scandir(self.components_dir):
            if entry.is_dir() and not os.path.exists(
                os.path.join(entry.path, "__init__.py")
            ):
                main_py = os.path.join(entry.path, "main.py")
                if not os.path.isfile(main_py):
                    continue
                spec = importlib.util.spec_from_file_location(
                    f"{package_name}.{entry.name}", main_py
                )
                if not spec or not spec.loader:
                    continue
                module = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(module)
                except Exception as e:
                    logger(f"Failed to import module {entry.name} from main.py: {e}")
                    req_file = os.path.join(entry.path, "requirements.txt")
                    meta = (
                        self._extract_metadata(main_py, req_file)
                        if os.path.isfile(main_py)
                        else {}
                    )
                    reqs = meta.get("requirements")
                    if reqs is None:
                        reqs = self._read_requirements_file(req_file)
                    comp = PlaceholderComponent(
                        meta.get("name", entry.name),
                        meta.get("description", ""),
                        reqs or [],
                    )
                    self.available[comp.name] = comp
                    continue

                if hasattr(module, "get_component"):
                    try:
                        comp = module.get_component()
                        if isinstance(comp, BaseComponent):
                            self.available[comp.name] = comp
                    except Exception as e:
                        logger(f"Failed to load component from module {entry.name}: {e}")

    def get_enabled_components(self):
        return [c for c in self.available.values() if c.name in self.enabled]
