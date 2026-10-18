"""
POPCONE ORDER & SALES CRM - BACKUP & RECOVERY ENGINE (STAGE 1)
--------------------------------------------------------------
Implements:
1. Strict external S3 object storage (AWS S3, Cloudflare R2, MinIO, Wasabi).
   Fails explicitly if S3 is not configured (no silent local fallback).
2. Atomic distributed S3 locking using conditional creation (IfNoneMatch) and safe TTL expiry.
3. Consistent read snapshot across all Turso tables using libSQL atomic batch execution.
4. Separately versioned AES-256-GCM encryption (with fresh 96-bit random nonce per backup)
   and HMAC-SHA256 authenticity signatures over the entire envelope.
5. PII and secret protection: active sessions excluded, password hashes encrypted at rest.
6. Durable S3 manifests and metadata independent of production database state.
7. Two-tier offline verification:
   - Tier 1: Cryptographic envelope, HMAC authenticity, AES-GCM tag, and payload SHA-256.
   - Tier 2: Isolated in-memory SQLite sandbox replay, PRAGMA integrity_check,
             PRAGMA foreign_key_check, relational constraints, and schema parity.
8. Production restoration is explicitly disabled in Stage 1.
"""

import os
import json
import uuid
import hmac
import struct
import hashlib
import secrets
import sqlite3
import threading
import io
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Any, Optional

import boto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Magic marker for POPCONE CRM encrypted backup archives
BACKUP_MAGIC = b"POPC1BAK"
BACKUP_FORMAT_VERSION = "popcone_crm_backup_v1"
DEFAULT_LOCK_TTL_SECONDS = 300  # 5 minutes
LOCK_S3_KEY = "locks/backup_active.lock"
MANIFEST_S3_KEY = "manifests/backups_manifest.json"

# Google Drive Storage Constants (Free Personal Tier - 15 GB quota)
GDRIVE_DEFAULT_FOLDER = "POPCONE_BACKUPS"
GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
GDRIVE_LOCK_NAME = "backup_active.lock"
GDRIVE_MANIFEST_NAME = "backups_manifest.json"

# Stage 2 Safe Retention Pruning Defaults & Safety Floors
DEFAULT_RETENTION_DAYS = 30
MIN_ENFORCED_RETENTION_DAYS = 7  # Safety floor to protect against accidental 0-day configs
DEFAULT_MIN_BACKUPS_RETAINED = 3  # Minimum backups to always preserve regardless of age
MIN_ENFORCED_RETAINED_COUNT = 1


class BackupError(Exception):
    """Base exception for backup operations."""
    pass


class StorageConfigurationError(BackupError):
    """Raised when backup storage is not configured or invalid."""
    pass


class AuthenticationError(BackupError):
    """Raised when Google Drive authentication or token refresh fails."""
    pass


class QuotaExceededError(BackupError):
    """Raised when Google Drive free storage quota is exceeded."""
    pass


class ConcurrencyLockError(BackupError):
    """Raised when another backup job holds an active distributed lock."""
    pass


class BackupIntegrityError(BackupError):
    """Raised when cryptographic or relational verification fails."""
    pass


class RestorationDisabledError(BackupError):
    """Raised because production restoration is strictly disabled in Stage 1."""
    pass


# ---------------------------------------------------------------------------
# Configuration & Keyring Management
# ---------------------------------------------------------------------------

def _load_env_file_if_needed():
    """Load local .env if present and not already loaded."""
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


_load_env_file_if_needed()


# ---------------------------------------------------------------------------
# Google Drive Storage & Authentication (Primary)
# ---------------------------------------------------------------------------

