#!/usr/bin/env bash
# Installs the Resource Monitor extension into Orca's user extensions folder.
#
# Only ~/.local/share/orca/extensions/resource_monitor is written. Approval is a
# separate, deliberate step, because Orca will not load an unapproved extension.
#
# Usage: ./install.sh [--yes]
#   --yes  Replace an existing installation without asking.

set -euo pipefail

package="resource_monitor"
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$package"
target_root="${XDG_DATA_HOME:-$HOME/.local/share}/orca/extensions"
target_dir="$target_root/$package"

assume_yes=false
for argument in "$@"; do
    case "$argument" in
        -y|--yes) assume_yes=true ;;
        -h|--help)
            sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown option: $argument" >&2; exit 2 ;;
    esac
done

if [ ! -f "$source_dir/__init__.py" ]; then
    echo "Cannot find $package/__init__.py next to this script." >&2
    exit 1
fi

for optional in nmcli iw nvidia-smi; do
    if ! command -v "$optional" >/dev/null 2>&1; then
        echo "Note: $optional is not on PATH. See README.md for what depends on it."
    fi
done

if [ -e "$target_dir" ]; then
    if ! $assume_yes; then
        printf 'Replace the existing extension at %s? [y/N] ' "$target_dir"
        read -r reply
        case "$reply" in
            [yY]*) ;;
            *) echo "Nothing was changed."; exit 0 ;;
        esac
    fi
    rm -rf -- "$target_dir"
fi

mkdir -p "$target_root"
cp -r -- "$source_dir" "$target_dir"
find "$target_dir" -name '__pycache__' -type d -prune -exec rm -rf -- {} +

echo "Installed to $target_dir"
echo
echo "Next steps:"
echo "  1. orca --approve-extension $package"
echo "     (or approve it on the User Extensions page of Orca's preferences)"
echo "  2. Restart Orca."
echo
echo "Re-run both steps after any update: changing the files changes the hash"
echo "Orca approved, so the extension will not load until it is approved again."
