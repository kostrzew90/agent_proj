import tiktoken
from dataclasses import dataclass

# cl100k_base works for most models as a reasonable approximation
_encoder = tiktoken.get_encoding("cl100k_base")

# Token budget (safe for 32K context window)
BUDGET = {
    "system": 1000,
    "skill": 800,
    "memory": 2000,
    "code": 3000,
    "history": 2000,
    "response": 4000,
}
TOTAL_BUDGET = sum(BUDGET.values())  # 12800


def count_tokens(text: str) -> int:
    """Count tokens in a string."""
    return len(_encoder.encode(text))


def count_messages_tokens(messages: list[dict]) -> int:
    """Count total tokens across a list of messages."""
    total = 0
    for msg in messages:
        total += count_tokens(msg.get("content", "") or "")
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                total += count_tokens(str(tc))
    return total


@dataclass
class ComposedContext:
    system_prompt: str
    messages: list[dict]
    total_tokens: int


SYSTEM_PROMPT = """You are Selfmadeagent, a self-hosted AI coding assistant.

You have access to these tools:
- read_file(path): Read file contents
- write_file(path, content): Write to a file
- edit_file(path, old_string, new_string): Edit a file
- bash(command, timeout): Run a shell command
- glob(pattern, path): Find files by pattern
- grep(pattern, path): Search file contents

Rules:
- Read files before editing them
- Use bash for system commands
- Be concise in responses
- If a task is unclear, ask for clarification
"""


def compose_context(
    history: list[dict],
    skill_text: str | None = None,
    memory_text: str | None = None,
    facts_text: str | None = None,
) -> ComposedContext:
    """Compose the final prompt within token budget.

    Priority order when over budget:
    1. System prompt (always included)
    2. Most recent messages (always included, at least last 2)
    3. Skill (if active)
    4. Memory context
    5. Older history (trimmed first)
    """
    system = SYSTEM_PROMPT

    # Inject FACTS (guardrails) — always first after system
    if facts_text:
        facts_tokens = count_tokens(facts_text)
        if facts_tokens <= 500:  # FACTS should be short
            system += f"\n\n## Workspace Rules\n{facts_text}"

    # Inject skill and memory into system prompt
    if skill_text:
        skill_tokens = count_tokens(skill_text)
        if skill_tokens <= BUDGET["skill"]:
            system += f"\n\n## Active Skill\n{skill_text}"

    if memory_text:
        mem_tokens = count_tokens(memory_text)
        if mem_tokens <= BUDGET["memory"]:
            system += f"\n\n## Relevant Context\n{memory_text}"

    system_tokens = count_tokens(system)
    available = TOTAL_BUDGET - system_tokens - BUDGET["response"]

    # Trim history from oldest to fit budget
    trimmed = []
    running = 0
    for msg in reversed(history):
        msg_tokens = count_tokens(msg.get("content", "") or "")
        if running + msg_tokens > available:
            break
        trimmed.insert(0, msg)
        running += msg_tokens

    # Always keep at least the last message
    if not trimmed and history:
        trimmed = [history[-1]]
        running = count_tokens(history[-1].get("content", "") or "")

    messages = [{"role": "system", "content": system}] + trimmed

    return ComposedContext(
        system_prompt=system,
        messages=messages,
        total_tokens=system_tokens + running,
    )
