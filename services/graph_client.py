"""Minimal Microsoft Graph client-credentials transport for shared mailboxes."""

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GRAPH_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


class GraphClientError(RuntimeError):
    """A safe, user-facing Graph transport error."""


@dataclass(frozen=True)
class GraphSettings:
    tenant_id: str
    client_id: str
    client_secret: str
    timeout_seconds: float = 30.0

    @classmethod
    def from_environment(cls) -> "GraphSettings":
        values = {
            "GRAPH_TENANT_ID": os.getenv("GRAPH_TENANT_ID", "").strip(),
            "GRAPH_CLIENT_ID": os.getenv("GRAPH_CLIENT_ID", "").strip(),
            "GRAPH_CLIENT_SECRET": os.getenv("GRAPH_CLIENT_SECRET", ""),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise GraphClientError(
                "Microsoft Graph is not configured; missing " + ", ".join(missing) + "."
            )
        try:
            timeout = float(os.getenv("GRAPH_TIMEOUT_SECONDS", "30"))
        except ValueError as exc:
            raise GraphClientError("GRAPH_TIMEOUT_SECONDS must be a number.") from exc
        if timeout <= 0:
            raise GraphClientError("GRAPH_TIMEOUT_SECONDS must be greater than zero.")
        return cls(values["GRAPH_TENANT_ID"], values["GRAPH_CLIENT_ID"], values["GRAPH_CLIENT_SECRET"], timeout)


class GraphClient:
    def __init__(
        self,
        settings: Optional[GraphSettings] = None,
        opener: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or GraphSettings.from_environment()
        self._opener = opener or urlopen
        self._clock = clock
        self._token: Optional[str] = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    def _request_json(self, request: Request) -> dict[str, Any]:
        try:
            response = self._opener(request, timeout=self.settings.timeout_seconds)
            if isinstance(response, HTTPError):
                raise response
            with response:
                raw = response.read()
        except HTTPError as exc:
            detail = "HTTP error"
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = payload.get("error", {}).get("code", detail)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            raise GraphClientError(f"Microsoft Graph request failed: {detail}.") from exc
        except (TimeoutError, URLError) as exc:
            raise GraphClientError("Microsoft Graph request timed out or was unreachable.") from exc
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GraphClientError("Microsoft Graph returned an invalid JSON response.") from exc
        if not isinstance(payload, dict):
            raise GraphClientError("Microsoft Graph returned an invalid response.")
        return payload

    def _acquire_token(self) -> str:
        body = urlencode({
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "scope": GRAPH_SCOPE,
            "grant_type": "client_credentials",
        }).encode("utf-8")
        request = Request(
            TOKEN_URL_TEMPLATE.format(tenant_id=self.settings.tenant_id),
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        payload = self._request_json(request)
        token = payload.get("access_token")
        expires_in = payload.get("expires_in", 0)
        if not isinstance(token, str) or not token:
            raise GraphClientError("Microsoft Graph token response was missing access_token.")
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            raise GraphClientError("Microsoft Graph token response was missing a valid expiry.")
        self._token = token
        self._token_expires_at = self._clock() + float(expires_in) - 60
        return token

    def _get_token(self, force_refresh: bool = False) -> str:
        with self._lock:
            if not force_refresh and self._token and self._clock() < self._token_expires_at:
                return self._token
            return self._acquire_token()

    def request(self, method: str, path: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        for attempt in range(2):
            token = self._get_token(force_refresh=attempt == 1)
            data = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            if data is not None:
                headers["Content-Type"] = "application/json"
            request = Request(GRAPH_BASE_URL + path, data=data, headers=headers, method=method)
            try:
                return self._request_json(request)
            except GraphClientError as exc:
                if attempt == 0 and "InvalidAuthenticationToken" in str(exc):
                    continue
                raise
        raise GraphClientError("Microsoft Graph request failed after token refresh.")
