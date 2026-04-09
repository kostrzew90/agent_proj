from agent.evaluator import heuristic_evaluate


def test_bash_success():
    score = heuristic_evaluate("bash", {"command": "ls"}, "file1.py\nfile2.py")
    assert score == 1.0


def test_bash_failure():
    score = heuristic_evaluate("bash", {"command": "invalid_cmd"}, "command not found\nExit code: 127")
    assert score == 0.3


def test_read_file_ok():
    score = heuristic_evaluate("read_file", {"path": "x.py"}, "def hello(): pass")
    assert score == 1.0


def test_read_file_empty():
    score = heuristic_evaluate("read_file", {"path": "x.py"}, "")
    assert score == 0.5


def test_write_file_ok():
    score = heuristic_evaluate("write_file", {"path": "x.py"}, "Written 42 bytes")
    assert score == 1.0


def test_tool_error():
    score = heuristic_evaluate("read_file", {"path": "x.py"}, "Tool error (read_file): File not found")
    assert score == 0.0
