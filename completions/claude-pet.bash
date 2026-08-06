# bash completion for claude-pet
#
# The candidate lists come from `claude-pet _complete`, so they are generated
# from the real argument parser and cannot drift out of date with it.
#
# Works in zsh too, after:
#   autoload -U +X bashcompinit && bashcompinit

_claude_pet() {
    local current previous sub
    current="${COMP_WORDS[COMP_CWORD]}"
    previous=""
    if [ "$COMP_CWORD" -gt 0 ]; then
        previous="${COMP_WORDS[COMP_CWORD-1]}"
    fi
    sub=""
    if [ "$COMP_CWORD" -gt 1 ]; then
        sub="${COMP_WORDS[1]}"
    fi

    # `--` matters: `previous` is frequently an option such as --pet, which
    # argparse would otherwise try to parse as a flag of its own.
    local IFS=$'\n'
    COMPREPLY=(
        $(claude-pet _complete -- "$COMP_CWORD" "$current" "$previous" "$sub" 2>/dev/null)
    )
}

complete -F _claude_pet claude-pet
