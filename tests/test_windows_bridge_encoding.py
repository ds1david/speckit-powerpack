from __future__ import annotations

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import windows_browser_bridge as bridge


def test_decode_windows_output_accepts_cp850_diagnostics():
    message = "'node' não é reconhecido como um comando interno ou externo"
    payload = message.encode("cp850")

    assert bridge._decode_windows_output(payload) == message


def test_decode_windows_output_preserves_utf8_node_output():
    payload = "v22.14.0\n".encode("utf-8")

    assert bridge._decode_windows_output(payload) == "v22.14.0\n"


def test_run_never_raises_unicode_decode_error_for_windows_output(monkeypatch):
    stderr = "Falha: não foi possível localizar o comando".encode("cp850")
    raw = subprocess.CompletedProcess(
        ["cmd.exe"],
        1,
        stdout=b"",
        stderr=stderr,
    )

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: raw)

    result = bridge._run(["cmd.exe", "/c", "node --version"])

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Falha: não foi possível localizar o comando"
