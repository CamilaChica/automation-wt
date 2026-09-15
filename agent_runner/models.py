from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class Policy:
    protected_branches: List[str]
    allowed_branch_prefixes: List[str]
    allowed_verify_commands: List[str]
    max_attempts: int
    trigger_label: str


@dataclass(frozen=True)
class RunnerConfig:
    workspace: Path
    artifacts_root: Path
    repo_full_name: str
    repo_owner: str
    repo_name: str
    event_name: str
    event_path: Optional[Path]
    base_branch: str
    codex_command: str
    github_token: str
    actor: str
    dry_run: bool
    allow_scheduled_writes: bool
    issue_comment_mode: bool
    policy: Policy


@dataclass(frozen=True)
class TriggerContext:
    should_run: bool
    task_text: str
    source: str
    issue_number: Optional[int]
    run_writes: bool


@dataclass(frozen=True)
class CommandResult:
    command: str
    return_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    command_results: List[CommandResult]
