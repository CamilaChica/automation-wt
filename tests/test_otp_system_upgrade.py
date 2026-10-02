import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from api import auth
from api.main import _auth_environment, _client_key, app
from services import shared_rate_limit
from api.auth import _PostgresConnection


@pytest.fixture
def auth_database(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_DB_PATH", str(tmp_path / "auth.db"))
    auth.init_auth_db()
    return str(tmp_path / "auth.db")


def test_otp_challenge_is_single_use_under_concurrent_verification(auth_database):
    challenge_id, code = auth.request_otp(
        "one-time@example.com",
        auth.ROLE_CUSTOMER,
    )
    barrier = Barrier(2)

    def verify():
        barrier.wait()
        try:
            auth.verify_otp(challenge_id, code)
            return "verified"
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: verify(), range(2)))

    assert results.count("verified") == 1
    assert results.count(401) == 1

    with closing(sqlite3.connect(auth_database)) as connection:
        session_count = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert session_count == 1


def test_new_otp_invalidates_previous_challenge(auth_database):
    old_challenge, _old_code = auth.request_otp(
        "resend@example.com",
        auth.ROLE_CUSTOMER,
    )
    new_challenge, new_code = auth.request_otp(
        "resend@example.com",
        auth.ROLE_CUSTOMER,
    )

    with pytest.raises(HTTPException) as exc_info:
        auth.verify_otp(old_challenge, "000000")
    assert exc_info.value.status_code == 401

    session = auth.verify_otp(new_challenge, new_code)
    assert session["email"] == "resend@example.com"


def test_failed_otp_attempts_persist_and_lock_challenge(auth_database):
    challenge_id, code = auth.request_otp(
        "locked@example.com",
        auth.ROLE_CUSTOMER,
    )
    wrong_code = "000000" if code != "000000" else "000001"

    for attempt in range(auth.MAX_OTP_ATTEMPTS):
        with pytest.raises(HTTPException) as exc_info:
            auth.verify_otp(challenge_id, wrong_code)
        expected_status = 429 if attempt == auth.MAX_OTP_ATTEMPTS - 1 else 401
        assert exc_info.value.status_code == expected_status

    with closing(sqlite3.connect(auth_database)) as connection:
        row = connection.execute(
            "SELECT attempt_count, locked_until FROM otp_challenges WHERE id = ?",
            (challenge_id,),
        ).fetchone()

    assert row[0] == auth.MAX_OTP_ATTEMPTS
    assert row[1] is not None


def test_production_otp_rate_limit_fails_closed(monkeypatch):
    monkeypatch.setenv("WT_AUTH_ENV", "production")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")

    def unavailable(*_args):
        raise shared_rate_limit.SharedRateLimitUnavailable("Redis unavailable")

    monkeypatch.setattr("api.main.check_shared_rate_limit", unavailable)

    response = TestClient(app).post(
        "/api/auth/otp/request",
        json={"email": "closed@example.com", "role": "ROLE_CUSTOMER"},
    )

    assert response.status_code == 503
    assert "rate limiting is unavailable" in response.text


def test_shared_rate_limit_hashes_subject_before_redis(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("WT_AUTH_SECRET", "test-secret-that-is-at-least-32-characters")
    captured = {}

    class FakeRedis:
        def eval(self, _script, key_count, key, now_ms, window_ms, limit, _member):
            captured.update(
                key_count=key_count,
                key=key,
                now_ms=now_ms,
                window_ms=window_ms,
                limit=limit,
            )
            return [1, 0]

    monkeypatch.setattr(shared_rate_limit.Redis, "from_url", lambda *_args, **_kwargs: FakeRedis())

    allowed, retry_after = shared_rate_limit.check_shared_rate_limit(
        "/api/auth/otp/request",
        "203.0.113.7",
        3,
        3600,
    )

    assert allowed
    assert retry_after == 0
    assert captured["key_count"] == 1
    assert "203.0.113.7" not in captured["key"]
    assert captured["window_ms"] == 3_600_000
    assert captured["limit"] == 3


def test_production_otp_rate_limit_returns_retry_after(monkeypatch):
    monkeypatch.setenv("WT_AUTH_ENV", "production")
    monkeypatch.setattr(
        "api.main.check_shared_rate_limit",
        lambda *_args: (False, 42),
    )

    response = TestClient(app).post(
        "/api/auth/otp/request",
        json={"email": "throttled@example.com", "role": "ROLE_CUSTOMER"},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "42"


def test_forwarded_for_is_not_trusted_as_the_client_ip():
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"198.51.100.42")],
        "client": ("10.0.0.5", 1234),
        "server": ("localhost", 80),
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "query_string": b"",
    }

    assert _client_key(Request(scope)) == "10.0.0.5"


def test_auth_environment_falls_back_to_runtime_environment(monkeypatch):
    monkeypatch.delenv("WT_AUTH_ENV", raising=False)
    monkeypatch.setenv("WT_ENV", "production")

    assert _auth_environment() == "production"


def test_postgres_connection_translates_sqlite_style_placeholders():
    class FakeCursor:
        def execute(self, query, parameters):
            self.query = query
            self.parameters = parameters

        def close(self):
            pass

    class FakeConnection:
        def __init__(self):
            self.last_cursor = None

        def cursor(self, **_kwargs):
            self.last_cursor = FakeCursor()
            return self.last_cursor

        def close(self):
            pass

    raw_connection = FakeConnection()
    connection = _PostgresConnection(raw_connection)
    connection.execute("SELECT * FROM auth_users WHERE email = ?", ("user@example.com",))

    assert raw_connection.last_cursor.query == "SELECT * FROM auth_users WHERE email = %s"
    assert raw_connection.last_cursor.parameters == ("user@example.com",)



def test_logout_revokes_server_session(internal_session):
    client, _session = internal_session

    rejected = client.post("/api/auth/logout")
    assert rejected.status_code == 403

    csrf_token = client.get("/api/auth/csrf").headers["X-CSRF-Token"]
    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 204

    protected_response = client.get("/api/internal/mailboxes/health")
    assert protected_response.status_code == 401


def test_auth_database_migrates_legacy_challenges_with_consumption_state(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy-auth.db"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            """CREATE TABLE otp_challenges (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                role TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                request_window_started INTEGER NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 1,
                locked_until INTEGER
            )"""
        )
        connection.commit()

    monkeypatch.setattr(auth, "AUTH_DB_PATH", str(database_path))
    auth.init_auth_db()

    with closing(sqlite3.connect(database_path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(otp_challenges)")}
    assert "consumed_at" in columns
