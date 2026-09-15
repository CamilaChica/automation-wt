import json
import os
from pathlib import Path

from agent_runner.models import Policy, RunnerConfig


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_policy(policy_path: Path) -> Policy:
    with policy_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    required_keys = {
        "protected_branches",
        "allowed_branch_prefixes",
        "allowed_verify_commands",
        "max_attempts",
        "trigger_label",
    }
    missing = required_keys.difference(data)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RuntimeError(f"Policy file is missing required keys: {missing_list}")

    return Policy(
        protected_branches=list(data["protected_branches"]),
        allowed_branch_prefixes=list(data["allowed_branch_prefixes"]),
        allowed_verify_commands=list(data["allowed_verify_commands"]),
        max_attempts=int(data["max_attempts"]),
        trigger_label=str(data["trigger_label"]),
    )


def load_config() -> RunnerConfig:
    workspace = Path(os.getenv("GITHUB_WORKSPACE", os.getcwd())).resolve()
    policy_path = workspace / "config" / "autonomous_agent_policy.json"
    policy = load_policy(policy_path)

    repo_full_name = _require_env("GITHUB_REPOSITORY")
    if "/" not in repo_full_name:
        raise RuntimeError("GITHUB_REPOSITORY must be in <owner>/<repo> format")
    repo_owner, repo_name = repo_full_name.split("/", 1)

    event_path_value = os.getenv("GITHUB_EVENT_PATH", "").strip()
    event_path = Path(event_path_value).resolve() if event_path_value else None

    event_name = _require_env("GITHUB_EVENT_NAME")
    issue_comment_mode = event_name == "issues"

    raw_codex_command = os.getenv("CODEX_COMMAND", "").strip()
    dry_run = _bool_env("DRY_RUN", default=False)
    if not raw_codex_command and not dry_run:
        raise RuntimeError("CODEX_COMMAND must be set unless DRY_RUN=true")

    return RunnerConfig(
        workspace=workspace,
        artifacts_root=(workspace / "artifacts" / "agent-runs").resolve(),
        repo_full_name=repo_full_name,
        repo_owner=repo_owner,
        repo_name=repo_name,
        event_name=event_name,
        event_path=event_path,
        base_branch=os.getenv("BASE_BRANCH", "main").strip() or "main",
        codex_command=raw_codex_command,
        github_token=_require_env("GITHUB_TOKEN"),
        actor=os.getenv("GITHUB_ACTOR", "unknown"),
        dry_run=dry_run,
        allow_scheduled_writes=_bool_env("ALLOW_SCHEDULED_WRITES", default=False),
        issue_comment_mode=issue_comment_mode,
        policy=policy,
    )
