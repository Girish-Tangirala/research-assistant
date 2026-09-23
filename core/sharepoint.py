"""Microsoft Graph client for the SharePoint backup of a paper's local-only folders.

Only the standard library is used: the device-code sign-in and the Graph REST API
are plain HTTPS calls, so the packaged app gains no new dependency.

The app is a **public client** and never holds a client secret. Each user signs in
with their own Microsoft account; only the refresh token is kept, in the OS
credential vault (:mod:`core.credentials`). Permissions are *delegated*, so the app
reaches exactly the sites the signed-in user can already reach - nothing more.

Uploads are one-way (this computer → SharePoint). Nothing is ever downloaded,
renamed or deleted there.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access User.Read Sites.ReadWrite.All"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
USER_AGENT = "ScientificResearchAssistant/1.0"

SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024      # Graph's limit for a one-shot PUT
CHUNK = 10 * 1024 * 1024                   # upload-session chunk (multiple of 320 KiB)
TIMEOUT = 60.0
DEFAULT_TENANT = "organizations"           # work/school accounts; a tenant id also works


class SharePointError(RuntimeError):
    """A SharePoint operation failed, with a user-facing explanation."""


class SharePointAuthError(SharePointError):
    """The stored sign-in is missing, expired or was revoked - sign in again."""


# ---------------------------------------------------------------------- #
# HTTP
# ---------------------------------------------------------------------- #
def _backoff(retry_after: str | None, attempt: int) -> float:
    if retry_after and retry_after.strip().isdigit():
        return min(float(retry_after.strip()), 60.0)
    return min(2.0 ** attempt, 30.0)


def _http(method: str, url: str, *, body: bytes | None = None, headers: dict[str, str] | None = None,
          timeout: float = TIMEOUT, retries: int = 4) -> tuple[int, dict[str, str], bytes]:
    """One HTTP request, retrying throttling and transient server errors.

    Returns ``(status, headers, body)``; HTTP error statuses are returned, not raised,
    because several of them are expected (409 folder exists, 404 not uploaded yet,
    400 authorization_pending).
    """
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    attempt = 0
    while True:
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(_backoff(exc.headers.get("Retry-After") if exc.headers else None, attempt))
                attempt += 1
                continue
            return exc.code, dict(exc.headers or {}), payload
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < retries:
                time.sleep(_backoff(None, attempt))
                attempt += 1
                continue
            raise SharePointError(f"Could not reach Microsoft 365: {exc}") from exc


def _decode(payload: bytes) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8", errors="replace") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _graph_error(status: int, payload: bytes) -> str:
    detail = _decode(payload).get("error")
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("code") or "").strip()
        if message:
            return f"{message} (HTTP {status})"
    return f"Microsoft 365 returned HTTP {status}."


def parse_time(value: str) -> datetime:
    """Parse a Graph timestamp (``2026-01-15T10:30:00Z``) as an aware UTC datetime."""
    text = value.strip().replace("Z", "+00:00")
    if "." in text:  # Graph can send more fractional digits than fromisoformat accepts
        head, _, tail = text.partition(".")
        digits = "".join(c for c in tail if c.isdigit())[:6]
        offset = tail[len(digits):] if not tail[len(digits):].isdigit() else ""
        text = f"{head}.{digits or '0'}{offset}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------- #
# Sign-in (OAuth 2.0 device code)
# ---------------------------------------------------------------------- #
@dataclass(frozen=True)
class DeviceCode:
    """A pending sign-in: the user types ``user_code`` at ``verification_uri``."""

    user_code: str
    verification_uri: str
    device_code: str
    interval: int
    expires_at: float


def _token_endpoint(tenant: str) -> str:
    return f"{AUTHORITY}/{urllib.parse.quote(tenant or DEFAULT_TENANT)}/oauth2/v2.0/token"


def _redeem(client_id: str, tenant: str, fields: dict[str, str]) -> dict[str, Any]:
    """POST to the token endpoint; returns the parsed payload (errors included)."""
    body = urllib.parse.urlencode({"client_id": client_id, **fields}).encode()
    status, _, payload = _http("POST", _token_endpoint(tenant), body=body,
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
    data = _decode(payload)
    data["_status"] = status
    return data


def start_device_code(client_id: str, tenant: str = DEFAULT_TENANT) -> DeviceCode:
    """Ask Microsoft for a code the user types in a browser."""
    if not client_id.strip():
        raise SharePointError("Enter the application (client) ID of your Azure app registration first.")
    url = f"{AUTHORITY}/{urllib.parse.quote(tenant or DEFAULT_TENANT)}/oauth2/v2.0/devicecode"
    body = urllib.parse.urlencode({"client_id": client_id.strip(), "scope": SCOPES}).encode()
    status, _, payload = _http("POST", url, body=body,
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
    data = _decode(payload)
    if status != 200 or "device_code" not in data:
        description = str(data.get("error_description") or "").split("\r")[0]
        if data.get("error") == "unauthorized_client":
            raise SharePointError(
                "Microsoft rejected the client ID. Check it, and make sure 'Allow public client flows' "
                "is turned on in the app registration (Authentication page).")
        raise SharePointError(description or f"Could not start the sign-in (HTTP {status}).")
    return DeviceCode(
        user_code=str(data["user_code"]),
        verification_uri=str(data.get("verification_uri") or "https://microsoft.com/devicelogin"),
        device_code=str(data["device_code"]),
        interval=max(int(data.get("interval", 5)), 1),
        expires_at=time.time() + float(data.get("expires_in", 900)),
    )


def poll_device_code(client_id: str, tenant: str, code: DeviceCode,
                     cancelled: Callable[[], bool] = lambda: False) -> str:
    """Wait until the user finishes signing in; returns the refresh token.

    Raises:
        SharePointError: if the sign-in is declined, expires or is cancelled.
    """
    interval = code.interval
    while True:
        if cancelled():
            raise SharePointError("Sign-in cancelled.")
        if time.time() > code.expires_at:
            raise SharePointError("The sign-in code expired. Start again.")
        time.sleep(interval)
        data = _redeem(client_id.strip(), tenant,
                       {"grant_type": DEVICE_CODE_GRANT, "device_code": code.device_code})
        error = str(data.get("error") or "")
        if not error:
            refresh = str(data.get("refresh_token") or "")
            if not refresh:
                raise SharePointError("Microsoft did not return a refresh token. Add the 'offline_access' "
                                      "permission to the app registration.")
            return refresh
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "expired_token":
            raise SharePointError("The sign-in code expired. Start again.")
        if error == "authorization_declined":
            raise SharePointError("The sign-in was declined.")
        description = str(data.get("error_description") or error).split("\r")[0]
        raise SharePointError(description)


class GraphSession:
    """Keeps a usable access token, refreshing it from the stored refresh token.

    ``on_refresh`` is called whenever Microsoft issues a new refresh token so the
    caller can write it back to the credential vault.
    """

    def __init__(self, client_id: str, tenant: str, refresh_token: str,
                 on_refresh: Callable[[str], None] | None = None) -> None:
        self.client_id = client_id.strip()
        self.tenant = (tenant or DEFAULT_TENANT).strip()
        self._refresh_token = refresh_token
        self._on_refresh = on_refresh
        self._access = ""
        self._expires = 0.0

    def access_token(self) -> str:
        if self._access and time.time() < self._expires - 120:
            return self._access
        if not self._refresh_token:
            raise SharePointAuthError("Not signed in to SharePoint.")
        data = _redeem(self.client_id, self.tenant,
                       {"grant_type": "refresh_token", "refresh_token": self._refresh_token,
                        "scope": SCOPES})
        if data.get("error") or not data.get("access_token"):
            description = str(data.get("error_description") or data.get("error") or "").split("\r")[0]
            raise SharePointAuthError(f"The SharePoint sign-in is no longer valid - sign in again.\n{description}")
        self._access = str(data["access_token"])
        self._expires = time.time() + float(data.get("expires_in", 3600))
        new_refresh = str(data.get("refresh_token") or "")
        if new_refresh and new_refresh != self._refresh_token:
            self._refresh_token = new_refresh
            if self._on_refresh:
                self._on_refresh(new_refresh)
        return self._access


# ---------------------------------------------------------------------- #
# Names SharePoint refuses
# ---------------------------------------------------------------------- #
INVALID_CHARS = set('"*:<>?/\\|')
RESERVED = {"con", "prn", "aux", "nul", "desktop.ini"} | {f"com{d}" for d in "0123456789"} | \
           {f"lpt{d}" for d in "0123456789"}
MAX_PATH = 380  # SharePoint's limit is 400 characters for the whole server-relative path


def name_problem(name: str) -> str | None:
    """Why SharePoint would refuse this file or folder name (``None`` = it is fine)."""
    if not name or name != name.strip():
        return "the name starts or ends with a space"
    bad = sorted(INVALID_CHARS & set(name))
    if bad:
        return f"the name contains {' '.join(bad)}"
    if name.endswith("."):
        return "the name ends with a full stop"
    if name.lower() in RESERVED or name.split(".")[0].lower() in RESERVED:
        return f"{name!r} is a name Windows reserves"
    if name.startswith("~$") or name == ".lock" or "_vti_" in name.lower():
        return "this name is reserved"
    return None


def path_problem(relative_path: str) -> str | None:
    """Why SharePoint would refuse this whole relative path (``None`` = it is fine)."""
    for part in relative_path.split("/"):
        problem = name_problem(part)
        if problem:
            return problem
    if len(relative_path) > MAX_PATH:
        return "the path is too long (over 400 characters)"
    return None


# ---------------------------------------------------------------------- #
# Graph calls
# ---------------------------------------------------------------------- #
@dataclass(frozen=True)
class RemoteFile:
    """A file already in the SharePoint library."""

    path: str
    size: int
    modified: datetime


def _item_url(drive_id: str, path: str, suffix: str) -> str:
    """Address a drive item by path: ``/drives/{id}/root:/a/b:{suffix}``."""
    clean = path.strip("/")
    if not clean:
        return f"{GRAPH}/drives/{drive_id}/root{suffix}"
    return f"{GRAPH}/drives/{drive_id}/root:/{urllib.parse.quote(clean)}:{suffix}"


class SharePointClient:
    """Upload-only access to one document library."""

    def __init__(self, session: GraphSession) -> None:
        self.session = session
        self.drive_id = ""
        self.drive_name = ""
        self.web_url = ""

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.session.access_token()}", **(extra or {})}

    def _get(self, url: str) -> dict[str, Any]:
        status, _, payload = _http("GET", url, headers=self._headers())
        if status == 401:
            raise SharePointAuthError("Microsoft 365 rejected the sign-in - sign in again.")
        if status == 403:
            raise SharePointError("Your account is not allowed to use this site. Ask whoever owns the "
                                  "library to give you Edit access.")
        if status >= 400:
            raise SharePointError(_graph_error(status, payload))
        return _decode(payload)

    def account(self) -> str:
        """The signed-in user (for the Accounts menu)."""
        me = self._get(f"{GRAPH}/me?$select=userPrincipalName,displayName")
        return str(me.get("userPrincipalName") or me.get("displayName") or "signed in")

    def connect(self, site_url: str, library: str = "") -> None:
        """Resolve the site URL and document library to a drive id."""
        host, site_path = split_site_url(site_url)
        address = f"{GRAPH}/sites/{urllib.parse.quote(host)}"
        if site_path:
            address += f":/{urllib.parse.quote(site_path)}"
        try:
            site = self._get(address)
        except SharePointError as exc:
            raise SharePointError(f"Could not open the SharePoint site {site_url!r}.\n{exc}") from exc
        site_id = str(site.get("id") or "")
        if not site_id:
            raise SharePointError(f"{site_url!r} does not look like a SharePoint site.")
        drives = self._get(f"{GRAPH}/sites/{site_id}/drives?$select=id,name,webUrl").get("value") or []
        wanted = library.strip().lower()
        chosen = next((d for d in drives if str(d.get("name", "")).lower() == wanted), None) if wanted else None
        if chosen is None and wanted:
            names = ", ".join(str(d.get("name")) for d in drives) or "none"
            raise SharePointError(f"The site has no document library called {library!r}. It has: {names}.")
        if chosen is None:
            chosen = self._get(f"{GRAPH}/sites/{site_id}/drive?$select=id,name,webUrl")
        self.drive_id = str(chosen.get("id") or "")
        self.drive_name = str(chosen.get("name") or "Documents")
        self.web_url = str(chosen.get("webUrl") or "")
        if not self.drive_id:
            raise SharePointError("Could not open a document library on that site.")

    def ensure_folder(self, path: str) -> None:
        """Create ``path`` (and its parents) in the library; existing folders are left alone."""
        parts = [p for p in path.strip("/").split("/") if p]
        for depth in range(len(parts)):
            parent, name = "/".join(parts[:depth]), parts[depth]
            body = json.dumps({"name": name, "folder": {},
                               "@microsoft.graph.conflictBehavior": "fail"}).encode()
            status, _, payload = _http("POST", _item_url(self.drive_id, parent, "/children"), body=body,
                                       headers=self._headers({"Content-Type": "application/json"}))
            if status in (200, 201, 409):     # 409: already there, which is the normal case
                continue
            if status == 401:
                raise SharePointAuthError("Microsoft 365 rejected the sign-in - sign in again.")
            raise SharePointError(f"Could not create the folder {'/'.join(parts[:depth + 1])!r} in "
                                  f"the library.\n{_graph_error(status, payload)}")

    def index(self, path: str) -> dict[str, RemoteFile]:
        """Every file at or below ``path``, keyed by path relative to it.

        A folder that does not exist yet is reported as empty.
        """
        found: dict[str, RemoteFile] = {}
        pending = [""]
        while pending:
            branch = pending.pop()
            full = f"{path.strip('/')}/{branch}".strip("/") if branch else path.strip("/")
            url = _item_url(self.drive_id, full, "/children") + \
                "?$select=name,size,lastModifiedDateTime,folder,file&$top=200"
            while url:
                status, _, payload = _http("GET", url, headers=self._headers())
                if status == 404:
                    break                      # nothing uploaded here yet
                if status == 401:
                    raise SharePointAuthError("Microsoft 365 rejected the sign-in - sign in again.")
                if status >= 400:
                    raise SharePointError(f"Could not list the SharePoint folder {full!r}.\n"
                                          f"{_graph_error(status, payload)}")
                data = _decode(payload)
                for item in data.get("value") or []:
                    name = str(item.get("name") or "")
                    relative = f"{branch}/{name}".strip("/") if branch else name
                    if "folder" in item:
                        pending.append(relative)
                    else:
                        found[relative] = RemoteFile(
                            relative, int(item.get("size") or 0),
                            parse_time(str(item.get("lastModifiedDateTime") or "")))
                url = str(data.get("@odata.nextLink") or "")
        return found

    def upload(self, local: Path, remote_path: str,
               progress: Callable[[int, int], None] | None = None) -> None:
        """Upload one file, replacing what is there. Large files go in chunks."""
        size = local.stat().st_size
        if size <= SIMPLE_UPLOAD_LIMIT:
            status, _, payload = _http(
                "PUT", _item_url(self.drive_id, remote_path, "/content"), body=local.read_bytes(),
                headers=self._headers({"Content-Type": "application/octet-stream"}))
            if status in (200, 201):
                if progress:
                    progress(size, size)
                return
            if status == 401:
                raise SharePointAuthError("Microsoft 365 rejected the sign-in - sign in again.")
            raise SharePointError(f"Could not upload {local.name}.\n{_graph_error(status, payload)}")
        self._upload_large(local, remote_path, size, progress)

    def _upload_large(self, local: Path, remote_path: str, size: int,
                      progress: Callable[[int, int], None] | None) -> None:
        body = json.dumps({"item": {"@microsoft.graph.conflictBehavior": "replace"}}).encode()
        status, _, payload = _http("POST", _item_url(self.drive_id, remote_path, "/createUploadSession"),
                                   body=body, headers=self._headers({"Content-Type": "application/json"}))
        if status not in (200, 201):
            raise SharePointError(f"Could not start the upload of {local.name}.\n"
                                  f"{_graph_error(status, payload)}")
        upload_url = str(_decode(payload).get("uploadUrl") or "")
        if not upload_url:
            raise SharePointError(f"Microsoft did not return an upload address for {local.name}.")
        sent = 0
        with local.open("rb") as handle:
            while sent < size:
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                last = sent + len(chunk) - 1
                # The upload URL carries its own credentials; no Authorization header.
                status, _, payload = _http("PUT", upload_url, body=chunk, timeout=300.0, headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {sent}-{last}/{size}"})
                if status not in (200, 201, 202):
                    _http("DELETE", upload_url)
                    raise SharePointError(f"Could not upload {local.name} "
                                          f"({sent // (1024 * 1024)} MB sent).\n"
                                          f"{_graph_error(status, payload)}")
                sent += len(chunk)
                if progress:
                    progress(sent, size)


def split_site_url(site_url: str) -> tuple[str, str]:
    """``https://contoso.sharepoint.com/sites/Research`` → ``('contoso.sharepoint.com', 'sites/Research')``."""
    url = site_url.strip()
    if not url:
        raise SharePointError("Enter the address of the SharePoint site.")
    if "://" not in url:
        url = f"https://{url}"
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise SharePointError(f"{site_url!r} is not a valid SharePoint address.")
    path = parsed.path.strip("/")
    for tail in ("/forms/allitems.aspx", "/sitepages"):   # tolerate a pasted browser URL
        cut = path.lower().find(tail)
        if cut > 0:
            path = path[:cut].strip("/")
    parts = path.split("/")
    if len(parts) > 2 and parts[0].lower() in ("sites", "teams", "personal"):
        path = "/".join(parts[:2])
    return host, path
