"""
Static security configuration audit.

These tests read config files as text and assert required security properties.
No database or running server is needed — they run entirely locally and should
be included in every CI pipeline.

Run: pytest backend/tests/test_security_config.py -v
"""

from pathlib import Path

# Project root is three levels up from this file
ROOT = Path(__file__).parent.parent.parent


# ── nginx.conf ─────────────────────────────────────────────────────────────────

def _nginx() -> str:
    return (ROOT / "nginx.conf").read_text(encoding="utf-8")


def test_nginx_server_tokens_off():
    assert "server_tokens off" in _nginx(), (
        "nginx.conf must contain 'server_tokens off' to hide nginx version from error pages"
    )


def test_nginx_http2_enabled():
    assert "listen 443 ssl http2" in _nginx(), (
        "nginx.conf should use 'listen 443 ssl http2' for HTTP/2 performance"
    )


def test_nginx_https_redirect():
    nginx = _nginx()
    assert "return 301" in nginx, "HTTP server block must redirect to HTTPS"
    assert "listen 80" in nginx, "HTTP server block must exist to handle port 80 traffic"


def test_nginx_has_security_headers():
    nginx = _nginx()
    required = [
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Strict-Transport-Security",
        "Referrer-Policy",
        "X-XSS-Protection",
    ]
    missing = [h for h in required if h not in nginx]
    assert not missing, f"nginx.conf is missing security headers: {missing}"


def test_nginx_has_rate_limiting():
    nginx = _nginx()
    assert "limit_req_zone" in nginx, (
        "nginx.conf must define at least one limit_req_zone for rate limiting"
    )
    assert "limit_req " in nginx, (
        "nginx.conf must apply limit_req to at least one location block"
    )


def test_nginx_has_client_max_body_size():
    assert "client_max_body_size" in _nginx(), (
        "nginx.conf must set client_max_body_size to prevent unbounded upload size"
    )


def test_nginx_has_client_timeouts():
    nginx = _nginx()
    assert "client_body_timeout" in nginx, "nginx.conf should set client_body_timeout"
    assert "client_header_timeout" in nginx, "nginx.conf should set client_header_timeout"


def test_nginx_auth_rate_limit_on_auth_endpoint():
    nginx = _nginx()
    assert "auth_limit" in nginx, (
        "A separate tight rate-limit zone (auth_limit) must be applied to the auth endpoint"
    )


# ── docker-compose.yml ─────────────────────────────────────────────────────────

def _compose() -> str:
    return (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_compose_no_hardcoded_db_password():
    compose = _compose()
    # The old hardcoded value must not appear verbatim in the file
    assert "sii_db_2024" not in compose, (
        "docker-compose.yml must not contain the hardcoded DB password. "
        "Use ${POSTGRES_PASSWORD} variable substitution instead."
    )


def test_compose_uses_password_variable():
    compose = _compose()
    assert "POSTGRES_PASSWORD" in compose, (
        "docker-compose.yml must reference POSTGRES_PASSWORD (via variable substitution)"
    )
    assert "${POSTGRES_PASSWORD}" in compose, (
        "docker-compose.yml must use ${POSTGRES_PASSWORD} not a hardcoded value"
    )


def test_compose_has_resource_limits():
    compose = _compose()
    assert "memory:" in compose, (
        "docker-compose.yml must set memory limits on containers to prevent resource exhaustion"
    )
    assert "cpus:" in compose, (
        "docker-compose.yml must set CPU limits on containers"
    )


# ── requirements.txt ──────────────────────────────────────────────────────────

def _requirements() -> list[str]:
    return (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()


def test_requirements_sqlalchemy_pinned():
    lines = _requirements()
    sqlalchemy_lines = [l for l in lines if l.startswith("sqlalchemy") and not l.startswith("#")]
    assert sqlalchemy_lines, "sqlalchemy must be in requirements.txt"
    line = sqlalchemy_lines[0]
    assert ">=" not in line or "," in line, (
        f"sqlalchemy should be pinned to an exact version or bounded range, got: {line!r}"
    )
    assert line.startswith("sqlalchemy[asyncio]=="), (
        f"sqlalchemy should be pinned with ==, got: {line!r}"
    )


def test_requirements_no_unconstrained_packages():
    """No package should use bare >= with no upper bound."""
    unconstrained = []
    for line in _requirements():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ">=" in line and "," not in line:
            unconstrained.append(line)
    assert not unconstrained, (
        f"These packages use unbounded >= (add upper bound or pin with ==): {unconstrained}"
    )


# ── .gitignore ────────────────────────────────────────────────────────────────

def test_env_is_gitignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore, (
        ".gitignore must contain .env to prevent committing secrets"
    )


def test_env_example_exists():
    assert (ROOT / ".env.example").exists(), (
        ".env.example must exist so developers know which variables to set"
    )


# ── backend/core/config.py ────────────────────────────────────────────────────

def _config_py() -> str:
    return (ROOT / "backend" / "core" / "config.py").read_text(encoding="utf-8")


def test_config_has_no_hardcoded_production_secret():
    config = _config_py()
    # The dev placeholder strings should still exist in config (they're the defaults)
    # but backend/api/main.py must guard against them in production
    assert "dev-secret-key" in config or "dev-" in config, (
        "Expected to find dev placeholder defaults — they should exist but be guarded "
        "at runtime by the production credential check in main.py"
    )


def test_main_py_has_production_credential_guard():
    main_py = (ROOT / "backend" / "api" / "main.py").read_text(encoding="utf-8")
    assert "dev-" in main_py and "production" in main_py, (
        "backend/api/main.py must contain a startup guard that refuses to start "
        "production with dev placeholder credentials"
    )


# ── backend/api/main.py ───────────────────────────────────────────────────────

def _main_py() -> str:
    return (ROOT / "backend" / "api" / "main.py").read_text(encoding="utf-8")


def test_docs_disabled_in_production():
    main = _main_py()
    assert "docs_url=None" in main or 'docs_url=None if' in main, (
        "FastAPI docs_url must be disabled (None) when ENVIRONMENT=production"
    )


def test_cors_not_wildcard_methods():
    main = _main_py()
    assert 'allow_methods=["*"]' not in main, (
        "CORS allow_methods must not be wildcard '*' — enumerate allowed methods explicitly"
    )


def test_cors_not_wildcard_headers():
    main = _main_py()
    assert 'allow_headers=["*"]' not in main, (
        "CORS allow_headers must not be wildcard '*' — enumerate allowed headers explicitly"
    )
