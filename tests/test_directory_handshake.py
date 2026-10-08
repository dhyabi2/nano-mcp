"""A directory must be able to START this server and introspect it, over stdio.

`tests/test_server_unconfigured.py` asks `server_from_env().list_tools()` in
process, and the `test` workflow's first-contact step does the same thing. Both
stand for a claim neither of them makes. A directory -- Glama, which
`punkpeye/awesome-mcp-servers` gates its listing on, or the official registry --
does not import this package. It runs the command the distribution installs,
writes JSON-RPC to that process's stdin and reads `tools/list` off its stdout.

Everything between `main()` and the wire is therefore untested by an in-process
call: the console script `pyproject.toml` declares, `main()` itself,
`server.run(transport="stdio")`, the framing of the replies, and whether
anything else gets printed on the stream a host parses as JSON-RPC. A break
anywhere in that span looks like a healthy server to the suite and like a dead
one to every directory -- which is the state the listing pull request has sat in
since 2026-10-02, labelled `missing-glama`.

So these laws run the real exchange, through `tools/directory_handshake.py` --
the same client the workflow points at the built image, so there is one
implementation rather than two spellings of it. The server is started as a
subprocess with `NANO_PAYMENT_MASTER_SECRET` scrubbed from its environment.
Nothing is mocked and nothing touches the network.
"""
from __future__ import annotations

import asyncio
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from nano_mcp.server import server_from_env

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools" / "directory_handshake.py"


def _load_probe():
    """Load the probe by path: `tools/` is not part of the distribution.

    The module has to be registered in `sys.modules` BEFORE it is executed.
    `@dataclass` looks its own class's module up there to resolve annotations, so
    an unregistered module makes the decorator raise `AttributeError: 'NoneType'
    object has no attribute '__dict__'` at import time -- a collection error
    whose text says nothing about the real cause.
    """
    name = "directory_handshake"
    spec = importlib.util.spec_from_file_location(name, PROBE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()

# The command the Dockerfile's CMD runs, and the one an MCP host puts in its
# config. Declared once here and asserted against the Dockerfile below.
CONSOLE_SCRIPT = "nano-mcp"


def test_the_module_entrypoint_completes_a_directorys_handshake():
    """`python -m nano_mcp.server`: the path that needs no console script."""
    result = probe.handshake([sys.executable, "-m", "nano_mcp.server"], timeout=120)
    assert result.ok, f"{result.problem}\n--- stderr ---\n{result.stderr}"
    assert result.returncode == 0, (
        "the server left a non-zero exit status behind after a clean exchange: "
        f"{result.returncode}\n--- stderr ---\n{result.stderr}"
    )
    assert "Traceback" not in result.stderr, (
        "the exchange completed but the server crashed on the way out:\n" + result.stderr
    )


def test_the_installed_console_script_completes_a_directorys_handshake():
    """The exact command the Dockerfile starts, as installed by pip."""
    found = shutil.which(CONSOLE_SCRIPT)
    if found is None:
        pytest.skip(
            f"{CONSOLE_SCRIPT!r} is not on PATH: this environment has the package "
            "importable but not installed, so the console script cannot be run here"
        )
    result = probe.handshake([found], timeout=120)
    assert result.ok, f"{result.problem}\n--- stderr ---\n{result.stderr}"
    assert result.returncode == 0, result.stderr


def test_the_wire_shows_exactly_what_the_code_exposes():
    """No hard-coded tool list: the subprocess answer must equal the server's own.

    A list written down here would have to be edited every time a tool is added,
    and the edit is what gets forgotten. Comparing the two sides instead pins the
    thing that actually matters -- that a tool the code exposes reaches the wire.
    """
    in_process = asyncio.run(server_from_env().list_tools())
    expected = {tool.name: (tool.description or "") for tool in in_process}

    result = probe.handshake([sys.executable, "-m", "nano_mcp.server"], timeout=120)
    assert result.ok, result.problem
    assert set(result.tools) == set(expected), (
        "the tools a directory sees are not the tools the server exposes; "
        f"only in process: {sorted(set(expected) - set(result.tools))}; "
        f"only on the wire: {sorted(set(result.tools) - set(expected))}"
    )
    for name, description in result.tools.items():
        assert description.strip(), f"{name} reaches a directory with no description"


def test_the_handshake_needs_no_secret():
    """The whole point of the gate: nothing is configured and it still answers."""
    result = probe.handshake(
        [sys.executable, "-m", "nano_mcp.server"],
        timeout=120,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
    )
    assert result.ok, f"an unconfigured server failed a directory: {result.problem}"
    assert result.tools, "unconfigured, the server lists nothing"


def test_a_secret_in_the_parent_environment_is_not_passed_to_the_server(tmp_path):
    """The scrub is real, so a developer's own shell cannot make this pass.

    Without it the suite would be green on a machine that exports the variable
    and red on the runner, and the gate being measured -- "starts with no
    configuration" -- would never actually be under test.
    """
    sentinel = "ab" * 32
    stub = tmp_path / "echo_env.py"
    stub.write_text(
        "import os, sys\n"
        "sys.stderr.write(repr(os.environ.get('NANO_PAYMENT_MASTER_SECRET')))\n"
    )
    result = probe.handshake(
        [sys.executable, str(stub)],
        timeout=60,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "NANO_PAYMENT_MASTER_SECRET": sentinel,
        },
    )
    # The stub is not a server, so the exchange cannot complete -- what is under
    # test is what reached its environment.
    assert not result.ok
    assert sentinel not in result.stderr, "the parent's secret reached the server"
    assert result.stderr.strip() == "None", (
        "the server should have seen no secret at all, it saw: " + result.stderr
    )