def get_gdrive_config() -> Dict[str, Any]:
    """
    Retrieve and validate Google Drive OAuth configuration for the user's personal Google account.
    Fails explicitly if required credentials are not configured.
    """
    client_id = (os.environ.get("GDRIVE_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("GDRIVE_CLIENT_SECRET") or "").strip()
    refresh_token = (os.environ.get("GDRIVE_REFRESH_TOKEN") or "").strip()
    folder_id = (os.environ.get("GDRIVE_FOLDER_ID") or "").strip()
    sa_json = (os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON") or "").strip()

    placeholders = {
        "",
        "your_gdrive_client_id_here",
        "your_gdrive_client_secret_here",
        "your_gdrive_refresh_token_here",
        "changeme",
        "replace_me"
    }

    if client_id and client_secret and refresh_token and client_id not in placeholders:
        return {
            "type": "oauth",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "folder_id": folder_id if folder_id else None
        }

    if sa_json:
        return {
            "type": "service_account",
            "service_account_json": sa_json,
            "folder_id": folder_id if folder_id else None
        }

    raise StorageConfigurationError(
        "Google Drive storage is not configured. Please configure GDRIVE_CLIENT_ID, "
        "GDRIVE_CLIENT_SECRET, and GDRIVE_REFRESH_TOKEN in your environment. "
        "Run 'python scripts/setup_gdrive_auth.py' to generate your refresh token."
    )


def is_gdrive_configured() -> bool:
    """Check if Google Drive storage is configured without throwing an exception."""
    try:
        get_gdrive_config()
        return True
    except StorageConfigurationError:
        return False


def get_gdrive_credentials(cfg: Optional[Dict[str, Any]] = None):
    """
    Constructs Google OAuth 2.0 Credentials using the long-lived refresh token
    and automatically refreshes the access token if needed.
    """
    c = cfg or get_gdrive_config()
    if c.get("type") == "service_account":
        try:
            from google.oauth2.service_account import Credentials as SACredentials
            info = json.loads(c["service_account_json"])
            return SACredentials.from_service_account_info(info, scopes=GDRIVE_SCOPES)
        except Exception as e:
            raise AuthenticationError(f"Google Drive service account authentication failed: {e}")

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        creds = Credentials(
            None,
            refresh_token=c["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=c["client_id"],
            client_secret=c["client_secret"],
            scopes=GDRIVE_SCOPES
        )
        if not creds.valid:
            creds.refresh(Request())
        return creds
    except Exception as e:
        raise AuthenticationError(f"Google Drive authentication failed (refresh token error): {e}")


def get_gdrive_service(creds=None):
    """Builds an authenticated Google Drive v3 API resource client."""
    c = creds or get_gdrive_credentials()
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=c, cache_discovery=False)


def get_storage_provider() -> str:
    """
    Returns the active backup storage provider:
    - 'gdrive' (Primary: Google Drive personal free tier)
    - 's3' (Secondary: S3-compatible storage)
    - 'none' (Unconfigured)
    """
    if is_gdrive_configured():
        return "gdrive"
    if is_s3_configured():
        return "s3"
    return "none"


def is_storage_configured() -> bool:
    """Check if any valid backup storage provider is configured."""
    return get_storage_provider() != "none"


# ---------------------------------------------------------------------------
# S3 Storage & Keyring Management (Legacy / Secondary)
# ---------------------------------------------------------------------------

def get_s3_config() -> Dict[str, Any]:
    """
    Retrieve and validate S3 object storage configuration.
    Fails explicitly if required credentials/bucket are not set.
    """
    bucket = (os.environ.get("BACKUP_S3_BUCKET") or "").strip()
    access_key = (os.environ.get("BACKUP_S3_ACCESS_KEY_ID") or "").strip()
    secret_key = (os.environ.get("BACKUP_S3_SECRET_ACCESS_KEY") or "").strip()
    endpoint = (os.environ.get("BACKUP_S3_ENDPOINT") or "").strip()
    region = (os.environ.get("BACKUP_S3_REGION") or "auto").strip()

    placeholder_vals = {"", "your_s3_access_key_id", "your_s3_secret_access_key", "popcone-crm-backups-placeholder"}
    if not bucket or not access_key or not secret_key or access_key in placeholder_vals:
        raise StorageConfigurationError(
            "External S3 object storage is not configured. Backups cannot be created "
            "without durable external storage. Please configure BACKUP_S3_BUCKET, "
            "BACKUP_S3_ACCESS_KEY_ID, and BACKUP_S3_SECRET_ACCESS_KEY."
        )

    return {
        "bucket": bucket,
        "access_key": access_key,
        "secret_key": secret_key,
        "endpoint": endpoint if endpoint else None,
        "region": region if region else "auto"
    }


def is_s3_configured() -> bool:
    """Check if S3 storage is configured without throwing an exception."""
    try:
        get_s3_config()
        return True
    except StorageConfigurationError:
        return False


def get_s3_client(config: Optional[Dict[str, Any]] = None):
    """Initialize a boto3 S3 client with the configured endpoint and credentials."""
    cfg = config or get_s3_config()
    kwargs: Dict[str, Any] = {
        "aws_access_key_id": cfg["access_key"],
        "aws_secret_access_key": cfg["secret_key"],
    }
    if cfg.get("endpoint"):
        kwargs["endpoint_url"] = cfg["endpoint"]
    if cfg.get("region") and cfg["region"] != "auto":
        kwargs["region_name"] = cfg["region"]
    return boto3.client("s3", **kwargs)


def _parse_key_bytes(raw_val: str, key_name: str) -> bytes:
    """Helper to parse a 32-byte key from hex, base64, or raw bytes."""
    val = raw_val.strip()
    if not val or val in {"your_32_byte_aes_gcm_encryption_key_here", "your_32_byte_hmac_sha256_signing_key_here"}:
        raise StorageConfigurationError(f"Missing or placeholder secret key: {key_name}.")

    # Try hex
    try:
        k = bytes.fromhex(val)
        if len(k) == 32:
            return k
    except Exception:
        pass

    # Try base64
    import base64
    try:
        k = base64.b64decode(val)
        if len(k) == 32:
            return k
    except Exception:
        pass

    # Fallback to UTF-8 SHA-256 derivation if raw string
    return hashlib.sha256(val.encode("utf-8")).digest()


def get_crypto_keyring() -> Tuple[Dict[str, bytes], str, Dict[str, bytes], str]:
    """
    Returns (encryption_keyring, current_enc_id, signing_keyring, current_sign_id).
    Supports independent key versioning and future rotation.
    """
    enc_raw = os.environ.get("BACKUP_ENCRYPTION_KEY", "")
    sign_raw = os.environ.get("BACKUP_SIGNING_KEY", "")
    current_enc_id = os.environ.get("CURRENT_ENCRYPTION_KEY_ID", "enc_v1").strip()
    current_sign_id = os.environ.get("CURRENT_SIGNING_KEY_ID", "sign_v1").strip()

    enc_key = _parse_key_bytes(enc_raw, "BACKUP_ENCRYPTION_KEY")
    sign_key = _parse_key_bytes(sign_raw, "BACKUP_SIGNING_KEY")

    enc_keyring = {current_enc_id: enc_key}
    sign_keyring = {current_sign_id: sign_key}

    # Optional multi-key keyring from JSON if configured
    extra_enc = os.environ.get("BACKUP_ENCRYPTION_KEYRING_JSON")
    if extra_enc:
        try:
            for k_id, k_val in json.loads(extra_enc).items():
                enc_keyring[k_id] = _parse_key_bytes(k_val, f"KEYRING:{k_id}")
        except Exception:
            pass

    extra_sign = os.environ.get("BACKUP_SIGNING_KEYRING_JSON")
    if extra_sign:
        try:
            for k_id, k_val in json.loads(extra_sign).items():
                sign_keyring[k_id] = _parse_key_bytes(k_val, f"SIGN_KEYRING:{k_id}")
        except Exception:
            pass

    return enc_keyring, current_enc_id, sign_keyring, current_sign_id


# ---------------------------------------------------------------------------
# Atomic S3 Distributed Lock
# ---------------------------------------------------------------------------

class S3DistributedLock:
    """
    Distributed mutex lock stored in S3 to prevent concurrent or overlapping backups.
    Uses S3 conditional object creation (IfNoneMatch='*') for atomic acquisition.
    Uses conditional update (IfMatch=ETag) for atomic Compare-And-Swap (CAS) stale lock reclamation.
    Handles stale lock expiration safely if a previous worker crashed.
    Verifies lock ownership before release to prevent deleting another worker's lock.
    """

    def __init__(self, s3_client, bucket: str, initiated_by: str, ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS):
        self.s3 = s3_client
        self.bucket = bucket
        self.initiated_by = initiated_by
        self.ttl_seconds = ttl_seconds
        self.job_id = str(uuid.uuid4())
        self.acquired = False

    def acquire(self):
        now_utc = datetime.now(timezone.utc)
        expires_at = now_utc + timedelta(seconds=self.ttl_seconds)
        payload = {
            "job_id": self.job_id,
            "initiated_by": self.initiated_by,
            "created_at": now_utc.isoformat(),
            "expires_at": expires_at.isoformat(),
            "ttl_seconds": self.ttl_seconds
        }
        body = json.dumps(payload, indent=2).encode("utf-8")

        # 1. Attempt atomic creation with IfNoneMatch='*'
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=LOCK_S3_KEY,
                Body=body,
                ContentType="application/json",
                IfNoneMatch="*"
            )
            self.acquired = True
            return self.job_id
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            # If not a conflict / precondition failed, check if provider doesn't support header
            if code not in ("PreconditionFailed", "412") and status != 412:
                if code in ("NotImplemented", "InvalidArgument", "MethodNotAllowed", "InvalidRequest"):
                    pass  # Non-AWS S3 provider missing conditional write support; inspect below
                elif code in ("NoSuchBucket", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
                    raise StorageConfigurationError(f"S3 storage error while acquiring lock: {e}")
                else:
                    raise StorageConfigurationError(f"Unexpected S3 error while acquiring lock: {e}")

        # 2. Lock already exists: check if it is active or expired
        try:
            res = self.s3.get_object(Bucket=self.bucket, Key=LOCK_S3_KEY)
            existing_data = json.loads(res["Body"].read().decode("utf-8"))
            existing_exp_str = existing_data.get("expires_at", "")
            existing_etag = res.get("ETag")
            existing_exp = datetime.fromisoformat(existing_exp_str)

            if now_utc < existing_exp:
                # Active lock! Block concurrent execution
                raise ConcurrencyLockError(
                    f"A backup job is already in progress (job: {existing_data.get('job_id')}, "
                    f"initiated by: {existing_data.get('initiated_by')}, "
                    f"expires: {existing_exp_str})."
                )
            else:
                # Stale lock from crashed job: reclaim lock safely with CAS (IfMatch=existing_etag)
                put_kwargs = {
                    "Bucket": self.bucket,
                    "Key": LOCK_S3_KEY,
                    "Body": body,
                    "ContentType": "application/json"
                }
                if existing_etag:
                    put_kwargs["IfMatch"] = existing_etag

                try:
                    self.s3.put_object(**put_kwargs)
                    self.acquired = True
                    return self.job_id
                except ClientError as e_reclaim:
                    code_r = e_reclaim.response.get("Error", {}).get("Code", "")
                    status_r = e_reclaim.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                    if code_r in ("PreconditionFailed", "412") or status_r == 412:
                        raise ConcurrencyLockError(
                            "Another worker concurrently reclaimed or updated the backup lock."
                        )
                    if code_r in ("AccessDenied", "NoSuchBucket", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
                        raise StorageConfigurationError(f"S3 storage error while reclaiming lock: {e_reclaim}")
                    # If provider does not support IfMatch, fallback to standard put
                    self.s3.put_object(
                        Bucket=self.bucket,
                        Key=LOCK_S3_KEY,
                        Body=body,
                        ContentType="application/json"
                    )
                    self.acquired = True
                    return self.job_id
        except (ConcurrencyLockError, StorageConfigurationError):
            raise
        except Exception as e:
            raise ConcurrencyLockError(f"Failed to acquire backup lock: {e}")

    def release(self):
        if not self.acquired:
            return
        try:
            # Safe release: verify that the lock still belongs to this job_id before deleting
            # to prevent deleting a lock acquired by another worker if TTL expired
            res = self.s3.get_object(Bucket=self.bucket, Key=LOCK_S3_KEY)
            existing_data = json.loads(res["Body"].read().decode("utf-8"))
            if existing_data.get("job_id") == self.job_id:
                self.s3.delete_object(Bucket=self.bucket, Key=LOCK_S3_KEY)
        except Exception:
            pass
        finally:
            self.acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


# ---------------------------------------------------------------------------
# Google Drive Folder Hierarchy, Quota Check & File Operations
# ---------------------------------------------------------------------------

def get_or_create_gdrive_folder(service, folder_name: str, parent_id: Optional[str] = None) -> str:
    """Finds or creates a folder in Google Drive. Returns the folder ID."""
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    else:
        query += " and 'root' in parents"

    res = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }
    metadata["parents"] = [parent_id] if parent_id else ["root"]
    created = service.files().create(body=metadata, fields="id").execute()
    return created["id"]


def ensure_gdrive_folders(service) -> Dict[str, str]:
    """
    Ensures the POPCONE_BACKUPS root folder and subfolders (archives, metadata) exist.
    Returns dict mapping: 'root', 'archives', 'metadata'.
    """
    cfg_folder = (os.environ.get("GDRIVE_FOLDER_ID") or "").strip()
    root_id = cfg_folder if cfg_folder else get_or_create_gdrive_folder(service, GDRIVE_DEFAULT_FOLDER)
    archives_id = get_or_create_gdrive_folder(service, "archives", parent_id=root_id)
    metadata_id = get_or_create_gdrive_folder(service, "metadata", parent_id=root_id)
    return {
        "root": root_id,
        "archives": archives_id,
        "metadata": metadata_id
    }


def check_gdrive_quota(service=None, required_bytes: int = 5 * 1024 * 1024) -> Dict[str, Any]:
    """
    Checks Google Drive storage quota using Drive API about().get(fields='storageQuota').
    Fails safely if free personal storage is exhausted, without incurring charges.
    """
    srv = service or get_gdrive_service()
    try:
        about = srv.about().get(fields="storageQuota").execute()
        quota = about.get("storageQuota", {})
        limit = int(quota.get("limit", -1))
        usage = int(quota.get("usage", 0))

        if limit > 0:
            remaining = limit - usage
            if remaining < required_bytes:
                raise QuotaExceededError(
                    f"Google Drive free storage quota exceeded: {remaining // 1024} KB remaining. "
                    f"Backup requires at least {required_bytes // 1024} KB."
                )
            return {
                "limit_bytes": limit,
                "usage_bytes": usage,
                "remaining_bytes": remaining,
                "quota_ok": True
            }
        return {
            "limit_bytes": -1,
            "usage_bytes": usage,
            "remaining_bytes": -1,
            "quota_ok": True
        }
    except QuotaExceededError:
        raise
    except Exception as e:
        err_str = str(e).lower()
        if "quota" in err_str or "storage" in err_str:
            raise QuotaExceededError(f"Google Drive quota error: {e}")
        return {"quota_ok": True, "warning": str(e)}


def upload_bytes_to_gdrive(service, folder_id: str, file_name: str, data: bytes, mime_type: str = "application/octet-stream") -> str:
    """Uploads or updates a file by name inside a Google Drive folder."""
    from googleapiclient.http import MediaIoBaseUpload

    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    res = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])

    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)

    try:
        if files:
            file_id = files[0]["id"]
            updated = service.files().update(fileId=file_id, media_body=media, fields="id").execute()
            return updated["id"]
        else:
            file_metadata = {
                "name": file_name,
                "parents": [folder_id]
            }
            created = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
            return created["id"]
    except Exception as e:
        err_str = str(e).lower()
        if "quota" in err_str or "storage" in err_str or "403" in str(e):
            raise QuotaExceededError(f"Upload failed due to Google Drive quota limit: {e}")
        raise BackupError(f"Failed to upload {file_name} to Google Drive: {e}")


