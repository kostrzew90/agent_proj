import importlib
import pkgutil
from pathlib import Path
from typing import Optional
import structlog

from plugins.base import SourcePlugin, SourceCategory

logger = structlog.get_logger()

PLUGIN_SUBDIRS = ["vin_decode", "registries", "damage", "osint_photo", "ads_archive"]


class PluginRegistry:
    def __init__(self):
        self.plugins: dict[str, SourcePlugin] = {}

    def discover(self):
        """Skanuj podkatalogi plugins/ i zarejestruj wszystkie klasy dziedziczące z SourcePlugin."""
        plugin_dir = Path(__file__).parent
        for subdir in PLUGIN_SUBDIRS:
            package = f"plugins.{subdir}"
            path = plugin_dir / subdir
            if not path.exists():
                continue
            for _, module_name, _ in pkgutil.iter_modules([str(path)]):
                try:
                    module = importlib.import_module(f"{package}.{module_name}")
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, SourcePlugin)
                            and attr is not SourcePlugin
                            and hasattr(attr, "name")
                        ):
                            instance = attr()
                            if not instance.requires_login:
                                self.plugins[instance.name] = instance
                                logger.info("plugin.registered", plugin=instance.name, category=instance.category.value)
                except Exception as e:
                    logger.error("plugin.discovery_error", module=module_name, error=str(e))

    def apply_db_config(self, db_configs: list[dict]):
        """Nadpisz enabled/settings z bazy danych.
        Kod pluginu ma priorytet: jeśli plugin ustawił enabled=False w klasie,
        DB nie może go włączyć z powrotem (np. CF-blocked pluginy).
        DB może tylko WYŁĄCZYĆ plugin który jest domyślnie włączony.
        """
        config_map = {c["name"]: c for c in db_configs}
        for name, plugin in self.plugins.items():
            if name in config_map:
                code_default = type(plugin).enabled if isinstance(type(plugin).enabled, bool) else True
                if not code_default:
                    plugin.enabled = False
                    logger.info("plugin.forced_disabled", plugin=name, reason="disabled in code")
                else:
                    plugin.enabled = config_map[name]["enabled"]

    def get_all(self) -> list[SourcePlugin]:
        return list(self.plugins.values())

    def get_enabled(self) -> list[SourcePlugin]:
        return [p for p in self.plugins.values() if p.enabled]

    def get_by_category(self, category: SourceCategory) -> list[SourcePlugin]:
        return [p for p in self.get_enabled() if p.category == category]

    def get(self, name: str) -> Optional[SourcePlugin]:
        return self.plugins.get(name)

    def set_enabled(self, name: str, enabled: bool):
        if name in self.plugins:
            self.plugins[name].enabled = enabled


plugin_registry = PluginRegistry()
