from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Sequence


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
