"""
Tests for built-in CLI tools: run_command, read_file, write_file.
Offline — no LlamaFarm required.
"""

import pytest
from openhoof.builtin_tools.cli import run_command, read_file, write_file
from openhoof import get_builtin_tool_schemas


class MockAgent:
    """Minimal agent stub for testing CLI tools."""
    def __init__(self, workspace):
        self.workspace = str(workspace)


# ── run_command ───────────────────────────────────────────────────────────────

def test_run_command_success(tmp_path):
    agent = MockAgent(tmp_path)
    result = run_command(agent, "echo hello")
    assert result["success"] is True
    assert result["returncode"] == 0
    assert "hello" in result["output"]
    assert result["cmd"] == "echo hello"


def test_run_command_returncode_on_failure(tmp_path):
    agent = MockAgent(tmp_path)
    result = run_command(agent, "ls /nonexistent_path_xyz_abc")
    assert result["success"] is False
    assert result["returncode"] != 0


def test_run_command_captures_stderr(tmp_path):
    agent = MockAgent(tmp_path)
    result = run_command(agent, "ls /nonexistent_path_xyz_abc")
    assert result["error"] != "" or result["returncode"] != 0


def test_run_command_shell_mode_pipe(tmp_path):
    agent = MockAgent(tmp_path)
    result = run_command(agent, "echo hello world | tr '[:lower:]' '[:upper:]'", shell=True)
    assert result["success"] is True
    assert "HELLO" in result["output"]


def test_run_command_with_cwd(tmp_path):
    agent = MockAgent(tmp_path)
    result = run_command(agent, "pwd", cwd=str(tmp_path))
    assert result["success"] is True
    assert str(tmp_path) in result["output"]


def test_run_command_timeout(tmp_path):
    agent = MockAgent(tmp_path)
    result = run_command(agent, "sleep 10", timeout=1)
    assert result["success"] is False
    assert "timed out" in result["error"].lower()


def test_run_command_not_found(tmp_path):
    agent = MockAgent(tmp_path)
    result = run_command(agent, "nonexistent_command_xyz_123")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_run_command_truncates_long_output(tmp_path):
    agent = MockAgent(tmp_path)
    # Generate very long output
    result = run_command(agent, "python3 -c \"print('x' * 10000)\"")
    assert result["success"] is True
    assert len(result["output"]) <= 5000   # well under raw 10k
    assert result["truncated"] is True


def test_run_command_short_output_not_truncated(tmp_path):
    agent = MockAgent(tmp_path)
    result = run_command(agent, "echo short")
    assert result["truncated"] is False


# ── read_file ─────────────────────────────────────────────────────────────────

