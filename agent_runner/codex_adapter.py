import subprocess
from pathlib import Path


def run_codex_command(command_template: str, prompt_path: Path, workspace: Path) -> subprocess.CompletedProcess[str]:
    command = command_template.format(prompt_file=str(prompt_path), workspace=str(workspace))
    if not command.strip():
        raise RuntimeError("Codex command template is empty")

    return subprocess.run(
        command,
        cwd=str(workspace),
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
