"""Tier 1: Working memory — current session state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WorkingMemory:
    """In-session memory: goal, recent steps, active files."""
    session_id: str
    goal: Optional[str] = None
    steps: list[dict] = field(default_factory=list)
    active_files: set[str] = field(default_factory=set)
    pending_questions: list[str] = field(default_factory=list)

    MAX_STEPS = 10

    def add_step(self, action: str, result_summary: str, score: float = 1.0):
        self.steps.append({
            "action": action,
            "result": result_summary,
            "score": score,
        })
        # Keep only last MAX_STEPS
        if len(self.steps) > self.MAX_STEPS:
            self.steps = self.steps[-self.MAX_STEPS:]

    def add_active_file(self, path: str):
        self.active_files.add(path)

    def get_relevant(self, query: str) -> str:
        """Format working memory as context string."""
        parts = []
        if self.goal:
            parts.append(f"Current goal: {self.goal}")
        if self.active_files:
            parts.append(f"Active files: {', '.join(sorted(self.active_files))}")
        if self.steps:
            recent = self.steps[-5:]
            steps_text = "\n".join(
                f"  - {s['action']}: {s['result'][:100]}" for s in recent
            )
            parts.append(f"Recent steps:\n{steps_text}")
        return "\n".join(parts) if parts else ""

    def to_summary(self) -> str:
        """Generate session summary for Tier 2 flush."""
        parts = [f"Goal: {self.goal or 'unset'}"]
        parts.append(f"Steps taken: {len(self.steps)}")
        parts.append(f"Files touched: {', '.join(sorted(self.active_files)) or 'none'}")
        if self.steps:
            successes = sum(1 for s in self.steps if s.get("score", 0) >= 0.7)
            parts.append(f"Success rate: {successes}/{len(self.steps)}")
        return "\n".join(parts)
