# SPDX-License-Identifier: Apache-2.0
"""Passport browser authentication and machine API-key utilities."""

import hashlib
import os
from pathlib import Path
import secrets
import stat
from typing import Optional

from fastapi import HTTPException, Request
from floated_claim.passport_exchange import (
    PassportClientError,
    PassportExchangeClient,
    delete_service_session_cookie,
    service_session_cookie_name,
    set_service_session_cookie,
)

# Global settings getter (set by init_auth)
_get_global_settings = None
_passport_client: PassportExchangeClient | None = None


def _client_config() -> dict[str, str]:
    secret_file = os.environ.get(
        "OMLX_PASSPORT_CLIENT_SECRET_FILE",
        str(Path.home() / ".omlx" / "passport-client.secret"),
    )
    path = Path(secret_file).expanduser()
    try:
        mode = path.stat().st_mode
    except OSError:
        return {}
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PassportClientError()
    return {
        "PASSPORT_AUTH_ORIGIN": os.environ.get(
            "OMLX_PASSPORT_ORIGIN", "https://id.bunrin.work"
        ),
        "PASSPORT_AUTH_CLIENT_ID": os.environ.get(
            "OMLX_PASSPORT_CLIENT_ID", "omlx"
        ),
        "PASSPORT_AUTH_CLIENT_ORIGIN": os.environ.get(
            "OMLX_PASSPORT_CLIENT_ORIGIN", "http://localhost:8000"
        ),
        "PASSPORT_AUTH_CLIENT_SECRET_FILE": str(path),
    }


def init_auth(global_settings_getter=None) -> None:
    """Load the server-only Passport client without creating a local issuer."""
    global _get_global_settings, _passport_client
    _get_global_settings = global_settings_getter
    config = _client_config()
    _passport_client = PassportExchangeClient.from_config(config) if config else None


def passport_client() -> PassportExchangeClient | None:
    return _passport_client


def cookie_secure() -> bool:
    return bool(_passport_client and _passport_client.client_origin.startswith("https://"))


def safe_admin_path(value: str | None) -> str:
    if (not value or not value.startswith("/admin") or value.startswith("//")
            or "\\" in value or "\r" in value or "\n" in value):
        return "/admin/dashboard"
    return value


def compare_keys(provided_key: str, expected_key: str) -> bool:
    """Compare two API keys in constant time, tolerating any str input.

    secrets.compare_digest raises TypeError when given str arguments that
    contain non-ASCII characters, which turns a bad client key into an
    unhandled 500 instead of a 401. Comparing UTF-8 bytes accepts any
    input while keeping the constant-time guarantee. surrogatepass covers
    lone surrogates, which json.loads can produce from escape sequences
    and which strict UTF-8 encoding rejects.

    Both arguments must be str; None is the caller's responsibility.

    Args:
        provided_key: The key supplied by the client (untrusted).
        expected_key: The configured key to compare against.

    Returns:
        True if the keys match, False otherwise.
    """
    return secrets.compare_digest(
        provided_key.encode("utf-8", "surrogatepass"),
        expected_key.encode("utf-8", "surrogatepass"),
    )


def fingerprint_key(api_key: str) -> str:
    """Return a short, non-reversible fingerprint of an API key for logging.

    Logging a rejected key verbatim leaks the client's secret into the server
    log. A truncated SHA-256 digest lets operators correlate repeated
    rejections of the same key without exposing the key itself. surrogatepass
    matches compare_keys() so any str the auth path accepts can be
    fingerprinted, including lone surrogates from json escape sequences.

    Args:
        api_key: The (untrusted) key to fingerprint. Empty string is allowed.

    Returns:
        The first 8 hex characters of the SHA-256 digest of the UTF-8 bytes.
    """
    digest = hashlib.sha256(api_key.encode("utf-8", "surrogatepass")).hexdigest()
    return digest[:8]