def download_bytes_from_gdrive(service, folder_id: str, file_name: str) -> bytes:
    """Downloads file bytes by name from the specified Google Drive folder."""
    from googleapiclient.http import MediaIoBaseDownload

    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    res = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])
    if not files:
        raise StorageConfigurationError(f"File '{file_name}' not found in Google Drive folder.")

    file_id = files[0]["id"]
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    try:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return fh.getvalue()
    except Exception:
        if hasattr(request, "execute"):
            res = request.execute()
            if isinstance(res, bytes):
                return res
            elif isinstance(res, str):
                return res.encode("utf-8")
        raise


def delete_gdrive_file(service, folder_id: str, file_name: str) -> bool:
    """Deletes a file by name from the specified Google Drive folder."""
    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    res = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])
    if not files:
        return False
    for f in files:
        service.files().delete(fileId=f["id"]).execute()
    return True


class GDriveDistributedLock:
    """
    Distributed mutex lock stored in Google Drive to prevent concurrent or overlapping backups.
    Handles stale lock expiration safely if a previous worker crashed.
    Verifies lock ownership before release to prevent deleting another worker's lock.
    """

    def __init__(self, service, root_folder_id: str, initiated_by: str, ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS):
        self.service = service
        self.folder_id = root_folder_id
        self.initiated_by = initiated_by
        self.ttl_seconds = ttl_seconds
        self.job_id = str(uuid.uuid4())
        self.acquired = False

    def acquire(self):
        now_utc = datetime.now(timezone.utc)
        expires_at = now_utc + timedelta(seconds=self.ttl_seconds)
        payload = {
            "job_id": self.job_id,
            "initiated_by": self.initiated_by,
            "created_at": now_utc.isoformat(),
            "expires_at": expires_at.isoformat(),
            "ttl_seconds": self.ttl_seconds
        }
        body_bytes = json.dumps(payload, indent=2).encode("utf-8")

        # 1. Search for existing lock
        query = f"name = '{GDRIVE_LOCK_NAME}' and '{self.folder_id}' in parents and trashed = false"
        res = self.service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
        files = res.get("files", [])

        if files:
            lock_id = files[0]["id"]
            try:
                content = download_bytes_from_gdrive(self.service, self.folder_id, GDRIVE_LOCK_NAME)
                existing_data = json.loads(content.decode("utf-8"))
                existing_exp = datetime.fromisoformat(existing_data.get("expires_at", ""))

                if now_utc < existing_exp:
                    # Active lock!
                    raise ConcurrencyLockError(
                        f"A backup job is already in progress on Google Drive (job: {existing_data.get('job_id')}, "
                        f"initiated by: {existing_data.get('initiated_by')}, "
                        f"expires: {existing_data.get('expires_at')})."
                    )
                else:
                    # Stale lock: remove it
                    try:
                        self.service.files().delete(fileId=lock_id).execute()
                    except Exception:
                        pass
            except ConcurrencyLockError:
                raise
            except Exception:
                pass

        # 2. Upload new lock file
        upload_bytes_to_gdrive(self.service, self.folder_id, GDRIVE_LOCK_NAME, body_bytes, mime_type="application/json")
        self.acquired = True
        return self.job_id

    def release(self):
        if not self.acquired:
            return
        try:
            # Safe release: verify ownership before deleting
            content = download_bytes_from_gdrive(self.service, self.folder_id, GDRIVE_LOCK_NAME)
            data = json.loads(content.decode("utf-8"))
            if data.get("job_id") == self.job_id:
                delete_gdrive_file(self.service, self.folder_id, GDRIVE_LOCK_NAME)
        except Exception:
            pass
        finally:
            self.acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


