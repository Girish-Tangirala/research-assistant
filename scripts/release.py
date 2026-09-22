"""Publish a new version: every installed copy of the app offers it at its next start.

    .venv\\Scripts\\python scripts\\release.py 1.1.0 --notes "Edit Text keeps footnotes; faster PDF preview"

Steps (it stops at the first problem, before anything is published):

1. checks that the Git repository is clean, on ``main``, and that 1.1.0 is newer than what is published,
2. writes the version into ``version.py``,
3. runs the tests (``--skip-tests`` to skip),
4. builds the app and the zips (``scripts/build_exe.py``),
5. commits ``version.py``, tags ``v1.1.0`` and pushes both to GitHub,
6. creates the GitHub release with the two zips attached.

GitHub access: a fine-grained token for the repository in ``version.UPDATE_REPO`` with *Contents:
read and write*. Save it once with ``release.py --set-token`` (hidden input, stored in Windows
Credential Manager), or set ``GITHUB_TOKEN``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import keyring

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import version  # noqa: E402
from core.credentials import GitCredential, git_auth_env  # noqa: E402
from core.updater import is_newer, parse_version  # noqa: E402

API = "https://api.github.com"
KEYRING_SERVICE = "ResearchAssistant-release"
PY = sys.executable


def fail(message: str) -> None:
    sys.exit(f"release: {message}")


def run(*cmd: str, env: dict | None = None) -> str:
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if result.returncode != 0:
        fail(f"{' '.join(cmd[:3])} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def credential() -> GitCredential:
    """The publishing token: ``GITHUB_TOKEN``, else the one saved with ``--set-token``.

    Kept apart from the app's own github.com sign-in, so the repository can belong to
    another GitHub account than the papers.
    """
    token = (os.getenv("GITHUB_TOKEN", "").strip()
             or keyring.get_password(KEYRING_SERVICE, version.UPDATE_REPO) or "")
    if not token:
        fail("no publishing token yet - run:  .venv\\Scripts\\python scripts\\release.py --set-token")
    return GitCredential("github.com", "x-access-token", token)


def set_token() -> None:
    """Ask for the token (hidden input), check it can publish to the repository, save it."""
    token = getpass.getpass(f"Paste the GitHub token for {version.UPDATE_REPO} (hidden) and press Enter: ").strip()
    if not token:
        fail("nothing entered")
    repo = github("GET", f"{API}/repos/{version.UPDATE_REPO}", token)
    if repo is None:
        fail(f"the token cannot see {version.UPDATE_REPO} - give it access to that repository.")
    if not repo.get("permissions", {}).get("push"):
        fail("the token can read but not write - set Contents to 'Read and write'.")
    keyring.set_password(KEYRING_SERVICE, version.UPDATE_REPO, token)
    print(f"Saved in Windows Credential Manager ({KEYRING_SERVICE}). It can publish to {version.UPDATE_REPO}.")


def github(method: str, url: str, token: str, body: bytes | None = None, content_type: str = "application/json"):
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type": content_type, "User-Agent": "ResearchAssistant-release"})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310 - GitHub API
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == "GET":
            return None
        fail(f"GitHub {method} {url} -> {exc.code}: {exc.read().decode(errors='replace')[:400]}")


def set_version(new: str) -> None:
    path = ROOT / "version.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(r'__version__ = "[^"]*"', f'__version__ = "{new}"', text, count=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", nargs="?", help="new version, e.g. 1.1.0")
    parser.add_argument("--notes", default="", help="what changed (shown to colleagues in the update window)")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--set-token", action="store_true", help="save the GitHub token used for publishing")
    args = parser.parse_args()
    if args.set_token:
        set_token()
        return
    if not args.version:
        parser.error("give the new version, e.g. 1.1.0")
    new, repo = args.version.lstrip("v"), version.UPDATE_REPO
    if not parse_version(new):
        fail(f"{args.version!r} is not a version like 1.2.0")

    # 1. checks
    if run("git", "rev-parse", "--abbrev-ref", "HEAD") != "main":
        fail("switch to the main branch first")
    if run("git", "status", "--porcelain"):
        fail("commit or undo your changes first (git status shows uncommitted files)")
    cred = credential()
    published = github("GET", f"{API}/repos/{repo}/releases/latest", cred.token)
    if published and not is_newer(new, published["tag_name"]):
        fail(f"{new} is not newer than the published {published['tag_name']}")
    if new != version.__version__ and not is_newer(new, version.__version__):
        fail(f"{new} is older than version.py ({version.__version__})")

    # 2.-4. version, tests, build
    set_version(new)
    try:
        if not args.skip_tests:
            print("Running the tests…")
            run(PY, "-m", "pytest", "-q", "--timeout", "300")
        print("Building…")
        run(PY, "scripts/build_exe.py")
    except SystemExit:
        run("git", "checkout", "--", "version.py")
        raise
    app_zip = ROOT / "dist" / f"ResearchAssistant-windows-{new}.zip"
    source_zip = ROOT / "dist" / f"ResearchAssistant-source-{new}.zip"

    # 5. commit, tag, push
    tag = f"v{new}"
    if run("git", "status", "--porcelain", "version.py"):
        run("git", "commit", "-m", f"Release {tag}", "--", "version.py")
    run("git", "tag", "-a", tag, "-m", f"Release {tag}")
    auth = git_auth_env(cred)
    run("git", "push", "origin", "main", env=auth)
    run("git", "push", "origin", tag, env=auth)

    # 6. release with the zips
    release = github("POST", f"{API}/repos/{repo}/releases", cred.token, json.dumps({
        "tag_name": tag, "name": f"Research Assistant {new}", "body": args.notes or f"Version {new}"}).encode())
    upload = release["upload_url"].split("{")[0]
    for path in (app_zip, source_zip):
        print(f"Uploading {path.name} ({path.stat().st_size / 1e6:.0f} MB)…")
        github("POST", f"{upload}?name={path.name}", cred.token, path.read_bytes(), "application/zip")
    print(f"Published {release['html_url']} - colleagues get it at their next start.")


if __name__ == "__main__":
    main()
