"""Plugin sandbox — permission checking based on manifest + config allowlist."""

from __future__ import annotations

import logging

from ai_repo.config import settings

logger = logging.getLogger(__name__)


class PluginSandbox:
    """Check plugin permissions against configured allowlist and manifest."""

    def __init__(self):
        self.allowlist = set(settings.plugins.allowlist)
        self.allow_network = settings.plugins.allow_network

    def is_allowed(self, plugin_name: str) -> bool:
        """Check if a plugin is in the allowlist."""
        return plugin_name in self.allowlist

    def check_permissions(self, plugin_name: str, manifest: dict) -> list[str]:
        """Validate plugin permissions against config.

        Returns list of violations (empty if all OK).
        """
        violations: list[str] = []

        if not self.is_allowed(plugin_name):
            violations.append(f"Plugin '{plugin_name}' not in allowlist")

        # Check network permission
        plugin_needs_network = manifest.get("permissions", {}).get("network", False)
        if plugin_needs_network and not self.allow_network:
            violations.append(
                f"Plugin '{plugin_name}' requires network access but "
                f"PLUGIN_ALLOW_NETWORK is false"
            )

        # Check requested capabilities
        requested = set(manifest.get("permissions", {}).get("capabilities", []))
        dangerous = requested & {"exec", "file_write", "file_delete"}
        if dangerous:
            violations.append(
                f"Plugin '{plugin_name}' requests dangerous capabilities: "
                f"{', '.join(dangerous)}"
            )

        if violations:
            for v in violations:
                logger.warning(f"Sandbox violation: {v}")

        return violations