# ---------------------------------------------------------------------------
# Turso Consistent Snapshot Extraction
# ---------------------------------------------------------------------------

def extract_database_snapshot(client=None) -> Dict[str, Any]:
    """
    Extracts a point-in-time consistent snapshot across all production tables.
    Uses Turso libSQL batch pipeline so all reads are executed within a single
    atomic transaction under SQLite WAL isolation.
    """
    from database import get_shared_client

    turso = client or get_shared_client()
    now_utc = datetime.now(timezone.utc).isoformat()

    # Tables to extract. Note: sessions table is intentionally EXCLUDED to protect active tokens.
    TABLES_TO_BACKUP = [
        "users",
        "settings",
        "inventory",
        "inventory_movements",
        "orders",
        "order_items",
        "audit_logs"
    ]

    # Build the atomic read batch
    batch_queries = [
        "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table', 'index', 'trigger') AND name NOT LIKE 'sqlite_%';",
        "PRAGMA user_version;"
    ]
    for tbl in TABLES_TO_BACKUP:
        batch_queries.append(f"SELECT * FROM {tbl};")

    # Execute all queries in a single atomic batch
    results = turso.batch(batch_queries)

    # 1. Parse Schema, Indexes, Triggers
    schema_res = results[0]
    schema_items = []
    for row in schema_res.rows:
        schema_items.append({
            "name": row[0],
            "type": row[1],
            "sql": row[2]
        })

    # 2. Parse User Version
    user_version = 0
    try:
        user_version = int(results[1].rows[0][0])
    except Exception:
        pass

    # 3. Parse Table Rows
    tables_data: Dict[str, List[Dict[str, Any]]] = {}
    table_counts: Dict[str, int] = {}

    for idx, tbl in enumerate(TABLES_TO_BACKUP):
        res = results[idx + 2]
        cols = list(res.columns)
        rows_list: List[Dict[str, Any]] = []
        for r in res.rows:
            row_dict = {}
            for col_idx, col_name in enumerate(cols):
                row_dict[col_name] = r[col_idx]
            rows_list.append(row_dict)

        tables_data[tbl] = rows_list
        table_counts[tbl] = len(rows_list)

    return {
        "extracted_at": now_utc,
        "schema_version": user_version,
        "schema": schema_items,
        "table_counts": table_counts,
        "tables": tables_data
    }


# ---------------------------------------------------------------------------
# Cryptographic Packaging & Verification Engine
# ---------------------------------------------------------------------------

def create_backup_package(
    snapshot_data: Dict[str, Any],
    backup_type: str = "MANUAL",
    enc_key: Optional[bytes] = None,
    sign_key: Optional[bytes] = None,
    enc_key_id: Optional[str] = None,
    sign_key_id: Optional[str] = None
) -> Tuple[bytes, Dict[str, Any]]:
    """
    Packs, encrypts (AES-256-GCM), and signs (HMAC-SHA256) a database snapshot.
    Uses unique 12-byte nonce per execution and binds unencrypted envelope
    header metadata as Associated Data (AAD).
    """
    if not enc_key or not sign_key:
        enc_keyring, default_enc_id, sign_keyring, default_sign_id = get_crypto_keyring()
        enc_key_id = enc_key_id or default_enc_id
        sign_key_id = sign_key_id or default_sign_id
        enc_key = enc_keyring[enc_key_id]
        sign_key = sign_keyring[sign_key_id]
    else:
        enc_key_id = enc_key_id or "enc_v1"
        sign_key_id = sign_key_id or "sign_v1"

    now_utc = datetime.now(timezone.utc)
    backup_id = f"bak_{now_utc.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"

    # 1. Canonical JSON representation of the database snapshot
    plaintext_bytes = json.dumps(snapshot_data, sort_keys=True, separators=(',', ':')).encode("utf-8")
    payload_sha256 = hashlib.sha256(plaintext_bytes).hexdigest()

    # 2. Generate unique 12-byte (96-bit) cryptographically secure nonce
    nonce = os.urandom(12)

    # 3. Create envelope metadata header
    header = {
        "format": BACKUP_FORMAT_VERSION,
        "backup_id": backup_id,
        "created_at": now_utc.isoformat(),
        "backup_type": backup_type,
        "enc_key_id": enc_key_id,
        "sign_key_id": sign_key_id,
        "payload_sha256": payload_sha256,
        "table_counts": snapshot_data["table_counts"],
        "schema_version": snapshot_data.get("schema_version", 0),
        "app_version": "1.0.0"
    }
    header_bytes = json.dumps(header, sort_keys=True, separators=(',', ':')).encode("utf-8")

    # 4. AES-256-GCM Encryption with Header as Authenticated Associated Data (AAD)
    aesgcm = AESGCM(enc_key)
    ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, associated_data=header_bytes)

    # 5. Pack body: [4 bytes header length] + [header bytes] + [12 bytes nonce] + [ciphertext]
    package_body = struct.pack(">I", len(header_bytes)) + header_bytes + nonce + ciphertext

    # 6. HMAC-SHA256 Authenticity Signature over package body
    signature = hmac.new(sign_key, package_body, hashlib.sha256).digest()

    # 7. Final binary archive: MAGIC + [32 bytes HMAC signature] + package_body
    final_archive = BACKUP_MAGIC + signature + package_body

    header["size_bytes"] = len(final_archive)
    header["archive_sha256"] = hashlib.sha256(final_archive).hexdigest()

    return final_archive, header


