import importlib
import importlib.util
import json
import os
import pkgutil
import logging

from component_base import BaseComponent


class ComponentManager:
    def __init__(self, components_dir="components", config_path="components.json"):
        self.components_dir = components_dir
        self.config_path = config_path
        self.available = {}
        self.enabled = []
        self.load_config()
        self.discover_components()

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
        for _, name, _ in pkgutil.iter_modules([self.components_dir]):
            try:
                module = importlib.import_module(f"{package_name}.{name}")
            except Exception as e:
                logging.error(f"Failed to import module {name}: {e}")
                continue

            if hasattr(module, "get_component"):
                try:
                    comp = module.get_component()
                    if isinstance(comp, BaseComponent):
                        self.available[comp.name] = comp
                except Exception as e:
                    logging.error(
                        f"Failed to load component from module {name}: {e}", exc_info=True
                    )

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
                    logging.error(
                        f"Failed to import module {entry.name} from main.py: {e}"
                    )
                    continue

                if hasattr(module, "get_component"):
                    try:
                        comp = module.get_component()
                        if isinstance(comp, BaseComponent):
                            self.available[comp.name] = comp
                    except Exception as e:
                        logging.error(
                            f"Failed to load component from module {entry.name}: {e}"
                        )

    def get_enabled_components(self):
        return [c for c in self.available.values() if c.name in self.enabled]
