"""FACTS.md loader — per-workspace guardrails for the agent."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Facts:
    """Parsed FACTS.md sections."""
    fakty: list[str] = field(default_factory=list)
    ograniczenia: list[str] = field(default_factory=list)
    inwarianty: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str) -> Facts:
        """Parse FACTS.md content into structured sections."""
        facts = cls()
        current_section = None

        for line in text.splitlines():
            stripped = line.strip()

            # Detect section headers
            header = stripped.lstrip("#").strip().upper()
            if header == "FAKTY":
                current_section = "fakty"
                continue
            elif header == "OGRANICZENIA":
                current_section = "ograniczenia"
                continue
            elif header == "INWARIANTY":
                current_section = "inwarianty"
                continue

            # Parse bullet items
            if current_section and stripped.startswith("- "):
                item = stripped[2:].strip()
                if item:
                    getattr(facts, current_section).append(item)

        return facts

    def to_prompt(self) -> str:
        """Format as prompt text for system message injection."""
        parts = []
        if self.fakty:
            parts.append("## FAKTY\n" + "\n".join(f"- {f}" for f in self.fakty))
        if self.ograniczenia:
            parts.append("## OGRANICZENIA (soft — warnings)\n" + "\n".join(f"- {o}" for o in self.ograniczenia))
        if self.inwarianty:
            parts.append("## INWARIANTY (hard — must not violate)\n" + "\n".join(f"- {i}" for i in self.inwarianty))
        return "\n\n".join(parts)


def load_facts(workspace_path: str) -> Optional[Facts]:
    """Load FACTS.md from workspace. Returns None if not found."""
    facts_path = Path(workspace_path) / "FACTS.md"
    if not facts_path.exists():
        return None
    text = facts_path.read_text(encoding="utf-8")
    return Facts.parse(text)