def test_the_dockerfile_starts_the_command_these_laws_proved():
    """The image may not drift onto an entrypoint nothing here exercises."""
    dockerfile = (ROOT / "Dockerfile").read_text()
    cmd_lines = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip().startswith("CMD")
    ]
    assert len(cmd_lines) == 1, f"expected exactly one CMD, found {cmd_lines}"
    assert cmd_lines[0] == f'CMD ["{CONSOLE_SCRIPT}"]', (
        "the Dockerfile starts something other than the console script the "
        f"handshake laws above run: {cmd_lines[0]}"
    )


def test_the_console_script_the_dockerfile_starts_is_the_one_declared():
    """And `pyproject.toml` must actually install that command."""
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert f'{CONSOLE_SCRIPT} = "nano_mcp.server:main"' in pyproject, (
        f"pyproject.toml no longer declares the {CONSOLE_SCRIPT!r} console script, "
        "so the Dockerfile's CMD would not exist in the image"
    )


def test_the_output_readers_are_joined_before_stderr_is_reported(monkeypatch):
    """`handshake` must not report a server's stderr while still reading it.

    This is the one law here that pins a mechanism rather than a behaviour, and
    it is deliberate: the behaviour cannot be tested honestly. `proc.wait()`
    returning says the CHILD has exited; it says nothing about the daemon thread
    still draining the child's stderr pipe into the list that becomes
    `result.stderr`. Reading that list without joining the thread loses whatever
    has not been appended yet -- **measured at 10 runs in 400** against a child
    that writes one line and exits at once, and more often under load.

    A behavioural law would therefore need a couple of hundred subprocesses to
    catch a 2.5% race, and would still be a coin toss. Worse, the race is
    invisible to every other law in this file, because every assertion about
    this field has the form "the bad thing is NOT in stderr" -- no `Traceback`,
    no leaked secret -- and an EMPTY stderr satisfies all of them. A crashed
    server and a leaked key both read as clean. That is the only direction a
    probe must never fail in, so the join is pinned where it can be seen.
    """
    created = []

    real_thread = probe.threading.Thread

    class RecordingThread(real_thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.joined = False
            created.append(self)

        def join(self, *args, **kwargs):
            self.joined = True
            return super().join(*args, **kwargs)

    monkeypatch.setattr(probe.threading, "Thread", RecordingThread)

    result = probe.handshake([sys.executable, "-m", "nano_mcp.server"], timeout=120)
    assert result.ok, f"{result.problem}\n--- stderr ---\n{result.stderr}"

    assert created, "handshake started no reader threads, so this law is watching nothing"
    unjoined = [thread for thread in created if not thread.joined]
    assert not unjoined, (
        f"{len(unjoined)} of {len(created)} reader thread(s) were never joined, so "
        "result.stderr can be read while a pipe is still being drained; a crashed "
        "server or a leaked secret would then read as clean output"
    )
