#!/usr/bin/env bash
# claude-pet installer. No git required.
#
#   curl -fsSL https://raw.githubusercontent.com/HaneulOscarLee/claude-pet/main/install.sh | bash
#
# Downloads the source tarball straight from GitHub, installs system
# dependencies if they are missing, and runs `claude-pet setup`.
#
# Environment:
#   CLAUDE_PET_DIR   where to install       (default ~/.local/share/claude-pet)
#   CLAUDE_PET_REF   branch or tag to fetch (default main)
#   CLAUDE_PET_NO_DEPS=1   skip installing system packages

set -euo pipefail

REPO="HaneulOscarLee/claude-pet"
REF="${CLAUDE_PET_REF:-main}"
DIR="${CLAUDE_PET_DIR:-$HOME/.local/share/claude-pet}"

say() { printf '%s\n' "$*"; }
die() { printf 'install: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ------------------------------------------------------------------ dependencies

# Package names per distro family, for each thing we need.
#   gtk     PyGObject and GTK 3 -- the overlay itself
#   pillow  sprite decoding
#   wmctrl  lets clicking the pet raise a terminal that is not running tmux
#   notify  optional desktop notifications
packages_for() {
    local manager="$1" item="$2"
    case "$manager:$item" in
        apt:gtk)       echo "python3-gi python3-gi-cairo gir1.2-gtk-3.0" ;;
        apt:pillow)    echo "python3-pil" ;;
        apt:wmctrl)    echo "wmctrl" ;;
        apt:notify)    echo "libnotify-bin" ;;
        dnf:gtk)       echo "python3-gobject gtk3" ;;
        dnf:pillow)    echo "python3-pillow" ;;
        dnf:wmctrl)    echo "wmctrl" ;;
        dnf:notify)    echo "libnotify" ;;
        pacman:gtk)    echo "python-gobject gtk3" ;;
        pacman:pillow) echo "python-pillow" ;;
        pacman:wmctrl) echo "wmctrl" ;;
        pacman:notify) echo "libnotify" ;;
        zypper:gtk)    echo "python3-gobject gtk3" ;;
        zypper:pillow) echo "python3-Pillow" ;;
        zypper:wmctrl) echo "wmctrl" ;;
        zypper:notify) echo "libnotify-tools" ;;
    esac
}

install_dependencies() {
    [ "${CLAUDE_PET_NO_DEPS:-}" = "1" ] && return 0
    have python3 || die "python3 is required but not installed"

    local missing=()
    python3 -c 'import gi' 2>/dev/null || missing+=(gtk)
    python3 -c 'import PIL' 2>/dev/null || missing+=(pillow)
    have wmctrl || have xdotool || missing+=(wmctrl)
    have notify-send || missing+=(notify)
    if [ ${#missing[@]} -eq 0 ]; then
        say "==> dependencies already present"
        return 0
    fi

    local manager=""
    for candidate in apt dnf pacman zypper; do
        local binary="$candidate"
        [ "$candidate" = "apt" ] && binary="apt-get"
        if have "$binary"; then
            manager="$candidate"
            break
        fi
    done
    if [ -z "$manager" ]; then
        say "install: no known package manager; install these yourself:"
        say "install:   PyGObject (GTK 3), Pillow, wmctrl, libnotify"
        return 0
    fi

    local packages=()
    for item in "${missing[@]}"; do
        # shellcheck disable=SC2207  # deliberate word splitting: one name per word
        packages+=($(packages_for "$manager" "$item"))
    done
    [ ${#packages[@]} -eq 0 ] && return 0

    say "==> installing ${packages[*]}"
    say "    (sudo may ask for your password)"
    # Not fatal: the overlay may still run, and setup reports what is missing.
    case "$manager" in
        apt) sudo apt-get update -qq && sudo apt-get install -y "${packages[@]}" || true ;;
        dnf) sudo dnf install -y "${packages[@]}" || true ;;
        pacman) sudo pacman -S --noconfirm "${packages[@]}" || true ;;
        zypper) sudo zypper --non-interactive install "${packages[@]}" || true ;;
    esac
}

# ---------------------------------------------------------------------- download

download() {
    local target="$1"
    local url="https://codeload.github.com/${REPO}/tar.gz/refs/heads/${REF}"
    if have curl; then
        curl -fsSL "$url" -o "$target" && return 0
    elif have wget; then
        wget -qO "$target" "$url" && return 0
    else
        die "curl or wget is required"
    fi
    # A tag rather than a branch is a different path; try that before failing.
    url="https://codeload.github.com/${REPO}/tar.gz/refs/tags/${REF}"
    if have curl; then
        curl -fsSL "$url" -o "$target"
    else
        wget -qO "$target" "$url"
    fi
}

# Refuse to delete anything that is not a previous install of ours.
clear_target() {
    [ -e "$DIR" ] || return 0
    [ -d "$DIR" ] || die "$DIR exists and is not a directory"
    if [ ! -e "$DIR/claude_pet/__init__.py" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
        die "$DIR is not empty and does not look like a claude-pet install"
    fi
    rm -rf "$DIR"
}

main() {
    install_dependencies

    local tmp
    tmp="$(mktemp -d)"
    # shellcheck disable=SC2064  # expand $tmp now, not at trap time
    trap "rm -rf '$tmp'" EXIT

    say "==> downloading ${REPO}@${REF}"
    download "$tmp/src.tar.gz"
    tar -xzf "$tmp/src.tar.gz" -C "$tmp"

    local src
    src="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
    [ -n "$src" ] || die "the downloaded archive looked empty"
    [ -x "$src/claude-pet" ] || die "the downloaded archive has no claude-pet launcher"

    say "==> installing into $DIR"
    clear_target
    mkdir -p "$(dirname "$DIR")"
    mv "$src" "$DIR"

    say "==> running setup"
    "$DIR/claude-pet" setup
}

main "$@"
