"""Updating an existing install in place.

Two install shapes exist and they update differently: a git clone pulls, and a
tarball install from `install.sh` re-downloads. Both end up at the same place,
so `claude-pet update` picks the right one rather than making the user know
which they have.

Stdlib only.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "HaneulOscarLee/claude-pet"
BRANCH = "main"
TIMEOUT_SECONDS = 30

#: Written next to the code by a tarball update, since there is no git history
#: to ask.
VERSION_FILE = ".claude-pet-version"


class UpdateError(Exception):
    """Raised when the update cannot proceed."""


def install_root() -> Path:
    from . import launch

    return launch.project_root()


def is_git_checkout(root: Path | None = None) -> bool:
    return ((root or install_root()) / ".git").exists()


def releases_url() -> str:
    return f"https://github.com/{REPO}/releases/latest"


def is_system_install(root: Path | None = None) -> bool:
    """A package-managed install: owned by root, so we must not rewrite it."""
    return not os.access(root or install_root(), os.W_OK)


def _git(*args: str, root: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv
        ["git", "-C", str(root or install_root()), *args],
        capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False,
    )


def installed_version() -> str:
    root = install_root()
    if is_git_checkout(root):
        result = _git("rev-parse", "--short", "HEAD", root=root)
        return result.stdout.strip() or "unknown"
    marker = root / VERSION_FILE
    try:
        return marker.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def latest_release() -> str:
    """Tag of the newest release, without the leading v.

    What a packaged install should compare against: a new .deb only exists when
    a release is cut, so comparing with the tip of the branch would report an
    update every time main moved.
    """
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    request = urllib.request.Request(
        url, headers={"User-Agent": "claude-pet", "Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError) as exc:
        raise UpdateError(f"could not reach GitHub: {exc}") from exc
    tag = payload.get("tag_name")
    if not tag:
        raise UpdateError("GitHub returned no release")
    return tag.lstrip("v")


def latest_sha() -> str:
    """The current head of the branch, from the GitHub API."""
    url = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "claude-pet", "Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError) as exc:
        raise UpdateError(f"could not reach GitHub: {exc}") from exc
    sha = payload.get("sha")
    if not sha:
        raise UpdateError("GitHub returned no commit for the branch")
    return sha


def _update_git(root: Path) -> tuple[str, str]:
    dirty = _git("status", "--porcelain", root=root).stdout.strip()
    if dirty:
        raise UpdateError(
            "this checkout has uncommitted changes; commit or stash them first\n"
            + "\n".join(f"  {line}" for line in dirty.splitlines()[:10])
        )

    before = _git("rev-parse", "--short", "HEAD", root=root).stdout.strip()
    fetch = _git("fetch", "--quiet", "origin", BRANCH, root=root)
    if fetch.returncode:
        raise UpdateError(f"git fetch failed: {fetch.stderr.strip()}")

    merge = _git("merge", "--ff-only", f"origin/{BRANCH}", root=root)
    if merge.returncode:
        raise UpdateError(
            f"cannot fast-forward: {merge.stderr.strip()}\n"
            "  the local branch has diverged; resolve it with git"
        )
    after = _git("rev-parse", "--short", "HEAD", root=root).stdout.strip()
    return before, after


def _update_tarball(root: Path) -> tuple[str, str]:
    before = installed_version()
    url = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
    request = urllib.request.Request(url, headers={"User-Agent": "claude-pet"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            archive = response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"download failed: {exc}") from exc

    with tempfile.TemporaryDirectory() as workspace:
        try:
            zipfile.ZipFile(io.BytesIO(archive)).extractall(workspace)
        except (zipfile.BadZipFile, OSError) as exc:
            raise UpdateError(f"the download was not a usable archive: {exc}") from exc

        extracted = next((path for path in Path(workspace).iterdir() if path.is_dir()), None)
        if extracted is None or not (extracted / "claude-pet").exists():
            raise UpdateError("the archive did not contain a claude-pet install")

        # Replace tracked content only; pets and config live outside the install.
        for item in extracted.iterdir():
            target = root / item.name
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
            shutil.move(str(item), str(target))

    (root / "claude-pet").chmod(0o755)
    after = latest_sha()[:7]
    (root / VERSION_FILE).write_text(after + "\n", encoding="utf-8")
    return before, after


def check() -> dict[str, str | bool]:
    """Installed vs latest, without touching anything.

    Raises UpdateError if GitHub cannot be reached, so callers can tell "no
    update" apart from "could not look".
    """
    current = installed_version()
    latest = latest_release() if is_system_install() else latest_sha()[:7]
    return {"current": current, "latest": latest, "available": current != latest}


def update(check_only: bool = False) -> int:
    root = install_root()
    current = installed_version()
    if is_system_install(root):
        kind = "system package"
    elif is_git_checkout(root):
        kind = "git checkout"
    else:
        kind = "tarball install"
    print(f"install : {root}  ({kind})")
    print(f"version : {current}")

    # A package-managed install belongs to the package manager. Rewriting /usr
    # behind its back would leave dpkg's idea of the files wrong.
    if is_system_install(root) and not check_only:
        try:
            latest = latest_release()
        except UpdateError as exc:
            print(f"claude-pet: {exc}")
            return 1
        if latest == current:
            print("already up to date")
            return 0
        print(f"latest  : {latest}")
        print("this is a system package; install the new .deb from:")
        print(f"  {releases_url()}")
        return 0

    if check_only:
        try:
            latest = latest_release() if is_system_install(root) else latest_sha()[:7]
        except UpdateError as exc:
            print(f"claude-pet: {exc}")
            return 1
        print(f"latest  : {latest}")
        print("up to date" if latest == current else "an update is available: claude-pet update")
        return 0

    try:
        before, after = _update_git(root) if is_git_checkout(root) else _update_tarball(root)
    except UpdateError as exc:
        print(f"claude-pet: {exc}")
        return 1

    if before == after:
        print("already up to date")
        return 0

    print(f"updated : {before} -> {after}")
    if is_git_checkout(root):
        log = _git("log", "--oneline", f"{before}..{after}", root=root).stdout.strip()
        for line in log.splitlines()[:10]:
            print(f"  {line}")

    _restart_overlay()
    return 0


def _restart_overlay() -> None:
    """Put the running pet on the new code; leave it alone if it was not up."""
    from . import launch

    pid = launch.overlay_pid()
    if pid is None:
        return
    print("restarting the pet...")
    try:
        os.kill(pid, 15)
    except OSError:
        return
    for _ in range(30):
        if launch.overlay_pid() is None:
            break
        import time

        time.sleep(0.1)
    if launch.spawn_detached(reason="update") is None:
        print("claude-pet: could not restart; run `claude-pet run --detach`")
