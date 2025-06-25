import importlib
import json
import os
import pkgutil

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
        for _, name, _ in pkgutil.iter_modules([self.components_dir]):
            module = importlib.import_module(f"{package_name}.{name}")
            if hasattr(module, "get_component"):
                comp = module.get_component()
                if isinstance(comp, BaseComponent):
                    self.available[comp.name] = comp

    def get_enabled_components(self):
        return [c for c in self.available.values() if c.name in self.enabled]
