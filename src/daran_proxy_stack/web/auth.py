"""Web panel authentication utilities.

Pure stdlib implementation (no extra deps beyond FastAPI):
  - PBKDF2-SHA256 password hashing
  - HS256 JWT tokens via hmac + hashlib
  - Credential storage in auth-config.json

Usage:
    from daran_proxy_stack.web.auth import AuthManager
    auth = AuthManager(config_dir)
    token = auth.create_token("admin")
    payload = auth.verify_token(token)   # None if invalid/expired
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

_TOKEN_EXPIRE_HOURS = 24 * 7   # 7 days
_PBKDF2_ITERATIONS = 200_000
_AUTH_FILE = "auth-config.json"
_KEY_FILE = "panel-secret.key"


# ---------------------------------------------------------------------------
# Password hashing (PBKDF2-SHA256)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash password with PBKDF2-SHA256 + random salt."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"pbkdf2$sha256${salt}${_PBKDF2_ITERATIONS}${dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """Verify plain password against stored hash."""
    try:
        _, alg, salt, iters_str, dk_hex = stored.split("$")
        iters = int(iters_str)
        dk = hashlib.pbkdf2_hmac(alg, plain.encode(), salt.encode(), iters)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT (HS256, stdlib only)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (padding % 4))


def create_token(username: str, secret: str, expire_hours: int = _TOKEN_EXPIRE_HOURS) -> str:
    """Create a signed HS256 JWT token."""
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps({
        "sub": username,
        "exp": int(time.time()) + expire_hours * 3600,
        "iat": int(time.time()),
    }).encode())
    msg = f"{header}.{payload}"
    sig = _b64url_encode(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest())
    return f"{msg}.{sig}"


def verify_token(token: str, secret: str) -> dict | None:
    """Verify JWT signature and expiry. Returns payload dict or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, payload_b64, sig = parts
        msg = f"{header}.{payload_b64}"
        expected_sig = _b64url_encode(
            hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig, expected_sig):
            return None
        data = json.loads(_b64url_decode(payload_b64))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


# ---------------------------------------------------------------------------
# AuthManager — credential + secret storage
# ---------------------------------------------------------------------------

class AuthManager:
    """Manages credentials and JWT secret for the web panel."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = Path(config_dir)
        self._secret: str | None = None

    def _load_secret(self) -> str:
        """Load or generate the HMAC signing secret."""
        if self._secret:
            return self._secret
        key_file = self.config_dir / _KEY_FILE
        if key_file.exists():
            self._secret = key_file.read_text(encoding="utf-8").strip()
        else:
            self._secret = secrets.token_hex(32)
            self.config_dir.mkdir(parents=True, exist_ok=True)
            key_file.write_text(self._secret, encoding="utf-8")
            try:
                os.chmod(key_file, 0o600)
            except Exception:
                pass
        return self._secret

    # ── Credentials ──────────────────────────────────────────────────────────

    def has_credentials(self) -> bool:
        return (self.config_dir / _AUTH_FILE).exists()

    def load_credentials(self) -> dict | None:
        path = self.config_dir / _AUTH_FILE
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_credentials(self, username: str, password: str) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        data = {"username": username, "password_hash": hash_password(password)}
        path = self.config_dir / _AUTH_FILE
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass

    # ── Token management ─────────────────────────────────────────────────────

    def create_token(self, username: str) -> str:
        return create_token(username, self._load_secret())

    def verify_token(self, token: str) -> dict | None:
        return verify_token(token, self._load_secret())

    # ── Login logic ──────────────────────────────────────────────────────────

    def authenticate(self, username: str, password: str) -> bool:
        creds = self.load_credentials()
        if not creds:
            return False
        if creds.get("username") != username:
            return False
        return verify_password(password, creds.get("password_hash", ""))

    def change_password(self, username: str, new_password: str) -> None:
        self.save_credentials(username, new_password)
