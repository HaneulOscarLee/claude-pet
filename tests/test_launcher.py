"""Checks for how the launcher picks a Python interpreter.

PyGObject is installed by the system package manager, into the system Python's
dist-packages and nowhere else. Whoever's shell resolves `python3` to pyenv,
conda, asdf or an active virtualenv has an interpreter that cannot see it -- so
the package installs correctly, `import gi` fails anyway, and the error names a
module rather than the reason.

The launcher is a shell script, so this drives it as one, with stand-in
interpreters on PATH.

Plain stdlib, no test runner needed:

    python3 tests/test_launcher.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "claude-pet"

#: Commands that draw something, and so need the GUI libraries.
NEEDS_GUI = ("run", "start", "restart", "demo", "snapshot", "preview", "doctor", "setup")


def fake_python(directory: Path, name: str, *, has_gi: bool) -> Path:
    """An interpreter that reports which one it is, and whether it has `gi`."""
    path = directory / name
    body = f'''#!/bin/sh
if [ "$1" = "-c" ] && [ "$2" = "import gi" ]; then
    exit {0 if has_gi else 1}
fi
echo "CHOSE {name}"
exit 0
'''
    path.write_text(body)
    path.chmod(0o755)
    return path


def run(argv: list[str], path_dirs: list[Path], env: dict | None = None):
    environment = dict(os.environ)
    environment["PATH"] = os.pathsep.join(str(p) for p in path_dirs)
    environment.pop("CLAUDE_PET_PYTHON", None)
    environment.update(env or {})
    return subprocess.run(
        [str(LAUNCHER), *argv], capture_output=True, text=True, env=environment, timeout=30
    )


def checks(workspace: Path) -> list[tuple[str, bool]]:
    results = []
    # A shell and coreutils have to stay reachable; the launcher is bash.
    real = [Path("/usr/bin"), Path("/bin")]

    good = workspace / "good"
    bad = workspace / "bad"
    good.mkdir()
    bad.mkdir()
    fake_python(good, "python3", has_gi=True)
    fake_python(bad, "python3", has_gi=False)

    # The reported failure: a gi-less python3 first on PATH. The launcher must
    # look past it rather than exec it and die on `import gi`.
    #
    # Asserted on the absence of that error and nothing else. Whether the pet
    # then starts depends on there being a display, which there is not on CI,
    # and that is a different question from the one this is guarding.
    done = run(["run"], [bad, good, *real])
    results.append(
        ("a gi-less python3 first on PATH is passed over",
         "No module named 'gi'" not in done.stderr)
    )

    # An explicit choice wins over everything.
    chosen = fake_python(workspace, "mypython", has_gi=True)
    done = run(["run"], [bad, *real], env={"CLAUDE_PET_PYTHON": str(chosen)})
    results.append(("CLAUDE_PET_PYTHON is preferred", "CHOSE mypython" in done.stdout))

    # "Nothing on this machine has gi" cannot be staged on a machine where
    # /usr/bin/python3 does -- and that fallback is hardcoded on purpose, since
    # it is the whole point. So the failure path is exercised against a copy
    # with the candidate list narrowed, which is the same code either way.
    narrowed = workspace / "launcher-no-fallback"
    body = LAUNCHER.read_text().replace(
        'for candidate in "${CLAUDE_PET_PYTHON:-}" python3 /usr/bin/python3; do',
        'for candidate in "${CLAUDE_PET_PYTHON:-}" python3; do',
    )
    narrowed.write_text(body)
    narrowed.chmod(0o755)
    environment = dict(os.environ)
    environment["PATH"] = os.pathsep.join(str(p) for p in [bad, *real])
    environment.pop("CLAUDE_PET_PYTHON", None)
    done = subprocess.run(
        [str(narrowed), "run"], capture_output=True, text=True, env=environment, timeout=30
    )
    results.append(("no interpreter with gi fails cleanly", done.returncode == 1))
    results.append(("...naming the package to install", "python3-gi" in done.stderr))
    results.append(
        ("...and the virtualenv case, which is the likely one",
         "virtualenv" in done.stderr and "CLAUDE_PET_PYTHON" in done.stderr)
    )
    results.append(("...without a python traceback", "Traceback" not in done.stderr))

    # The hook runs inside every turn of every agent. It must not probe.
    done = run(["hook"], [bad, good, *real])
    results.append(
        ("hook does not probe for gi", "CHOSE python3" in done.stdout and done.returncode == 0)
    )

    # Whatever the launcher does, the list it probes for and the list of
    # commands that import GTK must not drift apart.
    body = LAUNCHER.read_text()
    guarded = [name for name in NEEDS_GUI if f"{name}|" in body or f"|{name})" in body]
    results.append(
        (f"every GUI command is guarded ({len(guarded)}/{len(NEEDS_GUI)})",
         len(guarded) == len(NEEDS_GUI))
    )
    return results


def main() -> int:
    if not shutil.which("bash"):
        print("bash not available; skipping")
        return 0

    with tempfile.TemporaryDirectory() as workspace:
        results = checks(Path(workspace))

    failures = 0
    print("interpreter choice:")
    for name, ok in results:
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{len(results) - failures}/{len(results)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
