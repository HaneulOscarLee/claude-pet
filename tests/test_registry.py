"""Checks for installing a pack from a local .codex-pet.zip.

The gallery installer trusts the id it asked for and matches the download
against it. A local file has no such id to check, so the id is read from the
archive's own pet.json -- and the file name is not it: the pack the feature was
built for, shoga-strings.codex-pet.zip, carried an id of neon-gif-cat, and an
installer keyed on the file name would have written it to the wrong place.

No network here. Everything is a zip built in a temp directory.

Plain stdlib, no test runner needed:

    python3 tests/test_registry.py
"""

import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import registry  # noqa: E402


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


def _manifest(pet_id: str = "neon-gif-cat", display: str = "Shoga Strings") -> bytes:
    return json.dumps(
        {
            "id": pet_id,
            "displayName": display,
            "spritesheetPath": "spritesheet.webp",
            "spriteVersionNumber": 2,
        }
    ).encode("utf-8")


def checks() -> list[tuple[str, bool]]:
    results = []

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        # A well-formed pack, named nothing like its id.
        good = root / "shoga-strings.codex-pet.zip"
        good.write_bytes(_zip({"pet.json": _manifest(), "spritesheet.webp": b"webpdata"}))
        info = registry.install_local(good, root / "pets")
        results.append(("the id comes from pet.json, not the file name",
                        info["id"] == "neon-gif-cat"))
        results.append(("the display name is carried through",
                        info["display_name"] == "Shoga Strings"))
        results.append(("it lands under the id it declared",
                        info["directory"] == root / "pets" / "neon-gif-cat"))
        results.append(("both files are written out",
                        (info["directory"] / "pet.json").is_file()
                        and (info["directory"] / "spritesheet.webp").read_bytes() == b"webpdata"))

        # A missing file is a clear error, not a traceback.
        missing = root / "missing.zip"
        try:
            registry.install_local(missing, root / "pets")
            results.append(("a missing file is refused", False))
        except registry.RegistryError as exc:
            results.append(("a missing file is refused", "no such file" in str(exc)))

        # Something that is not a zip at all.
        junk = root / "notazip.zip"
        junk.write_bytes(b"not a zip")
        try:
            registry.install_local(junk, root / "pets")
            results.append(("a non-zip is refused", False))
        except registry.RegistryError as exc:
            results.append(("a non-zip is refused", "not a valid zip" in str(exc)))

        # A zip missing the spritesheet.
        half = root / "half.zip"
        half.write_bytes(_zip({"pet.json": _manifest()}))
        try:
            registry.install_local(half, root / "pets")
            results.append(("an incomplete pack is refused", False))
        except registry.RegistryError as exc:
            results.append(("an incomplete pack is refused", "spritesheet.webp" in str(exc)))

        # A manifest without a usable id.
        no_id = root / "noid.zip"
        no_id.write_bytes(_zip({"pet.json": b'{"displayName": "x"}',
                                "spritesheet.webp": b"webpdata"}))
        try:
            registry.install_local(no_id, root / "pets")
            results.append(("a pack with no id is refused", False))
        except registry.RegistryError as exc:
            results.append(("a pack with no id is refused", "usable id" in str(exc)))

        # An id that is not a slug is rejected before anything is written.
        bad_id = root / "badid.zip"
        bad_id.write_bytes(_zip({"pet.json": _manifest("Not A Slug!"),
                                 "spritesheet.webp": b"webpdata"}))
        try:
            registry.install_local(bad_id, root / "pets")
            results.append(("a non-slug id is refused", False))
        except registry.RegistryError:
            results.append(("a non-slug id is refused",
                            not (root / "pets" / "Not A Slug!").exists()))

    return results


def main() -> int:
    results = checks()
    failures = sum(not ok for _name, ok in results)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{len(results) - failures}/{len(results)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
