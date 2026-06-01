"""Tests for labro.github_app — JWT generation and installation token retrieval.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
from base64 import urlsafe_b64decode
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from labro.github_app import generate_jwt, get_installation_token

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rsa_private_key_pem() -> str:
    """Generate a 2048-bit RSA private key PEM for testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem: bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode()


def _decode_b64url(s: str) -> bytes:
    padded = s + "=" * (4 - len(s) % 4)
    return urlsafe_b64decode(padded)


# ── generate_jwt ──────────────────────────────────────────────────────────────


class TestGenerateJwt:
    def test_produces_three_part_jwt(self, rsa_private_key_pem: str) -> None:
        jwt = generate_jwt(12345, rsa_private_key_pem)
        assert len(jwt.split(".")) == 3

    def test_header_is_rs256(self, rsa_private_key_pem: str) -> None:
        jwt = generate_jwt(12345, rsa_private_key_pem)
        header = json.loads(_decode_b64url(jwt.split(".")[0]))
        assert header["alg"] == "RS256"
        assert header["typ"] == "JWT"

    def test_payload_contains_iss_and_exp(self, rsa_private_key_pem: str) -> None:
        jwt = generate_jwt(42, rsa_private_key_pem)
        payload = json.loads(_decode_b64url(jwt.split(".")[1]))
        assert payload["iss"] == "42"
        assert "exp" in payload
        assert "iat" in payload
        assert payload["exp"] > payload["iat"]

    def test_non_rsa_key_raises_value_error(self) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        with pytest.raises(ValueError, match="RSA"):
            generate_jwt(1, pem)


# ── get_installation_token ────────────────────────────────────────────────────


class TestGetInstallationToken:
    def test_returns_token_on_success(self) -> None:
        with (
            patch("labro.github_app.generate_jwt", return_value="fakejwt"),
            patch("labro.github_app._api_get", return_value={"id": 999}),
            patch("labro.github_app._api_post", return_value={"token": "ghs_testtoken"}),
        ):
            result = get_installation_token(12345, "fake-pem", "my-org/my-repo")

        assert result == "ghs_testtoken"

    def test_missing_installation_id_raises(self) -> None:
        with (
            patch("labro.github_app.generate_jwt", return_value="fakejwt"),
            patch("labro.github_app._api_get", return_value={"not_id": "x"}),
        ):
            with pytest.raises(RuntimeError, match="installation response"):
                get_installation_token(12345, "fake-pem", "my-org/my-repo")

    def test_missing_token_in_response_raises(self) -> None:
        with (
            patch("labro.github_app.generate_jwt", return_value="fakejwt"),
            patch("labro.github_app._api_get", return_value={"id": 999}),
            patch("labro.github_app._api_post", return_value={"not_token": "x"}),
        ):
            with pytest.raises(RuntimeError, match="token response"):
                get_installation_token(12345, "fake-pem", "my-org/my-repo")

    def test_api_get_error_propagates(self) -> None:
        with (
            patch("labro.github_app.generate_jwt", return_value="fakejwt"),
            patch("labro.github_app._api_get", side_effect=RuntimeError("HTTP 404")),
        ):
            with pytest.raises(RuntimeError, match="HTTP 404"):
                get_installation_token(12345, "fake-pem", "my-org/my-repo")

    def test_pem_passed_to_generate_jwt(self, rsa_private_key_pem: str) -> None:
        """Verify the PEM string is forwarded directly to generate_jwt."""
        calls: list[str] = []

        def fake_generate_jwt(app_id: int, pem: str) -> str:
            calls.append(pem)
            return "fakejwt"

        with (
            patch("labro.github_app.generate_jwt", side_effect=fake_generate_jwt),
            patch("labro.github_app._api_get", return_value={"id": 1}),
            patch("labro.github_app._api_post", return_value={"token": "ghs_x"}),
        ):
            get_installation_token(99, rsa_private_key_pem, "o/r")

        assert calls[0] == rsa_private_key_pem
