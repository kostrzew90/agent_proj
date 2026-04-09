"""Per-session retry budget — prevents infinite retry loops."""

from dataclasses import dataclass


@dataclass
class RetryBudget:
    max_per_action: int = 3
    max_per_session: int = 15
    _action_count: int = 0
    _session_count: int = 0

    @property
    def action_remaining(self) -> int:
        return self.max_per_action - self._action_count

    @property
    def session_remaining(self) -> int:
        return self.max_per_session - self._session_count

    def can_retry(self) -> bool:
        return self._action_count < self.max_per_action and self._session_count < self.max_per_session

    def consume(self):
        self._action_count += 1
        self._session_count += 1

    def reset_action(self):
        self._action_count = 0

    def status(self) -> dict:
        return {
            "action": f"{self.action_remaining}/{self.max_per_action}",
            "session": f"{self.session_remaining}/{self.max_per_session}",
        }