def verify_api_key(api_key: str, server_api_key: str) -> bool:
    """Verify an API key using constant-time comparison.

    This function uses constant-time comparison to prevent timing attacks
    when comparing the provided API key with the server's API key.

    Args:
        api_key: The API key provided by the client.
        server_api_key: The server's configured API key.

    Returns:
        True if the API keys match, False otherwise.

    Example:
        >>> verify_api_key("secret123", "secret123")
        True
        >>> verify_api_key("wrong", "secret123")
        False
    """
    if not api_key or not server_api_key:
        return False
    return compare_keys(api_key, server_api_key)


def verify_any_api_key(api_key: str, main_key: str, sub_keys: list) -> bool:
    """Verify an API key against the main key and all sub keys.

    Uses constant-time comparison for each key to prevent timing attacks.
    Checks the main key first, then iterates through sub keys.

    Args:
        api_key: The API key provided by the client.
        main_key: The server's main API key.
        sub_keys: List of SubKeyEntry objects with .key attribute.

    Returns:
        True if the API key matches any configured key, False otherwise.
    """
    if not api_key:
        return False
    # Check main key
    if main_key and compare_keys(api_key, main_key):
        return True
    # Check sub keys
    for sk in sub_keys:
        if sk.key and compare_keys(api_key, sk.key):
            return True
    return False


def validate_api_key(api_key: str) -> tuple[bool, str]:
    """Validate API key format requirements.

    Rules:
    - Minimum 4 characters
    - No whitespace characters (space, tab, newline, etc.)
    - Printable characters only (no control characters)
    - ASCII characters only

    The ASCII-only rule is not cosmetic: HTTP request headers are decoded as
    latin-1 by the ASGI layer, so a client cannot transmit a non-ASCII key
    intact. A configured key such as "café" therefore starts the server
    fine but can never be matched over the wire, yielding silent 401s on every
    authenticated request. Rejecting it at configuration time surfaces the
    misconfiguration immediately instead.

    Args:
        api_key: The API key string to validate.

    Returns:
        Tuple of (is_valid, error_message). Error message is empty if valid.
    """
    if len(api_key) < 4:
        return False, "API key must be at least 4 characters"
    if any(c.isspace() for c in api_key):
        return False, "API key must not contain whitespace"
    if not api_key.isprintable():
        return False, "API key must contain only printable characters"
    if not api_key.isascii():
        return False, "API key must contain only ASCII characters"
    return True, ""


async def verify_session(request: Request) -> bool:
    """Ask Passport for the current client-bound authorization decision."""
    client = passport_client()
    if client is None:
        return False
    token = request.cookies.get(service_session_cookie_name(secure=cookie_secure()))
    if not token:
        return False
    try:
        session = await client.validate_session(token=token)
    except PassportClientError:
        return False
    if not session.authorized:
        return False
    request.state.passport_session = session
    return True


async def require_admin(request: Request) -> bool:
    """FastAPI dependency to require admin authentication.

    This dependency can be used in route definitions to protect
    admin-only endpoints. It checks for a valid session cookie.

    Args:
        request: The FastAPI request object (injected by FastAPI).

    Returns:
        True if authentication is successful.

    Raises:
        HTTPException: 401 Unauthorized if not authenticated.

    Example:
        >>> from fastapi import Depends
        >>> @app.get("/admin/settings")
        ... async def get_settings(is_admin: bool = Depends(require_admin)):
        ...     return {"settings": "..."}
    """
    authorization = request.headers.get("authorization", "")
    machine_authorized = False
    if authorization.startswith("Bearer ") and _get_global_settings is not None:
        settings = _get_global_settings()
        configured = settings.auth.api_key if settings is not None else None
        supplied = authorization[len("Bearer "):].strip()
        machine_authorized = bool(
            configured and supplied and verify_api_key(supplied, configured)
        )
    if not machine_authorized and not await verify_session(request):
        # Browser requests (Accept: text/html) get redirected to login page
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            raise _RedirectToLogin()
        raise HTTPException(
            status_code=401,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return True


class _RedirectToLogin(Exception):
    """Raised to trigger a redirect to the admin login page."""
    pass
