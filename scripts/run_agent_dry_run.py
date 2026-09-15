import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_FIXTURES = {
    "issues": "data/fixtures/issues_labeled_auto_implement.json",
    "workflow_dispatch": "data/fixtures/workflow_dispatch_auto_implement.json",
    "schedule": "data/fixtures/schedule_auto_implement.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run autonomous agent in local dry-run mode.")
    parser.add_argument(
        "--mode",
        choices=["issues", "workflow_dispatch", "schedule"],
        default="issues",
        help="GitHub trigger mode to simulate.",
    )
    parser.add_argument(
        "--event",
        default="",
        help="Path to the GitHub event payload fixture relative to the repository root.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    fixture_path = args.event or DEFAULT_FIXTURES[args.mode]
    event_path = (repo_root / fixture_path).resolve()
    if not event_path.exists():
        raise FileNotFoundError(f"Event fixture not found: {event_path}")

    env = os.environ.copy()
    env["GITHUB_WORKSPACE"] = str(repo_root)
    env["GITHUB_EVENT_NAME"] = args.mode
    env["GITHUB_EVENT_PATH"] = str(event_path)
    env["GITHUB_REPOSITORY"] = env.get("GITHUB_REPOSITORY", "local/automation-wt")
    env["GITHUB_ACTOR"] = env.get("GITHUB_ACTOR", "local-dry-run")
    env["GITHUB_TOKEN"] = env.get("GITHUB_TOKEN", "local-dry-run-token")
    env["BASE_BRANCH"] = env.get("BASE_BRANCH", "main")
    env["DRY_RUN"] = "true"
    env["ALLOW_SCHEDULED_WRITES"] = "false"

    process = subprocess.run(
        [sys.executable, "-m", "agent_runner"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.stdout:
        print(process.stdout)
    if process.stderr:
        print(process.stderr, file=sys.stderr)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
