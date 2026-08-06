"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from . import config, state
from .errors import PetError

# `sprites` pulls in Pillow and `registry` opens sockets, so both are imported
# inside the commands that need them: the `hook` subcommand runs on every tool
# call and must not pay for either.

HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "Stop",
    "SubagentStop",
    "SessionEnd",
)
#: Substring that identifies a hook entry as ours. Must match what
#: `install-hooks` writes, which is the launcher path ending in `claude-pet`.
HOOK_MARKER = "claude-pet"


def launcher_path() -> Path:
    return Path(__file__).resolve().parent.parent / "claude-pet"


# --------------------------------------------------------------------- pets


def cmd_list(_args: argparse.Namespace) -> int:
    from . import sprites

    available = config.discover()
    if not available:
        print("설치된 펫이 없습니다. `claude-pet search` 로 찾고 `claude-pet add <id>` 로 받으세요.")
        return 0
    active = config.active_pet_dir()
    for pet_id, directory in available.items():
        marker = "*" if active and directory == active else " "
        try:
            pet = sprites.load_pet(directory)
            counts = pet.frame_counts
            summary = (
                f"v{pet.version} · {pet.cell[0]}x{pet.cell[1]} · "
                f"{sum(counts.values())} frames · {len(pet.looks)} looks"
            )
        except sprites.SpriteError as exc:
            summary = f"불량: {exc}"
        print(f"{marker} {pet_id:<24} {summary}")
        print(f"    {directory}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from . import registry

    try:
        result = registry.search(
            args.query or "", page_size=args.limit, sort=args.sort, version=args.version or ""
        )
    except registry.RegistryError as exc:
        print(f"claude-pet: {exc}", file=sys.stderr)
        return 1
    pets = result["pets"]
    if not pets:
        print("결과 없음")
        return 0
    print(f"{result['total']}개 중 {len(pets)}개 표시\n")
    for pet in pets:
        version = pet.get("spriteVersionNumber") or 1
        likes = pet.get("likeCount") or 0
        print(f"  {pet.get('id'):<26} v{version}  ♥{likes:<5} {pet.get('displayName')}")
        description = (pet.get("description") or "").strip()
        if description:
            print(f"    {description[:96]}")
    print("\n설치: claude-pet add <id>")
    return 0


def _install_root(args: argparse.Namespace) -> Path:
    if getattr(args, "codex_home", False):
        return config.codex_home() / "pets"
    return config.claude_home() / "pets"


def cmd_add(args: argparse.Namespace) -> int:
    from . import registry, sprites

    root = _install_root(args)
    failures = 0
    for pet_id in args.pet_ids:
        try:
            installed = registry.install(pet_id, root)
        except registry.RegistryError as exc:
            print(f"claude-pet: {exc}", file=sys.stderr)
            failures += 1
            continue
        try:
            pet = sprites.load_pet(installed["directory"])
        except sprites.SpriteError as exc:
            print(f"claude-pet: {pet_id} 설치했지만 스프라이트 검증 실패: {exc}", file=sys.stderr)
            failures += 1
            continue
        print(
            f"설치 완료  {pet.id}  ({pet.display_name}, v{pet.version}, "
            f"{sum(pet.frame_counts.values())} frames) -> {installed['directory']}"
        )
    if not failures and args.pet_ids:
        settings = config.load()
        if not settings.get("pet"):
            settings["pet"] = args.pet_ids[0]
            config.save(settings)
            print(f"활성 펫으로 지정: {args.pet_ids[0]}")
    return 1 if failures else 0


def cmd_add_collection(args: argparse.Namespace) -> int:
    from . import registry

    root = _install_root(args)
    try:
        installed = registry.install_collection(args.slug, root)
    except registry.RegistryError as exc:
        print(f"claude-pet: {exc}", file=sys.stderr)
        return 1
    for entry in installed:
        print(f"설치 완료  {entry['id']} -> {entry['directory']}")
    print(f"{len(installed)}개 설치")
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    available = config.discover()
    if args.pet_id not in available:
        print(f"claude-pet: {args.pet_id} 가 설치되어 있지 않습니다", file=sys.stderr)
        return 1
    settings = config.load()
    settings["pet"] = args.pet_id
    config.save(settings)
    print(f"활성 펫: {args.pet_id}")
    if _overlay_pid():
        print("오버레이 재시작이 필요합니다: claude-pet restart")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    from . import sprites

    available = config.discover()
    directory = available.get(args.pet_id) if args.pet_id else config.active_pet_dir()
    if directory is None:
        print("claude-pet: 펫을 찾을 수 없습니다", file=sys.stderr)
        return 1
    pet = sprites.load_pet(directory)
    output = Path(args.output or f"{pet.id}-preview.png").expanduser()
    sprites.contact_sheet(pet).convert("RGB").save(output)
    print(f"{pet.id} v{pet.version}  cells {pet.cell[0]}x{pet.cell[1]}")
    for name, count in pet.frame_counts.items():
        print(f"  {name:<16} {count} frames")
    print(f"  look-directions  {len(pet.looks)} poses")
    print(f"\n저장: {output}")
    return 0


# ------------------------------------------------------------------ overlay


def _overlay_pid() -> int | None:
    try:
        pid = int(state.pid_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if Path(f"/proc/{pid}").exists() else None


def cmd_run(args: argparse.Namespace) -> int:
    from . import overlay

    return overlay.run(args.pet)


def cmd_snapshot(args: argparse.Namespace) -> int:
    from . import overlay

    return overlay.snapshot(
        args.output, pet_id=args.pet, state_name=args.state, detail=args.detail or ""
    )


def cmd_stop(_args: argparse.Namespace) -> int:
    pid = _overlay_pid()
    if pid is None:
        print("오버레이가 실행 중이 아닙니다")
        return 0
    os.kill(pid, signal.SIGTERM)
    print(f"종료 신호 전송 (pid {pid})")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    cmd_stop(args)
    import time

    for _ in range(20):
        if _overlay_pid() is None:
            break
        time.sleep(0.1)
    return cmd_run(args)


def cmd_status(_args: argparse.Namespace) -> int:
    snapshot = state.aggregate()
    pid = _overlay_pid()
    print(f"오버레이     : {'실행 중 (pid %d)' % pid if pid else '정지'}")
    print(f"집계 상태    : {snapshot['state']}  ({snapshot['sessions']} sessions)")
    if snapshot.get("detail"):
        print(f"상세         : {snapshot['detail']}")
    settings = config.load()
    print(f"활성 펫      : {settings.get('pet') or '(자동 선택)'}")
    print(f"상태 파일    : {state.state_path()}")

    data = state.read()
    for session_id, session in data.get("sessions", {}).items():
        print(f"  {session_id[:8]}  {session.get('state'):<8} {session.get('detail') or ''}")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    if args.key not in config.DEFAULTS:
        keys = ", ".join(sorted(config.DEFAULTS))
        print(f"claude-pet: 알 수 없는 키 {args.key!r}. 사용 가능: {keys}", file=sys.stderr)
        return 1
    settings = config.load()
    raw = args.value
    if raw.lower() in {"true", "false"}:
        value: Any = raw.lower() == "true"
    elif raw.lower() in {"none", "null"}:
        value = None
    else:
        try:
            value = int(raw)
        except ValueError:
            value = raw
    settings[args.key] = value
    if args.key == "anchor":
        # A stored drag position would otherwise override the new anchor.
        settings["position"] = None
    config.save(settings)
    print(f"{args.key} = {value!r}")
    if _overlay_pid():
        print("적용: claude-pet restart")
    return 0


# -------------------------------------------------------------------- hooks


def _settings_file(project: bool) -> Path:
    if project:
        return Path.cwd() / ".claude" / "settings.json"
    return config.claude_home() / "settings.json"


def _read_settings(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _entry_is_ours(entry: Any) -> bool:
    """True when a hooks[] entry was written by `install-hooks`."""
    if not isinstance(entry, dict):
        return False
    return any(
        HOOK_MARKER in str(hook.get("command", ""))
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    )


def cmd_install_hooks(args: argparse.Namespace) -> int:
    path = _settings_file(args.project)
    settings = _read_settings(path)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print(f"claude-pet: {path} 의 hooks 가 객체가 아닙니다", file=sys.stderr)
        return 1

    command = f"{launcher_path()} hook"
    added = 0
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            print(f"claude-pet: hooks.{event} 가 배열이 아닙니다 — 건너뜀", file=sys.stderr)
            continue
        if any(_entry_is_ours(entry) for entry in entries):
            continue
        entries.append({"hooks": [{"type": "command", "command": command, "timeout": 5}]})
        added += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{path}: {added}개 이벤트에 hook 추가 (기존 hook은 보존)")
    if added:
        print("새 Claude Code 세션을 시작하면 펫이 상태를 따라갑니다.")
    return 0


def cmd_uninstall_hooks(args: argparse.Namespace) -> int:
    path = _settings_file(args.project)
    settings = _read_settings(path)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        print(f"{path}: 제거할 hook 없음")
        return 0

    removed = 0
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            if _entry_is_ours(entry):
                removed += 1
                continue
            kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event)

    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{path}: {removed}개 hook 제거")
    return 0


# ------------------------------------------------------------------- doctor


def cmd_doctor(_args: argparse.Namespace) -> int:
    from . import sprites

    problems = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal problems
        print(f"  {'OK  ' if ok else 'FAIL'}  {label}{'  — ' + detail if detail else ''}")
        if not ok:
            problems += 1

    print("환경")
    session = os.environ.get("XDG_SESSION_TYPE", "?")
    display = os.environ.get("DISPLAY", "")
    check("DISPLAY (X11/XWayland)", bool(display), display or "미설정 — 오버레이가 뜨지 않습니다")
    print(f"  INFO  세션 타입: {session}" + (" (XWayland 경유)" if session == "wayland" else ""))

    try:
        from PIL import features

        check("Pillow WebP 디코딩", bool(features.check("webp")))
    except ImportError:
        check("Pillow", False, "pip install Pillow")

    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401

        check("PyGObject / GTK3", True)
    except (ImportError, ValueError) as exc:
        check("PyGObject / GTK3", False, str(exc))

    from shutil import which

    check("notify-send", which("notify-send") is not None, "libnotify-bin 없으면 알림 생략")

    print("\n펫")
    available = config.discover()
    check("설치된 팩", bool(available), f"{len(available)}개" if available else "claude-pet add <id>")
    for pet_id, directory in available.items():
        try:
            pet = sprites.load_pet(directory)
            print(f"  OK    {pet_id} v{pet.version}")
        except sprites.SpriteError as exc:
            print(f"  FAIL  {pet_id} — {exc}")
            problems += 1

    print("\n연동")
    settings_path = config.claude_home() / "settings.json"
    settings = _read_settings(settings_path)
    installed_events = [
        event
        for event, entries in (settings.get("hooks") or {}).items()
        if isinstance(entries, list) and any(_entry_is_ours(entry) for entry in entries)
    ]
    check(
        "hook 설치",
        len(installed_events) >= len(HOOK_EVENTS),
        f"{len(installed_events)}/{len(HOOK_EVENTS)} — claude-pet install-hooks",
    )
    pid = _overlay_pid()
    print(f"  INFO  오버레이: {'pid %d' % pid if pid else '정지'}")
    print(f"\n{'문제 없음' if not problems else f'{problems}건 확인 필요'}")
    return 1 if problems else 0


# ---------------------------------------------------------------- entrypoint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-pet",
        description="Codex 펫 스프라이트로 동작하는 Claude Code 데스크톱 펫",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="설치된 펫 나열").set_defaults(func=cmd_list)

    search = subparsers.add_parser("search", help="codex-pets.net 갤러리 검색")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--sort", default="popular", choices=["new", "popular", "likes", "random"])
    search.add_argument("--version", choices=["1", "2"])
    search.set_defaults(func=cmd_search)

    add = subparsers.add_parser("add", help="codex-pets.net 에서 펫 설치")
    add.add_argument("pet_ids", nargs="+", metavar="PET_ID")
    add.add_argument("--codex-home", action="store_true", help="~/.codex/pets 에 설치")
    add.set_defaults(func=cmd_add)

    collection = subparsers.add_parser("add-collection", help="컬렉션 전체 설치")
    collection.add_argument("slug")
    collection.add_argument("--codex-home", action="store_true")
    collection.set_defaults(func=cmd_add_collection)

    use = subparsers.add_parser("use", help="활성 펫 지정")
    use.add_argument("pet_id")
    use.set_defaults(func=cmd_use)

    preview = subparsers.add_parser("preview", help="스프라이트 시트를 PNG로 덤프")
    preview.add_argument("pet_id", nargs="?")
    preview.add_argument("-o", "--output")
    preview.set_defaults(func=cmd_preview)

    run = subparsers.add_parser("run", help="오버레이 실행")
    run.add_argument("--pet", help="이번 실행에만 사용할 펫 id")
    run.set_defaults(func=cmd_run)

    restart = subparsers.add_parser("restart", help="오버레이 재시작")
    restart.add_argument("--pet")
    restart.set_defaults(func=cmd_restart)

    snapshot = subparsers.add_parser("snapshot", help="오버레이 창을 PNG로 캡처 (디버그)")
    snapshot.add_argument("output")
    snapshot.add_argument("--pet")
    snapshot.add_argument("--state", choices=list(state.PRIORITY))
    snapshot.add_argument("--detail", default="")
    snapshot.set_defaults(func=cmd_snapshot)

    subparsers.add_parser("stop", help="오버레이 종료").set_defaults(func=cmd_stop)
    subparsers.add_parser("status", help="현재 상태 표시").set_defaults(func=cmd_status)
    subparsers.add_parser("doctor", help="환경 점검").set_defaults(func=cmd_doctor)

    setter = subparsers.add_parser("set", help="설정 변경")
    setter.add_argument("key")
    setter.add_argument("value")
    setter.set_defaults(func=cmd_set)

    install = subparsers.add_parser("install-hooks", help="Claude Code settings.json 에 hook 추가")
    install.add_argument("--project", action="store_true", help="전역 대신 ./.claude/settings.json")
    install.set_defaults(func=cmd_install_hooks)

    uninstall = subparsers.add_parser("uninstall-hooks", help="hook 제거")
    uninstall.add_argument("--project", action="store_true")
    uninstall.set_defaults(func=cmd_uninstall_hooks)

    hook = subparsers.add_parser("hook", help="(내부) hook 이벤트 처리")
    hook.add_argument("event", nargs="?")
    hook.set_defaults(func=cmd_hook)

    return parser


def cmd_hook(args: argparse.Namespace) -> int:
    from . import hook

    return hook.main([args.event] if args.event else [])


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PetError as exc:
        print(f"claude-pet: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