def verify_backup_tier1(
    archive_bytes: bytes,
    enc_keyring: Optional[Dict[str, bytes]] = None,
    sign_keyring: Optional[Dict[str, bytes]] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Tier 1 Verification:
    - Verifies MAGIC header
    - Verifies HMAC-SHA256 signature using the appropriate signing key
    - Decrypts AES-256-GCM using unique nonce and authenticated header data
    - Verifies SHA-256 payload checksum against decrypted bytes
    Returns (header, snapshot_data).
    """
    if not enc_keyring or not sign_keyring:
        enc_keyring, _, sign_keyring, _ = get_crypto_keyring()

    magic_len = len(BACKUP_MAGIC)
    if len(archive_bytes) < magic_len + 32 + 4 + 12 + 16:
        raise BackupIntegrityError("Corrupted or incomplete backup archive (file is truncated).")

    # Check magic bytes
    if archive_bytes[:magic_len] != BACKUP_MAGIC:
        raise BackupIntegrityError("Invalid backup archive: missing POPCONE magic header.")

    # Extract signature and body
    sig_start = magic_len
    sig_end = sig_start + 32
    expected_sig = archive_bytes[sig_start:sig_end]
    package_body = archive_bytes[sig_end:]

    # Parse header length
    header_len = struct.unpack(">I", package_body[:4])[0]
    header_bytes = package_body[4:4 + header_len]
    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except Exception as e:
        raise BackupIntegrityError(f"Corrupted backup header metadata: {e}")

    # Check format version
    if header.get("format") != BACKUP_FORMAT_VERSION:
        raise BackupIntegrityError(f"Unsupported backup format version: {header.get('format')}")

    # Verify HMAC Authenticity Signature
    sign_key_id = header.get("sign_key_id")
    if sign_key_id not in sign_keyring:
        raise BackupIntegrityError(f"Unknown signing key ID '{sign_key_id}'. Key is missing from keyring.")

    computed_sig = hmac.new(sign_keyring[sign_key_id], package_body, hashlib.sha256).digest()
    if not secrets.compare_digest(expected_sig, computed_sig):
        raise BackupIntegrityError("Authenticity verification failed: HMAC signature mismatch (archive has been tampered with).")

    # Verify Encryption Key ID
    enc_key_id = header.get("enc_key_id")
    if enc_key_id not in enc_keyring:
        raise BackupIntegrityError(f"Unknown encryption key ID '{enc_key_id}'. Key is missing from keyring.")

    # Decrypt AES-256-GCM Payload
    nonce_start = 4 + header_len
    nonce_end = nonce_start + 12
    nonce = package_body[nonce_start:nonce_end]
    ciphertext = package_body[nonce_end:]

    aesgcm = AESGCM(enc_keyring[enc_key_id])
    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, associated_data=header_bytes)
    except Exception as e:
        raise BackupIntegrityError(f"Decryption failed: AES-256-GCM authentication tag mismatch: {e}")

    # Check SHA-256 payload checksum
    actual_sha256 = hashlib.sha256(plaintext_bytes).hexdigest()
    if actual_sha256 != header.get("payload_sha256"):
        raise BackupIntegrityError("Payload checksum mismatch: data corruption detected after decryption.")

    snapshot_data = json.loads(plaintext_bytes.decode("utf-8"))
    return header, snapshot_data


def verify_backup_tier2(snapshot_data: Dict[str, Any], expected_counts: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """
    Tier 2 Verification (Isolated Sandbox Test):
    Replays the backup schema and data into an isolated in-memory SQLite database (:memory:),
    executing PRAGMA integrity_check, PRAGMA foreign_key_check, constraint validation,
    and row count assertions.
    """
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    try:
        # Defer foreign-key enforcement during snapshot population to allow all tables
        # and dependent rows to be inserted regardless of dictionary key sorting.
        cursor.execute("PRAGMA foreign_keys = OFF;")

        # 1. Replay Schema (tables, indexes, triggers)
        schema_items = snapshot_data.get("schema", [])
        for item in schema_items:
            sql = item.get("sql")
            if sql:
                try:
                    cursor.execute(sql)
                except Exception as e:
                    raise BackupIntegrityError(f"Schema DDL replay error for {item.get('name')}: {e}")

        # 2. Insert Data in parent-first dependency order
        TABLE_ORDER = [
            "users",
            "settings",
            "inventory",
            "inventory_movements",
            "orders",
            "order_items",
            "audit_logs"
        ]
        tables = snapshot_data.get("tables", {})

        def table_order_key(name: str):
            try:
                return (TABLE_ORDER.index(name), name)
            except ValueError:
                return (len(TABLE_ORDER), name)

        for table_name in sorted(tables.keys(), key=table_order_key):
            rows = tables[table_name]
            if not rows:
                continue
            cols = list(rows[0].keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            insert_sql = f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders});"

            batch_values = []
            for r in rows:
                batch_values.append([r[c] for c in cols])

            try:
                cursor.executemany(insert_sql, batch_values)
            except Exception as e:
                raise BackupIntegrityError(f"Data constraint violation while populating table '{table_name}': {e}")

        # Re-enable foreign keys once all tables and rows are loaded
        cursor.execute("PRAGMA foreign_keys = ON;")

        # 3. Database Integrity Check
        cursor.execute("PRAGMA integrity_check;")
        integrity_res = cursor.fetchall()
        if not integrity_res or integrity_res[0][0] != "ok":
            raise BackupIntegrityError(f"SQLite PRAGMA integrity_check failed: {integrity_res}")

        # 4. Foreign Key Constraints Check
        cursor.execute("PRAGMA foreign_key_check;")
        fk_violations = cursor.fetchall()
        if fk_violations:
            raise BackupIntegrityError(f"Foreign key integrity check failed with violations: {fk_violations}")

        # 5. Required Tables & Row Count Assertions
        REQUIRED_TABLES = ["users", "settings", "inventory", "inventory_movements", "orders", "order_items", "audit_logs"]
        for req in REQUIRED_TABLES:
            if req not in tables:
                raise BackupIntegrityError(f"Missing required table in backup: '{req}'.")

            cursor.execute(f"SELECT COUNT(*) FROM {req};")
            actual_count = cursor.fetchone()[0]

            expected = (expected_counts or snapshot_data.get("table_counts", {})).get(req)
            if expected is not None and actual_count != expected:
                raise BackupIntegrityError(f"Row count mismatch in table '{req}': expected {expected}, got {actual_count}.")

        # 6. Specific Domain Constraint Verifications
        # Verify order_items link to valid orders
        cursor.execute("""
            SELECT COUNT(*) FROM order_items oi
            LEFT JOIN orders o ON oi.order_id = o.order_id
            WHERE o.order_id IS NULL;
        """)
        orphaned_items = cursor.fetchone()[0]
        if orphaned_items > 0:
            raise BackupIntegrityError(f"Detected {orphaned_items} orphaned order_items without a valid parent order.")

        # Verify admin account presence
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'ADMIN';")
        admin_count = cursor.fetchone()[0]
        if admin_count < 1:
            raise BackupIntegrityError("Backup validation failed: no ADMIN account found in users table.")

        return {
            "tier2_verified": True,
            "integrity_check": "ok",
            "fk_check": "ok",
            "tables_verified": list(tables.keys()),
            "total_rows": sum(snapshot_data.get("table_counts", {}).values())
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# S3 Manifest Management
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# S3 Storage Engine (Secondary / Fallback)
# ---------------------------------------------------------------------------

def get_s3_manifest(s3_client=None, bucket: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetches the durable backup manifest index from S3."""
    cfg = get_s3_config()
    b = bucket or cfg["bucket"]
    s3 = s3_client or get_s3_client(cfg)

    try:
        res = s3.get_object(Bucket=b, Key=MANIFEST_S3_KEY)
        manifest_data = json.loads(res["Body"].read().decode("utf-8"))
        if isinstance(manifest_data, list):
            return manifest_data
        return manifest_data.get("backups", [])
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            return []
        raise StorageConfigurationError(f"Failed to read backup manifest from S3: {e}")
    except Exception as e:
        raise StorageConfigurationError(f"Error parsing S3 backup manifest: {e}")


def _save_s3_manifest(manifest_entries: List[Dict[str, Any]], s3_client=None, bucket: Optional[str] = None):
    """Saves updated manifest entries to S3."""
    cfg = get_s3_config()
    b = bucket or cfg["bucket"]
    s3 = s3_client or get_s3_client(cfg)

    manifest_entries.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    payload = json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "backups": manifest_entries}, indent=2).encode("utf-8")

    s3.put_object(
        Bucket=b,
        Key=MANIFEST_S3_KEY,
        Body=payload,
        ContentType="application/json"
    )


def execute_s3_backup(
    backup_type: str = "MANUAL",
    initiated_by: str = "system",
    s3_client=None,
    db_client=None
) -> Dict[str, Any]:
    """Executes full backup pipeline to external S3 storage."""
    s3_cfg = get_s3_config()
    s3 = s3_client or get_s3_client(s3_cfg)
    bucket = s3_cfg["bucket"]

    with S3DistributedLock(s3, bucket, initiated_by=initiated_by):
        snapshot_data = extract_database_snapshot(client=db_client)
        archive_bytes, header = create_backup_package(snapshot_data, backup_type=backup_type)
        backup_id = header["backup_id"]

        verify_backup_tier1(archive_bytes)
        tier2_result = verify_backup_tier2(snapshot_data)

        archive_s3_key = f"archives/{backup_id}.enc.bak"
        metadata_s3_key = f"metadata/{backup_id}.meta.json"

        s3.put_object(
            Bucket=bucket,
            Key=archive_s3_key,
            Body=archive_bytes,
            ContentType="application/octet-stream"
        )

        meta_payload = {
            **header,
            "tier1_verified": True,
            "tier2_verified": True,
            "tier2_details": tier2_result,
            "storage_provider": "s3",
            "s3_archive_key": archive_s3_key,
            "s3_metadata_key": metadata_s3_key,
            "status": "COMPLETED"
        }
        s3.put_object(
            Bucket=bucket,
            Key=metadata_s3_key,
            Body=json.dumps(meta_payload, indent=2).encode("utf-8"),
            ContentType="application/json"
        )

        current_manifest = get_s3_manifest(s3, bucket)
        current_manifest = [m for m in current_manifest if m.get("backup_id") != backup_id]
        current_manifest.append(meta_payload)
        _save_s3_manifest(current_manifest, s3, bucket)

        return meta_payload


