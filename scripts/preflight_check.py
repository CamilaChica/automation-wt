import json
import os
import shlex
import sqlite3
import sys
from pathlib import Path
from urllib import error, request

from scripts.deployment_common import CheckResult, print_checklist_table, run_command

REQUIRED_TABLES = (
    "inventory_items",
    "suppliers",
    "csv_ingestion_logs",
    "purchase_orders",
)
REQUIRED_SECRETS = (
    "GODADDY_API_KEY",
    "GODADDY_API_SECRET",
    "RENDER_DEPLOY_HOOK",
)
INTERFACE_PATHS = (
    "/customer",
    "/sales",
    "/procurement",
    "/admin",
)


def _auth_secret_present() -> tuple[bool, str]:
    if os.getenv("JWT_SECRET"):
        return True, "JWT_SECRET present"
    if os.getenv("WT_AUTH_SECRET"):
        return True, "WT_AUTH_SECRET present (repo auth secret)"
    return False, "Missing JWT_SECRET (or WT_AUTH_SECRET equivalent)"


def check_database_path_and_tables(db_path: str) -> CheckResult:
    db_parent = Path(db_path).parent
    if not db_parent.exists():
        return CheckResult("Database path", False, f"Parent directory missing: {db_parent}")
    if not os.access(db_parent, os.W_OK):
        return CheckResult("Database path", False, f"Parent directory not writable: {db_parent}")
    if not Path(db_path).exists():
        return CheckResult("Database path", False, f"Database file missing: {db_path}")

    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = {row[0] for row in cursor.fetchall()}
    missing = [table for table in REQUIRED_TABLES if table not in existing_tables]
    if missing:
        return CheckResult("Database schema", False, f"Missing tables: {', '.join(missing)}")
    return CheckResult("Database schema", True, f"All required tables exist in {db_path}")


def check_required_secrets() -> list[CheckResult]:
    results: list[CheckResult] = []
    auth_ok, auth_details = _auth_secret_present()
    results.append(CheckResult("Auth secret", auth_ok, auth_details))

    for secret in REQUIRED_SECRETS:
        present = bool(os.getenv(secret))
        details = f"{secret} present" if present else f"Missing {secret}"
        results.append(CheckResult(f"Secret: {secret}", present, details))
    return results


def check_interface_health(base_url: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    trimmed_base = base_url.rstrip("/")
    for path in INTERFACE_PATHS:
        url = f"{trimmed_base}{path}"
        req = request.Request(url=url, method="GET")
        try:
            with request.urlopen(req, timeout=10) as response:
                passed = response.status == 200
                details = f"{url} -> HTTP {response.status}"
                results.append(CheckResult(f"Route {path}", passed, details))
        except error.HTTPError as exc:
            results.append(CheckResult(f"Route {path}", False, f"{url} -> HTTPError {exc.code}"))
        except error.URLError as exc:
            results.append(CheckResult(f"Route {path}", False, f"{url} -> URLError {exc.reason}"))
    return results


def check_e2e_and_build() -> list[CheckResult]:
    repo_root = Path(__file__).resolve().parents[1]
    frontend_dir = repo_root / "frontend"

    results: list[CheckResult] = []
    backend_tests = run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=str(repo_root),
    )
    backend_ok = backend_tests.returncode == 0
    results.append(
        CheckResult(
            "Backend test suite",
            backend_ok,
            "python -m unittest discover passed" if backend_ok else "Backend tests failed",
        )
    )

    frontend_build = run_command(["npm", "run", "build"], cwd=str(frontend_dir))
    frontend_ok = frontend_build.returncode == 0
    results.append(
        CheckResult(
            "Frontend build",
            frontend_ok,
            "npm run build passed" if frontend_ok else "Frontend build failed",
        )
    )

    package_json_path = frontend_dir / "package.json"
    with package_json_path.open("r", encoding="utf-8") as handle:
        package_json = json.load(handle)
    scripts = package_json.get("scripts", {})
    e2e_command = os.getenv("E2E_CHECK_COMMAND", "")
    if not e2e_command and "test:e2e" in scripts:
        e2e_command = "npm run test:e2e"

    if not e2e_command:
        results.append(
            CheckResult(
                "E2E compliance/ordering suite",
                False,
                "No E2E_CHECK_COMMAND configured and no test:e2e script found",
            )
        )
        return results

    e2e_result = run_command(shlex.split(e2e_command, posix=False), cwd=str(repo_root))
    output = f"{e2e_result.stdout}\n{e2e_result.stderr}".lower()
    has_warning = "warning" in output
    e2e_ok = e2e_result.returncode == 0 and not has_warning
    detail = f"{e2e_command} passed without warnings" if e2e_ok else f"{e2e_command} failed or emitted warnings"
    results.append(CheckResult("E2E compliance/ordering suite", e2e_ok, detail))
    return results


def run_preflight() -> int:
    db_path = os.getenv("MIGRATION_SQLITE_PATH", "/var/data/app.db")
    interface_base_url = os.getenv("INTERFACE_BASE_URL", "http://127.0.0.1:3000")

    checks: list[CheckResult] = []
    checks.append(check_database_path_and_tables(db_path))
    checks.extend(check_required_secrets())
    checks.extend(check_interface_health(interface_base_url))
    checks.extend(check_e2e_and_build())
    print_checklist_table("Deployment Pre-Flight Checklist", checks)
    return 0 if all(item.passed for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(run_preflight())
