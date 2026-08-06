# claude-pet

**A desktop pet for [Claude Code](https://claude.com/claude-code), on Linux.**

An always-on-top sprite sits on your desktop and reacts to what Claude Code is
actually doing — working, blocked on you, finished, or failed — so you can tell
at a glance without switching to the terminal.

It renders **sprite packs from [codex-pets.net](https://codex-pets.net/)**, so
all ~3000 community packs made for the Codex desktop app work here unchanged.

![claude-pet showing running, waiting, review and idle states](docs/demo.png)

## Why this exists

OpenAI shipped pets for the **Codex** desktop app, on **macOS and Windows
only**. There is no Linux build, and nothing equivalent for Claude Code.

claude-pet is the same idea pointed at a different agent and a different OS:

|  | Codex pets | claude-pet |
|---|---|---|
| Agent | Codex | **Claude Code** |
| Platform | macOS, Windows | **Linux** (X11 / Wayland via XWayland) |
| Sprite packs | codex-pets.net | **the same packs, unchanged** |

Built and tested on **Ubuntu 24.04** (GNOME 46, Wayland session). Nothing in it
is Ubuntu-specific beyond the dependency names.

## Requirements

- Linux with X11, or a Wayland session with XWayland (GNOME, KDE — both fine)
- Python 3.10+
- PyGObject / GTK 3, and Pillow with WebP support

On Ubuntu or Debian:

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-pil libnotify-bin
```

`libnotify-bin` is optional — only needed if you turn desktop notifications on.

> **Why XWayland?** `_NET_WM_STATE_ABOVE` is the only always-on-top mechanism
> mutter honours for an ordinary client, and `gtk-layer-shell` is wlroots-only.
> So the launcher exports `GDK_BACKEND=x11` and the window goes through
> XWayland even in a Wayland session. You do not have to configure anything.

## Install

```bash
git clone https://github.com/HaneulOscarLee/claude-pet.git
cd claude-pet
./claude-pet doctor          # confirm the environment is ready
```

There is nothing to build and no virtualenv to create. Optionally put it on
your `PATH`:

```bash
ln -s "$PWD/claude-pet" ~/.local/bin/claude-pet
```

## Quick start

```bash
claude-pet search                # browse the gallery
claude-pet add clawd             # install a pack
claude-pet install-hooks         # wire into ~/.claude/settings.json
claude-pet run                   # start the overlay
```

Then start a new Claude Code session. That is it — the pet follows along.

After `install-hooks` you never start or stop the pet by hand:

- **starts with Claude** — the `SessionStart` hook launches the overlay
  detached, so it survives the terminal that started it
- **quits with Claude** — once every session has ended, the pet waits out a
  60 second grace period (in case you are just reopening a terminal) and exits.
  `SessionEnd` is the clean signal, but it never arrives when Claude is killed
  outright — a terminal closed with its window button, a crash, a reboot — so
  each session's Claude pid is recorded and checked directly. A session whose
  process is gone stops counting immediately, whether or not it said goodbye.

Both are on by default and can be toggled from the pet's right-click menu, or
with `claude-pet set autostart false` / `set exit_when_no_sessions false`.
`exit_grace_seconds` sets the wait.

If you do start it yourself, `claude-pet run --detach` backgrounds it so
closing the terminal does not take the pet with it. Plain `claude-pet run`
stays in the foreground, which is what you want for debugging.

## What the pet shows

| Claude Code hook | State | Bubble reads |
|---|---|---|
| `SessionStart` | `waving` | session started |
| `UserPromptSubmit` | `running` | working |
| `PreToolUse` / `PostToolUse` | `running` | working · *tool name* |
| `PostToolUse` reporting an error | `failed` | failed |
| `Notification` | `waiting` | needs you · *Claude's own message* |
| `Stop` | `review` | done |
| `SubagentStop` | `running` | working · subagent finished |
| `SessionEnd` | — | the session is forgotten |

All nine animation rows get used, because states have a lifecycle rather than
just switching:

```
SessionStart ──> waving ──────────────────> idle ──> wanders (running-left/right)
UserPromptSubmit ──> running
Stop ──> jumping (once) ──> review ──20s──> idle ──> wanders
tool error ──> failed ──────────────20s──> idle
Notification ──> waiting  (holds until Claude moves on — never times out)
```

Finishing a turn earns a hop, then the pet shows `done` for 20 seconds, then
settles and starts wandering. Without that dwell `review` would stick until
your next prompt, and the idle and walking rows would never be seen.

A dwell belongs to **the session that reported it**, not to the pet. When one
session finishes while others are still working, that session says `done` for
its 20 seconds and then hands the pet back — it does not drag everything to
idle while real work is going on.

Several Claude sessions at once collapse into the most urgent state:

```
waiting  >  failed  >  review  >  running  >  waving  >  idle
```

So a pet reading **needs you** means *some* session wants your attention, the
bubble names which message, and the bubble shows `(N sessions)` when more than
one is live. One pet covers every session — it does not matter how many
terminals or projects you have open:

| Live sessions | Pet shows |
|---|---|
| A `running`, B `review`, C `waiting` | **needs you** · *C's message* · `(3 sessions)` |
| A `running`, B just finished | **done** `(2 sessions)` for 20s, then **working** |
| A `running` | **working** · *tool name* |
| all idle at their prompts | **idle**, and it starts wandering |
| none | **idle** |

Sessions are tracked by Claude's own session id and dropped on `SessionEnd`, or
after six hours of silence if a session dies without one.

Bubble labels ship in English and Korean: `claude-pet set language ko`
(`auto`, the default, follows your locale).

Desktop notifications are **off** by default — the bubble is the channel, and
a notification on top of it is the same news twice. Turn them on with
`claude-pet set notifications true` or from the right-click menu.

## Usage

```
claude-pet <command> [options]
```

### Pets

```bash
claude-pet search                       # most popular packs
claude-pet search penguin --limit 5     # search by text
claude-pet search --version 2           # only v2 packs (these have mouse-look)
claude-pet search --sort new

claude-pet add clawd                    # install one
claude-pet add clawd tennis-ball dario  # or several
claude-pet add-collection cats          # a whole curated collection
claude-pet add guga --codex-home        # install into ~/.codex/pets instead

claude-pet list                          # what is installed
claude-pet use tennis-ball               # pick the active pack
claude-pet preview tennis-ball           # dump all animation rows to a PNG
claude-pet demo                          # watch every row in the live window
```

Found a pack you like on the gallery? The pet id is the last path segment of
its URL, so `https://codex-pets.net/#/pets/doro-v2-roshan` becomes:

```bash
claude-pet add doro-v2-roshan
claude-pet use doro-v2-roshan
claude-pet restart
```

```console
$ claude-pet list
* clawd                    v1 · 192x208 · 57 frames · 0 looks
    /home/you/.claude/pets/clawd
  tennis-ball              v2 · 192x208 · 58 frames · 16 looks
    /home/you/.claude/pets/tennis-ball
```

### Overlay

```bash
claude-pet run                  # start it in the foreground
claude-pet run --detach         # ...or in the background, outliving the terminal
claude-pet run --pet dario      # start with a specific pack, just this once
claude-pet restart              # after changing the pack or settings
claude-pet stop
claude-pet status               # current state and every live session
```

```console
$ claude-pet status
overlay   : running (pid 3877683)
state     : running  (1 sessions)
detail    : Bash
active pet: clawd
state file: /home/you/.local/state/claude-pet/state.json
  ed0f2f9c  running  Bash
```

### Integration

```bash
claude-pet install-hooks              # ~/.claude/settings.json (global)
claude-pet install-hooks --project    # ./.claude/settings.json (this repo only)
claude-pet uninstall-hooks
claude-pet doctor                     # environment + integration check
```

`install-hooks` **merges** into your existing settings: it never touches hooks
it did not write, and re-running it adds nothing. `uninstall-hooks` removes
only its own entries.

### Settings

```bash
claude-pet set height 160             # sprite height in pixels
claude-pet set anchor bottom-left     # bottom-right | bottom-left | top-right | top-left
claude-pet set walk false             # stop wandering
claude-pet set language ko
claude-pet set bubble alerts          # only speak up when it needs you
claude-pet set position none          # forget a dragged position, re-anchor
```

| Key | Default | Meaning |
|---|---|---|
| `pet` | first found | active pack id |
| `height` | `132` | on-screen sprite height in pixels |
| `anchor` | `bottom-right` | corner to start in |
| `walk` | `true` | wander along the screen edge while idle |
| `language` | `auto` | bubble labels: `auto` \| `en` \| `ko` |
| `bubble` | `active` | when to speak: `active` (any non-idle state) \| `alerts` (only needs-you / done / failed) \| `never` |
| `notifications` | `false` | also send a desktop notification |
| `look_at_mouse` | `true` | v2 packs: face the pointer while idle |
| `autostart` | `true` | let the `SessionStart` hook launch the overlay |
| `exit_when_no_sessions` | `true` | quit once every Claude session has ended |
| `exit_grace_seconds` | `60` | how long to wait first, in case one reopens |
| `position` | `null` | remembered drag position |

Stored in `~/.config/claude-pet/config.json`.

### Debugging

```bash
claude-pet demo                                      # cycle every animation row
claude-pet demo --pet doro-v2-roshan --seconds 1     # check a specific pack, faster
claude-pet snapshot out.png                          # capture the live overlay
claude-pet snapshot out.png --state waiting \
    --detail "needs permission"                      # capture a forced state
```

Useful because GNOME blocks its screenshot D-Bus API for unauthorised callers,
so this is how you get a picture of the window.

## Interaction

| Action | Result |
|---|---|
| click, while it needs you | **jump to that session** (see below) |
| click, otherwise | pin / unpin the speech bubble |
| drag | move the pet; the position is remembered |
| right-click | switch pack; toggle wandering, notifications, start-with-Claude and quit-when-no-sessions; quit |

Clicks land only on the sprite itself — the rest of the window is
click-through, so the pet never steals a click meant for what is underneath.
A drag only begins once the pointer has actually travelled a few pixels, so a
plain click stays a click.

### Jumping back to a session

When the pet is showing **needs you**, **done** or **failed**, the bubble adds
`↩ click to jump` and clicking takes you to the session behind it.

| Setup | What happens |
|---|---|
| Claude running inside **tmux** | switches to the exact pane — precise and reliable |
| **X11 or XWayland** terminal, with `wmctrl` or `xdotool` installed | raises the terminal window |
| **Wayland-native** terminal (GNOME Terminal on Wayland, etc.) | not possible — the pet says so |

That last row is a compositor limitation, not a missing feature. Under mutter
a client cannot raise another application's window: `org.gnome.Shell.FocusApp`,
`.Introspect` and `.Eval` all answer `AccessDenied`, and xdg-activation needs a
token only the target application can hand out. Running Claude inside tmux is
the reliable answer, and gives pane-level precision as a bonus.

`claude-pet doctor` reports which methods are available on your machine.

## Sprite packs

Any pack from [codex-pets.net](https://codex-pets.net/) works, in either atlas
format. Packs you already installed with `npx codex-pets add` are picked up
from `~/.codex/pets/` directly, without being copied.

Search order: `~/.claude/pets/`, then `~/.codex/pets/`
(`$CLAUDE_CONFIG_DIR` and `$CODEX_HOME` are respected).

### The format

|  | v1 | v2 |
|---|---|---|
| atlas | 1536 × 1872 | 1536 × 2288 |
| grid | 8 columns × 9 rows | 8 columns × 11 rows |
| cell | 192 × 208 | 192 × 208 |
| `pet.json` | no version field | `"spriteVersionNumber": 2` |

Animation rows, in order:

| Row | Animation | Row | Animation |
|---|---|---|---|
| 0 | `idle` | 5 | `failed` |
| 1 | `running-right` | 6 | `waiting` |
| 2 | `running-left` | 7 | `running` |
| 3 | `waving` | 8 | `review` |
| 4 | `jumping` | 9–10 | 16 look directions (v2 only) |

The v2 look-direction rows are a left-to-right yaw sweep, used to make the pet
face your mouse pointer while idle.

Frame counts per row are **measured from the alpha channel** rather than read
from the published table — real packs sometimes draw a frame past the nominal
count, and trailing cells are required to be fully transparent anyway.

### Rolling your own

A pack is just a directory:

```
my-pet/
  pet.json
  spritesheet.webp
```

```json
{
  "id": "my-pet",
  "displayName": "My Pet",
  "description": "A pet I drew",
  "spritesheetPath": "spritesheet.webp",
  "spriteVersionNumber": 2,
  "kind": "animal"
}
```

Drop it in `~/.claude/pets/my-pet/` and check it loaded:

```bash
claude-pet list
claude-pet preview my-pet -o check.png    # eyeball every row and frame count
claude-pet demo --pet my-pet              # or watch them animate, row by row
```

`preview` prints the frame count it detected per row, which is the fastest way
to catch a misaligned grid. `demo` is the desktop equivalent of the state
buttons on a gallery page — it steps the real window through every row.

## How it works

```
Claude Code hook ──> claude-pet hook ──> state.json ──> overlay (polls, 250 ms)
```

The hooks and the window share one small JSON file at
`~/.local/state/claude-pet/state.json`, written atomically with a lock that has
a hard timeout. The hook bridge is stdlib-only — no Pillow, no GTK, no network
— and always exits 0, so a broken pet can never break a Claude turn. It costs
about **33 ms** per tool call.

| File | Role |
|---|---|
| `claude_pet/sprites.py` | atlas parsing, v1/v2 detection, frame slicing |
| `claude_pet/state.py` | shared state file, multi-session aggregation |
| `claude_pet/hook.py` | hook event → pet state, overlay autostart |
| `claude_pet/overlay.py` | GTK3 window, animation, bubble, walking, mouse-look |
| `claude_pet/launch.py` | starting the overlay detached, shared by hook and CLI |
| `claude_pet/locate.py` | recording where a session runs (hook side) |
| `claude_pet/jump.py` | jumping back to it (overlay side) |
| `claude_pet/registry.py` | codex-pets.net API client and installer |
| `claude_pet/config.py` | settings and pack discovery |
| `claude_pet/cli.py` | command line interface |
| `tests/test_aggregate.py` | multi-session aggregation and dwell behaviour |

```bash
python3 tests/test_aggregate.py    # stdlib only, no test runner needed
```

## Troubleshooting

Start with `claude-pet doctor` — it checks every item below at once.

**No pet appears.** Check `DISPLAY` is set. In a Wayland session the overlay
needs XWayland; `doctor` reports which backend it will use. Look at
`~/.local/state/claude-pet/overlay.log` for a traceback.

**The pet is not on top.** Confirm the window has the right state:

```bash
xprop -name claude-pet _NET_WM_STATE     # expect _NET_WM_STATE_ABOVE
```

Some tiling window managers ignore `_NET_WM_STATE_ABOVE`; there is no
workaround from the client side.

**The pet never changes state.** Hooks are per-settings-file, and a running
session does not pick up newly installed hooks. Run `claude-pet install-hooks`,
then start a *new* session. `claude-pet status` shows whether events are
arriving at all.

**The pet never wanders.** Wandering only happens while `idle`. If any session
is mid-turn the state is `running`, which is correct — wait until every session
is sitting at its prompt.

**The pet is silent.** With `bubble: alerts` it only speaks for needs-you, done
and failed. The default `active` also narrates tool calls.

**The pet does not exit when I close Claude.** Give it `exit_grace_seconds`
(60 by default) — closing a terminal and checking a few seconds later is too
soon. `claude-pet status` shows the auto-exit setting and lists every session
it still counts, marking any whose Claude process has died. If a session lingers
there with a live pid, that Claude really is still running somewhere.

**Clicking does not jump anywhere.** The bubble only offers `↩ click to jump`
when a location was recorded. Sessions that started before `install-hooks` have
none — send one prompt and it is picked up. If the bubble offers it but nothing
happens, `claude-pet doctor` says which methods are usable; on a Wayland-native
terminal none are.

**A pack shows as `broken` in `list`.** The message names the reason. The usual
cause is an atlas that is not 8 columns wide or whose height is not divisible
by 9 or 11.

## Uninstall

```bash
claude-pet stop
claude-pet uninstall-hooks
rm -rf ~/.config/claude-pet ~/.local/state/claude-pet ~/.claude/pets
```

## Credits

Sprite packs and the pack format come from the community gallery at
[codex-pets.net](https://codex-pets.net/)
([`portons/codex-pet-share`](https://github.com/portons/codex-pet-share)); the
format is documented in
[`gennadi-kuzmin/awesome-codex-pets`](https://github.com/gennadi-kuzmin/awesome-codex-pets).

Neither this project nor those is affiliated with, endorsed by, or supported by
OpenAI or Anthropic.

## License

[MIT](LICENSE)