def prune_expired_s3_backups(
    s3_client=None,
    bucket: Optional[str] = None,
    retention_days: Optional[int] = None,
    min_retained: Optional[int] = None
) -> Dict[str, Any]:
    """Prunes expired backups from S3 preserving min_retained backups."""
    if bucket and s3_client:
        b = bucket
        s3 = s3_client
    else:
        cfg = get_s3_config()
        b = bucket or cfg["bucket"]
        s3 = s3_client or get_s3_client(cfg)

    if retention_days is None:
        try:
            retention_days = int(os.environ.get("BACKUP_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
        except (ValueError, TypeError):
            retention_days = DEFAULT_RETENTION_DAYS
    retention_days = max(retention_days, MIN_ENFORCED_RETENTION_DAYS)

    if min_retained is None:
        try:
            min_retained = int(os.environ.get("MIN_BACKUPS_RETAINED", DEFAULT_MIN_BACKUPS_RETAINED))
        except (ValueError, TypeError):
            min_retained = DEFAULT_MIN_BACKUPS_RETAINED
    min_retained = max(min_retained, MIN_ENFORCED_RETAINED_COUNT)

    manifest = get_backups_manifest(s3_client=s3, bucket=b)
    if len(manifest) <= min_retained:
        return {
            "pruned_count": 0,
            "pruned_backups": [],
            "surviving_count": len(manifest),
            "retention_days": retention_days,
            "min_retained": min_retained,
            "errors": []
        }

    manifest.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    now_utc = datetime.now(timezone.utc)
    cutoff_time = now_utc - timedelta(days=retention_days)

    protected_backups = manifest[:min_retained]
    candidate_backups = manifest[min_retained:]

    surviving_candidates = []
    pruned_backups = []
    errors = []

    for item in candidate_backups:
        created_str = item.get("created_at", "")
        try:
            created_dt = datetime.fromisoformat(created_str)
        except Exception:
            surviving_candidates.append(item)
            continue

        if created_dt < cutoff_time:
            backup_id = item.get("backup_id")
            archive_key = item.get("s3_archive_key", f"archives/{backup_id}.enc.bak")
            meta_key = item.get("s3_metadata_key", f"metadata/{backup_id}.meta.json")

            delete_failed = False
            for k in [archive_key, meta_key]:
                try:
                    s3.delete_object(Bucket=b, Key=k)
                except Exception as e:
                    errors.append(f"Failed to delete {k} in S3: {e}")
                    delete_failed = True

            if not delete_failed:
                pruned_backups.append(backup_id)
            else:
                surviving_candidates.append(item)
        else:
            surviving_candidates.append(item)

    if pruned_backups:
        final_manifest = protected_backups + surviving_candidates
        _save_backups_manifest(final_manifest, s3_client=s3, bucket=b)

    return {
        "pruned_count": len(pruned_backups),
        "pruned_backups": pruned_backups,
        "surviving_count": len(protected_backups) + len(surviving_candidates),
        "retention_days": retention_days,
        "min_retained": min_retained,
        "errors": errors
    }


def execute_s3_scheduled_daily_backup(
    s3_client=None,
    db_client=None,
    retention_days: Optional[int] = None,
    min_retained: Optional[int] = None
) -> Dict[str, Any]:
    """Executes scheduled daily backup to S3 with idempotency check."""
    s3_cfg = get_s3_config()
    s3 = s3_client or get_s3_client(s3_cfg)
    bucket = s3_cfg["bucket"]

    current_manifest = get_s3_manifest(s3, bucket)
    existing_today = check_daily_backup_idempotency(current_manifest)
    if existing_today:
        return {
            "status": "ALREADY_COMPLETED",
            "message": f"Daily scheduled backup for {datetime.now(timezone.utc).strftime('%Y-%m-%d')} already completed successfully in S3.",
            "backup_id": existing_today.get("backup_id"),
            "created_at": existing_today.get("created_at"),
            "size_bytes": existing_today.get("size_bytes"),
            "pruned_count": 0
        }

    try:
        backup_meta = execute_s3_backup(
            backup_type="SCHEDULED_DAILY",
            initiated_by="vercel-cron",
            s3_client=s3,
            db_client=db_client
        )
    except ConcurrencyLockError:
        refreshed = get_s3_manifest(s3, bucket)
        existing_now = check_daily_backup_idempotency(refreshed)
        if existing_now:
            return {
                "status": "ALREADY_COMPLETED",
                "message": "Daily scheduled backup completed concurrently by another worker in S3.",
                "backup_id": existing_now.get("backup_id"),
                "created_at": existing_now.get("created_at"),
                "size_bytes": existing_now.get("size_bytes"),
                "pruned_count": 0
            }
        raise

    try:
        with S3DistributedLock(s3, bucket, initiated_by="retention-pruning"):
            prune_result = prune_expired_s3_backups(
                s3_client=s3,
                bucket=bucket,
                retention_days=retention_days,
                min_retained=min_retained
            )
    except ConcurrencyLockError:
        prune_result = {
            "pruned_count": 0,
            "pruned_backups": [],
            "errors": ["Skipped pruning: distributed lock currently held by another worker."]
        }

    return {
        "status": "COMPLETED",
        "message": f"Daily backup {backup_meta.get('backup_id')} completed and verified successfully in S3.",
        "backup": backup_meta,
        "pruning": prune_result
    }


# ---------------------------------------------------------------------------
# Google Drive Storage Engine (Primary)
# ---------------------------------------------------------------------------

def get_gdrive_manifest(service, root_folder_id: str) -> List[Dict[str, Any]]:
    """Fetches the durable backup manifest index from Google Drive."""
    try:
        data = download_bytes_from_gdrive(service, root_folder_id, GDRIVE_MANIFEST_NAME)
        parsed = json.loads(data.decode("utf-8"))
        if isinstance(parsed, list):
            return parsed
        return parsed.get("backups", [])
    except StorageConfigurationError:
        return []
    except Exception as e:
        err_str = str(e).lower()
        if "not found" in err_str:
            return []
        raise StorageConfigurationError(f"Failed to read backup manifest from Google Drive: {e}")


def save_gdrive_manifest(manifest_entries: List[Dict[str, Any]], service, root_folder_id: str):
    """Saves updated manifest entries to Google Drive."""
    manifest_entries.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    payload = json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "backups": manifest_entries}, indent=2).encode("utf-8")
    upload_bytes_to_gdrive(service, root_folder_id, GDRIVE_MANIFEST_NAME, payload, mime_type="application/json")


def execute_gdrive_backup(
    backup_type: str = "MANUAL",
    initiated_by: str = "system",
    service=None,
    db_client=None
) -> Dict[str, Any]:
    """Executes full backup pipeline to user's private Google Drive folder."""
    srv = service or get_gdrive_service()
    folders = ensure_gdrive_folders(srv)
    root_id = folders["root"]
    archives_id = folders["archives"]
    metadata_id = folders["metadata"]

    check_gdrive_quota(srv)

    with GDriveDistributedLock(srv, root_id, initiated_by=initiated_by):
        snapshot_data = extract_database_snapshot(client=db_client)
        archive_bytes, header = create_backup_package(snapshot_data, backup_type=backup_type)
        backup_id = header["backup_id"]

        verify_backup_tier1(archive_bytes)
        tier2_result = verify_backup_tier2(snapshot_data)

        archive_filename = f"{backup_id}.enc.bak"
        metadata_filename = f"{backup_id}.meta.json"

        archive_file_id = upload_bytes_to_gdrive(srv, archives_id, archive_filename, archive_bytes)

        meta_payload = {
            **header,
            "tier1_verified": True,
            "tier2_verified": True,
            "tier2_details": tier2_result,
            "storage_provider": "gdrive",
            "gdrive_archive_file_id": archive_file_id,
            "archive_filename": archive_filename,
            "metadata_filename": metadata_filename,
            "status": "COMPLETED"
        }
        meta_bytes = json.dumps(meta_payload, indent=2).encode("utf-8")
        upload_bytes_to_gdrive(srv, metadata_id, metadata_filename, meta_bytes, mime_type="application/json")

        current_manifest = get_gdrive_manifest(srv, root_id)
        current_manifest = [m for m in current_manifest if m.get("backup_id") != backup_id]
        current_manifest.append(meta_payload)
        save_gdrive_manifest(current_manifest, srv, root_id)

        return meta_payload


