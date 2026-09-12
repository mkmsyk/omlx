# SPDX-License-Identifier: Apache-2.0
"""Tests for admin authentication and chat page API key injection."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from floated_claim.passport_exchange import PassportClientError, PassportSession
from starlette.responses import Response

import omlx.server  # noqa: F401 — ensure server module is imported first
import omlx.admin.auth as admin_auth
import omlx.admin.routes as admin_routes


def _mock_global_settings(api_key=None):
    """Create a mock GlobalSettings with the given API key."""
    mock = MagicMock()
    mock.auth.api_key = api_key
    mock.auth.skip_api_key_verification = False
    return mock


def _patch_getter(mock_settings):
    """Replace the module-level _get_global_settings with a lambda returning mock."""
    original = admin_routes._get_global_settings
    admin_routes._get_global_settings = lambda: mock_settings
    return original


def _restore_getter(original):
    """Restore the original _get_global_settings."""
    admin_routes._get_global_settings = original


class FakePassport:
    def __init__(self, *, authorized=True):
        self.client_origin = "http://localhost:8000"
        self.authorized = authorized
        self.validated = None
        self.revoked = None

    def login_url(self, *, next_path):
        return f"https://id.bunrin.work/login?next={next_path}"

    async def redeem_ticket(self, *, ticket):
        if ticket != "ticket":
            raise PassportClientError()
        return PassportSession(
            "600f7f6d-dc60-4f20-bba1-0a91eb906d4b",
            self.authorized,
            "passport-token",
            4_000_000_000,
        )

    async def validate_session(self, *, token):
        self.validated = token
        return PassportSession(
            "600f7f6d-dc60-4f20-bba1-0a91eb906d4b",
            self.authorized,
            token,
            4_000_000_000,
        )

    async def revoke_session(self, *, token):
        self.revoked = token


class TestPassportRoutes:
    def test_api_key_browser_session_routes_are_absent(self):
        paths = {route.path for route in admin_routes.router.routes}
        assert "/admin/api/login" not in paths
        assert "/admin/auto-login" not in paths

    def test_login_uses_registered_client_and_sanitizes_next(self):
        passport = FakePassport()
        with patch.object(admin_routes, "passport_client", return_value=passport):
            result = asyncio.run(admin_routes.passport_login(next="//attacker.test"))
        assert result.status_code == 302
        assert result.headers["location"].endswith("next=/admin/dashboard")

    def test_callback_relays_passport_token(self):
        passport = FakePassport()
        with (
            patch.object(admin_routes, "passport_client", return_value=passport),
            patch.object(admin_routes, "cookie_secure", return_value=False),
        ):
            result = asyncio.run(
                admin_routes.passport_callback(ticket="ticket", next="/admin/chat")
            )
        assert result.headers["location"] == "/admin/chat"
        assert "bunrin_session=passport-token" in result.headers["set-cookie"]
        assert "omlx_admin_session" not in result.headers["set-cookie"]

    def test_callback_rejects_non_admin_decision(self):
        with patch.object(
            admin_routes, "passport_client", return_value=FakePassport(authorized=False)
        ):
            result = asyncio.run(admin_routes.passport_callback(ticket="ticket"))
        assert result.headers["location"] == "/admin?error=passport"
        assert "set-cookie" not in result.headers

    def test_logout_revokes_at_passport_and_clears_cookie(self):
        passport = FakePassport()
        request = MagicMock()
        request.cookies.get.return_value = "passport-token"
        response = MagicMock()
        with (
            patch.object(admin_routes, "passport_client", return_value=passport),
            patch.object(admin_routes, "cookie_secure", return_value=False),
        ):
            result = asyncio.run(admin_routes.logout(request, response))
        assert result == {"success": True}
        assert passport.revoked == "passport-token"
        response.delete_cookie.assert_called_once()


class TestLoginPage:
    """Tests for GET /admin login page TemplateResponse signature."""

    def test_login_page_uses_new_template_signature(self):
        """login_page should pass request as first arg to TemplateResponse."""
        mock_settings = _mock_global_settings(api_key="test-key")
        original = _patch_getter(mock_settings)
        try:
            mock_request = MagicMock()
            mock_request.query_params.get.return_value = None
            with (
                patch.object(admin_routes, "verify_session", new=AsyncMock(return_value=False)),
                patch.object(admin_routes, "passport_client", return_value=FakePassport()),
            ):
                with patch.object(admin_routes, "templates") as mock_templates:
                    mock_templates.TemplateResponse.return_value = MagicMock()
                    asyncio.run(admin_routes.login_page(request=mock_request))
                    mock_templates.TemplateResponse.assert_called_once_with(
                        mock_request,
                        "login.html",
                        {"passport_configured": True, "login_error": False},
                    )
        finally:
            _restore_getter(original)


class TestDashboardPage:
    """Tests for GET /admin/dashboard TemplateResponse signature."""

    def test_dashboard_page_uses_new_template_signature(self):
        """dashboard_page should pass request as first arg to TemplateResponse."""
        mock_request = MagicMock()
        with patch.object(admin_routes, "templates") as mock_templates:
            mock_templates.TemplateResponse.return_value = MagicMock()
            asyncio.run(
                admin_routes.dashboard_page(request=mock_request, is_admin=True)
            )
            mock_templates.TemplateResponse.assert_called_once_with(
                mock_request, "dashboard.html", {}
            )


class TestChatPageApiKeyInjection:
    """Tests for GET /admin/chat API key template injection."""

    def test_chat_page_passes_api_key_in_context(self):
        """Chat page should include API key in template context."""
        mock_settings = _mock_global_settings(api_key="test-chat-key")
        original = _patch_getter(mock_settings)
        try:
            mock_request = MagicMock()
            with patch.object(admin_routes, "templates") as mock_templates:
                mock_templates.TemplateResponse.return_value = MagicMock()
                asyncio.run(
                    admin_routes.chat_page(request=mock_request, is_admin=True)
                )
                mock_templates.TemplateResponse.assert_called_once_with(
                    mock_request,
                    "chat.html",
                    {"api_key": "test-chat-key"},
                )
        finally:
            _restore_getter(original)

    def test_chat_page_passes_empty_when_no_key(self):
        """Chat page should pass empty string when no API key is configured."""
        mock_settings = _mock_global_settings(api_key=None)
        original = _patch_getter(mock_settings)
        try:
            mock_request = MagicMock()
            with patch.object(admin_routes, "templates") as mock_templates:
                mock_templates.TemplateResponse.return_value = MagicMock()
                asyncio.run(
                    admin_routes.chat_page(request=mock_request, is_admin=True)
                )
                call_args = mock_templates.TemplateResponse.call_args
                context = call_args[0][2]
                assert context["api_key"] == ""
        finally:
            _restore_getter(original)

    def test_chat_page_passes_empty_when_no_settings(self):
        """Chat page should pass empty string when global settings is None."""
        original = admin_routes._get_global_settings
        admin_routes._get_global_settings = lambda: None
        try:
            mock_request = MagicMock()
            with patch.object(admin_routes, "templates") as mock_templates:
                mock_templates.TemplateResponse.return_value = MagicMock()
                asyncio.run(
                    admin_routes.chat_page(request=mock_request, is_admin=True)
                )
                call_args = mock_templates.TemplateResponse.call_args
                context = call_args[0][2]
                assert context["api_key"] == ""
        finally:
            admin_routes._get_global_settings = original


class TestPassportVerification:
    def test_verified_session_reissues_passport_cookie_with_expiry(self):
        request = MagicMock()
        request.state.passport_session = PassportSession(
            "600f7f6d-dc60-4f20-bba1-0a91eb906d4b", True, "passport-token", 4_000_000_000,
        )
        response = Response()
        with patch.object(admin_auth, "cookie_secure", return_value=False):
            admin_auth.renew_verified_session_cookie(request, response)
        cookie = response.headers["set-cookie"]
        assert "bunrin_session=passport-token" in cookie
        assert "Max-Age=" in cookie

    def test_require_admin_validates_with_passport_even_when_api_skip_is_enabled(self):
        passport = FakePassport()
        request = MagicMock()
        request.cookies.get.return_value = "passport-token"
        with (
            patch.object(admin_auth, "passport_client", return_value=passport),
            patch.object(admin_auth, "cookie_secure", return_value=False),
        ):
            assert asyncio.run(admin_auth.require_admin(request)) is True
        assert passport.validated == "passport-token"

    def test_missing_passport_session_is_unauthorized(self):
        request = MagicMock()
        request.cookies.get.return_value = None
        request.headers.get.return_value = "application/json"
        with patch.object(admin_auth, "passport_client", return_value=FakePassport()):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(admin_auth.require_admin(request))
        assert exc_info.value.status_code == 401

    def test_native_machine_bearer_does_not_create_or_validate_a_session(self):
        settings = _mock_global_settings(api_key="machine-key")
        request = MagicMock()
        request.headers.get.return_value = "Bearer machine-key"
        original = admin_auth._get_global_settings
        admin_auth._get_global_settings = lambda: settings
        try:
            with patch.object(admin_auth, "verify_session", new=AsyncMock()) as verify:
                assert asyncio.run(admin_auth.require_admin(request)) is True
                verify.assert_not_awaited()
        finally:
            admin_auth._get_global_settings = original

    def test_init_auth_requires_owner_only_secret_file(self, tmp_path, monkeypatch):
        secret = tmp_path / "passport.secret"
        secret.write_text("s" * 32, encoding="ascii")
        secret.chmod(0o600)
        monkeypatch.setenv("OMLX_PASSPORT_CLIENT_SECRET_FILE", str(secret))
        admin_auth.init_auth()
        assert admin_auth.passport_client() is not None
        assert admin_auth.passport_client().client_origin == "http://localhost:8000"

        secret.chmod(0o644)
        with pytest.raises(PassportClientError):
            admin_auth.init_auth()


# =============================================================================
# Update Check
# =============================================================================


def _make_async_return(value):
    """Create a coroutine function that returns the given value."""

    async def _coro(*args, **kwargs):
        return value

    return _coro


class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json


class TestCheckUpdate:
    """Tests for update-check version filtering."""

    def setup_method(self):
        admin_routes._update_cache = {}
        admin_routes._update_cache_time = {}
        admin_routes._UPDATE_PREFS_PATH = Path(
            "/tmp/omlx-test-missing-update-prefs.json"
        )

    @pytest.mark.asyncio
    async def test_prerelease_not_shown(self):
        """Dev/pre-release GitHub releases should not trigger update notification."""
        fake_resp = _FakeResponse(
            200,
            [{
                "tag_name": "v99.0.0.dev1",
                "html_url": "https://github.com/jundot/omlx/releases/tag/v99.0.0.dev1",
            }],
        )
        with patch("omlx.admin.routes.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _make_async_return(fake_resp)
            result = await admin_routes.check_update(is_admin=True)

        assert result["update_available"] is False
        assert result["latest_version"] is None

    @pytest.mark.asyncio
    async def test_stable_version_shown(self):
        """Stable GitHub releases should trigger update notification."""
        fake_resp = _FakeResponse(
            200,
            [{
                "tag_name": "v99.0.0",
                "html_url": "https://github.com/jundot/omlx/releases/tag/v99.0.0",
            }],
        )
        with patch("omlx.admin.routes.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _make_async_return(fake_resp)
            result = await admin_routes.check_update(is_admin=True)

        assert result["update_available"] is True
        assert result["latest_version"] == "99.0.0"

    @pytest.mark.asyncio
    async def test_rc_not_shown(self):
        """RC releases should not trigger update notification."""
        fake_resp = _FakeResponse(
            200,
            [{
                "tag_name": "v99.0.0rc1",
                "html_url": "https://github.com/jundot/omlx/releases/tag/v99.0.0rc1",
            }],
        )
        with patch("omlx.admin.routes.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = _make_async_return(fake_resp)
            result = await admin_routes.check_update(is_admin=True)

        assert result["update_available"] is False
        assert result["latest_version"] is None
