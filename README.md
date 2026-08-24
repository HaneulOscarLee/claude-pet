# claude-pet

[![CI](https://github.com/HaneulOscarLee/claude-pet/actions/workflows/ci.yml/badge.svg)](https://github.com/HaneulOscarLee/claude-pet/actions/workflows/ci.yml)

**A desktop pet for [Claude Code](https://claude.com/claude-code), on Linux.**

An always-on-top sprite sits on your desktop and reacts to what your coding
agent is doing — working, blocked on you, finished, or failed — so you can tell
at a glance without switching to the terminal. It follows **Claude Code**,
**Codex** and **Gemini CLI** at once, and the Claude Desktop app too.

It renders **sprite packs from [codex-pets.net](https://codex-pets.net/)**, so
all ~3000 community packs made for the Codex desktop app work here unchanged.

![claude-pet showing running, waiting, review and idle states](docs/demo.png)

OpenAI shipped pets for the **Codex** desktop app, on macOS and Windows only.
This is the same idea pointed at Linux and at Claude Code — same packs,
unchanged. Built and tested on Ubuntu 24.04 (GNOME 46, Wayland); nothing in it
is Ubuntu-specific beyond the dependency names.

## Install

### Debian / Ubuntu, without a terminal

Download the `.deb` from
[Releases](https://github.com/HaneulOscarLee/claude-pet/releases/latest) and
open it.

The hooks go into your own `~/.claude/settings.json`, which a package
installing as root cannot write for you — so they are wired up at your next
login by an autostart entry, or immediately if you launch **claude-pet** once
from your applications menu. Nothing to type either way.

### One line, any distro

```bash
curl -fsSL https://raw.githubusercontent.com/HaneulOscarLee/claude-pet/main/install.sh | bash
```

Downloads the source into `~/.local/share/claude-pet`, installs what it needs
through your package manager, and runs `setup`. Knobs: `CLAUDE_PET_DIR`,
`CLAUDE_PET_REF`, `CLAUDE_PET_NO_DEPS=1`.

If piping a script into a shell is not your thing — reasonable — read
[`install.sh`](install.sh) first, or clone and run `setup` yourself:

```bash
git clone https://github.com/HaneulOscarLee/claude-pet.git
cd claude-pet && ./claude-pet setup
```

`setup` links `claude-pet` into `~/.local/bin`, installs tab completion, offers
to install `wmctrl`, downloads a sprite pack, wires the hooks, and starts the
pet. It is idempotent. Run `exec $SHELL` afterwards for PATH and completion.
Then start a new agent session — that is it.

Nothing is built and no virtualenv is created, so keep the install directory
where it is, or re-run `setup` after moving it.

### Requirements

- Linux with X11, or a Wayland session with XWayland (GNOME, KDE — both fine)
- Python 3.10+, PyGObject / GTK 3, Pillow with WebP support

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-pil \
                 wmctrl libnotify-bin
```

The last two are optional: `wmctrl` lets clicking the pet raise a terminal that
is not running tmux, and `libnotify-bin` enables desktop notifications, which
are off by default.

> **`No module named 'gi'`, with `python3-gi` installed?** Your `python3` is a
> virtualenv, pyenv, conda or asdf one, and PyGObject is installed into the
> *system* Python only. claude-pet looks past them for an interpreter that can
> see it; `CLAUDE_PET_PYTHON=/usr/bin/python3` settles it outright.

> **Why XWayland?** `_NET_WM_STATE_ABOVE` is the only always-on-top mechanism
> mutter honours for an ordinary client, and `gtk-layer-shell` is wlroots-only.
> So the launcher exports `GDK_BACKEND=x11`. You do not have to configure
> anything.

## More than one agent

Claude Code, Codex and Gemini CLI share a hook vocabulary — Codex carries
Claude's event names verbatim, and Gemini ships a `hooks migrate` whose whole
job is rewriting a Claude configuration into its own. One bridge serves all
three, and the pet starts with whichever agent you start.

```console
$ claude-pet install-hooks
  Claude Code  /home/you/.claude/settings.json  added 8 event(s)
  Codex        /home/you/.codex/config.toml     added 8 event(s)
               approve them once in Codex with /hooks
  Gemini CLI   /home/you/.gemini/settings.json  added 7 event(s)
```

| | Claude Code | Gemini CLI | Codex |
|---|---|---|---|
| turn starts | `UserPromptSubmit` | `BeforeAgent` | `UserPromptSubmit` |
| turn ends | `Stop` | `AfterAgent` | `Stop` |
| tool calls | `Pre`/`PostToolUse` | `Before`/`AfterTool` | `Pre`/`PostToolUse` |
| settings | `~/.claude/settings.json` | `~/.gemini/settings.json` | `~/.codex/config.toml` |

**Codex asks you to approve hooks once**, in its own `/hooks` view — anything
that can run a command on its behalf starts out untrusted, and that is Codex's
business to ask rather than claude-pet's to answer. Its TOML settings are
edited between markers, so your comments and key order survive and
`uninstall-hooks` takes the block back out byte for byte.

Not every agent has every event: Codex has no `Notification` or `SessionEnd`,
Gemini no `SubagentStop`. Nothing is offered to an agent that would reject it.

Two things about Codex are worth knowing, both its own behaviour rather than
anything configurable here. **Hooks do not load in a directory you have not
trusted** — Codex says so in the prompt it shows on entering one, and until
you answer it the pet hears nothing. And **`codex exec` fires only `Stop`**,
with no `SessionStart` or `UserPromptSubmit`, so a non-interactive run will
not bring the pet up.
Non-Claude sessions are labelled in `claude-pet status`, and `doctor` says
where each agent stands.

**OpenCode is not supported.** Its extension point is a JavaScript plugin
rather than a command a hook can run, and its event bus carries message
traffic with nothing that plainly marks a turn starting or ending — so
`working` and `done` would have to be inferred, and a pet built on inference
sits on the wrong state.

## What the pet shows

| Hook | State | Bubble reads |
|---|---|---|
| `SessionStart` | `waving` | session started |
| `UserPromptSubmit` | `running` | working |
| `PreToolUse` / `PostToolUse` | `running` | working · *tool name* |
| `PostToolUse` reporting an error | `failed` | failed |
| `Notification`, blocked | `waiting` | needs you · *the agent's message* |
| `Stop` | `review` | done |
| `SubagentStop` | `running` | working · subagent finished |
| `SessionEnd` | — | the session is forgotten |

States have a lifecycle rather than just switching, so all nine animation rows
get used:

```
SessionStart ──> waving ─────────────────> idle ──> wanders (running-left/right)
UserPromptSubmit ──> running
Stop ──> jumping (once) ──> review ──20s──> idle ──> wanders
tool error ──> failed ─────────────20s───> idle
Notification ──> waiting  (holds until the agent moves on — never times out)
```

A dwell belongs to **the session that reported it**. When one session finishes
while others are still working, that session says `done` for its 20 seconds
and then hands the pet back.

**needs you** is reserved for the agent actually being blocked. Claude Code
sends `Notification` for two unrelated situations — it wants permission, or a
turn ended and you have not typed since — so a notification arriving after
`Stop` is ignored. The same wording *during* a turn still counts.

**working** gets a second opinion, because a turn you interrupt sends no
`Stop`. The pet watches whether the session's process is doing anything: a
working agent burns measurable CPU (~0.17s per second) and one sitting at its
prompt does not (~0.005s). After 45 seconds of a stale `running` on an idle
process, the pet gives up on it. Only `running` is second-guessed — `waiting`
is a claim about *you*, and an idle agent is exactly what that looks like.

Several sessions at once collapse into the most urgent state:

```
waiting  >  failed  >  review  >  running  >  waving  >  idle
```

| Live sessions | Pet shows |
|---|---|
| A `running`, B `review`, C `waiting` | **needs you** · *C's message* · `(3 sessions)` |
| A `running`, B just finished | **done** `(2 sessions)` for 20s, then **working** |
| A `running` | **working** · *tool name* |
| all idle at their prompts | **idle**, and it starts wandering |

One pet covers every session, however many terminals or projects are open.
Sessions are dropped on `SessionEnd`, or as soon as the pet notices the
process is gone — a terminal closed with its window button, a crash, a reboot.
Going quiet is not going away: a session left at its prompt overnight stays
tracked for as long as its process lives.

`claude-pet status` shows what each session reported and which event put it
there; `claude-pet log` keeps a short history, which is where to start when
the pet shows something you do not expect.

```console
$ claude-pet log
12:18:04  idle -> running  via=PreToolUse           session=ed0f2f9c  detail='Bash'
12:18:07  running -> review  via=DesktopNotification  session=claude-desktop
```

Bubble labels ship in English and Korean (`claude-pet set language ko`;
`auto` follows your locale). Desktop notifications are off by default — the
bubble is the channel, and a notification on top of it is the same news twice.

### The Claude Desktop app

| In Claude Desktop | Pet shows | How |
|---|---|---|
| a **Claude Code** session | every state, exactly as in a terminal | the app runs the real binary, which fires the same hooks |
| a **plain chat** | **done** when a reply lands | the app's desktop notification, the only turn signal it emits |
| open, nothing happening | `idle`, and the pet stays up | — |

Claude Code inside the app needs no setup — it reads the same
`~/.claude/settings.json`, and clicking the pet brings the app forward.

A plain chat is coarser, and honestly so. There is no hook surface, so the pet
watches the notification the app posts when a reply arrives. That means no
**working** (nothing announces a turn starting) and never **needs you** (the
text of a notification is not evidence of what it wants — reading it for words
like "permission" turned ordinary Korean notices into a pet demanding
attention). Both states time out on their own, unlike a session's, since
nothing will ever say the reply was read. Notifications only fire while the
app is unfocused, which is exactly when a pet is worth glancing at.

Turn it off with `claude-pet set desktop false` or **Follow Claude Desktop**
in the menu.

## Usage

### Pets

```bash
claude-pet search                       # most popular packs
claude-pet search penguin --limit 5     # search by text
claude-pet search --version 2           # only v2 packs (these have mouse-look)

claude-pet add clawd                    # install one, or several
claude-pet add-collection cats          # a whole curated collection
claude-pet add guga --codex-home        # install into ~/.codex/pets instead
claude-pet hatch ~/Pictures/cat.png     # build a pack from any image
claude-pet remove dario -y

claude-pet list                         # what is installed
claude-pet use tennis-ball              # pick the active pack
claude-pet preview tennis-ball          # dump all animation rows to a PNG
claude-pet demo                         # watch every row in the live window
```

The pet id is the last path segment of a gallery URL, so
`https://codex-pets.net/#/pets/doro-v2-roshan` becomes `claude-pet add
doro-v2-roshan`.

### Overlay

```bash
claude-pet run [--detach] [--pet dario]
claude-pet restart              # after changing the pack or settings
claude-pet stop
claude-pet status               # current state and every live session
claude-pet log                  # what it showed over time, and why
claude-pet reset-position       # send it back to its corner
```

### Integration

```bash
claude-pet setup                      # pack + hooks + PATH link + start
claude-pet update [--check]           # fetch the new version, then restart
claude-pet doctor [--fix]             # environment + integration check

claude-pet install-hooks [--project]  # global, or ./.claude/settings.json
claude-pet uninstall-hooks

claude-pet fix-pointer [--undo]       # be callable from anywhere on Wayland
claude-pet fix-terminal [--undo]      # run the terminal under XWayland
```

`install-hooks` **merges** into your existing settings: it never touches hooks
it did not write, and `uninstall-hooks` removes only its own entries.

`update` works out which kind of install it is looking at — a git clone is
fast-forwarded (refused if you have uncommitted changes), a tarball install is
re-downloaded, a `.deb` is fetched and handed to the system installer, which
asks for authority through the desktop's usual prompt. Either way the running
pet restarts onto the new code, and it also notices when its files are
replaced underneath it, so an apt upgrade applies without it carrying on with
the old behaviour.

### Settings

```bash
claude-pet set height 160
claude-pet set anchor bottom-left
claude-pet set walk false
claude-pet set language ko
```

| Key | Default | Meaning |
|---|---|---|
| `pet` | first found | active pack id |
| `height` | `132` | on-screen sprite height in pixels |
| `anchor` | `bottom-right` | corner to start in |
| `walk` | `true` | wander along the screen edge while idle |
| `walk_speed` | `3` | pixels per step while wandering |
| `language` | `auto` | bubble labels: `auto` \| `en` \| `ko` |
| `bubble` | `active` | when to speak: `active` \| `alerts` \| `never` |
| `notifications` | `false` | also send a desktop notification |
| `look_at_mouse` | `true` | v2 packs: face the pointer while idle |
| `petting` | `true` | react to being stroked |
| `throwing` | `true` | can be thrown with a flick |
| `call` | `true` | come when a circle is drawn |
| `teleport` | `true` | appear at a drawn star |
| `on_top` | `true` | keep the pet above other windows |
| `throw_flick` | `4500` | px/s a release must reach to count as a throw |
| `throw_friction` | `0.08` | fraction of speed kept after a second |
| `throw_bounce` | `0.45` | how much a wall gives back |
| `call_pace` | `2.0` | walking speed on an errand, as a multiple of wandering |
| `call_seconds` | `0.4` | how quickly the circle must be drawn |
| `call_size` | `90` | how big it must be, across |
| `call_roundness` | `0.6` | how round: short axis over long |
| `star_size` | `220` | how big a star must be, across, to teleport |
| `usage` | `true` | show Claude's 5h/weekly limits and cost, and warn on the 5h limit |
| `usage_warn_percent` | `90` | 5h limit % that earns a bubble warning |
| `fps` | `10` | animation frames per second |
| `autostart` | `true` | let the `SessionStart` hook launch the overlay |
| `update_check` | `true` | look for a newer version in the background |
| `desktop` | `true` | follow the Claude Desktop app as well |
| `exit_when_no_sessions` | `true` | quit once every session has ended |
| `exit_grace_seconds` | `30` | how long to wait first, in case one reopens |
| `position` | `null` | remembered drag position |

Stored in `~/.config/claude-pet/config.json`.

## Usage & limits

The pet reads Claude Code's own usage figures — **5-hour and weekly limit %**,
cost, and reset times — and shows them at the top of the right-click menu
(`5h 15% · 7d 9% · $24.73`). When the 5-hour limit crosses a threshold (90% by
default) the pet says so in a bubble, once per window.

Nothing is computed or estimated here. The percentages are the server's own
accounting — it knows your plan's caps and reports how much of each window you
have spent on every request — which Claude Code carries into the JSON it hands
its `statusLine` on every render. That JSON is the only place the figures
appear; the hooks never see them and the transcripts do not carry them.

- If you already run a status line (**oh-my-claudecode**, or your own),
  claude-pet reads the figures from its cache and leaves your status line
  alone.
- If you have **no** status line, `install-hooks` claims the slot with a tiny
  one (`5h 15% · 7d 9% · $24.73`) purely to capture the figures; `uninstall-hooks`
  removes only what it wrote.
- Turn the whole thing off with `claude-pet set usage false`; change the
  warning point with `claude-pet set usage_warn_percent 80`.

Only **Claude Code** reports these — Codex, Gemini and the rest emit no such
figures, so the line simply shows what is available.

## Interaction

| Action | Result |
|---|---|
| click | **jump to that session**, or pin the bubble if there is nowhere to jump |
| drag | move the pet — mid-stride is fine |
| rub back and forth over it | pet it |
| flick it while dragging | throw it — it slides and bounces off the edges |
| draw a circle anywhere on screen | it walks over |
| draw a star | it appears there instead of walking |
| right-click | everything below, without a terminal |

Clicks land only on the sprite itself; the rest of the window is click-through,
so the pet never steals a click meant for what is underneath. Drag it right up
to the top edge — the bubble moves underneath when there is no room above.

**Stroking** is a gesture, not a click: move the pointer back and forth over
the sprite and it stops walking, perks up and says something. What separates
that from a pointer merely crossing the sprite is that a stroke turns around,
ignoring movements too small to be deliberate, so a hand resting on the mouse
never counts. Being petted is deliberately *not* a state — the states belong to
what your agents are doing.

**Throwing** takes a deliberate flick. Only the speed in the last tenth of a
second decides, and the bar sits above what a normal drag reaches, because
guessing wrong moves the pet somewhere you did not put it.
`CLAUDE_PET_DEBUG=1` prints the speed of every release.

**Calling it** is a small circle drawn with the pointer, anywhere on screen.
It has to be at least coin-sized, roughly round, and quick — about half a
second for the full turn. A large circle is therefore not a summons at all,
since no hand carries one round that fast: what is being asked for is a flick
of a circle, not a slow sweep. Roundness is judged through the shape's own
axes rather than the screen's, so a sliver drawn cornerwise does not pass for
a circle just because its bounding box is square.

The pet waves the moment it hears you, follows the pointer as it walks, and
stops *beside* it rather than on top of it. It goes a little brisker than it
wanders and no more. Wandering itself stays along the ground, sideways only;
up and down is for being called.

**A star teleports it** there instead, for when a walk across two monitors is
a wait rather than a charm. It has to be a big one — well over twice the room
a circle needs — because appearing somewhere else is the more disruptive
answer of the two, and worth asking for a drawing nobody makes by accident. A
star is corners where a circle is a curve, which is how they are told apart: the five points each turn about 144 degrees, all
the same way round, with straight runs between. A circle, a square, a triangle
and a zigzag are none of them stars, and a star does not also read as a
circle.

**How all this feels is yours to set.** Right-click → Behaviour → Tuning opens
a window with a slider for each of it — how hard a flick has to be, how much friction and
bounce a throw has, how fast the pet walks when called, and how quick, how big
and how round the circle has to be. They apply as you drag them, and **Reset
to defaults** puts them all back. Every one of these was guessed at and
argued about before it was a slider, which is the argument for making it one.

**Always on top** is in the same menu, on by default. Normally the point of an
overlay, but a pet in front of what you are reading is a pet in the way, and
nothing else can put it behind a window.

### Calling it on Wayland

**Out of the box, on a Wayland session, the pet can only be called from over
an X11/XWayland window** — a terminal, say, but not a Wayland-native browser.
The overlay runs under XWayland, and XWayland is told where the pointer is
only while the pointer is over one of its own windows. Move onto a
Wayland-native one and the position freezes where it left, so the same circle
is recognised over a terminal and ignored over a browser. It is also why the
pet can seem to stop at the join between two monitors.

The compositor never lost track, though; the difficulty was only that nothing
would say. So:

```bash
claude-pet fix-pointer      # then log out and back in
```

installs a GNOME Shell extension of one method, which answers
`global.get_pointer()` on the shell's own bus name. After that the pet is
callable from anywhere. It watches nothing, owns no bus name of its own, and
comes off again with `--undo`. The log out is not optional: GNOME reads its
extensions once, at startup.

`setup` and every update lay this down for you on GNOME/Wayland, so
`fix-pointer` by hand is rarely needed — but the log out still is, and the pet
says so once on its next start when the bridge is installed but not yet
loaded.

Two formats ship, because GNOME 45 moved extensions to ES modules: the right
one is chosen from the running shell's version, so **GNOME 42 (Ubuntu 22.04)
through 48** are covered. A copy left behind in the wrong format — an install
from before the older format was supported, which is present and inert — is
replaced rather than mistaken for a working one.

The pet asks X11 first and only falls back to the bridge once X11 has lost
sight, so in the ordinary case the compositor is not asked at all. Without the
bridge it still knows when not to believe what it is told, and walks nowhere
rather than to a position that stopped moving. `claude-pet doctor` reports
which is in force.

If you would rather not install an extension, draw the circle over an XWayland
window — a terminal will do — or run the browser under X11
(`--ozone-platform=x11` for Chrome, Chromium and Whale; `MOZ_ENABLE_WAYLAND=0`
for Firefox). On an X11 session none of this applies.

### The menu

Right-click the pet. It opens on a short page rather than one long list.

```
clawd · v2
──────────────
Pets…                  →  pick one · browse the gallery · install · remove
Language…              →  automatic · English · 한국어
Behaviour…             →  wander · petted · thrown · called · star · tuning…
──────────────
Always on top               ✓
Desktop notifications
Start with Claude           ✓
Follow Claude Desktop       ✓
Quit when no sessions       ✓
──────────────
Reset position
Up to date
Quit
```

Language takes effect immediately; picking a different pack restarts the pet,
because the sprites have to be reloaded. The version is checked in the
background 20 seconds after start and every six hours after that.

### When you cannot find the pet

Everything above goes *through* the pet, which is no help when it is somewhere
you cannot click — on a screen since unplugged, or buried under something
full-screen. The same controls live in the status bar, with **reset position**
at the top. That needs `gir1.2-ayatanaappindicator3-0.1` and, on GNOME, a tray
extension; Ubuntu ships one enabled and `doctor` says whether you have it.

Failing that, `claude-pet reset-position` from any shell. The pet also
re-anchors at startup if its remembered place is no longer on any screen.

### Jumping back to a session

When the pet shows **needs you**, **done** or **failed**, the bubble adds
`↩ click to jump`.

| Setup | What happens |
|---|---|
| session started in **Claude Desktop** | brings the app forward |
| running inside **tmux** | raises the terminal *and* switches to the exact pane |
| **X11/XWayland** terminal, with `wmctrl` or `xdotool` | raises the terminal window |
| **Wayland-native** terminal implementing `org.freedesktop.Application` | asks it to present itself |
| any other **Wayland-native** terminal | not possible — the pet says so rather than pretending |

The last row is a mutter rule, not an oversight: a client may not raise
*another* application's window, and xdg-activation needs a token only the
target can hand out. An application raising *itself* is always allowed, which
is what the D-Bus route uses — but the terminal has to expose a method for it,
and not all do.

A terminal that serves several windows from **one process** gives them all the
same `_NET_WM_PID`, so "the window owned by that process" is ambiguous and the
pet used to raise whichever came first — reported as clicking **needs you**
bringing up a different window than the session that was waiting. Terminator
puts a per-terminal uuid in the environment and will map it to a window title
on request, so where that is available the right window is picked exactly. For
terminals that offer nothing of the kind it is still the first window, and
tmux is still the way to land on an exact pane.

`setup` handles this when it applies, by making your terminal run under
XWayland so `wmctrl` can reach it:

```bash
claude-pet fix-terminal [--undo]
```

It writes two things, both under your home directory and both removed by
`--undo`: `~/.local/bin/x-terminal-emulator`, a wrapper that execs the real
terminal with `GDK_BACKEND=x11` (this is what covers **Ctrl+Alt+T**), and a
copy of the terminal's `.desktop` file with the same prefix, which covers the
launcher and the dock. It is skipped where it would not help. On a HiDPI
screen an XWayland window can look slightly softer than a native one.

The alternative, which changes nothing about your terminal, is to run your
agent inside tmux — the pet then jumps to the exact pane. tmux is the only way
to land on a *particular* place inside a terminal, since tabs and splits are
widgets rather than windows and nothing outside can address them.

A jump never takes a session away from another window. If a client is already
attached to the target's session, the window is selected and nobody is moved;
otherwise a client is lent only when its own session has another client
watching it, and named explicitly rather than left to tmux to choose — an
unnamed `switch-client` picks a client itself, and picks one watching
something else.

## Sprite packs

Any pack from [codex-pets.net](https://codex-pets.net/) works, in either atlas
format. Packs installed with `npx codex-pets add` are picked up from
`~/.codex/pets/` directly. Search order: `~/.claude/pets/`, then
`~/.codex/pets/` (`$CLAUDE_CONFIG_DIR` and `$CODEX_HOME` respected).

|  | v1 | v2 |
|---|---|---|
| atlas | 1536 × 1872 | 1536 × 2288 |
| grid | 8 columns × 9 rows | 8 columns × 11 rows |
| cell | 192 × 208 | 192 × 208 |
| `pet.json` | no version field | `"spriteVersionNumber": 2` |

| Row | Animation | Row | Animation |
|---|---|---|---|
| 0 | `idle` | 5 | `failed` |
| 1 | `running-right` | 6 | `waiting` |
| 2 | `running-left` | 7 | `running` |
| 3 | `waving` | 8 | `review` |
| 4 | `jumping` | 9–10 | 16 look directions (v2 only) |

The v2 rows are a left-to-right yaw sweep, used to face the pointer while
idle. Frame counts are measured from the alpha channel rather than read from
the published table, since real packs sometimes draw a frame past the nominal
count.

### Making one

`hatch` draws no art. Point it at an image you already have and it derives the
nine rows by transforming that one picture — bobbing for idle, leaning for the
running rows, arcing with a squash for jumping, desaturating and shedding a
tear for failure:

```bash
claude-pet hatch ~/Pictures/my-cat.png
claude-pet demo --pet my-cat
```

That is half of what Codex's `/hatch-pet` does — Codex generates the sprite
art with an image model, this only does the packaging. It will not beat art
drawn frame by frame, but it is a real pack.

Rolling your own by hand is just a directory with `pet.json` and
`spritesheet.webp`:

```json
{
  "id": "my-pet",
  "displayName": "My Pet",
  "spritesheetPath": "spritesheet.webp",
  "spriteVersionNumber": 2,
  "kind": "animal"
}
```

Drop it in `~/.claude/pets/my-pet/` and check it with `claude-pet preview
my-pet -o check.png`, which prints the frame count detected per row — the
fastest way to catch a misaligned grid.

## How it works

```
agent hook ──> claude-pet hook ──> state.json ──> overlay (polls, 250 ms)
```

The hooks and the window share one small JSON file at
`~/.local/state/claude-pet/state.json`, written atomically with a lock that
has a hard timeout. The hook bridge is stdlib-only — no Pillow, no GTK, no
network — and always exits 0, so a broken pet can never break a turn. It costs
about **33 ms** per tool call.

Tests are stdlib-only and need no runner: `python3 tests/test_aggregate.py`
and friends. [CONTRIBUTING.md](CONTRIBUTING.md) covers how the pieces fit.

## Troubleshooting

Start with `claude-pet doctor` — it checks every item below at once.

**No pet appears.** Check `DISPLAY` is set. In a Wayland session the overlay
needs XWayland. Look at `~/.local/state/claude-pet/overlay.log` for a
traceback.

**The pet is not on top.** `xprop -name claude-pet _NET_WM_STATE` should list
`_NET_WM_STATE_ABOVE`. Some tiling window managers ignore it, and there is no
workaround from the client side.

**The pet never changes state.** A running session does not pick up newly
installed hooks. Run `claude-pet install-hooks`, then start a *new* session.

**The pet never wanders.** Wandering only happens while `idle`. If any session
is mid-turn the state is `running`, which is correct.

**Calling it does nothing.** On Wayland, see
[calling it on Wayland](#calling-it-on-wayland). Otherwise the circle may be
too big or too slow — it wants a quick, coin-sized one.

**The pet does not exit when I close my agent.** Give it
`exit_grace_seconds` (30 by default). `claude-pet status` lists every session
it still counts and marks any whose process has died.

**Clicking does not jump anywhere.** The bubble only offers `↩ click to jump`
when a location was recorded; sessions started before `install-hooks` have
none. `doctor` says which methods are usable.

**A pack shows as `broken` in `list`.** The message names the reason, usually
an atlas that is not 8 columns wide or whose height is not divisible by 9 or
11.

**Tab completion does nothing.** Run `exec $SHELL`, or open a new terminal.

## Uninstall

```bash
claude-pet stop
claude-pet uninstall-hooks
claude-pet fix-pointer --undo        # if you installed the shell extension
rm -rf ~/.config/claude-pet ~/.local/state/claude-pet ~/.claude/pets
```

## Contributing

Patches and bug reports are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md)
for the handful of constraints worth knowing (chiefly: the hook path runs on
every tool call and must stay stdlib-only and fast).

Bug reports should include `claude-pet doctor` and `claude-pet status`. Almost
every problem here has turned out to be environment-specific.

## Credits

The bundled `pocket` pack is original, drawn by `tools/make_default_pack.py`
and covered by this repository's licence. Every other pack is someone else's
work, downloaded on request and never redistributed here.

Sprite packs and the pack format come from the community gallery at
[codex-pets.net](https://codex-pets.net/)
([`portons/codex-pet-share`](https://github.com/portons/codex-pet-share)); the
format is documented in
[`gennadi-kuzmin/awesome-codex-pets`](https://github.com/gennadi-kuzmin/awesome-codex-pets).

Neither this project nor those is affiliated with, endorsed by, or supported
by OpenAI or Anthropic.

## License

[MIT](LICENSE)
