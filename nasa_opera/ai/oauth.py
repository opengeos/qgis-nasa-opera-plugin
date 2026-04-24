"""
OAuth PKCE Flow for NASA OPERA Plugin.

Implements OAuth 2.0 Authorization Code Flow with PKCE for authenticating
with Claude Code and OpenAI Codex. Uses a local HTTP server to receive
the authorization callback.
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import urllib.parse
from typing import Callable, Dict, Optional, Tuple

from qgis.PyQt.QtCore import QSettings, QUrl
from qgis.PyQt.QtGui import QDesktopServices

# OAuth configuration per provider
# These endpoints should be updated when official OAuth endpoints are available
OAUTH_CONFIG = {
    "anthropic": {
        "auth_url": "https://console.anthropic.com/oauth/authorize",
        "token_url": "https://console.anthropic.com/oauth/token",  # nosec B105
        "client_id": "",
        "scope": "api",
    },
    "openai": {
        "auth_url": "https://platform.openai.com/oauth/authorize",
        "token_url": "https://platform.openai.com/oauth/token",  # nosec B105
        "client_id": "",
        "scope": "api",
    },
}


def _require_https(url: str) -> None:
    """Reject any URL that does not use the https scheme.

    Args:
        url: URL string to validate.

    Raises:
        ValueError: If the URL is not https.
    """
    if not url.lower().startswith("https://"):
        raise ValueError(f"Refusing non-https URL: {url!r}")


def _generate_pkce_pair() -> Tuple[str, str]:
    """Generate a PKCE code verifier and code challenge.

    Returns:
        Tuple of (code_verifier, code_challenge).
    """
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the OAuth callback."""

    def do_GET(self):
        """Handle the OAuth callback GET request."""
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        self.server.oauth_code = params.get("code", [None])[0]
        self.server.oauth_state = params.get("state", [None])[0]
        self.server.oauth_error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        if self.server.oauth_code:
            body = (
                "<html><body><h2>Authentication successful!</h2>"
                "<p>You can close this window and return to QGIS.</p>"
                "</body></html>"
            )
        else:
            error = self.server.oauth_error or "Unknown error"
            body = (
                f"<html><body><h2>Authentication failed</h2>"
                f"<p>Error: {error}</p>"
                f"<p>Please close this window and try again.</p>"
                f"</body></html>"
            )

        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass


class OAuthFlow:
    """Manages OAuth 2.0 PKCE authorization flow."""

    SETTINGS_PREFIX = "NasaOpera/"

    def __init__(self, provider: str):
        """Initialize the OAuth flow.

        Args:
            provider: Provider name ('anthropic' or 'openai').
        """
        self.provider = provider.lower()
        self.settings = QSettings()
        self._server = None
        self._server_thread = None

    def start_flow(
        self,
        callback: Optional[Callable[[bool, str], None]] = None,
    ) -> Tuple[bool, str]:
        """Start the OAuth authorization flow.

        Opens the browser for user authorization and starts a local
        server to receive the callback.

        Args:
            callback: Optional callback(success, message) called when flow completes.

        Returns:
            Tuple of (success, message_or_token).
        """
        config = OAUTH_CONFIG.get(self.provider)
        if not config:
            return False, f"OAuth not configured for provider: {self.provider}"

        if not config["client_id"]:
            return False, (
                f"OAuth client_id not configured for {self.provider}. "
                "Please use API key authentication instead, or update "
                "the OAuth configuration with your client credentials."
            )

        # Generate PKCE pair
        code_verifier, code_challenge = _generate_pkce_pair()
        state = secrets.token_urlsafe(32)

        # Start local callback server
        try:
            self._server = http.server.HTTPServer(("localhost", 0), _CallbackHandler)
            port = self._server.server_address[1]
            redirect_uri = f"http://localhost:{port}/callback"

            self._server.oauth_code = None
            self._server.oauth_state = None
            self._server.oauth_error = None
        except OSError as e:
            return False, f"Failed to start callback server: {e}"

        # Build authorization URL
        params = {
            "response_type": "code",
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri,
            "scope": config["scope"],
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{config['auth_url']}?{urllib.parse.urlencode(params)}"

        # Open browser
        QDesktopServices.openUrl(QUrl(auth_url))

        # Wait for callback in a thread
        def wait_for_callback():
            self._server.handle_request()  # Handle single request

        self._server_thread = threading.Thread(target=wait_for_callback)
        self._server_thread.daemon = True
        self._server_thread.start()
        self._server_thread.join(timeout=120)  # 2 minute timeout

        if not self._server.oauth_code:
            error = self._server.oauth_error or "Timed out waiting for authorization"
            if callback:
                callback(False, error)
            return False, error

        if self._server.oauth_state != state:
            msg = "State mismatch -- possible CSRF attack"
            if callback:
                callback(False, msg)
            return False, msg

        # Exchange code for token
        success, result = self._exchange_code(
            self._server.oauth_code,
            code_verifier,
            redirect_uri,
            config,
        )

        if callback:
            callback(success, result)

        return success, result

    def _exchange_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        config: Dict,
    ) -> Tuple[bool, str]:
        """Exchange authorization code for access token.

        Args:
            code: Authorization code from callback.
            code_verifier: PKCE code verifier.
            redirect_uri: Redirect URI used in the authorization request.
            config: OAuth provider configuration.

        Returns:
            Tuple of (success, token_or_error_message).
        """
        import urllib.request

        data = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": config["client_id"],
                "code_verifier": code_verifier,
            }
        ).encode("utf-8")

        _require_https(config["token_url"])
        req = urllib.request.Request(
            config["token_url"],
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:  # nosec B310
                token_data = json.loads(response.read().decode("utf-8"))
        except Exception as e:
            return False, f"Token exchange failed: {e}"

        access_token = token_data.get("access_token")
        if not access_token:
            return False, "No access token in response"

        # Store token
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}ai_oauth_token_{self.provider}",
            access_token,
        )
        refresh_token = token_data.get("refresh_token")
        if refresh_token:
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}ai_oauth_refresh_{self.provider}",
                refresh_token,
            )

        return True, access_token

    def get_stored_token(self) -> Optional[str]:
        """Get a stored OAuth token for this provider.

        Returns:
            Access token string or None.
        """
        return self.settings.value(
            f"{self.SETTINGS_PREFIX}ai_oauth_token_{self.provider}",
            None,
            type=str,
        )

    def clear_token(self):
        """Remove stored OAuth tokens for this provider."""
        self.settings.remove(f"{self.SETTINGS_PREFIX}ai_oauth_token_{self.provider}")
        self.settings.remove(f"{self.SETTINGS_PREFIX}ai_oauth_refresh_{self.provider}")
