import subprocess
from pathlib import Path


def _run_git(args: list[str], workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--no-pager", *args],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
    )


def prepare_feature_branch(workspace: Path, base_branch: str, branch_name: str) -> None:
    fetch = _run_git(["fetch", "origin", base_branch], workspace)
    if fetch.returncode != 0:
        raise RuntimeError(f"git fetch failed: {fetch.stderr.strip()}")

    checkout = _run_git(["checkout", base_branch], workspace)
    if checkout.returncode != 0:
        raise RuntimeError(f"git checkout {base_branch} failed: {checkout.stderr.strip()}")

    pull = _run_git(["pull", "--ff-only", "origin", base_branch], workspace)
    if pull.returncode != 0:
        raise RuntimeError(f"git pull failed: {pull.stderr.strip()}")

    create = _run_git(["checkout", "-B", branch_name], workspace)
    if create.returncode != 0:
        raise RuntimeError(f"git branch create failed: {create.stderr.strip()}")


def get_changed_files(workspace: Path) -> list[str]:
    status = _run_git(["status", "--porcelain"], workspace)
    if status.returncode != 0:
        raise RuntimeError(f"git status failed: {status.stderr.strip()}")

    changed = []
    for raw_line in status.stdout.splitlines():
        if not raw_line:
            continue
        if len(raw_line) < 4:
            continue
        path_fragment = raw_line[3:].strip()
        if " -> " in path_fragment:
            path_fragment = path_fragment.split(" -> ", 1)[1].strip()
        if path_fragment:
            changed.append(path_fragment)
    return changed


def commit_and_push(workspace: Path, branch_name: str, commit_message: str) -> None:
    add = _run_git(["add", "-A"], workspace)
    if add.returncode != 0:
        raise RuntimeError(f"git add failed: {add.stderr.strip()}")

    commit = _run_git(["commit", "-m", commit_message], workspace)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit failed: {commit.stderr.strip()}")

    push = _run_git(["push", "--set-upstream", "origin", branch_name], workspace)
    if push.returncode != 0:
        raise RuntimeError(f"git push failed: {push.stderr.strip()}")
