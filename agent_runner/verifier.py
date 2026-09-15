import subprocess
from pathlib import Path
from typing import Iterable, List

from agent_runner.models import CommandResult, VerificationResult


def _run_command(command: str, cwd: Path) -> CommandResult:
    process = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        command=command,
        return_code=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def run_verification(allowed_commands: Iterable[str], workspace: Path) -> VerificationResult:
    results: List[CommandResult] = []

    for command in allowed_commands:
        command_cwd = workspace / "frontend" if command.startswith("npm ") else workspace
        result = _run_command(command=command, cwd=command_cwd)
        results.append(result)
        if result.return_code != 0:
            return VerificationResult(success=False, command_results=results)

    return VerificationResult(success=True, command_results=results)