def prune_expired_gdrive_backups(
    service=None,
    root_folder_id: Optional[str] = None,
    retention_days: Optional[int] = None,
    min_retained: Optional[int] = None
) -> Dict[str, Any]:
    """Prunes expired backups from Google Drive while strictly preserving min_retained backups."""
    srv = service or get_gdrive_service()
    folders = ensure_gdrive_folders(srv)
    r_id = root_folder_id or folders["root"]
    arch_id = folders["archives"]
    meta_id = folders["metadata"]

    if retention_days is None:
        try:
            retention_days = int(os.environ.get("BACKUP_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
        except (ValueError, TypeError):
            retention_days = DEFAULT_RETENTION_DAYS
    retention_days = max(retention_days, MIN_ENFORCED_RETENTION_DAYS)

    if min_retained is None:
        try:
            min_retained = int(os.environ.get("MIN_BACKUPS_RETAINED", DEFAULT_MIN_BACKUPS_RETAINED))
        except (ValueError, TypeError):
            min_retained = DEFAULT_MIN_BACKUPS_RETAINED
    min_retained = max(min_retained, MIN_ENFORCED_RETAINED_COUNT)

    manifest = get_gdrive_manifest(srv, r_id)
    if len(manifest) <= min_retained:
        return {
            "pruned_count": 0,
            "pruned_backups": [],
            "surviving_count": len(manifest),
            "retention_days": retention_days,
            "min_retained": min_retained,
            "errors": []
        }

    manifest.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    now_utc = datetime.now(timezone.utc)
    cutoff_time = now_utc - timedelta(days=retention_days)

    protected_backups = manifest[:min_retained]
    candidate_backups = manifest[min_retained:]

    surviving_candidates = []
    pruned_backups = []
    errors = []

    for item in candidate_backups:
        created_str = item.get("created_at", "")
        try:
            created_dt = datetime.fromisoformat(created_str)
        except Exception:
            surviving_candidates.append(item)
            continue

        if created_dt < cutoff_time:
            backup_id = item.get("backup_id")
            arch_name = item.get("archive_filename", f"{backup_id}.enc.bak")
            meta_name = item.get("metadata_filename", f"{backup_id}.meta.json")

            delete_failed = False
            try:
                delete_gdrive_file(srv, arch_id, arch_name)
                delete_gdrive_file(srv, meta_id, meta_name)
            except Exception as e:
                errors.append(f"Failed to delete {backup_id} in Google Drive: {e}")
                delete_failed = True

            if not delete_failed:
                pruned_backups.append(backup_id)
            else:
                surviving_candidates.append(item)
        else:
            surviving_candidates.append(item)

    if pruned_backups:
        final_manifest = protected_backups + surviving_candidates
        save_gdrive_manifest(final_manifest, srv, r_id)

    return {
        "pruned_count": len(pruned_backups),
        "pruned_backups": pruned_backups,
        "surviving_count": len(protected_backups) + len(surviving_candidates),
        "retention_days": retention_days,
        "min_retained": min_retained,
        "errors": errors
    }


def execute_gdrive_scheduled_daily_backup(
    service=None,
    db_client=None,
    retention_days: Optional[int] = None,
    min_retained: Optional[int] = None
) -> Dict[str, Any]:
    """Executes scheduled daily backup to Google Drive with idempotency check."""
    srv = service or get_gdrive_service()
    folders = ensure_gdrive_folders(srv)
    root_id = folders["root"]

    manifest = get_gdrive_manifest(srv, root_id)
    existing_today = check_daily_backup_idempotency(manifest)
    if existing_today:
        return {
            "status": "ALREADY_COMPLETED",
            "message": f"Daily scheduled backup for {datetime.now(timezone.utc).strftime('%Y-%m-%d')} already completed successfully in Google Drive.",
            "backup_id": existing_today.get("backup_id"),
            "created_at": existing_today.get("created_at"),
            "size_bytes": existing_today.get("size_bytes"),
            "pruned_count": 0
        }

    try:
        backup_meta = execute_gdrive_backup(
            backup_type="SCHEDULED_DAILY",
            initiated_by="vercel-cron",
            service=srv,
            db_client=db_client
        )
    except ConcurrencyLockError:
        refreshed = get_gdrive_manifest(srv, root_id)
        existing_now = check_daily_backup_idempotency(refreshed)
        if existing_now:
            return {
                "status": "ALREADY_COMPLETED",
                "message": "Daily scheduled backup completed concurrently by another worker in Google Drive.",
                "backup_id": existing_now.get("backup_id"),
                "created_at": existing_now.get("created_at"),
                "size_bytes": existing_now.get("size_bytes"),
                "pruned_count": 0
            }
        raise

    try:
        with GDriveDistributedLock(srv, root_id, initiated_by="retention-pruning"):
            prune_result = prune_expired_gdrive_backups(
                service=srv,
                root_folder_id=root_id,
                retention_days=retention_days,
                min_retained=min_retained
            )
    except ConcurrencyLockError:
        prune_result = {
            "pruned_count": 0,
            "pruned_backups": [],
            "errors": ["Skipped pruning: distributed lock currently held by another worker."]
        }

    return {
        "status": "COMPLETED",
        "message": f"Daily backup {backup_meta.get('backup_id')} completed and verified successfully in Google Drive.",
        "backup": backup_meta,
        "pruning": prune_result
    }


# ---------------------------------------------------------------------------
# Unified Storage Router Functions (Google Drive Primary + S3 Fallback)
# ---------------------------------------------------------------------------

def check_daily_backup_idempotency(
    manifest: List[Dict[str, Any]],
    target_date_utc: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Checks if a successful SCHEDULED_DAILY backup exists for the given UTC calendar day."""
    date_str = target_date_utc or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for b in manifest:
        if b.get("backup_type") == "SCHEDULED_DAILY" and b.get("status") == "COMPLETED" and b.get("tier1_verified"):
            created_at = b.get("created_at", "")
            if created_at.startswith(date_str):
                return b
    return None


def get_backups_manifest(
    s3_client=None,
    gdrive_service=None,
    bucket: Optional[str] = None,
    gdrive_folder_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetches backup manifest from the active storage provider (Google Drive or S3)."""
    if (s3_client is not None or bucket is not None) and gdrive_service is None and gdrive_folder_id is None:
        return get_s3_manifest(s3_client=s3_client, bucket=bucket)
    if (gdrive_service is not None or gdrive_folder_id is not None) and s3_client is None and bucket is None:
        srv = gdrive_service or get_gdrive_service()
        folders = ensure_gdrive_folders(srv)
        r_id = gdrive_folder_id or folders["root"]
        return get_gdrive_manifest(srv, r_id)
    provider = get_storage_provider()
    if provider == "gdrive":
        srv = gdrive_service or get_gdrive_service()
        folders = ensure_gdrive_folders(srv)
        r_id = gdrive_folder_id or folders["root"]
        return get_gdrive_manifest(srv, r_id)
    elif provider == "s3":
        return get_s3_manifest(s3_client=s3_client, bucket=bucket)
    return []


def _save_backups_manifest(
    manifest_entries: List[Dict[str, Any]],
    s3_client=None,
    gdrive_service=None,
    bucket: Optional[str] = None,
    gdrive_folder_id: Optional[str] = None
):
    """Saves backup manifest to the active storage provider."""
    if (s3_client is not None or bucket is not None) and gdrive_service is None and gdrive_folder_id is None:
        _save_s3_manifest(manifest_entries, s3_client=s3_client, bucket=bucket)
        return
    if (gdrive_service is not None or gdrive_folder_id is not None) and s3_client is None and bucket is None:
        srv = gdrive_service or get_gdrive_service()
        folders = ensure_gdrive_folders(srv)
        r_id = gdrive_folder_id or folders["root"]
        save_gdrive_manifest(manifest_entries, srv, r_id)
        return
    provider = get_storage_provider()
    if provider == "gdrive":
        srv = gdrive_service or get_gdrive_service()
        folders = ensure_gdrive_folders(srv)
        r_id = gdrive_folder_id or folders["root"]
        save_gdrive_manifest(manifest_entries, srv, r_id)
    elif provider == "s3":
        _save_s3_manifest(manifest_entries, s3_client=s3_client, bucket=bucket)


def execute_backup(
    backup_type: str = "MANUAL",
    initiated_by: str = "system",
    s3_client=None,
    gdrive_service=None,
    db_client=None
) -> Dict[str, Any]:
    """Executes backup using the configured storage provider (Google Drive or S3)."""
    if s3_client is not None and gdrive_service is None:
        return execute_s3_backup(
            backup_type=backup_type,
            initiated_by=initiated_by,
            s3_client=s3_client,
            db_client=db_client
        )
    if gdrive_service is not None and s3_client is None:
        return execute_gdrive_backup(
            backup_type=backup_type,
            initiated_by=initiated_by,
            service=gdrive_service,
            db_client=db_client
        )
    provider = get_storage_provider()
    if provider == "gdrive":
        return execute_gdrive_backup(
            backup_type=backup_type,
            initiated_by=initiated_by,
            service=gdrive_service,
            db_client=db_client
        )
    elif provider == "s3":
        return execute_s3_backup(
            backup_type=backup_type,
            initiated_by=initiated_by,
            s3_client=s3_client,
            db_client=db_client
        )
    else:
        raise StorageConfigurationError(
            "Backup storage is not configured. Please configure Google Drive credentials "
            "(GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN). "
            "Run 'python scripts/setup_gdrive_auth.py' to generate your OAuth refresh token."
        )


def execute_scheduled_daily_backup(
    s3_client=None,
    gdrive_service=None,
    db_client=None,
    retention_days: Optional[int] = None,
    min_retained: Optional[int] = None
) -> Dict[str, Any]:
    """Executes scheduled daily backup using the active storage provider."""
    if s3_client is not None and gdrive_service is None:
        return execute_s3_scheduled_daily_backup(
            s3_client=s3_client,
            db_client=db_client,
            retention_days=retention_days,
            min_retained=min_retained
        )
    if gdrive_service is not None and s3_client is None:
        return execute_gdrive_scheduled_daily_backup(
            service=gdrive_service,
            db_client=db_client,
            retention_days=retention_days,
            min_retained=min_retained
        )
    provider = get_storage_provider()
    if provider == "gdrive":
        return execute_gdrive_scheduled_daily_backup(
            service=gdrive_service,
            db_client=db_client,
            retention_days=retention_days,
            min_retained=min_retained
        )
    elif provider == "s3":
        return execute_s3_scheduled_daily_backup(
            s3_client=s3_client,
            db_client=db_client,
            retention_days=retention_days,
            min_retained=min_retained
        )
    else:
        raise StorageConfigurationError(
            "Backup storage is not configured. Please configure Google Drive credentials."
        )


def prune_expired_backups(
    s3_client=None,
    gdrive_service=None,
    bucket: Optional[str] = None,
    gdrive_folder_id: Optional[str] = None,
    retention_days: Optional[int] = None,
    min_retained: Optional[int] = None
) -> Dict[str, Any]:
    """Prunes expired backups using the active storage provider."""
    if (s3_client is not None or bucket is not None) and gdrive_service is None and gdrive_folder_id is None:
        return prune_expired_s3_backups(
            s3_client=s3_client,
            bucket=bucket,
            retention_days=retention_days,
            min_retained=min_retained
        )
    if (gdrive_service is not None or gdrive_folder_id is not None) and s3_client is None and bucket is None:
        return prune_expired_gdrive_backups(
            service=gdrive_service,
            root_folder_id=gdrive_folder_id,
            retention_days=retention_days,
            min_retained=min_retained
        )
    provider = get_storage_provider()
    if provider == "gdrive":
        return prune_expired_gdrive_backups(
            service=gdrive_service,
            root_folder_id=gdrive_folder_id,
            retention_days=retention_days,
            min_retained=min_retained
        )
    elif provider == "s3":
        return prune_expired_s3_backups(
            s3_client=s3_client,
            bucket=bucket,
            retention_days=retention_days,
            min_retained=min_retained
        )
    return {
        "pruned_count": 0,
        "pruned_backups": [],
        "errors": ["No storage provider configured."]
    }


def verify_backup_archive_by_id(
    backup_id: str,
    s3_client=None,
    gdrive_service=None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Downloads an archive from the active storage provider and performs Tier 1 & Tier 2 verification."""
    if s3_client is not None and gdrive_service is None:
        cfg = get_s3_config()
        s3 = s3_client
        archive_key = f"archives/{backup_id}.enc.bak"
        res = s3.get_object(Bucket=cfg["bucket"], Key=archive_key)
        arch_bytes = res["Body"].read()
        header, snapshot = verify_backup_tier1(arch_bytes)
        verify_backup_tier2(snapshot)
        return header, snapshot
    if gdrive_service is not None and s3_client is None:
        srv = gdrive_service
        folders = ensure_gdrive_folders(srv)
        arch_bytes = download_bytes_from_gdrive(srv, folders["archives"], f"{backup_id}.enc.bak")
        header, snapshot = verify_backup_tier1(arch_bytes)
        verify_backup_tier2(snapshot)
        return header, snapshot
    provider = get_storage_provider()
    if provider == "gdrive":
        srv = gdrive_service or get_gdrive_service()
        folders = ensure_gdrive_folders(srv)
        arch_bytes = download_bytes_from_gdrive(srv, folders["archives"], f"{backup_id}.enc.bak")
        header, snapshot = verify_backup_tier1(arch_bytes)
        verify_backup_tier2(snapshot)
        return header, snapshot
    elif provider == "s3":
        cfg = get_s3_config()
        s3 = s3_client or get_s3_client(cfg)
        archive_key = f"archives/{backup_id}.enc.bak"
        res = s3.get_object(Bucket=cfg["bucket"], Key=archive_key)
        arch_bytes = res["Body"].read()
        header, snapshot = verify_backup_tier1(arch_bytes)
        verify_backup_tier2(snapshot)
        return header, snapshot
    else:
        raise StorageConfigurationError("No backup storage provider is configured.")


# ---------------------------------------------------------------------------
# Stage 1 Safety Barrier
# ---------------------------------------------------------------------------

def restore_production_database(*args, **kwargs):
    """
    STRICT SAFETY BARRIER FOR STAGE 1:
    Production restoration is disabled. Stage 1 implements and tests
    backup creation, cryptographic validation, and offline sandbox checks only.
    """
    raise RestorationDisabledError(
        "Production restoration is disabled in Stage 1 per safety protocol. "
        "Production data cannot be modified until isolated staging restore "
        "tests pass and the recovery plan is approved."
    )
