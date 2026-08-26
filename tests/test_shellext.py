"""Checks for installing the shell extension that answers where the pointer is.

An extension runs inside the compositor's own process, so the two things that
must not go wrong are putting it somewhere the shell will never look, and
failing to take it away again when asked. Both are arithmetic on paths and a
settings list, and both are checked here against a temporary home rather than
the real one.

Plain stdlib, no test runner needed:

    python3 tests/test_shellext.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import shellext  # noqa: E402


class FakeSettings:
    """Stands in for gsettings, which a test must not write to for real."""

    def __init__(self, names: list[str]) -> None:
        self.names = list(names)

    def __enter__(self):
        self.real_get = shellext._enabled_list
        self.real_set = shellext._set_enabled
        shellext._enabled_list = lambda: list(self.names)

        def write(names: list[str]) -> bool:
            self.names = list(names)
            return True

        shellext._set_enabled = write
        return self

    def __exit__(self, *_exc) -> None:
        shellext._enabled_list = self.real_get
        shellext._set_enabled = self.real_set


class TempHome:
    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.was = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = self.dir.name
        return self

    def __exit__(self, *_exc) -> None:
        if self.was is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self.was
        self.dir.cleanup()


def variant_checks() -> list[tuple[str, bool]]:
    """Both formats ship, and the right one is picked for the running shell.

    GNOME 45 moved extensions to ES modules. A 45+ extension does not load on
    GNOME 42 (Ubuntu 22.04) and the shell says nothing about why, so the bridge
    looked installed and was simply dead -- the pointer stayed unreadable over
    a browser exactly as if it had never been installed.
    """
    results = []
    root = Path(__file__).resolve().parent.parent
    modern = root / "assets" / "gnome-extension" / shellext.UUID
    legacy = root / "assets" / "gnome-extension-legacy" / shellext.UUID
    results.append(("the modern (ESM) extension ships", (modern / "extension.js").is_file()))
    results.append(("the legacy (pre-45) one ships too", (legacy / "extension.js").is_file()))
    if not (modern / "metadata.json").is_file() or not (legacy / "metadata.json").is_file():
        return results

    modern_meta = json.loads((modern / "metadata.json").read_text())
    legacy_meta = json.loads((legacy / "metadata.json").read_text())
    results.append(("the legacy one declares GNOME 42",
                    "42" in legacy_meta["shell-version"]))
    results.append(("...and the modern one does not",
                    "42" not in modern_meta["shell-version"]))
    results.append(("they share the uuid, so only one is ever installed",
                    legacy_meta["uuid"] == modern_meta["uuid"] == shellext.UUID))

    legacy_code = (legacy / "extension.js").read_text()
    modern_code = (modern / "extension.js").read_text()
    # The formats are mutually exclusive, and mixing them is the failure.
    results.append(("the legacy one uses the old imports form",
                    "imports.gi" in legacy_code and "import " not in legacy_code))
    results.append(("...and exports init()", "function init()" in legacy_code))
    results.append(("the modern one is an ES module",
                    "export default class" in modern_code))
    results.append(("both answer with the compositor's pointer",
                    "global.get_pointer()" in legacy_code
                    and "global.get_pointer()" in modern_code))
    results.append(("both can raise a window for the compositor",
                    "RaiseWindowForPids" in legacy_code
                    and "RaiseWindowForPids" in modern_code))
    results.append(("...using activate, which a client cannot do to another app",
                    ".activate(" in legacy_code and ".activate(" in modern_code))

    # Version steering, with the shell's answer stubbed both ways.
    real = shellext.shell_version
    try:
        shellext.shell_version = lambda: 42
        results.append(("on GNOME 42 the legacy copy is chosen",
                        shellext.source_path() == legacy))
        shellext.shell_version = lambda: 46
        results.append(("on GNOME 46 the modern copy is chosen",
                        shellext.source_path() == modern))
        shellext.shell_version = lambda: 44
        results.append(("on GNOME 44 (still pre-ESM) the legacy copy is chosen",
                        shellext.source_path() == legacy))
        shellext.shell_version = lambda: None
        results.append(("with no version to go on it still finds one",
                        shellext.source_path() is not None))
    finally:
        shellext.shell_version = real
    return results


def shipped_checks() -> list[tuple[str, bool]]:
    """The copy in the repo has to be something the shell would actually load."""
    results = []
    source = shellext.source_path()
    results.append(("the extension ships with claude-pet", source is not None))
    if source is None:
        return results

    meta = json.loads((source / "metadata.json").read_text())
    # The shell matches the directory name against the uuid and refuses a
    # mismatch, which is silent -- it simply never appears.
    results.append(("its uuid matches its directory", meta["uuid"] == source.name))
    results.append(("...and the uuid the code looks for", meta["uuid"] == shellext.UUID))
    results.append(("it declares the GNOME versions it runs on",
                    "46" in meta["shell-version"]))

    code = (source / "extension.js").read_text()
    # GNOME 45 onwards loads extensions as ES modules; the old
    # `imports.misc.extensionUtils` shape fails to load with nothing on screen
    # to say why.
    results.append(("it is an ES module, as GNOME 45+ requires",
                    "export default class" in code and "imports." not in code))
    results.append(("it exports the method the pet calls",
                    "GetPointer" in code and shellext.UUID in meta["uuid"]))
    results.append(("it asks the compositor for the pointer",
                    "global.get_pointer()" in code))
    # It has one job. Anything watching input would be a different proposition
    # entirely, and worth noticing in review if it ever appeared.
    results.append(("it registers no listeners", "connect(" not in code))
    return results


def install_checks() -> list[tuple[str, bool]]:
    results = []
    with TempHome() as home, FakeSettings(["ding@rastersoft.com"]) as settings:
        results.append(("nothing is installed to start with", not shellext.installed()))

        results.append(("installing works", shellext.install()))
        results.append(("...into the directory the shell reads",
                        shellext.install_path().parent == Path(home.dir.name)
                        / "gnome-shell" / "extensions"))
        results.append(("...with the metadata beside it", shellext.installed()))
        results.append(("...and switched on", shellext.UUID in settings.names))
        results.append(("...without disturbing the others",
                        "ding@rastersoft.com" in settings.names))

        # Installing twice is what an update does, and must not end up with
        # the uuid listed twice -- the shell would enable it once and the
        # list would grow every release.
        shellext.install()
        results.append(("installing again does not list it twice",
                        settings.names.count(shellext.UUID) == 1))

        results.append(("removing works", shellext.uninstall()))
        results.append(("...taking the files", not shellext.installed()))
        results.append(("...and the setting", shellext.UUID not in settings.names))
        results.append(("...leaving the others alone",
                        "ding@rastersoft.com" in settings.names))
        results.append(("removing again is not an error", not shellext.uninstall()))

        # A copy in the wrong format for this shell must be replaced, not
        # reported as "already" -- that is the state an older install left on
        # Ubuntu 22.04: present, and inert.
        import os as _os2
        was2 = _os2.environ.get("XDG_CURRENT_DESKTOP"), _os2.environ.get("XDG_SESSION_TYPE")
        real_ver = shellext.shell_version
        _os2.environ["XDG_CURRENT_DESKTOP"] = "ubuntu:GNOME"
        _os2.environ["XDG_SESSION_TYPE"] = "wayland"
        try:
            shellext.shell_version = lambda: 46
            shellext.install()                      # lays down the ESM copy
            results.append(("a matching format reads as matching",
                            shellext.installed_matches_shell()))
            results.append(("...so ensure leaves it alone", shellext.ensure() == "already"))

            shellext.shell_version = lambda: 42     # same files, older shell
            results.append(("the same copy on GNOME 42 reads as mismatched",
                            not shellext.installed_matches_shell()))
            results.append(("...and ensure replaces it", shellext.ensure() == "installed"))
            code = (shellext.install_path() / "extension.js").read_text()
            results.append(("...with the legacy format", "function init()" in code))
            results.append(("...which then reads as matching",
                            shellext.installed_matches_shell()))
        finally:
            shellext.shell_version = real_ver
            for k, v in zip(("XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE"), was2):
                if v is None:
                    _os2.environ.pop(k, None)
                else:
                    _os2.environ[k] = v

        # ensure(): idempotent lay-down used by setup and update.
        #
        # Starts from nothing on purpose. The block above leaves a copy behind,
        # and "installs when missing" then depended on whether this machine's
        # shell version happened to disagree with it -- which passed locally
        # (GNOME 46 vs a legacy copy: replaced) and failed on CI, where there
        # is no gnome-shell to ask and a copy is left alone.
        shellext.uninstall()
        import os as _os
        was = _os.environ.get("XDG_CURRENT_DESKTOP"), _os.environ.get("XDG_SESSION_TYPE")
        _os.environ["XDG_CURRENT_DESKTOP"] = "ubuntu:GNOME"
        _os.environ["XDG_SESSION_TYPE"] = "wayland"
        try:
            results.append(("nothing is installed going in", not shellext.installed()))
            results.append(("ensure installs when missing", shellext.ensure() == "installed"))
            results.append(("...and is idempotent the second time",
                            shellext.ensure() == "already"))
            _os.environ["XDG_SESSION_TYPE"] = "x11"
            results.append(("ensure is a no-op off Wayland",
                            shellext.ensure() == "unsupported"))
        finally:
            for k, v in zip(("XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE"), was):
                if v is None:
                    _os.environ.pop(k, None)
                else:
                    _os.environ[k] = v
    return results


def content_checks() -> list[tuple[str, bool]]:
    """A release that changes the extension must actually replace the old copy.

    `ensure()` reported "already" on any present copy of the right format, so a
    new method added to the extension never reached an existing install --
    their updater ran before the new code and the pet's startup only re-copied
    if the format differed. Now the content is compared too.
    """
    results = []
    with TempHome(), FakeSettings([]):
        import os as _os
        was = _os.environ.get("XDG_CURRENT_DESKTOP"), _os.environ.get("XDG_SESSION_TYPE")
        real_ver = shellext.shell_version
        _os.environ["XDG_CURRENT_DESKTOP"] = "ubuntu:GNOME"
        _os.environ["XDG_SESSION_TYPE"] = "wayland"
        try:
            shellext.shell_version = lambda: 46
            shellext.ensure()
            results.append(("a fresh copy matches the shipped source",
                            shellext.installed_matches_shell()))
            # Tamper with the installed copy: it must now read as not matching,
            # and ensure() must put the shipped one back.
            (shellext.install_path() / "extension.js").write_text("// stale copy")
            results.append(("an out-of-date copy is detected",
                            not shellext.installed_matches_shell()))
            results.append(("...and ensure replaces it", shellext.ensure() == "installed"))
            results.append(("...restoring the shipped code",
                            shellext.installed_matches_shell()))
        finally:
            shellext.shell_version = real_ver
            for k, v in zip(("XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE"), was):
                if v is None: _os.environ.pop(k, None)
                else: _os.environ[k] = v
    return results


def where_checks() -> list[tuple[str, bool]]:
    """It is only worth installing on GNOME, on Wayland."""
    results = []

    def supported(desktop: str, session: str) -> bool:
        was = os.environ.get("XDG_CURRENT_DESKTOP"), os.environ.get("XDG_SESSION_TYPE")
        os.environ["XDG_CURRENT_DESKTOP"] = desktop
        os.environ["XDG_SESSION_TYPE"] = session
        try:
            return shellext.supported_here()
        finally:
            for key, value in zip(("XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE"), was):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    results.append(("GNOME on Wayland is where it helps", supported("ubuntu:GNOME", "wayland")))
    results.append(("GNOME on X11 does not need it", not supported("GNOME", "x11")))
    results.append(("KDE on Wayland cannot use it", not supported("KDE", "wayland")))
    results.append(("an unknown desktop is left alone", not supported("", "wayland")))
    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("variants", variant_checks()),
                            ("shipped", shipped_checks()), ("install", install_checks()),
                            ("content", content_checks()),
                            ("where", where_checks())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