def test_read_file_success(tmp_path):
    agent = MockAgent(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("line1\nline2\nline3\n")

    result = read_file(agent, str(f))
    assert result["success"] is True
    assert "line1" in result["content"]
    assert result["total_lines"] == 3
    assert result["truncated"] is False


def test_read_file_max_lines(tmp_path):
    agent = MockAgent(tmp_path)
    f = tmp_path / "big.txt"
    f.write_text("\n".join(f"line{i}" for i in range(500)))

    result = read_file(agent, str(f), max_lines=10)
    assert result["success"] is True
    assert result["returned_lines"] == 10
    assert result["truncated"] is True
    assert result["total_lines"] == 500


def test_read_file_offset_pagination(tmp_path):
    agent = MockAgent(tmp_path)
    f = tmp_path / "paged.txt"
    f.write_text("\n".join(f"line{i}" for i in range(100)))

    page1 = read_file(agent, str(f), max_lines=10, offset=0)
    page2 = read_file(agent, str(f), max_lines=10, offset=10)

    assert "line0" in page1["content"]
    assert "line10" in page2["content"]
    assert "line0" not in page2["content"]


def test_read_file_not_found(tmp_path):
    agent = MockAgent(tmp_path)
    result = read_file(agent, "/nonexistent/file.txt")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_read_file_relative_path(tmp_path):
    agent = MockAgent(tmp_path)
    (tmp_path / "relative.txt").write_text("relative content")
    result = read_file(agent, "relative.txt")
    assert result["success"] is True
    assert "relative content" in result["content"]


# ── write_file ────────────────────────────────────────────────────────────────

def test_write_file_creates_file(tmp_path):
    agent = MockAgent(tmp_path)
    result = write_file(agent, str(tmp_path / "new.txt"), "hello world")
    assert result["success"] is True
    assert (tmp_path / "new.txt").read_text() == "hello world"


def test_write_file_overwrites_by_default(tmp_path):
    agent = MockAgent(tmp_path)
    f = tmp_path / "over.txt"
    f.write_text("old content")
    write_file(agent, str(f), "new content")
    assert f.read_text() == "new content"


def test_write_file_append_mode(tmp_path):
    agent = MockAgent(tmp_path)
    f = tmp_path / "append.txt"
    write_file(agent, str(f), "line1\n")
    write_file(agent, str(f), "line2\n", append=True)
    assert f.read_text() == "line1\nline2\n"


def test_write_file_creates_parent_dirs(tmp_path):
    agent = MockAgent(tmp_path)
    deep = tmp_path / "a" / "b" / "c" / "file.txt"
    result = write_file(agent, str(deep), "deep content")
    assert result["success"] is True
    assert deep.read_text() == "deep content"


def test_write_file_relative_path(tmp_path):
    agent = MockAgent(tmp_path)
    result = write_file(agent, "output/result.txt", "output data")
    assert result["success"] is True
    assert (tmp_path / "output" / "result.txt").read_text() == "output data"


def test_write_file_reports_bytes(tmp_path):
    agent = MockAgent(tmp_path)
    content = "hello"
    result = write_file(agent, str(tmp_path / "f.txt"), content)
    assert result["bytes_written"] == len(content.encode())


# ── schema registration ───────────────────────────────────────────────────────

def test_cli_tools_in_builtin_schemas():
    schemas = get_builtin_tool_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "run_command" in names
    assert "read_file" in names
    assert "write_file" in names


def test_run_command_schema_has_required_fields():
    schemas = get_builtin_tool_schemas()
    schema = next(s for s in schemas if s["function"]["name"] == "run_command")
    params = schema["function"]["parameters"]
    assert "cmd" in params["required"]
    assert "timeout" in params["properties"]
    assert "shell" in params["properties"]
    assert "cwd" in params["properties"]


# ── shell_exec ────────────────────────────────────────────────────────────────

def test_shell_exec_basic(tmp_path):
    from openhoof.builtin_tools.cli import shell_exec
    agent = MockAgent(tmp_path)
    result = shell_exec(agent, "echo hello")
    assert result["success"] is True
    assert "hello" in result["output"]


def test_shell_exec_pipe(tmp_path):
    from openhoof.builtin_tools.cli import shell_exec
    agent = MockAgent(tmp_path)
    result = shell_exec(agent, "echo 'hello world' | tr '[:lower:]' '[:upper:]'")
    assert result["success"] is True
    assert "HELLO" in result["output"]


def test_shell_exec_in_schemas():
    schemas = get_builtin_tool_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "shell_exec" in names


# ── http_request ──────────────────────────────────────────────────────────────

def test_http_request_in_schemas():
    schemas = get_builtin_tool_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "http_request" in names


def test_http_request_schema_required_fields():
    from openhoof import get_builtin_tool_schemas
    schemas = get_builtin_tool_schemas()
    schema = next(s for s in schemas if s["function"]["name"] == "http_request")
    assert "url" in schema["function"]["parameters"]["required"]
    assert "method" in schema["function"]["parameters"]["properties"]
    assert "body" in schema["function"]["parameters"]["properties"]


def test_http_request_no_requests_lib(tmp_path, monkeypatch):
    """Graceful error when requests is not installed."""
    from openhoof.builtin_tools import http_tools
    monkeypatch.setattr(http_tools, "HAVE_REQUESTS", False)
    agent = MockAgent(tmp_path)
    result = http_tools.http_request(agent, url="http://example.com")
    assert result["success"] is False
    assert "requests" in result["error"].lower()


def test_http_request_total_schema_count():
    """15 built-in schemas total (smoke test)."""
    schemas = get_builtin_tool_schemas()
    assert len(schemas) == 15
