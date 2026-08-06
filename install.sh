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

install_dependencies() {
    [ "${CLAUDE_PET_NO_DEPS:-}" = "1" ] && return 0
    have python3 || die "python3 is required but not installed"

    local missing=()
    python3 -c 'import gi' 2>/dev/null || missing+=(gtk)
    python3 -c 'import PIL' 2>/dev/null || missing+=(pillow)
    [ ${#missing[@]} -eq 0 ] && return 0

    local packages=()
    local manager=""
    if have apt-get; then
        manager="apt"
        for item in "${missing[@]}"; do
            case "$item" in
                gtk) packages+=(python3-gi python3-gi-cairo gir1.2-gtk-3.0) ;;
                pillow) packages+=(python3-pil) ;;
            esac
        done
    elif have dnf; then
        manager="dnf"
        for item in "${missing[@]}"; do
            case "$item" in
                gtk) packages+=(python3-gobject gtk3) ;;
                pillow) packages+=(python3-pillow) ;;
            esac
        done
    elif have pacman; then
        manager="pacman"
        for item in "${missing[@]}"; do
            case "$item" in
                gtk) packages+=(python-gobject gtk3) ;;
                pillow) packages+=(python-pillow) ;;
            esac
        done
    elif have zypper; then
        manager="zypper"
        for item in "${missing[@]}"; do
            case "$item" in
                gtk) packages+=(python3-gobject gtk3) ;;
                pillow) packages+=(python3-Pillow) ;;
            esac
        done
    else
        say "install: missing ${missing[*]}, and no known package manager."
        say "install: install PyGObject (GTK 3) and Pillow, then re-run."
        return 0
    fi

    say "==> installing ${packages[*]}"
    case "$manager" in
        apt) sudo apt-get update -qq && sudo apt-get install -y "${packages[@]}" ;;
        dnf) sudo dnf install -y "${packages[@]}" ;;
        pacman) sudo pacman -S --noconfirm "${packages[@]}" ;;
        zypper) sudo zypper --non-interactive install "${packages[@]}" ;;
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
