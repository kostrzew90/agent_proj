"""Plugin loader — discovers and loads plugins from plugins/ and _vendor/."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from ai_repo.config import settings
from ai_repo.plugins.base import PluginBase, PluginContext

logger = logging.getLogger(__name__)


class PluginLoader:
    """Discover and load plugins from configured directories."""

    def __init__(self):
        root = settings.project_root
        self.plugin_dir = root / settings.plugins.directory
        self.vendor_dir = root / settings.plugins.vendor_directory
        self.allowlist = settings.plugins.allowlist

    def discover(self) -> list[dict[str, Any]]:
        """Scan plugin directories and return manifests for available plugins."""
        plugins: list[dict] = []

        for search_dir in [self.plugin_dir, self.vendor_dir]:
            if not search_dir.exists():
                continue

            for item in search_dir.iterdir():
                if not item.is_dir():
                    continue

                # Check for nested version directories (vendor installs)
                manifest_path = item / "plugin.yaml"
                if manifest_path.exists():
                    manifest = self._read_manifest(manifest_path)
                    if manifest:
                        manifest["_path"] = str(item)
                        plugins.append(manifest)
                else:
                    # Check subdirectories (for vendor/<name>/<ref>/)
                    for sub in item.iterdir():
                        if sub.is_dir():
                            sub_manifest = sub / "plugin.yaml"
                            if sub_manifest.exists():
                                manifest = self._read_manifest(sub_manifest)
                                if manifest:
                                    manifest["_path"] = str(sub)
                                    plugins.append(manifest)

        return plugins

    def load_all(self, db: Any = None, llm: Any = None) -> int:
        """Load all discovered plugins that are on the allowlist.

        Returns number of successfully loaded plugins.
        """
        from ai_repo.api.mcp.registry import ToolDefinition, registry

        def register_tool_callback(tool_def: ToolDefinition):
            registry.register(tool_def)

        context = PluginContext(
            db=db,
            llm=llm,
            register_tool=register_tool_callback,
        )

        plugins = self.discover()
        loaded = 0

        for manifest in plugins:
            name = manifest.get("name", "")
            if name not in self.allowlist:
                logger.debug(f"Plugin '{name}' not in allowlist, skipping")
                continue

            try:
                self._load_plugin(manifest, context)
                loaded += 1
                logger.info(f"Loaded plugin: {name}")
                if db:
                    try:
                        from ai_repo.core.metrics import emit_event
                        emit_event(db, "plugins", "info", f"Loaded {name}")
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Failed to load plugin '{name}': {e}")
                if db:
                    try:
                        from ai_repo.core.metrics import emit_event
                        emit_event(
                            db, "plugins", "error",
                            f"Failed to load {name}: {e}",
                            signature=name,
                        )
                    except Exception:
                        pass

        return loaded

    def _load_plugin(self, manifest: dict, context: PluginContext):
        """Import and register a single plugin."""
        plugin_path = Path(manifest["_path"])
        entrypoint = manifest.get("entrypoint", "__init__.py")

        module_file = plugin_path / entrypoint
        if not module_file.exists():
            raise FileNotFoundError(f"Entrypoint not found: {module_file}")

        # Dynamic import
        spec = importlib.util.spec_from_file_location(
            f"plugin_{manifest['name']}", str(module_file)
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {module_file}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find PluginBase subclass or register() function
        plugin_cls = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, PluginBase)
                and attr is not PluginBase
            ):
                plugin_cls = attr
                break

        if plugin_cls:
            instance = plugin_cls()
            tools = instance.register(context)
            if tools:
                from ai_repo.api.mcp.registry import ToolDefinition, registry
                for tool_name, handler in tools.items():
                    registry.register(ToolDefinition(
                        name=tool_name,
                        description=f"Plugin tool: {tool_name}",
                        input_schema={"type": "object"},
                        handler=handler,
                        source=manifest["name"],
                    ))
        elif hasattr(module, "register"):
            module.register(context)

    @staticmethod
    def _read_manifest(path: Path) -> dict | None:
        """Read and validate plugin.yaml."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if "name" not in data:
                logger.warning(f"Plugin manifest missing 'name': {path}")
                return None
            return data
        except Exception as e:
            logger.warning(f"Failed to read manifest {path}: {e}")
            return None
