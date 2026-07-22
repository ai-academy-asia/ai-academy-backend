"""Thin S3 wrapper. Credentials come from boto3's default chain (env vars,
shared profile, or the EC2 instance role in prod) — never hard-coded."""
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app

_client = None


class S3StorageError(Exception):
    """Raised on any storage failure (upload/download/delete)."""


def _s3():
    global _client
    if _client is None:
        _client = boto3.client("s3", region_name=current_app.config["AWS_REGION"])
    return _client


def build_key(*parts: str) -> str:
    """Join key parts under the configured prefix, e.g.
    build_key('courses', '3', 'cert_template.pdf')."""
    prefix = current_app.config.get("S3_PREFIX", "") or ""
    segments = [p.strip("/") for p in (prefix, *parts) if p and p.strip("/")]
    return "/".join(segments)


def upload_fileobj(fileobj, key: str, content_type: str = None) -> None:
    extra = {"ContentType": content_type} if content_type else {}
    try:
        _s3().upload_fileobj(
            fileobj, current_app.config["S3_BUCKET"], key, ExtraArgs=extra
        )
    except (BotoCoreError, ClientError) as exc:
        raise S3StorageError(f"upload failed: {exc}") from exc


def download_stream(key: str):
    """Return a streaming body for ``key`` (a file-like with .read())."""
    try:
        obj = _s3().get_object(Bucket=current_app.config["S3_BUCKET"], Key=key)
        return obj["Body"], obj.get("ContentType")
    except (BotoCoreError, ClientError) as exc:
        raise S3StorageError(f"download failed: {exc}") from exc


def presigned_url(key: str, expires: int = 300) -> str:
    """Short-lived GET URL — lets a client download straight from S3."""
    try:
        return _s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": current_app.config["S3_BUCKET"], "Key": key},
            ExpiresIn=expires,
        )
    except (BotoCoreError, ClientError) as exc:
        raise S3StorageError(f"presign failed: {exc}") from exc


def delete_object(key: str) -> None:
    try:
        _s3().delete_object(Bucket=current_app.config["S3_BUCKET"], Key=key)
    except (BotoCoreError, ClientError) as exc:
        raise S3StorageError(f"delete failed: {exc}") from exc
