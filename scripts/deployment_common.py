import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional
from urllib import error, request


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    details: str


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def print_checklist_table(title: str, results: Iterable[CheckResult]) -> None:
    rows = list(results)
    widths = {
        "check": max(len("Check"), *(len(row.name) for row in rows)) if rows else len("Check"),
        "status": len("Status"),
        "details": max(len("Details"), *(len(row.details) for row in rows)) if rows else len("Details"),
    }
    divider = f"+-{'-' * widths['check']}-+-{'-' * widths['status']}-+-{'-' * widths['details']}-+"
    print(f"\n{title}")
    print(divider)
    print(
        f"| {'Check'.ljust(widths['check'])} | {'Status'.ljust(widths['status'])} | {'Details'.ljust(widths['details'])} |"
    )
    print(divider)
    for row in rows:
        status_text = "PASS" if row.passed else "FAIL"
        print(
            f"| {row.name.ljust(widths['check'])} | {status_text.ljust(widths['status'])} | {row.details.ljust(widths['details'])} |"
        )
    print(divider)


def run_command(command: list[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def http_request(
    method: str,
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    payload: Optional[dict | list] = None,
    timeout_seconds: int = 15,
) -> tuple[int, str]:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    req = request.Request(url=url, method=method.upper(), data=body, headers=request_headers)
    with request.urlopen(req, timeout=timeout_seconds) as response:
        data = response.read().decode("utf-8")
        return int(response.status), data


def safe_http_request(
    method: str,
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    payload: Optional[dict | list] = None,
    timeout_seconds: int = 15,
) -> tuple[bool, str]:
    try:
        status, body = http_request(
            method,
            url,
            headers=headers,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        return True, f"HTTP {status} ({len(body)} bytes)"
    except error.HTTPError as exc:
        return False, f"HTTPError {exc.code}: {exc.reason}"
    except error.URLError as exc:
        return False, f"URLError: {exc.reason}"
