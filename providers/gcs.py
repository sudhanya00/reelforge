"""Cloud Storage, only for what Vertex delivers there (Omni 1080p/4k). Plain JSON API over the
same Application Default Credentials the app already uses, billed to the project.

TRANSPORT is a hook for tests: fn(method, url, **kw) -> response-like (status_code, content, json()).
"""
from __future__ import annotations

from urllib.parse import quote

API = "https://storage.googleapis.com/storage/v1"
DOWNLOAD = "https://storage.googleapis.com/download/storage/v1"
TRANSPORT = None
_sessions: dict[str, object] = {}


def _request(project: str, method: str, url: str, **kw):
    if TRANSPORT:
        return TRANSPORT(method, url, **kw)
    if project not in _sessions:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"],
                                       quota_project_id=project or None)
        _sessions[project] = AuthorizedSession(creds)
    return _sessions[project].request(method, url, timeout=300, **kw)


def split(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a Cloud Storage uri: {uri}")
    bucket, _, name = uri[5:].partition("/")
    return bucket, name


def _check(r, what: str):
    if r.status_code >= 400:
        from .base import ProviderError
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            msg = ""
        raise ProviderError(r.status_code, f"Cloud Storage {what} failed: {msg or r.status_code}")
    return r


def download(uri: str, project: str) -> bytes:
    """The object's bytes. A prefix (ending in /) means the first .mp4 under it."""
    bucket, name = split(uri)
    if not name or name.endswith("/"):
        r = _check(_request(project, "GET", f"{API}/b/{bucket}/o", params={"prefix": name}), "listing")
        mp4s = [o["name"] for o in r.json().get("items", []) if o["name"].endswith(".mp4")]
        if not mp4s:
            raise RuntimeError(f"No video found under {uri}")
        name = mp4s[0]
    r = _check(_request(project, "GET", f"{DOWNLOAD}/b/{bucket}/o/{quote(name, safe='')}",
                        params={"alt": "media"}), "download")
    return r.content


def delete_prefix(uri: str, project: str) -> None:
    """Best effort: videos only pass through the bucket (a lifecycle rule is the backstop)."""
    try:
        bucket, name = split(uri)
        prefix = name if name.endswith("/") else name.rsplit("/", 1)[0] + "/"
        r = _request(project, "GET", f"{API}/b/{bucket}/o", params={"prefix": prefix})
        for o in (r.json().get("items", []) if r.status_code < 400 else []):
            _request(project, "DELETE", f"{API}/b/{bucket}/o/{quote(o['name'], safe='')}")
    except Exception:  # noqa: BLE001
        pass


def ensure_bucket(bucket: str, project: str, location: str = "US-CENTRAL1") -> bool:
    """Create the bucket if it doesn't exist (private, objects deleted after a day).
    Returns True if it was created."""
    r = _request(project, "GET", f"{API}/b/{bucket}")
    if r.status_code == 200:
        return False
    if r.status_code != 404:
        _check(r, "bucket check")
    body = {"name": bucket, "location": location, "storageClass": "STANDARD",
            "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True},
                                 "publicAccessPrevention": "enforced"},
            "lifecycle": {"rule": [{"action": {"type": "Delete"}, "condition": {"age": 1}}]},
            "labels": {"app": "reelforge"}}
    _check(_request(project, "POST", f"{API}/b", params={"project": project}, json=body), "bucket creation")
    return True
