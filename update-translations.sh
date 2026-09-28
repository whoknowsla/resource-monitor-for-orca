#!/usr/bin/env bash
# Regenerates the translation template, merges it into every translation, and
# compiles the catalogs Orca loads. Requires GNU gettext.
#
# Run it after changing any user-visible string. The compiled .mo files are
# part of the extension package, so re-approve the extension afterwards.

set -euo pipefail

package_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resource_monitor"
domain="resource_monitor"
cd "$package_dir"

xgettext --language=Python --from-code=UTF-8 \
    --keyword=_ \
    --keyword=ngettext:1,2 \
    --keyword=pgettext:1c,2 \
    --add-comments=Translators \
    --package-name="$domain" \
    --msgid-bugs-address="aygund@pm.me" \
    --copyright-holder="Deniz Aygun" \
    --sort-by-file \
    --output="po/$domain.pot" \
    ./*.py

for po in po/*.po; do
    [ -e "$po" ] || continue
    language="$(basename "$po" .po)"
    msgmerge --quiet --update --backup=none "$po" "po/$domain.pot"
    mkdir -p "locale/$language/LC_MESSAGES"
    msgfmt --check --output-file="locale/$language/LC_MESSAGES/$domain.mo" "$po"
    echo "Compiled $language"
done
