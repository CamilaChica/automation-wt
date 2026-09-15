import json
from datetime import datetime, UTC
from pathlib import Path
from textwrap import dedent
from typing import Optional

from agent_runner.codex_adapter import run_codex_command
from agent_runner.config import load_config
from agent_runner.event_parser import parse_trigger_context
from agent_runner.git_ops import commit_and_push, get_changed_files, prepare_feature_branch
from agent_runner.models import VerificationResult
from agent_runner.pr_ops import create_pull_request, post_issue_comment
from agent_runner.verifier import run_verification


def _ensure_branch_allowed(branch_name: str, protected_branches: list[str], allowed_prefixes: list[str]) -> None:
    if branch_name in protected_branches:
        raise RuntimeError(f"Generated branch is protected and cannot be used: {branch_name}")
    if not any(branch_name.startswith(prefix) for prefix in allowed_prefixes):
        prefixes = ", ".join(allowed_prefixes)
        raise RuntimeError(f"Generated branch does not match allowed prefixes ({prefixes}): {branch_name}")


def _build_prompt(task_text: str, previous_failure: Optional[VerificationResult]) -> str:
    feedback = ""
    if previous_failure is not None:
        failed = previous_failure.command_results[-1]
        feedback = dedent(
            f"""
            Previous verification failed.
            Failed command: {failed.command}
            Return code: {failed.return_code}
            STDOUT:
            {failed.stdout[-4000:]}
            STDERR:
            {failed.stderr[-4000:]}
            """
        ).strip()

    return dedent(
        f"""
        You are operating inside this repository and must make minimal, targeted edits for the following task:

        {task_text}

        Required constraints:
        - Do not commit secrets or credentials.
        - Keep changes scoped to the task.
        - Preserve existing behavior outside the task scope.
        - Run or prepare for required verification commands defined in AGENTS.md.

        {feedback}
        """
    ).strip()


