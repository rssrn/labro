"""Cloudflare R2 upload via hand-rolled AWS SigV4 (S3-compatible API).

No external dependencies — uses only stdlib hmac/hashlib/urllib.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import hashlib
import hmac
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime


def _sign(key: bytes, msg: str) -> bytes:
    """HMAC-SHA256 of *msg* using *key*."""
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    """Derive the SigV4 signing key via 4 chained HMAC-SHA256 rounds."""
    k_date = _sign(("AWS4" + secret).encode(), date)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _put_object(
    *,
    endpoint: str,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
    access_key_id: str,
    secret_access_key: str,
    cache_control: str | None = None,
) -> None:
    """PUT *body* to R2 (S3-compatible) with SigV4 auth.

    This is the single network seam — mock ``labro.r2._put_object`` in tests.
    Raises RuntimeError on any HTTP error.
    """
    region = "auto"
    service = "s3"

    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    host = endpoint.removeprefix("https://").removeprefix("http://")
    payload_hash = _sha256_hex(body)

    # Canonical headers (sorted, lowercase)
    canonical_headers_map: dict[str, str] = {
        "content-type": content_type,
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if cache_control is not None:
        canonical_headers_map["cache-control"] = cache_control

    signed_header_names = sorted(canonical_headers_map)
    canonical_headers = "".join(f"{k}:{canonical_headers_map[k]}\n" for k in signed_header_names)
    signed_headers = ";".join(signed_header_names)

    canonical_uri = f"/{bucket}/{key}"
    canonical_request = "\n".join(
        [
            "PUT",
            canonical_uri,
            "",  # no query string
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            _sha256_hex(canonical_request.encode()),
        ]
    )

    signing_key = _signing_key(secret_access_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    url = f"{endpoint}/{bucket}/{key}"
    req_headers = {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if cache_control is not None:
        req_headers["Cache-Control"] = cache_control

    req = urllib.request.Request(url, data=body, method="PUT", headers=req_headers)
    try:
        with urllib.request.urlopen(req):
            pass
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode() if exc.fp else ""
        raise RuntimeError(f"R2 PUT {url} returned HTTP {exc.code}: {body_text}") from exc


@dataclass(frozen=True)
class R2Credentials:
    """Cloudflare R2 credentials and endpoint config."""

    access_key_id: str
    secret_access_key: str
    account_id: str
    endpoint: str  # e.g. https://<account>.r2.cloudflarestorage.com


def credentials_from_env() -> R2Credentials:
    """Build R2Credentials from environment variables.

    Required: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID.
    Raises KeyError if any are missing.
    """
    access_key_id = os.environ["R2_ACCESS_KEY_ID"]
    secret_access_key = os.environ["R2_SECRET_ACCESS_KEY"]
    account_id = os.environ["R2_ACCOUNT_ID"]
    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    return R2Credentials(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        account_id=account_id,
        endpoint=endpoint,
    )


def upload_snapshot(
    creds: R2Credentials,
    *,
    db_path: str,
    db_key: str,
    bucket: str,
) -> None:
    """Upload a DB snapshot file to R2 with immutable cache headers."""
    with open(db_path, "rb") as f:
        body = f.read()
    _put_object(
        endpoint=creds.endpoint,
        bucket=bucket,
        key=db_key,
        body=body,
        content_type="application/octet-stream",
        access_key_id=creds.access_key_id,
        secret_access_key=creds.secret_access_key,
        cache_control="public, max-age=31536000, immutable",
    )


def upload_manifest(
    creds: R2Credentials,
    *,
    manifest: bytes,
    bucket: str,
    key: str = "manifest.json",
) -> None:
    """Upload manifest.json to R2 with short-lived cache headers."""
    _put_object(
        endpoint=creds.endpoint,
        bucket=bucket,
        key=key,
        body=manifest,
        content_type="application/json",
        access_key_id=creds.access_key_id,
        secret_access_key=creds.secret_access_key,
        cache_control="public, max-age=60, must-revalidate",
    )
