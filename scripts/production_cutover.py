import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib import error

from scripts.deployment_common import http_request


@dataclass(frozen=True)
class CutoverConfig:
    domain: str
    root_ip: str
    www_target: str
    production_hook: str
    production_url: str
    timeout_seconds: int
    poll_seconds: int
    auth_header: str


def require_approval() -> None:
    if os.getenv("APPROVAL_CONFIRMED") != "true":
        raise RuntimeError("Production cutover blocked: set APPROVAL_CONFIRMED=true to continue.")


def load_config() -> CutoverConfig:
    domain = os.getenv("GODADDY_DOMAIN", "").strip()
    root_ip = os.getenv("RENDER_PRODUCTION_IP", "").strip()
    www_target = os.getenv("RENDER_PRODUCTION_HOST", "").strip()
    production_hook = (os.getenv("RENDER_PRODUCTION_DEPLOY_HOOK") or os.getenv("RENDER_DEPLOY_HOOK") or "").strip()
    production_url = os.getenv("PRODUCTION_URL", "").strip()

    api_key = os.getenv("GODADDY_API_KEY", "").strip()
    api_secret = os.getenv("GODADDY_API_SECRET", "").strip()
    timeout_seconds = int(os.getenv("CUTOVER_TIMEOUT_SECONDS", "1800"))
    poll_seconds = int(os.getenv("CUTOVER_POLL_SECONDS", "15"))

    missing = []
    if not domain:
        missing.append("GODADDY_DOMAIN")
    if not root_ip:
        missing.append("RENDER_PRODUCTION_IP")
    if not www_target:
        missing.append("RENDER_PRODUCTION_HOST")
    if not production_hook:
        missing.append("RENDER_PRODUCTION_DEPLOY_HOOK (or RENDER_DEPLOY_HOOK)")
    if not production_url:
        missing.append("PRODUCTION_URL")
    if not api_key:
        missing.append("GODADDY_API_KEY")
    if not api_secret:
        missing.append("GODADDY_API_SECRET")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    auth_header = f"sso-key {api_key}:{api_secret}"
    return CutoverConfig(
        domain=domain,
        root_ip=root_ip,
        www_target=www_target,
        production_hook=production_hook,
        production_url=production_url,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
        auth_header=auth_header,
    )


def update_godaddy_record(config: CutoverConfig, record_type: str, name: str, data_value: str) -> None:
    url = f"https://api.godaddy.com/v1/domains/{config.domain}/records/{record_type}/{name}"
    headers = {"Authorization": config.auth_header}
    payload = [{"data": data_value, "ttl": 600}]
    status, _ = http_request("PUT", url, headers=headers, payload=payload, timeout_seconds=20)
    if status not in (200, 204):
        raise RuntimeError(f"GoDaddy update failed for {record_type} {name}: HTTP {status}")


def get_godaddy_record(config: CutoverConfig, record_type: str, name: str) -> list[dict]:
    url = f"https://api.godaddy.com/v1/domains/{config.domain}/records/{record_type}/{name}"
    status, body = http_request("GET", url, headers={"Authorization": config.auth_header}, timeout_seconds=20)
    if status != 200:
        raise RuntimeError(f"GoDaddy read failed for {record_type} {name}: HTTP {status}")
    parsed = json.loads(body)
    if not isinstance(parsed, list):
        raise RuntimeError(f"Unexpected GoDaddy response for {record_type} {name}: {body}")
    return parsed


def trigger_render_production_deploy(config: CutoverConfig) -> None:
    status, _ = http_request("POST", config.production_hook, timeout_seconds=20)
    if status not in (200, 201, 202, 204):
        raise RuntimeError(f"Render deploy hook failed: HTTP {status}")


def dns_points_to_ip(hostname: str, expected_ip: str) -> bool:
    addresses = {entry[4][0] for entry in socket.getaddrinfo(hostname, None, family=socket.AF_INET)}
    return expected_ip in addresses


def https_is_healthy(url: str) -> bool:
    status, _ = http_request("GET", url, timeout_seconds=20)
    return status == 200


def poll_until_live(config: CutoverConfig) -> tuple[bool, str]:
    started = time.time()
    while (time.time() - started) <= config.timeout_seconds:
        a_records = get_godaddy_record(config, "A", "@")
        cname_records = get_godaddy_record(config, "CNAME", "www")
        a_ok = any(record.get("data") == config.root_ip for record in a_records)
        cname_ok = any(record.get("data") == config.www_target for record in cname_records)
        dns_root_ok = dns_points_to_ip(config.domain, config.root_ip)
        https_ok = https_is_healthy(config.production_url)
        if a_ok and cname_ok and dns_root_ok and https_ok:
            return True, "DNS records and HTTPS health check are live."
        time.sleep(config.poll_seconds)
    return False, f"Timed out after {config.timeout_seconds}s waiting for DNS/HTTPS propagation."


def main() -> int:
    require_approval()
    config = load_config()

    update_godaddy_record(config, "A", "@", config.root_ip)
    update_godaddy_record(config, "CNAME", "www", config.www_target)
    trigger_render_production_deploy(config)

    ok, status_message = poll_until_live(config)
    timestamp = datetime.now(timezone.utc).isoformat()
    print("\nProduction deployment audit")
    print(f"  timestamp_utc: {timestamp}")
    print(f"  domain: {config.domain}")
    print(f"  production_url: {config.production_url}")
    print(f"  dns_a_target: {config.root_ip}")
    print(f"  dns_cname_target: {config.www_target}")
    print(f"  status: {'SUCCESS' if ok else 'FAILED'}")
    print(f"  details: {status_message}")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
    except error.HTTPError as exc:
        print(f"HTTPError {exc.code}: {exc.reason}")
        raise SystemExit(1)
    except error.URLError as exc:
        print(f"URLError: {exc.reason}")
        raise SystemExit(1)
    except socket.gaierror as exc:
        print(f"DNS resolution error: {exc}")
        raise SystemExit(1)
