"""Output validator — HARD/SOFT validation with FACTS integration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional

from agent.facts import Facts


DESTRUCTIVE_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+\*",
    r"mkfs\.",
    r"dd\s+if=.*of=/dev/",
    r">\s*/dev/sd",
    r"DROP\s+DATABASE",
    r"DROP\s+TABLE",
    r"TRUNCATE\s+",
    r"chmod\s+-R\s+777\s+/",
    r":(){ :\|:& };:",
]

SOFT_WARNING_PATTERNS = [
    (r"\brm\b", "Deletion detected — consider confirming with user first"),
    (r"git\s+push\s+--force", "Force push detected — risky operation"),
    (r"sudo\s+", "sudo usage detected — verify necessity"),
]


@dataclass
class ValidationResult:
    valid: bool
    severity: str = "none"  # "none", "hard", "soft"
    reason: str = ""
    can_retry: bool = True
    warnings: list[str] = field(default_factory=list)


class OutputValidator:
    def __init__(self, facts: Optional[Facts] = None):
        self.facts = facts

    def validate_tool_call(
        self,
        name: str,
        arguments: dict,
        workspace: str,
    ) -> ValidationResult:
        """Validate a single tool call. Returns ValidationResult."""
        warnings = []

        # --- HARD: Path safety ---
        path_args = []
        if name in ("read_file", "write_file", "edit_file"):
            path_args.append(arguments.get("path", ""))
        if name == "glob":
            path_args.append(arguments.get("path", "."))
        if name == "grep":
            path_args.append(arguments.get("path", "."))

        for p in path_args:
            if not self._is_safe_path(p, workspace):
                return ValidationResult(
                    valid=False,
                    severity="hard",
                    reason=f"Path traversal blocked: {p} is outside workspace {workspace}",
                    can_retry=False,
                )

        # --- HARD: Destructive commands ---
        if name == "bash":
            cmd = arguments.get("command", "")
            for pattern in DESTRUCTIVE_PATTERNS:
                if re.search(pattern, cmd, re.IGNORECASE):
                    return ValidationResult(
                        valid=False,
                        severity="hard",
                        reason=f"Destructive command blocked: matches '{pattern}'",
                        can_retry=False,
                    )

        # --- HARD: INWARIANTY ---
        if self.facts and self.facts.inwarianty:
            inv_result = self._check_inwarianty(name, arguments, workspace)
            if inv_result:
                return inv_result

        # --- SOFT: OGRANICZENIA ---
        if name == "bash":
            cmd = arguments.get("command", "")
            for pattern, msg in SOFT_WARNING_PATTERNS:
                if re.search(pattern, cmd, re.IGNORECASE):
                    warnings.append(msg)

        if self.facts and self.facts.ograniczenia:
            soft_warnings = self._check_ograniczenia(name, arguments)
            warnings.extend(soft_warnings)

        return ValidationResult(valid=True, warnings=warnings)

    def _is_safe_path(self, path: str, workspace: str) -> bool:
        """Check if path is within workspace or is relative."""
        if not path:
            return True
        p = PurePosixPath(path)
        # Relative paths are OK (resolved against workspace by claw_bridge)
        if not p.is_absolute():
            return True
        # Absolute paths must be under workspace
        try:
            PurePosixPath(path).relative_to(workspace)
            return True
        except ValueError:
            return False

    def _check_inwarianty(
        self, name: str, arguments: dict, workspace: str
    ) -> Optional[ValidationResult]:
        """Check HARD constraints from INWARIANTY section."""
        for inv in self.facts.inwarianty:
            inv_lower = inv.lower()

            # "nie modyfikuj plików poza workspace/"
            if "poza workspace" in inv_lower and name in ("write_file", "edit_file"):
                path = arguments.get("path", "")
                if path and PurePosixPath(path).is_absolute():
                    if not self._is_safe_path(path, workspace):
                        return ValidationResult(
                            valid=False,
                            severity="hard",
                            reason=f"INWARIANT violation: {inv}",
                            can_retry=False,
                        )

            # "nie uruchamiaj rm -rf"
            if "rm -rf" in inv_lower and name == "bash":
                cmd = arguments.get("command", "")
                if "rm -rf" in cmd or "rm -r " in cmd:
                    return ValidationResult(
                        valid=False,
                        severity="hard",
                        reason=f"INWARIANT violation: {inv}",
                        can_retry=False,
                    )

        return None

    def _check_ograniczenia(self, name: str, arguments: dict) -> list[str]:
        """Check SOFT constraints from OGRANICZENIA section. Returns warnings."""
        warnings = []
        for ogr in self.facts.ograniczenia:
            ogr_lower = ogr.lower()

            if "nie usuwaj" in ogr_lower and name == "bash":
                cmd = arguments.get("command", "")
                if re.search(r"\brm\b", cmd):
                    warnings.append(f"OGRANICZENIE: {ogr}")

            if "nie zgaduj" in ogr_lower and "ścieżek" in ogr_lower:
                # This is checked at a higher level (agent should read before edit)
                pass

        return warnings
