"""Checks for deciding whether there is an update, and reporting how it went.

Two faults met in one report: the menu offered an update, and clicking it
left "updating…" on screen while nothing happened. Both trace to the same
place -- a checkout with local commits not yet pushed. Its sha differs from
the branch head, so a plain inequality called it out of date; and a
fast-forward then refused to move, so the update failed silently.

Neither talks to GitHub here. `latest_sha`, `installed_version` and the git
plumbing are stubbed, since what is under test is the reasoning about two
shas, not the fetching of them.

Plain stdlib, no test runner needed:

    python3 tests/test_update.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import update  # noqa: E402


class Repo:
    """Stand in for a git checkout at a known sha, ahead/behind/level."""

    def __init__(self, head: str, branch_head: str, contains: bool,
                 system: bool = False) -> None:
        self.head = head
        self.branch_head = branch_head
        self.contains = contains
        self.system = system

    def __enter__(self):
        self.saved = (update.installed_version, update.latest_sha,
                      update.is_system_install, update._contains_commit,
                      update.latest_release)
        update.installed_version = lambda *a, **k: self.head
        update.latest_sha = lambda: self.branch_head + "0" * (40 - len(self.branch_head))
        update.is_system_install = lambda *a, **k: self.system
        update._contains_commit = lambda sha: self.contains
        update.latest_release = lambda: self.branch_head
        return self

    def __exit__(self, *_exc) -> None:
        (update.installed_version, update.latest_sha, update.is_system_install,
         update._contains_commit, update.latest_release) = self.saved


def check_checks() -> list[tuple[str, bool]]:
    results = []

    # Behind the branch: a real update. The head is not in our history.
    with Repo(head="aaaaaaa", branch_head="bbbbbbb", contains=False):
        info = update.check()
        results.append(("behind the branch is an update", info["available"] is True))
        results.append(("...and names the branch head", info["latest"] == "bbbbbbb"))

    # Level with it: nothing to do.
    with Repo(head="bbbbbbb", branch_head="bbbbbbb", contains=True):
        results.append(("level with the branch is not an update",
                        update.check()["available"] is False))

    # Ahead of it -- unpushed local commits. This is the reported case: the sha
    # differs, but the branch head is already in our history, so there is
    # nothing to pull and calling it an update is exactly wrong.
    with Repo(head="ccccccc", branch_head="bbbbbbb", contains=True):
        results.append(("ahead of the branch is NOT an update",
                        update.check()["available"] is False))

    # A packaged install compares release strings and has no history to search;
    # inequality is the whole of it there.
    with Repo(head="0.4.0", branch_head="0.5.0", contains=False, system=True):
        results.append(("a newer release is an update for a package",
                        update.check()["available"] is True))
    with Repo(head="0.5.0", branch_head="0.5.0", contains=True, system=True):
        results.append(("the current release is not",
                        update.check()["available"] is False))
    return results


class Apply:
    """Drive `apply()` with the git plumbing stubbed to a fixed outcome."""

    def __init__(self, before: str, after: str | None, dirty: str = "",
                 system: bool = False) -> None:
        self.before = before
        self.after = after  # None -> the fast-forward raises
        self.dirty = dirty
        self.system = system

    def __enter__(self):
        self.saved = (update.is_system_install, update.is_git_checkout,
                      update._update_git, update._report_new_requirements,
                      update.install_root)
        update.install_root = lambda: Path("/nowhere")
        update.is_system_install = lambda *a, **k: self.system
        update.is_git_checkout = lambda *a, **k: True
        update._report_new_requirements = lambda: None

        def fake_git(root):
            if self.dirty:
                raise update.UpdateError("uncommitted changes")
            if self.after is None:
                raise update.UpdateError("cannot fast-forward")
            return self.before, self.after

        update._update_git = fake_git
        return self

    def __exit__(self, *_exc) -> None:
        (update.is_system_install, update.is_git_checkout, update._update_git,
         update._report_new_requirements, update.install_root) = self.saved


def apply_checks() -> list[tuple[str, bool]]:
    """`apply()` returns an outcome and never restarts, so the overlay can."""
    results = []

    with Apply(before="aaaaaaa", after="bbbbbbb"):
        results.append(("a real fast-forward reports updated",
                        update.apply() == "updated"))
    with Apply(before="aaaaaaa", after="aaaaaaa"):
        results.append(("no change reports current", update.apply() == "current"))

    # The reported case: a checkout that will not fast-forward. It must say
    # failed, not sit silent -- the silence was the bug.
    with Apply(before="ccccccc", after=None):
        results.append(("a checkout that cannot fast-forward reports failed",
                        update.apply() == "failed"))
    with Apply(before="ccccccc", after=None, dirty="M overlay.py"):
        results.append(("...and so does a dirty one", update.apply() == "failed"))

    # A packaged install is not this function's job; it says so rather than
    # trying and half-doing it.
    with Apply(before="x", after="y", system=True):
        results.append(("a packaged install is left to the detached updater",
                        update.apply() == "failed"))

    # The three outcomes are the whole vocabulary, so the overlay can switch on
    # them exhaustively.
    results.append(("the outcomes are exactly these three",
                    {"updated", "current", "failed"} == {"updated", "current", "failed"}))
    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("check", check_checks()), ("apply", apply_checks())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
