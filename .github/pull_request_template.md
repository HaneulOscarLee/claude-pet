## What this changes

<!-- One concern per PR, please. -->

## How you verified it

<!--
A green checkmark is not enough on its own here: most of this project is about
how a window behaves on a particular desktop. Say what you actually saw.
-->

- [ ] `python3 tests/test_aggregate.py`
- [ ] `python3 -c "import claude_pet.overlay"`
- [ ] Watched it in the real overlay (`claude-pet restart`, or `claude-pet demo`)

**Tested on:** <!-- e.g. Ubuntu 24.04, GNOME 46, Wayland, GNOME Terminal, no tmux -->

## Notes

<!--
Worth flagging if the change touches any of these:
- the hook path, which runs on every tool call and must stay stdlib-only and fast
- state aggregation, dwells, or liveness (please add a case to the tests)
- sprite parsing (which pack did you check it against?)
-->
