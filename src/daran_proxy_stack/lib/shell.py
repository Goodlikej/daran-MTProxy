from __future__ import annotations

import shlex
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run(command: Sequence[str], check: bool = False) -> CommandResult:
    completed = subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
    )
    result = CommandResult(
        command=" ".join(shlex.quote(part) for part in command),
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )
    if check and not result.ok:
        raise RuntimeError(f"Command failed: {result.command}\n{result.stderr}")
    return result


def run_live(
    command: Sequence[str],
    console=None,
    on_line: Callable[[str], None] | None = None,
) -> CommandResult:
    """Run a command and stream stdout/stderr line by line in real time.

    Args:
        command:  Command to execute.
        console:  Rich Console to print lines to (optional).
        on_line:  Callback called for each output line (optional).

    Returns:
        CommandResult with aggregated stdout/stderr.
    """
    process = subprocess.Popen(
        list(command),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _read_stream(stream, lines: list[str], style: str = "") -> None:
        for raw in stream:
            line = raw.rstrip("\n")
            lines.append(line)
            if console is not None:
                if style:
                    console.print(line, style=style)
                else:
                    console.print(line)
            if on_line is not None:
                on_line(line)

    t_out = threading.Thread(target=_read_stream, args=(process.stdout, stdout_lines, ""))
    t_err = threading.Thread(target=_read_stream, args=(process.stderr, stderr_lines, "dim red"))
    t_out.start()
    t_err.start()
    t_out.join()
    t_err.join()
    process.wait()

    return CommandResult(
        command=" ".join(shlex.quote(part) for part in command),
        returncode=process.returncode,
        stdout="\n".join(stdout_lines).strip(),
        stderr="\n".join(stderr_lines).strip(),
    )
