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

        # ensure(): idempotent lay-down used by setup and update.
        import os as _os
        was = _os.environ.get("XDG_CURRENT_DESKTOP"), _os.environ.get("XDG_SESSION_TYPE")
        _os.environ["XDG_CURRENT_DESKTOP"] = "ubuntu:GNOME"
        _os.environ["XDG_SESSION_TYPE"] = "wayland"
        try:
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
    for label, results in (("shipped", shipped_checks()), ("install", install_checks()),
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
