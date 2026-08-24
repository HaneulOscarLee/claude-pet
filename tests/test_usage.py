"""Checks for reading Claude Code's own usage figures.

None of these numbers are ours to compute -- they are the server's accounting,
carried in the JSON Claude Code hands its statusLine, and this only catches and
reads it back. So the tests pin the reading, the freshest-wins rule across two
sources, and that a broken blob never raises on the statusLine hot path.

Plain stdlib, no test runner needed:

    python3 tests/test_usage.py
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import usage  # noqa: E402

STATUSLINE_JSON = {
    "session_id": "sess-abc",
    "model": {"display_name": "Opus 4.8"},
    "cost": {"total_cost_usd": 16.24},
    "rate_limits": {
        "five_hour": {"used_percentage": 14, "resets_at": 1787218800},
        "seven_day": {"used_percentage": 9, "resets_at": 1787641200},
    },
}


class TempState:
    """Point the state dir and the OMC cache glob at throwaway directories."""

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.omc = tempfile.TemporaryDirectory()
        self.was = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.dir.name
        self.real_glob = usage._omc_cache_glob
        usage._omc_cache_glob = lambda: str(Path(self.omc.name) / "stdin.*.json")
        return self

    def __exit__(self, *_exc):
        usage._omc_cache_glob = self.real_glob
        if self.was is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.was
        self.dir.cleanup()
        self.omc.cleanup()

    def write_omc(self, name, payload, age=0.0):
        path = Path(self.omc.name) / f"stdin.{name}.json"
        path.write_text(json.dumps(payload))
        if age:
            old = time.time() - age
            os.utime(path, (old, old))
        return path


def extract_checks():
    results = []
    figures = usage.extract(STATUSLINE_JSON)
    results.append(("the five-hour percentage is read", figures["five_hour_pct"] == 14))
    results.append(("the weekly percentage is read", figures["seven_day_pct"] == 9))
    results.append(("the reset time is kept", figures["five_hour_resets_at"] == 1787218800))
    results.append(("the cost is kept", figures["cost_usd"] == 16.24))
    # A float percentage (14.000000002) is rounded to a plain integer.
    odd = {"rate_limits": {"five_hour": {"used_percentage": 14.0000002}}}
    results.append(("a float percentage rounds to an int",
                    usage.extract(odd)["five_hour_pct"] == 14))
    # No limits yet -- a fresh session before the server has reported one.
    results.append(("no limits yet is None", usage.extract({"cost": {}}) is None))
    results.append(("junk is None", usage.extract("not a dict") is None))
    return results


def capture_checks():
    results = []
    with TempState():
        figures = usage.capture(json.dumps(STATUSLINE_JSON))
        results.append(("capturing returns the figures", figures["five_hour_pct"] == 14))
        results.append(("...and writes a session file",
                        (usage.cache_dir() / "sess-abc.json").is_file()))
        # A broken blob must not raise -- the status bar is waiting on stdout.
        try:
            crash = usage.capture("{not json")
            ok = crash is None
        except Exception:  # noqa: BLE001
            ok = False
        results.append(("a broken blob is swallowed, not raised", ok))
        results.append(("empty input is None", usage.capture("") is None))
    return results


def read_checks():
    results = []
    with TempState() as env:
        results.append(("nothing written yet reads as None", usage.read() is None))

        # Only OMC's cache present: read it directly, same schema.
        env.write_omc("s1", STATUSLINE_JSON, age=100)
        got = usage.read()
        results.append(("OMC's cache is read when it is all there is",
                        got and got["five_hour_pct"] == 14))

        # Our own fresher capture wins over an older OMC file.
        fresh = dict(STATUSLINE_JSON, rate_limits={
            "five_hour": {"used_percentage": 55, "resets_at": 1787218800},
            "seven_day": {"used_percentage": 12, "resets_at": 1787641200},
        }, session_id="sess-new")
        usage.capture(json.dumps(fresh))  # written now, so newest
        got = usage.read()
        results.append(("the freshest source wins (ours, at 55%)",
                        got and got["five_hour_pct"] == 55))

        # ...and an even newer OMC file wins back.
        env.write_omc("s2", dict(STATUSLINE_JSON, rate_limits={
            "five_hour": {"used_percentage": 77, "resets_at": 1787218800}}), age=0)
        # our capture was ~now too; make OMC's strictly newer.
        newest = Path(env.omc.name) / "stdin.s2.json"
        future = time.time() + 5
        os.utime(newest, (future, future))
        got = usage.read()
        results.append(("a newer OMC file wins back (77%)",
                        got and got["five_hour_pct"] == 77))
    return results


def wrap_checks():
    """Wrapping a status line the user already has, so its figures stop vanishing.

    "Usage read from it instead" used to be said of every existing status line
    and was only ever true of oh-my-claudecode; anyone else's left `read()`
    empty for good. Now theirs is wrapped -- captured on the way past, output
    untouched -- and unwrapping puts back exactly what they had.
    """
    import json
    import tempfile
    from pathlib import Path as P

    from claude_pet import cli

    results = []
    with tempfile.TemporaryDirectory() as home:
        path = P(home) / "settings.json"

        # An empty slot: ours, plain.
        path.write_text("{}")
        results.append(("an empty slot gets our capture",
                        cli._install_statusline(path) == "installed"))
        results.append(("...and is recognised as ours afterwards",
                        cli._install_statusline(path) == "already"))
        results.append(("uninstalling an empty-slot install removes it",
                        cli._uninstall_statusline(path)
                        and "statusLine" not in json.loads(path.read_text())))

        # A third-party line, awkward quoting included: wrapped, not skipped.
        theirs = "/usr/local/bin/fancy --flag 'has spaces' \"and quotes\""
        path.write_text(json.dumps({"statusLine": {"type": "command", "command": theirs}}))
        results.append(("a third-party line is wrapped",
                        cli._install_statusline(path) == "wrapped"))
        wrapped = json.loads(path.read_text())["statusLine"]["command"]
        results.append(("...ours on the outside", "statusline --wrap" in wrapped))
        results.append(("...theirs carried intact",
                        cli._statusline_wrapped_original(wrapped) == theirs))
        results.append(("...and wrapping is idempotent",
                        cli._install_statusline(path) == "already"))
        results.append(("unwrapping puts back exactly what they had",
                        cli._uninstall_statusline(path)
                        and json.loads(path.read_text())["statusLine"]["command"] == theirs))

        # oh-my-claudecode: its cache already carries the JSON, so it is left
        # alone rather than paying a python start-up per render for nothing.
        omc = "sh ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hud/omc-hud-cache.sh"
        path.write_text(json.dumps({"statusLine": {"type": "command", "command": omc}}))
        results.append(("oh-my-claudecode is kept, not wrapped",
                        cli._install_statusline(path) == "kept"))
        results.append(("...and untouched",
                        json.loads(path.read_text())["statusLine"]["command"] == omc))

        # A statusLine with no command string is not understood: hands off.
        path.write_text(json.dumps({"statusLine": {"type": "something-else"}}))
        results.append(("an unrecognised statusLine is left alone",
                        cli._install_statusline(path) == "kept"))

    # The parser side: a plain install carries no original.
    results.append(("a plain install is not mistaken for a wrap",
                    cli._statusline_wrapped_original("x statusline") is None))
    results.append(("garbage quoting is not a wrap",
                    cli._statusline_wrapped_original("x --wrap 'unclosed") is None))
    return results


def main():
    failures = total = 0
    for label, results in (("extract", extract_checks()), ("capture", capture_checks()),
                           ("read", read_checks()), ("wrap", wrap_checks())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
