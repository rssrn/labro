"""GitHub App authentication: JWT generation and installation token retrieval.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from base64 import urlsafe_b64encode
from typing import Any


def _b64url(data: bytes) -> bytes:
    """URL-safe base64 encode without padding (RFC 7515)."""
    return urlsafe_b64encode(data).rstrip(b"=")


def _rsa_sha256_sign(message: bytes, private_key_pem: str) -> bytes:
    """Sign *message* with RSA-SHA256 using the PEM-encoded private key."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    raw_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    if not isinstance(raw_key, RSAPrivateKey):
        raise ValueError("GitHub App private key must be an RSA key")
    result: bytes = raw_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return result


def generate_jwt(app_id: int, private_key_pem: str) -> str:
    """Generate a GitHub App JWT valid for ~10 minutes.

    The ``iat`` claim is backdated 60 s to tolerate minor clock drift.
    """
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"iat": now - 60, "exp": now + 540, "iss": str(app_id)}).encode())
    signing_input = header + b"." + payload
    signature = _b64url(_rsa_sha256_sign(signing_input, private_key_pem))
    return (signing_input + b"." + signature).decode()


def _api_get(url: str, jwt: str) -> dict[str, Any]:
    """GET a GitHub REST API endpoint authenticated with *jwt*."""
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "labro/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode() if exc.fp else ""
        raise RuntimeError(f"GitHub API GET {url} returned HTTP {exc.code}: {body}") from exc


def _api_post(url: str, jwt: str) -> dict[str, Any]:
    """POST to a GitHub REST API endpoint authenticated with *jwt*."""
    req = urllib.request.Request(
        url,
        method="POST",
        data=b"{}",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "labro/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode() if exc.fp else ""
        raise RuntimeError(f"GitHub API POST {url} returned HTTP {exc.code}: {body}") from exc


def get_installation_token(app_id: int, private_key_pem: str, repo: str) -> str:
    """Return an installation access token for *repo*.

    *private_key_pem* is the RSA private key as a PEM string (the caller
    resolves whether it came from an env var or a file).  Generates a JWT,
    resolves the installation ID for *repo*, and exchanges it for an access
    token (``ghs_``-prefixed, valid for 1 hour).

    Raises:
        RuntimeError: if the GitHub API calls fail or return unexpected data.
        ValueError: if the private key is not an RSA key.
    """
    jwt = generate_jwt(app_id, private_key_pem)

    installation = _api_get(f"https://api.github.com/repos/{repo}/installation", jwt)
    installation_id = installation.get("id")
    if not isinstance(installation_id, int):
        raise RuntimeError(f"Unexpected installation response for {repo}: {installation}")

    token_data = _api_post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens", jwt
    )
    token = token_data.get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"Unexpected token response: {token_data}")
    return token
