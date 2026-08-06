# claude-pet

A floating desktop pet for Claude Code, driven by Claude's live session state
and rendered from **codex-pets.net sprite packs** — the same packs the Codex
desktop app uses.

Codex ships pets for its own app on macOS and Windows only. This is the same
idea for Claude Code on Linux: an always-on-top sprite that reacts to whether
Claude is working, blocked on you, done, or failed, so you can tell without
looking at the terminal.

```
  ┌──────────────────────────────┐
  │ 입력 대기 · Bash 실행 권한... │   <- speech bubble, colour-coded by state
  └──────────────────────────────┘
              (\_/)                  <- your sprite pack, animated
```

## Requirements

- Linux with X11 or a Wayland session that has XWayland (GNOME is fine)
- Python 3.10+, `python3-gi` (PyGObject/GTK3), `python3-pil` with WebP support

Run `./claude-pet doctor` to check all of it at once.

Wayland note: the overlay deliberately runs through XWayland. `_NET_WM_STATE_ABOVE`
is the only always-on-top mechanism mutter honours for a normal client, so the
launcher exports `GDK_BACKEND=x11`.

## Quick start

```bash
./claude-pet search                 # browse the codex-pets.net gallery
./claude-pet add clawd              # install a pack
./claude-pet install-hooks          # wire it into ~/.claude/settings.json
./claude-pet run                    # start the overlay (hooks can autostart it)
```

Start a new Claude Code session and the pet follows along.

## Sprite compatibility

Any pack from [codex-pets.net](https://codex-pets.net/) works, both atlas
versions, and packs already installed with `npx codex-pets add` are picked up
from `~/.codex/pets/` without being copied.

| | v1 | v2 |
|---|---|---|
| atlas | 1536×1872 | 1536×2288 |
| grid | 8 cols × 9 rows | 8 cols × 11 rows |
| cell | 192×208 | 192×208 |
| `pet.json` | no version field | `"spriteVersionNumber": 2` |

Animation rows, in order: `idle`, `running-right`, `running-left`, `waving`,
`jumping`, `failed`, `waiting`, `running`, `review`. v2 adds rows 9–10, which
hold 16 look-direction poses — used to make the pet face your mouse while idle.

Frame counts per row are measured from the alpha channel rather than assumed,
because real packs sometimes draw an extra frame past the documented count.

Search order for packs: `~/.claude/pets/`, then `~/.codex/pets/`
(`$CLAUDE_CONFIG_DIR` / `$CODEX_HOME` respected).

## State mapping

| Claude Code hook | Pet state | Bubble |
|---|---|---|
| `SessionStart` | `waving` | 세션 시작 |
| `UserPromptSubmit` | `running` | 작업 중 |
| `PreToolUse` / `PostToolUse` | `running` | 작업 중 · *tool name* |
| `PostToolUse` with an error | `failed` | 실패 |
| `Notification` | `waiting` | 입력 대기 · *Claude's message* |
| `Stop` | `review` | 응답 완료 |
| `SubagentStop` | `running` | 서브에이전트 완료 |
| `SessionEnd` | — | session forgotten |

Multiple sessions collapse to the most urgent state, in this order:
`waiting` → `failed` → `review` → `running` → `waving` → `idle`. So a pet
showing 입력 대기 means *some* session wants you, and the bubble names it.

Desktop notifications are **off** by default — the bubble is the channel. Turn
them on with `./claude-pet set notifications true` or the right-click menu.

## Interaction

- **drag** — move the pet; the position is remembered
- **double-click** — pin/unpin the bubble
- **right-click** — switch pack, toggle wandering, toggle notifications, quit
- clicks land only on the sprite; the rest of the window is click-through

## Commands

```
list                     installed packs, with format and frame counts
search [QUERY]           browse the gallery (--sort, --version, --limit)
add PET_ID...            install packs (--codex-home to install to ~/.codex/pets)
add-collection SLUG      install a whole collection
use PET_ID               choose the active pack
preview [PET_ID]         dump every animation row to a PNG to eyeball a pack
run / restart / stop     control the overlay
status                   current aggregate state and live sessions
set KEY VALUE            pet, height, anchor, walk, notifications,
                         look_at_mouse, autostart, position
snapshot OUT.png         capture the overlay window (--state, --detail)
install-hooks            add hooks to ~/.claude/settings.json (--project for repo-local)
uninstall-hooks          remove them again
doctor                   environment and integration check
```

`install-hooks` merges into existing settings and is idempotent — it never
touches hooks it did not write, and re-running adds nothing.

## How it works

The hooks and the window share a small JSON file at
`~/.local/state/claude-pet/state.json`, written atomically. The hook bridge is
stdlib-only and always exits 0, so a broken pet can never break a Claude turn —
it costs about 33 ms per tool call.

```
Claude Code hook ──> claude-pet hook ──> state.json ──> overlay (polls, 250ms)
```

## Layout

| File | Role |
|---|---|
| `claude_pet/sprites.py` | atlas parsing, v1/v2 layout detection, frame slicing |
| `claude_pet/state.py` | shared state file, multi-session aggregation |
| `claude_pet/hook.py` | hook event → pet state, overlay autostart |
| `claude_pet/overlay.py` | GTK3 window, animation, bubble, walking, mouse-look |
| `claude_pet/registry.py` | codex-pets.net API client and installer |
| `claude_pet/config.py` | settings and pack discovery |
| `claude_pet/cli.py` | command line interface |

## Credits

Sprite packs and the pack format come from the community gallery at
[codex-pets.net](https://codex-pets.net/) (`portons/codex-pet-share`); the
format is documented in `gennadi-kuzmin/awesome-codex-pets`. Neither this tool
nor those projects are affiliated with OpenAI or Anthropic.
