import json
from pathlib import Path
from typing import Any, Dict, Optional

from agent_runner.models import RunnerConfig, TriggerContext


def _read_event_payload(event_path: Optional[Path]) -> Dict[str, Any]:
    if event_path is None:
        return {}
    with event_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _extract_issue_task(payload: Dict[str, Any]) -> str:
    issue = payload.get("issue", {})
    title = str(issue.get("title", "")).strip()
    body = str(issue.get("body", "")).strip()
    task_parts = [part for part in (title, body) if part]
    return "\n\n".join(task_parts)


def parse_trigger_context(config: RunnerConfig) -> TriggerContext:
    payload = _read_event_payload(config.event_path)
    event_name = config.event_name
    policy = config.policy

    if event_name == "issues":
        action = str(payload.get("action", "")).strip()
        if action != "labeled":
            return TriggerContext(
                should_run=False,
                task_text="",
                source=f"issues:{action}",
                issue_number=payload.get("issue", {}).get("number"),
                run_writes=False,
            )

        label = str(payload.get("label", {}).get("name", "")).strip()
        if label != policy.trigger_label:
            return TriggerContext(
                should_run=False,
                task_text="",
                source=f"issues:labeled:{label}",
                issue_number=payload.get("issue", {}).get("number"),
                run_writes=False,
            )

        task_text = _extract_issue_task(payload)
        if not task_text:
            raise RuntimeError("Issue payload did not include title/body task content")

        return TriggerContext(
            should_run=True,
            task_text=task_text,
            source=f"issues:labeled:{label}",
            issue_number=payload.get("issue", {}).get("number"),
            run_writes=not config.dry_run,
        )

    if event_name == "schedule":
        task_text = (
            "Scheduled maintenance run: inspect feature linkages, run verification commands, "
            "and apply only minimal safe fixes with full PR summary."
        )
        if config.dry_run:
            run_writes = False
        else:
            run_writes = config.allow_scheduled_writes

        return TriggerContext(
            should_run=True,
            task_text=task_text,
            source="schedule",
            issue_number=None,
            run_writes=run_writes,
        )

    if event_name == "workflow_dispatch":
        inputs = payload.get("inputs", {}) if isinstance(payload.get("inputs"), dict) else {}
        task_text = str(inputs.get("task", "")).strip()
        if not task_text:
            task_text = "Manual dispatch task: run autonomous implementation workflow with configured constraints."

        write_input = str(inputs.get("allow_writes", "")).strip().lower()
        allow_writes = write_input in {"1", "true", "yes", "y", "on"} if write_input else not config.dry_run

        return TriggerContext(
            should_run=True,
            task_text=task_text,
            source="workflow_dispatch",
            issue_number=None,
            run_writes=allow_writes and not config.dry_run,
        )

    return TriggerContext(
        should_run=False,
        task_text="",
        source=event_name,
        issue_number=None,
        run_writes=False,
    )
