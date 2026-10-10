#!/usr/bin/env bash
# Installs the Resource Monitor extension into Orca's user extensions folder
# and approves it. Orca loads it the next time it starts; to restart Orca now,
# run: orca --replace &
#
# Run this again after changing the extension: any change alters the
# extension's hash, and Orca will not load it until it is approved again.
#
# Usage:
#   ./install.sh               install (or replace) and approve
#   ./install.sh --uninstall   revoke approval and remove the installed copy
#   --yes                      with either form, do not ask before replacing
#                              or removing an installed copy

set -euo pipefail

package="resource_monitor"
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_dir="$repo_dir/$package"
po_dir="$source_dir/po"
target_root="${XDG_DATA_HOME:-$HOME/.local/share}/orca/extensions"
target_dir="$target_root/$package"

uninstall=false
assume_yes=false
for argument in "$@"; do
    case "$argument" in
        --uninstall) uninstall=true ;;
        -y|--yes) assume_yes=true ;;
        -h|--help)
            sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown option: $argument (use --uninstall, --yes, or no option to install)" >&2
            exit 2
            ;;
    esac
done

confirm() {
    if $assume_yes; then
        return 0
    fi
    printf '%s [y/N] ' "$1"
    read -r reply
    case "$reply" in
        [yY]*) return 0 ;;
        *) return 1 ;;
    esac
}

if $uninstall; then
    if [ ! -e "$target_dir" ]; then
        echo "Resource Monitor is not installed in $target_dir."
        exit 0
    fi
    if ! confirm "Remove Resource Monitor from $target_dir?"; then
        echo "Nothing was changed."
        exit 0
    fi
    if command -v orca >/dev/null 2>&1; then
        orca --revoke-extension "$package" || true
    fi
    rm -rf -- "$target_dir"
    echo "Removed Resource Monitor. Restart Orca to unload it."
    exit 0
fi

if [ ! -f "$source_dir/__init__.py" ]; then
    echo "Cannot find $package/__init__.py next to this script." >&2
    exit 1
fi

if ! command -v orca >/dev/null 2>&1; then
    echo "Orca is not on PATH; install Orca with user-extension support first." >&2
    exit 1
fi

# These helpers are optional: without them the matching reports say the
# information is unavailable, so a missing one is only a note.
for optional in nmcli iw nvidia-smi; do
    if ! command -v "$optional" >/dev/null 2>&1; then
        echo "Note: $optional is not on PATH. See README.md for what depends on it."
    fi
done

if [ -e "$target_dir" ]; then
    if ! confirm "Replace the existing extension at $target_dir?"; then
        echo "Nothing was changed."
        exit 0
    fi
    rm -rf -- "$target_dir"
fi

mkdir -p "$target_root"
cp -r -- "$source_dir" "$target_dir"
find "$target_dir" -name '__pycache__' -type d -prune -exec rm -rf -- {} +

# Recompile the translations into the installed copy, before approving it: the
# compiled catalogues are part of what Orca hashes. Without msgfmt the
# catalogues committed in the repository are installed as they are.
shopt -s nullglob
po_files=("$po_dir"/*.po)
if [ "${#po_files[@]}" -gt 0 ] && command -v msgfmt >/dev/null 2>&1; then
    for po in "${po_files[@]}"; do
        language="$(basename "$po" .po)"
        mkdir -p "$target_dir/locale/$language/LC_MESSAGES"
        msgfmt --check --output-file="$target_dir/locale/$language/LC_MESSAGES/$package.mo" "$po"
    done
fi

orca --approve-extension "$package"
echo "Installed Resource Monitor in $target_dir. Restart Orca to load it."
