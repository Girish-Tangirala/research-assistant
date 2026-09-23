"""SharePoint backup: URL parsing, name rules, the Graph calls and the upload plan.

No network: :func:`core.sharepoint._http` is replaced with a table of canned replies.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core import onedrive
from core import sharepoint as sp
from core.app_state import AppState, SharePointSettings, validate_sharepoint
from core.onedrive import covering_root
from core.credentials import CredentialStore
from core.sharepoint_folder import LocalLibraryClient
from core.sharepoint_sync import (
    Upload, human_size, load_manifest, local_files, plan_backup, remote_base, run_backup,
)
from tests.test_credentials_state import MemoryBackend

GRAPH = sp.GRAPH


class FakeHttp:
    """Stands in for ``_http``: answers from ``routes``, remembers every call."""

    def __init__(self, routes: dict[tuple[str, str], tuple[int, dict, bytes]]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, bytes | None]] = []

    def __call__(self, method, url, *, body=None, headers=None, timeout=sp.TIMEOUT, retries=4):
        self.calls.append((method, url, body))
        for (route_method, fragment), reply in self.routes.items():
            if method == route_method and fragment in url:
                return reply
        return 404, {}, b'{"error": {"code": "itemNotFound", "message": "not found"}}'


def ok(payload: dict) -> tuple[int, dict, bytes]:
    return 200, {}, json.dumps(payload).encode()


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(sp.time, "sleep", lambda _s: None)


# ---------------------------------------------------------------------- #
# URLs and names
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(("url", "expected"), [
    ("https://contoso.sharepoint.com/sites/Research", ("contoso.sharepoint.com", "sites/Research")),
    ("contoso.sharepoint.com/sites/Research/", ("contoso.sharepoint.com", "sites/Research")),
    ("https://contoso.sharepoint.com", ("contoso.sharepoint.com", "")),
    ("https://contoso.sharepoint.com/sites/Research/Shared%20Documents/Forms/AllItems.aspx",
     ("contoso.sharepoint.com", "sites/Research")),
    ("https://contoso.sharepoint.com/teams/Lab/SitePages/Home.aspx", ("contoso.sharepoint.com", "teams/Lab")),
])
def test_split_site_url(url, expected):
    assert sp.split_site_url(url) == expected


def test_split_site_url_rejects_rubbish():
    with pytest.raises(sp.SharePointError):
        sp.split_site_url("   ")


@pytest.mark.parametrize("name", ["results.csv", "run 3.dat", "figure-1.png", "a.b.c.txt"])
def test_good_names_pass(name):
    assert sp.name_problem(name) is None


@pytest.mark.parametrize("name", ["bad:name.csv", "with*star.txt", "ends.", " leading.txt",
                                  "CON", "~$draft.xlsx", ".lock", 'quote".txt'])
def test_bad_names_are_explained(name):
    assert sp.name_problem(name)


def test_path_problem_checks_every_part_and_length():
    assert sp.path_problem("data/good/file.csv") is None
    assert "contains" in sp.path_problem("data/bad:folder/file.csv")
    assert "too long" in sp.path_problem("data/" + "x" * 400)


def test_parse_time_handles_graph_shapes():
    assert sp.parse_time("2026-01-15T10:30:00Z") == datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc)
    assert sp.parse_time("2026-01-15T10:30:00.1234567Z").year == 2026
    assert sp.parse_time("nonsense").year == 1970


# ---------------------------------------------------------------------- #
# Sign-in
# ---------------------------------------------------------------------- #
def test_device_code_start_and_poll(monkeypatch, no_sleep):
    replies = [
        (200, {}, json.dumps({"device_code": "dev", "user_code": "ABCD-EFGH", "interval": 1,
                              "expires_in": 900, "verification_uri": "https://microsoft.com/devicelogin"}).encode()),
        (400, {}, json.dumps({"error": "authorization_pending"}).encode()),
        (400, {}, json.dumps({"error": "slow_down"}).encode()),
        (200, {}, json.dumps({"access_token": "at", "refresh_token": "rt", "expires_in": 3600}).encode()),
    ]
    monkeypatch.setattr(sp, "_http", lambda *a, **k: replies.pop(0))
    code = sp.start_device_code("client-id", "organizations")
    assert code.user_code == "ABCD-EFGH"
    assert sp.poll_device_code("client-id", "organizations", code) == "rt"


def test_device_code_reports_a_bad_client_id(monkeypatch):
    monkeypatch.setattr(sp, "_http", lambda *a, **k: (
        400, {}, json.dumps({"error": "unauthorized_client"}).encode()))
    with pytest.raises(sp.SharePointError, match="public client flows"):
        sp.start_device_code("wrong", "organizations")


def test_declined_sign_in_is_reported(monkeypatch, no_sleep):
    code = sp.DeviceCode("A", "https://x", "dev", 1, sp.time.time() + 60)
    monkeypatch.setattr(sp, "_http", lambda *a, **k: (
        400, {}, json.dumps({"error": "authorization_declined"}).encode()))
    with pytest.raises(sp.SharePointError, match="declined"):
        sp.poll_device_code("client-id", "organizations", code)


def test_session_refreshes_and_reports_a_new_refresh_token(monkeypatch):
    monkeypatch.setattr(sp, "_http", lambda *a, **k: ok(
        {"access_token": "at-1", "refresh_token": "rt-2", "expires_in": 3600}))
    saved: list[str] = []
    session = sp.GraphSession("client-id", "organizations", "rt-1", on_refresh=saved.append)
    assert session.access_token() == "at-1"
    assert saved == ["rt-2"]
    assert session.access_token() == "at-1"  # cached, no second redemption


def test_revoked_sign_in_raises_auth_error(monkeypatch):
    monkeypatch.setattr(sp, "_http", lambda *a, **k: (
        400, {}, json.dumps({"error": "invalid_grant", "error_description": "revoked"}).encode()))
    with pytest.raises(sp.SharePointAuthError, match="sign in again"):
        sp.GraphSession("client-id", "organizations", "rt").access_token()


# ---------------------------------------------------------------------- #
# Graph calls
# ---------------------------------------------------------------------- #
def _client(monkeypatch, routes) -> tuple[sp.SharePointClient, FakeHttp]:
    fake = FakeHttp(routes)
    monkeypatch.setattr(sp, "_http", fake)
    session = sp.GraphSession("client-id", "organizations", "rt")
    monkeypatch.setattr(session, "access_token", lambda: "at")
    return sp.SharePointClient(session), fake


SITE_ROUTES = {
    ("GET", "/sites/contoso.sharepoint.com:/sites/Research"): ok({"id": "site-1"}),
    ("GET", "/sites/site-1/drives"): ok({"value": [{"id": "drive-1", "name": "Documents",
                                                    "webUrl": "https://contoso.sharepoint.com/d"}]}),
}


def test_connect_picks_the_named_library(monkeypatch):
    client, _ = _client(monkeypatch, SITE_ROUTES)
    client.connect("https://contoso.sharepoint.com/sites/Research", "Documents")
    assert (client.drive_id, client.drive_name) == ("drive-1", "Documents")


def test_connect_explains_a_missing_library(monkeypatch):
    client, _ = _client(monkeypatch, SITE_ROUTES)
    with pytest.raises(sp.SharePointError, match="no document library called 'Data'"):
        client.connect("https://contoso.sharepoint.com/sites/Research", "Data")


def test_index_walks_subfolders_and_tolerates_a_missing_root(monkeypatch):
    routes = {
        ("GET", "root:/Papers/P1:/children"): ok({"value": [
            {"name": "a.csv", "size": 10, "lastModifiedDateTime": "2026-01-01T00:00:00Z", "file": {}},
            {"name": "runs", "folder": {"childCount": 1}},
        ]}),
        ("GET", "root:/Papers/P1/runs:/children"): ok({"value": [
            {"name": "b.dat", "size": 20, "lastModifiedDateTime": "2026-01-02T00:00:00Z", "file": {}},
        ]}),
    }
    client, _ = _client(monkeypatch, routes)
    client.drive_id = "drive-1"
    index = client.index("Papers/P1")
    assert sorted(index) == ["a.csv", "runs/b.dat"]
    assert index["runs/b.dat"].size == 20
    assert client.index("Papers/Missing") == {}


def test_ensure_folder_creates_each_level_and_accepts_existing(monkeypatch):
    routes = {("POST", "/children"): (409, {}, b'{"error": {"code": "nameAlreadyExists"}}')}
    client, fake = _client(monkeypatch, routes)
    client.drive_id = "drive-1"
    client.ensure_folder("Papers/P1/data/runs")
    names = [json.loads(body)["name"] for method, _url, body in fake.calls if method == "POST"]
    assert names == ["Papers", "P1", "data", "runs"]


def test_small_upload_uses_a_single_put(monkeypatch, tmp_path):
    routes = {("PUT", "root:/Papers/a.csv:/content"): ok({"id": "item-1"})}
    client, fake = _client(monkeypatch, routes)
    client.drive_id = "drive-1"
    local = tmp_path / "a.csv"
    local.write_bytes(b"x,y\n1,2\n")
    client.upload(local, "Papers/a.csv")
    assert [c[0] for c in fake.calls] == ["PUT"]


def test_large_upload_is_chunked(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "SIMPLE_UPLOAD_LIMIT", 8)
    monkeypatch.setattr(sp, "CHUNK", 8)
    routes = {
        ("POST", "/createUploadSession"): ok({"uploadUrl": "https://upload.example/session"}),
        ("PUT", "https://upload.example/session"): (202, {}, b"{}"),
    }
    client, fake = _client(monkeypatch, routes)
    client.drive_id = "drive-1"
    local = tmp_path / "big.bin"
    local.write_bytes(b"0123456789abcdefghij")   # 20 bytes -> 3 chunks
    seen: list[tuple[int, int]] = []
    client.upload(local, "Papers/big.bin", progress=lambda sent, total: seen.append((sent, total)))
    assert len([c for c in fake.calls if c[0] == "PUT"]) == 3
    assert seen == [(8, 20), (16, 20), (20, 20)]


def test_upload_failure_carries_the_graph_message(monkeypatch, tmp_path):
    routes = {("PUT", "/content"): (507, {}, json.dumps(
        {"error": {"code": "quotaLimitReached", "message": "Storage quota exceeded"}}).encode())}
    client, _ = _client(monkeypatch, routes)
    client.drive_id = "drive-1"
    local = tmp_path / "a.csv"
    local.write_bytes(b"data")
    with pytest.raises(sp.SharePointError, match="Storage quota exceeded"):
        client.upload(local, "Papers/a.csv")


def test_401_becomes_an_auth_error(monkeypatch):
    client, _ = _client(monkeypatch, {("GET", "/me"): (401, {}, b'{"error": {"code": "InvalidAuthenticationToken"}}')})
    with pytest.raises(sp.SharePointAuthError):
        client.account()


# ---------------------------------------------------------------------- #
# Planning the backup
# ---------------------------------------------------------------------- #
@pytest.fixture
def paper(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    (root / "data" / "runs").mkdir(parents=True)
    (root / "supplementary").mkdir()
    (root / "manuscript").mkdir()
    (root / "data" / "results.csv").write_bytes(b"a,b\n1,2\n")
    (root / "data" / "runs" / "run1.dat").write_bytes(b"0" * 100)
    (root / "data" / "Thumbs.db").write_bytes(b"junk")
    (root / "supplementary" / "video.mp4").write_bytes(b"1" * 50)
    (root / "manuscript" / "intro.tex").write_bytes(b"text")
    return root


def test_remote_base_joins_and_trims():
    assert remote_base("Research papers/", " Paper 1 ") == "Research papers/Paper 1"
    assert remote_base("", "Paper 1") == "Paper 1"


def test_local_files_takes_only_the_chosen_folders(paper):
    found = [rel for _p, rel in local_files(paper, ["data", "supplementary"])]
    assert "data/results.csv" in found
    assert "data/runs/run1.dat" in found
    assert "supplementary/video.mp4" in found
    assert "manuscript/intro.tex" not in found       # that one goes to Overleaf instead
    assert "data/Thumbs.db" not in found             # operating-system clutter


def test_plan_marks_new_changed_and_unchanged(paper):
    base = "Papers/P1"
    stat = (paper / "data" / "results.csv").stat()
    manifest = {"data/results.csv": [stat.st_size, stat.st_mtime_ns],
                "data/runs/run1.dat": [1, 1]}
    remote = {
        "data/results.csv": sp.RemoteFile("data/results.csv", stat.st_size,
                                          datetime(2026, 1, 1, tzinfo=timezone.utc)),
        "data/runs/run1.dat": sp.RemoteFile("data/runs/run1.dat", 1,
                                            datetime(2026, 1, 1, tzinfo=timezone.utc)),
    }
    plan = plan_backup(paper, ["data", "supplementary"], base, remote, manifest)
    by_path = {u.relative: u for u in plan.uploads}
    assert plan.unchanged == 1                       # results.csv is already there, untouched
    assert by_path["data/runs/run1.dat"].new is False  # there, but edited here since
    assert by_path["supplementary/video.mp4"].new is True
    assert by_path["supplementary/video.mp4"].remote_path == "Papers/P1/supplementary/video.mp4"


def test_plan_skips_names_that_are_not_allowed(tmp_path):
    root = tmp_path / "paper"
    (root / "data").mkdir(parents=True)
    (root / "data" / "CON.txt").write_bytes(b"x")
    (root / "data" / "fine.txt").write_bytes(b"x")
    plan = plan_backup(root, ["data"], "Papers/P1", {}, {})
    assert [u.relative for u in plan.uploads] == ["data/fine.txt"]
    assert plan.skipped[0].relative == "data/CON.txt"
    assert "reserves" in plan.skipped[0].reason


def test_plan_is_empty_when_nothing_changed(paper):
    plan = plan_backup(paper, ["data"], "Papers/P1", {}, {})
    manifest = {u.relative: [u.local.stat().st_size, u.local.stat().st_mtime_ns] for u in plan.uploads}
    remote = {u.relative: sp.RemoteFile(u.relative, u.size, datetime(2026, 1, 1, tzinfo=timezone.utc))
              for u in plan.uploads}
    assert plan_backup(paper, ["data"], "Papers/P1", remote, manifest).empty


# ---------------------------------------------------------------------- #
# Running the backup
# ---------------------------------------------------------------------- #
class FakeClient:
    """A SharePointClient that records instead of uploading; ``fail`` names a casualty."""

    def __init__(self, fail: str = "", auth_error_on: str = "") -> None:
        self.folders: list[str] = []
        self.uploaded: list[str] = []
        self.fail, self.auth_error_on = fail, auth_error_on
        self.web_url = "https://contoso.sharepoint.com/d"

    def ensure_folder(self, path: str) -> None:
        self.folders.append(path)

    def upload(self, local: Path, remote_path: str, progress=None) -> None:
        if self.auth_error_on and self.auth_error_on in remote_path:
            raise sp.SharePointAuthError("token revoked")
        if self.fail and self.fail in remote_path:
            raise sp.SharePointError("blocked file type")
        self.uploaded.append(remote_path)


def test_run_backup_uploads_and_remembers(paper, tmp_path):
    workspace = tmp_path / "workspace"
    plan = plan_backup(paper, ["data", "supplementary"], "Papers/P1", {}, {})
    client = FakeClient()
    result = run_backup(client, plan, "Papers/P1", workspace, "Paper 1")
    assert result.uploaded == len(plan.uploads)
    assert "Papers/P1/data/runs" in client.folders
    manifest = load_manifest(workspace, "Paper 1")
    assert manifest["data/results.csv"][0] == (paper / "data" / "results.csv").stat().st_size
    # A second run has nothing left to do.
    remote = {u.relative: sp.RemoteFile(u.relative, u.size, datetime.now(timezone.utc))
              for u in plan.uploads}
    assert plan_backup(paper, ["data", "supplementary"], "Papers/P1", remote, manifest).empty


def test_one_rejected_file_does_not_stop_the_rest(paper, tmp_path):
    plan = plan_backup(paper, ["data", "supplementary"], "Papers/P1", {}, {})
    result = run_backup(FakeClient(fail="video.mp4"), plan, "Papers/P1", tmp_path, "Paper 1")
    assert result.uploaded == len(plan.uploads) - 1
    assert result.failed[0].relative == "supplementary/video.mp4"
    assert "blocked file type" in result.failed[0].reason


def test_a_revoked_sign_in_stops_everything_but_keeps_what_was_sent(paper, tmp_path):
    plan = plan_backup(paper, ["data", "supplementary"], "Papers/P1", {}, {})
    client = FakeClient(auth_error_on="video.mp4")
    with pytest.raises(sp.SharePointAuthError):
        run_backup(client, plan, "Papers/P1", tmp_path, "Paper 1")
    assert load_manifest(tmp_path, "Paper 1")        # the files that did go are remembered


def test_cancelling_stops_after_the_current_file(paper, tmp_path):
    plan = plan_backup(paper, ["data", "supplementary"], "Papers/P1", {}, {})
    assert len(plan.uploads) > 2
    sent: list[Upload] = []
    result = run_backup(FakeClient(), plan, "Papers/P1", tmp_path, "Paper 1",
                        on_file=lambda u, _i, _t: sent.append(u),
                        cancelled=lambda: len(sent) >= 2)
    assert result.cancelled and result.uploaded == 2
    assert load_manifest(tmp_path, "Paper 1")        # what did go is remembered for next time


def test_progress_never_goes_backwards_and_ends_full(paper, tmp_path):
    plan = plan_backup(paper, ["data", "supplementary"], "Papers/P1", {}, {})
    seen: list[tuple[int, int]] = []
    run_backup(FakeClient(), plan, "Papers/P1", tmp_path, "Paper 1",
               on_bytes=lambda sent, total: seen.append((sent, total)))
    assert seen[-1] == (plan.total_bytes, plan.total_bytes)
    assert [s for s, _t in seen] == sorted(s for s, _t in seen)
    assert all(s <= t for s, t in seen)


def test_a_failed_file_still_advances_the_progress(paper, tmp_path):
    """Otherwise the bar would stall at a rejected file and look frozen."""
    plan = plan_backup(paper, ["data", "supplementary"], "Papers/P1", {}, {})
    seen: list[tuple[int, int]] = []
    result = run_backup(FakeClient(fail="video.mp4"), plan, "Papers/P1", tmp_path, "Paper 1",
                        on_bytes=lambda sent, total: seen.append((sent, total)))
    assert result.failed and seen[-1] == (plan.total_bytes, plan.total_bytes)


def test_progress_follows_the_chunks_of_one_large_file(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "SIMPLE_UPLOAD_LIMIT", 8)
    monkeypatch.setattr(sp, "CHUNK", 8)
    routes = {("POST", "/createUploadSession"): ok({"uploadUrl": "https://upload.example/s"}),
              ("PUT", "https://upload.example/s"): (202, {}, b"{}"),
              ("POST", "/children"): (409, {}, b'{"error": {"code": "nameAlreadyExists"}}')}
    client, _ = _client(monkeypatch, routes)
    client.drive_id = "drive-1"
    root = tmp_path / "paper"
    (root / "data").mkdir(parents=True)
    (root / "data" / "big.bin").write_bytes(b"x" * 20)
    plan = plan_backup(root, ["data"], "P1", {}, {})
    seen: list[int] = []
    run_backup(client, plan, "P1", tmp_path / "ws", "P1", on_bytes=lambda sent, _t: seen.append(sent))
    assert seen == [8, 16, 20, 20]          # three chunks, then the file completing


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KB"
    assert human_size(5 * 1024 * 1024) == "5.0 MB"


class FakeLibrary:
    """A stateful stand-in for a document library, driven through the real client."""

    def __init__(self) -> None:
        self.files: dict[str, int] = {}
        self.folders: set[str] = set()
        self.uploads = 0

    def _path_of(self, url: str) -> str:
        from urllib.parse import unquote
        body = url.split("/root", 1)[1]
        if body.startswith(":/"):
            return unquote(body[2:].split(":", 1)[0])
        return ""

    def __call__(self, method, url, *, body=None, headers=None, timeout=sp.TIMEOUT, retries=4):
        path = self._path_of(url)
        if method == "POST" and url.endswith("/children"):
            name = json.loads(body)["name"]
            full = f"{path}/{name}".strip("/")
            if full in self.folders:
                return 409, {}, b'{"error": {"code": "nameAlreadyExists"}}'
            self.folders.add(full)
            return 201, {}, b'{"id": "f"}'
        if method == "GET" and "/children" in url:
            if path and path not in self.folders:
                return 404, {}, b'{"error": {"code": "itemNotFound"}}'
            children = []
            for folder in self.folders:
                if folder.rsplit("/", 1)[0] == path and folder != path:
                    children.append({"name": folder.rsplit("/", 1)[-1], "folder": {}})
            for name, size in self.files.items():
                if name.rsplit("/", 1)[0] == path:
                    children.append({"name": name.rsplit("/", 1)[-1], "size": size,
                                     "lastModifiedDateTime": "2026-01-01T00:00:00Z", "file": {}})
            return ok({"value": children})
        if method == "PUT" and url.endswith("/content"):
            self.files[path] = len(body or b"")
            self.uploads += 1
            return 201, {}, b'{"id": "i"}'
        return 404, {}, b'{"error": {"code": "itemNotFound"}}'


def test_a_second_backup_uploads_nothing(monkeypatch, paper, tmp_path):
    """The whole round trip: the library ends up mirroring the paper, and stays quiet after."""
    library = FakeLibrary()
    monkeypatch.setattr(sp, "_http", library)
    session = sp.GraphSession("cid", "organizations", "rt")
    monkeypatch.setattr(session, "access_token", lambda: "at")
    client = sp.SharePointClient(session)
    client.drive_id = "drive-1"
    base, workspace, folders = "Research papers/Paper 1", tmp_path / "ws", ["data", "supplementary"]

    def one_run():
        plan = plan_backup(paper, folders, base, client.index(base), load_manifest(workspace, "Paper 1"))
        return run_backup(client, plan, base, workspace, "Paper 1")

    first = one_run()
    assert first.uploaded == 3 and not first.failed
    assert sorted(library.files) == [
        "Research papers/Paper 1/data/results.csv",
        "Research papers/Paper 1/data/runs/run1.dat",
        "Research papers/Paper 1/supplementary/video.mp4",
    ]
    assert one_run().uploaded == 0                    # nothing changed here, so nothing is sent
    (paper / "data" / "results.csv").write_bytes(b"a,b\n1,2\n3,4\n")
    third = one_run()
    assert third.uploaded == 1 and third.unchanged == 2


# ---------------------------------------------------------------------- #
# The OneDrive-synced folder route
# ---------------------------------------------------------------------- #
def test_folder_client_mirrors_the_paper(paper, tmp_path):
    library = tmp_path / "OneDrive - University" / "Team - Documents"
    library.mkdir(parents=True)
    client = LocalLibraryClient(library)
    client.check()
    base, workspace, folders = "Research papers/Paper 1", tmp_path / "ws", ["data", "supplementary"]

    def one_run():
        plan = plan_backup(paper, folders, base, client.index(base), load_manifest(workspace, "Paper 1"))
        return run_backup(client, plan, base, workspace, "Paper 1")

    assert one_run().uploaded == 3
    assert (library / base / "data" / "runs" / "run1.dat").read_bytes() == b"0" * 100
    assert (library / base / "supplementary" / "video.mp4").is_file()
    assert one_run().uploaded == 0                    # OneDrive is left alone when nothing changed
    (paper / "data" / "results.csv").write_bytes(b"a,b\n9,9\n")
    assert one_run().uploaded == 1


def test_folder_client_explains_a_missing_folder(tmp_path):
    with pytest.raises(sp.SharePointError, match="does not exist"):
        LocalLibraryClient(tmp_path / "gone").check()


def test_folder_client_leaves_no_partial_file_behind(paper, tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    client = LocalLibraryClient(library)
    client.upload(paper / "data" / "results.csv", "P1/data/results.csv")
    assert [p.name for p in (library / "P1" / "data").iterdir()] == ["results.csv"]


def test_folder_client_ignores_its_own_partial_files(paper, tmp_path):
    library = tmp_path / "lib"
    (library / "P1").mkdir(parents=True)
    (library / "P1" / "a.csv").write_bytes(b"x")
    (library / "P1" / "b.csv.part-researchassistant").write_bytes(b"half")
    assert sorted(LocalLibraryClient(library).index("P1")) == ["a.csv"]


def test_folder_client_refuses_to_escape_the_library(tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    with pytest.raises(sp.SharePointError, match="outside the library"):
        LocalLibraryClient(library).ensure_folder("../elsewhere")


# ---------------------------------------------------------------------- #
# Is the folder one OneDrive actually syncs?
# ---------------------------------------------------------------------- #
def test_covering_root_matches_the_folder_and_its_children(tmp_path):
    root = tmp_path / "OneDrive - Uni"
    inside = root / "Team - Documents" / "Research papers"
    inside.mkdir(parents=True)
    outside = tmp_path / "Desktop"
    outside.mkdir()
    assert covering_root(inside, [root]) == root.resolve()
    assert covering_root(root, [root]) == root.resolve()
    assert covering_root(outside, [root]) is None
    assert covering_root(inside, []) is None


def test_covering_root_is_not_fooled_by_a_shared_prefix(tmp_path):
    root = tmp_path / "OneDrive"
    root.mkdir()
    sibling = tmp_path / "OneDrive backup"
    sibling.mkdir()
    assert covering_root(sibling, [root]) is None


def test_folder_problem_names_the_folders_onedrive_does_sync(monkeypatch, tmp_path):
    root = tmp_path / "OneDrive - Uni"
    root.mkdir()
    monkeypatch.setattr(onedrive, "sync_roots", lambda: [root])
    monkeypatch.setattr(onedrive, "is_running", lambda: True)
    assert onedrive.folder_problem(root / "Team - Documents") is None
    problem = onedrive.folder_problem(tmp_path / "Desktop")
    assert "not inside a folder OneDrive syncs" in problem
    assert str(root) in problem


def test_folder_problem_warns_when_onedrive_is_closed_or_absent(monkeypatch, tmp_path):
    root = tmp_path / "OneDrive"
    root.mkdir()
    monkeypatch.setattr(onedrive, "sync_roots", lambda: [root])
    monkeypatch.setattr(onedrive, "is_running", lambda: False)
    assert "not running" in onedrive.folder_problem(root)
    monkeypatch.setattr(onedrive, "sync_roots", list)
    assert "does not seem to be set up" in onedrive.folder_problem(root)


def test_registry_paths_with_variables_are_expanded(monkeypatch):
    monkeypatch.setenv("UserProfile", r"C:\Users\someone")
    assert onedrive._as_path(r"%UserProfile%\OneDrive") == Path(r"C:\Users\someone\OneDrive")
    assert onedrive._as_path("") is None
    assert onedrive._as_path(r"%NotSet%\OneDrive") is None


# ---------------------------------------------------------------------- #
# Settings
# ---------------------------------------------------------------------- #
def test_settings_survive_a_save_and_load(tmp_path):
    state = AppState()
    state.sharepoint = SharePointSettings(mode="graph", client_id="cid", tenant="tid",
                                          site_url="https://contoso.sharepoint.com/sites/R",
                                          library="Documents", root_folder="Papers",
                                          folders="data, supplementary", account="me@contoso.com")
    path = tmp_path / "app_state.json"
    state.save(path)
    assert "cid" in path.read_text(encoding="utf-8")
    loaded = AppState.load(path).sharepoint
    assert loaded.client_id == "cid" and loaded.account == "me@contoso.com"
    assert loaded.folder_list == ["data", "supplementary"]
    assert loaded.uses_graph and loaded.configured


def test_state_without_sharepoint_still_loads(tmp_path):
    path = tmp_path / "app_state.json"
    path.write_text(json.dumps({"papers": [], "selected": ""}), encoding="utf-8")
    settings = AppState.load(path).sharepoint
    assert settings.configured is False
    assert settings.mode == "folder"          # the route that needs no app registration


def test_an_unknown_mode_falls_back_to_the_folder_route(tmp_path):
    path = tmp_path / "app_state.json"
    path.write_text(json.dumps({"sharepoint": {"mode": "carrier pigeon"}}), encoding="utf-8")
    assert AppState.load(path).sharepoint.mode == "folder"


def test_graph_settings_need_a_client_id_and_site():
    assert validate_sharepoint(SharePointSettings(mode="graph"))
    assert not validate_sharepoint(SharePointSettings(
        mode="graph", client_id="cid", site_url="https://contoso.sharepoint.com/sites/R"))
    assert any("folder" in p for p in validate_sharepoint(SharePointSettings(
        mode="graph", client_id="cid", site_url="https://contoso.sharepoint.com/sites/R", folders=" ")))


def test_folder_settings_need_a_real_folder(tmp_path):
    assert any("OneDrive" in p for p in validate_sharepoint(SharePointSettings()))
    missing = validate_sharepoint(SharePointSettings(local_library=str(tmp_path / "nope")))
    assert any("not a folder" in p for p in missing)
    assert not validate_sharepoint(SharePointSettings(local_library=str(tmp_path)))


# ---------------------------------------------------------------------- #
# Nothing the user can read says "SharePoint"
# ---------------------------------------------------------------------- #
# The word is kept out of the interface while the Graph route is hidden: the group has no
# SharePoint library, so it would only confuse. These are the modules whose strings can
# reach a user through the OneDrive route; core/sharepoint.py is Graph-only and unreachable.
USER_FACING = ("gui", "core/onedrive.py", "core/sharepoint_folder.py", "core/sharepoint_sync.py",
               "core/app_state.py")
# Internal identifiers, never shown as prose: a settings key and a credential-vault key.
ALLOWED = {"sharepoint", "sharepoint_token"}


def _visible_strings(path: Path):
    """Every string literal in ``path`` that is not a docstring, with its line number."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {doc for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and (doc := ast.get_docstring(node, clean=False))}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in docstrings:
            yield node.lineno, node.value


def test_no_user_visible_string_mentions_sharepoint():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for entry in USER_FACING:
        target = root / entry
        for path in (sorted(target.rglob("*.py")) if target.is_dir() else [target]):
            for line, value in _visible_strings(path):
                if "sharepoint" in value.lower() and value.strip().lower() not in ALLOWED:
                    offenders.append(f"{path.relative_to(root)}:{line}: {value.strip()[:70]}")
    assert not offenders, "user-visible text still says SharePoint:\n" + "\n".join(offenders)


def test_the_graph_route_is_still_intact_behind_the_scenes():
    """Hidden, not deleted - it comes back when a library and an app registration exist."""
    assert SharePointSettings(mode="graph", client_id="c", site_url="https://x/sites/y").uses_graph
    assert callable(sp.start_device_code) and callable(sp.SharePointClient.upload)


def test_token_is_stored_in_the_vault():
    store = CredentialStore(MemoryBackend())
    assert store.get_sharepoint_token() is None
    store.set_sharepoint_token("  refresh-token  ")
    assert store.get_sharepoint_token() == "refresh-token"
    store.clear_sharepoint_token()
    store.clear_sharepoint_token()
    assert store.get_sharepoint_token() is None
