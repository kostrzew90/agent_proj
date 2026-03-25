"""Plugin installer — clone from git into vendor directory."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

import yaml

from ai_repo.config import settings

logger = logging.getLogger(__name__)


class PluginInstaller:
    """Install plugins from git repositories into _vendor/."""

    def __init__(self):
        self.vendor_dir = settings.project_root / settings.plugins.vendor_directory

    def install(self, git_url: str, ref: str = "main") -> str:
        """Clone a plugin from git into _vendor/<name>/<ref>/.

        Args:
            git_url: Git repository URL.
            ref: Branch or tag to checkout.

        Returns:
            Plugin name from manifest.

        Raises:
            ValueError: If manifest is invalid.
            RuntimeError: If git clone fails.
        """
        import git

        # Create temp clone
        tmp_dir = self.vendor_dir / "_tmp_install"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)

        try:
            logger.info(f"Cloning {git_url} (ref={ref})")
            repo = git.Repo.clone_from(git_url, str(tmp_dir), branch=ref, depth=1)

            # Validate manifest
            manifest_path = tmp_dir / "plugin.yaml"
            if not manifest_path.exists():
                raise ValueError("Plugin missing plugin.yaml manifest")

            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = yaml.safe_load(f) or {}

            name = manifest.get("name")
            if not name:
                raise ValueError("plugin.yaml missing 'name' field")

            # Compute checksum of manifest
            checksum = hashlib.sha256(manifest_path.read_bytes()).hexdigest()[:12]

            # Move to final location
            target_dir = self.vendor_dir / name / ref
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_dir), str(target_dir))

            # Remove .git directory from installed plugin
            git_dir = target_dir / ".git"
            if git_dir.exists():
                shutil.rmtree(git_dir)

            logger.info(f"Installed plugin '{name}' at {target_dir} (checksum: {checksum})")
            return name

        finally:
            # Cleanup temp
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
