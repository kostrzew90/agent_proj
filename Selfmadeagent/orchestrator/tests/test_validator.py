import pytest
from agent.validator import OutputValidator, ValidationResult
from agent.facts import Facts
from agent.retry_budget import RetryBudget


def make_validator(facts_text=""):
    facts = Facts.parse(facts_text) if facts_text else None
    return OutputValidator(facts=facts)


def test_valid_tool_call():
    v = make_validator()
    result = v.validate_tool_call(
        name="read_file",
        arguments={"path": "src/main.py"},
        workspace="/workspace",
    )
    assert result.valid


def test_path_traversal_blocked():
    v = make_validator()
    result = v.validate_tool_call(
        name="read_file",
        arguments={"path": "/etc/passwd"},
        workspace="/workspace",
    )
    assert not result.valid
    assert result.severity == "hard"
    assert "path" in result.reason.lower()


def test_destructive_command_blocked():
    v = make_validator()
    result = v.validate_tool_call(
        name="bash",
        arguments={"command": "rm -rf /"},
        workspace="/workspace",
    )
    assert not result.valid
    assert result.severity == "hard"


def test_inwariant_violation():
    v = make_validator("# INWARIANTY\n- nie modyfikuj plików poza workspace/")
    result = v.validate_tool_call(
        name="write_file",
        arguments={"path": "/tmp/outside.txt", "content": "hack"},
        workspace="/workspace",
    )
    assert not result.valid
    assert result.severity == "hard"


def test_ograniczenie_warning():
    v = make_validator("# OGRANICZENIA\n- nie usuwaj plików bez potwierdzenia")
    result = v.validate_tool_call(
        name="bash",
        arguments={"command": "rm important.txt"},
        workspace="/workspace",
    )
    # SOFT: still valid but with warnings
    assert result.valid
    assert len(result.warnings) > 0


def test_safe_command_passes():
    v = make_validator()
    result = v.validate_tool_call(
        name="bash",
        arguments={"command": "ls -la"},
        workspace="/workspace",
    )
    assert result.valid
    assert len(result.warnings) == 0