def _write_attempt_artifacts(run_dir: Path, attempt: int, prompt_text: str, codex_stdout: str, codex_stderr: str, verification: VerificationResult) -> None:
    attempt_dir = run_dir / f"attempt-{attempt:02d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)

    (attempt_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    (attempt_dir / "codex.stdout.log").write_text(codex_stdout, encoding="utf-8")
    (attempt_dir / "codex.stderr.log").write_text(codex_stderr, encoding="utf-8")

    verify_payload = {
        "success": verification.success,
        "commands": [
            {
                "command": item.command,
                "return_code": item.return_code,
                "stdout_tail": item.stdout[-4000:],
                "stderr_tail": item.stderr[-4000:],
            }
            for item in verification.command_results
        ],
    }
    (attempt_dir / "verification.json").write_text(json.dumps(verify_payload, indent=2), encoding="utf-8")


def _format_pr_body(task_text: str, changed_files: list[str], verification: VerificationResult, run_source: str) -> str:
    checks = "\n".join(
        f"- `{result.command}`: {'PASS' if result.return_code == 0 else 'FAIL'}"
        for result in verification.command_results
    )
    files_block = "\n".join(f"- `{path}`" for path in changed_files) if changed_files else "- No file changes detected"
    return dedent(
        f"""
        ## Autonomous agent summary

        **Trigger source:** `{run_source}`

        ### Task
        {task_text}

        ### Changed files
        {files_block}

        ### Verification
        {checks}
        """
    ).strip()


def _comment_issue_if_needed(owner: str, repo: str, token: str, issue_number: Optional[int], body: str) -> None:
    if issue_number is None:
        return
    post_issue_comment(owner=owner, repo=repo, issue_number=issue_number, token=token, body=body)


def _safe_commit_title(task_text: str) -> str:
    first_line = task_text.splitlines()[0].strip()
    if not first_line:
        first_line = "Autonomous update"
    title = first_line[:62].rstrip()
    return f"autonomous: {title}"


def run() -> None:
    config = load_config()
    context = parse_trigger_context(config)
    if not context.should_run:
        print(f"No-op: trigger did not match run criteria ({context.source})")
        return

    started_at = datetime.now(UTC)
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.artifacts_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    branch_name = f"codex/feature-update-{run_id.lower()}"
    _ensure_branch_allowed(
        branch_name=branch_name,
        protected_branches=config.policy.protected_branches,
        allowed_prefixes=config.policy.allowed_branch_prefixes,
    )

    if context.run_writes:
        prepare_feature_branch(config.workspace, config.base_branch, branch_name)

    verification_result: Optional[VerificationResult] = None
    codex_stdout = ""
    codex_stderr = ""

    for attempt in range(1, config.policy.max_attempts + 1):
        prompt = _build_prompt(context.task_text, verification_result)
        prompt_path = run_dir / f"attempt-{attempt:02d}-prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")

        if context.run_writes:
            codex_result = run_codex_command(
                command_template=config.codex_command,
                prompt_path=prompt_path,
                workspace=config.workspace,
            )
            codex_stdout = codex_result.stdout
            codex_stderr = codex_result.stderr
            if codex_result.returncode != 0:
                raise RuntimeError(
                    f"Codex command failed on attempt {attempt} with exit code {codex_result.returncode}:\n{codex_stderr[-4000:]}"
                )
        else:
            codex_stdout = "Dry-run mode: Codex command skipped."
            codex_stderr = ""

        verification_result = run_verification(
            allowed_commands=config.policy.allowed_verify_commands,
            workspace=config.workspace,
        )
        _write_attempt_artifacts(
            run_dir=run_dir,
            attempt=attempt,
            prompt_text=prompt,
            codex_stdout=codex_stdout,
            codex_stderr=codex_stderr,
            verification=verification_result,
        )

        if verification_result.success:
            break

    if verification_result is None:
        raise RuntimeError("No verification result captured")

    if not verification_result.success:
        summary_path = run_dir / "summary.txt"
        summary_path.write_text(
            "Autonomous run ended without passing verification after max attempts.",
            encoding="utf-8",
        )
        _comment_issue_if_needed(
            owner=config.repo_owner,
            repo=config.repo_name,
            token=config.github_token,
            issue_number=context.issue_number,
            body="Autonomous run failed verification. See workflow artifacts for full diagnostics.",
        )
        raise RuntimeError("Verification did not pass within retry limit")

    changed_files = get_changed_files(config.workspace)
    if not changed_files:
        summary = "Autonomous run completed with no repository changes."
        (run_dir / "summary.txt").write_text(summary, encoding="utf-8")
        _comment_issue_if_needed(
            owner=config.repo_owner,
            repo=config.repo_name,
            token=config.github_token,
            issue_number=context.issue_number,
            body=summary,
        )
        return

    pr_url: Optional[str] = None
    if context.run_writes:
        commit_message = _safe_commit_title(context.task_text)
        commit_and_push(config.workspace, branch_name, commit_message)
        pr_title = f"Autonomous update: {context.task_text.splitlines()[0][:70]}"
        pr_body = _format_pr_body(
            task_text=context.task_text,
            changed_files=changed_files,
            verification=verification_result,
            run_source=context.source,
        )
        pr_url = create_pull_request(
            owner=config.repo_owner,
            repo=config.repo_name,
            token=config.github_token,
            title=pr_title,
            body=pr_body,
            head_branch=branch_name,
            base_branch=config.base_branch,
            draft=True,
        )
        _comment_issue_if_needed(
            owner=config.repo_owner,
            repo=config.repo_name,
            token=config.github_token,
            issue_number=context.issue_number,
            body=f"Autonomous implementation opened a draft PR: {pr_url}",
        )

    summary_payload = {
        "run_id": run_id,
        "source": context.source,
        "writes_enabled": context.run_writes,
        "branch_name": branch_name if context.run_writes else None,
        "changed_files": changed_files,
        "pr_url": pr_url,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    print(json.dumps(summary_payload, indent=2))
