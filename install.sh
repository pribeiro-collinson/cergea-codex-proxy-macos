#!/bin/bash
set -euo pipefail

# Resolve this script's own directory, not the caller's current directory.
BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RELEASE_VERSION="$(tr -d '\r\n' < "$BUNDLE_ROOT/VERSION")"
if [[ ! "$RELEASE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid VERSION file in package: $BUNDLE_ROOT/VERSION" >&2
  exit 1
fi
DEFAULT_CODEX_HOME="$HOME/.codex"
if [[ -d "$DEFAULT_CODEX_HOME" ]]; then
  DEFAULT_CODEX_HOME="$(cd "$DEFAULT_CODEX_HOME" && pwd -P)"
else
  DEFAULT_CODEX_HOME="$(cd "$HOME" && pwd -P)/.codex"
fi
CODEX_HOME="${CODEX_HOME:-$DEFAULT_CODEX_HOME}"
MODE="${1:-install}"
if [[ "$MODE" != "install" && "$MODE" != "--copy-only" ]]; then
  echo "Usage: $0 [--copy-only]" >&2
  exit 2
fi

MANIFEST="$BUNDLE_ROOT/DISTRIBUTION-MANIFEST.txt"
mkdir -p "$CODEX_HOME"
CODEX_HOME="$(cd "$CODEX_HOME" && pwd -P)"

# Refresh the release inventory before copying it. Never scan CODEX_HOME itself:
# it may contain config.toml, session data, user scripts, and unrelated files.
if [[ "$BUNDLE_ROOT" != "$CODEX_HOME" && "$BUNDLE_ROOT" != "$DEFAULT_CODEX_HOME" ]] && [[ -f "$BUNDLE_ROOT/tools/update_distribution_manifest.py" ]]; then
  python3 "$BUNDLE_ROOT/tools/update_distribution_manifest.py" "$BUNDLE_ROOT"
fi
if [[ ! -f "$MANIFEST" ]]; then
  echo "Distribution manifest is missing: $MANIFEST" >&2
  echo "Extract the complete ZIP; do not copy only install.sh." >&2
  exit 1
fi
STAMP="$(date '+%Y%m%d-%H%M%S')"

copy_bundle_file() {
  local source_file="$1"
  local target="$2"
  local rel="$3"
  mkdir -p "$(dirname "$target")"

  # Covers direct extraction into ~/.codex, symlinks, and hard links.
  if [[ "$source_file" == "$target" ]]; then
    echo "Already in destination, skipped: $rel"
    return 0
  fi

  # Never follow a destination symlink into a user's unrelated file. Preserve
  # the symlink itself as a backup, then install a regular package-owned file.
  if [[ -L "$target" ]]; then
    local backup="$target.pre-cergea-v${RELEASE_VERSION}-${STAMP}.bak"
    mv "$target" "$backup"
    echo "Backed up destination symlink $target -> $backup"
  elif [[ -e "$target" ]] && [[ "$source_file" -ef "$target" ]]; then
    echo "Already in destination, skipped: $rel"
    return 0
  elif [[ -f "$target" ]] && ! cmp -s "$source_file" "$target"; then
    local backup="$target.pre-cergea-v${RELEASE_VERSION}-${STAMP}.bak"
    cp -p "$target" "$backup"
    echo "Backed up $target -> $backup"
  fi
  cp -p "$source_file" "$target"
}

# Copy exactly the files listed in the package-owned manifest. This also updates
# install.sh itself and the manifest when invoked from an extracted folder, so
# tests and repeat runs use the same release that the user just downloaded.
while IFS= read -r rel || [[ -n "$rel" ]]; do
  rel="${rel%$'\r'}"
  [[ -z "$rel" || "$rel" == \#* ]] && continue
  case "$rel" in
    /*|..|../*|*/../*|*/..)
      echo "Unsafe path in distribution manifest: $rel" >&2
      exit 1
      ;;
  esac
  source_file="$BUNDLE_ROOT/$rel"
  target="$CODEX_HOME/$rel"
  if [[ ! -f "$source_file" ]]; then
    echo "Manifest entry is missing from the extracted package: $rel" >&2
    exit 1
  fi
  copy_bundle_file "$source_file" "$target" "$rel"
done < "$MANIFEST"

# Only set executable bits on package-owned executable scripts, not user files.
for executable in \
  bin/install-cergea-codex bin/start-cergea-codex bin/stop-cergea-codex \
  bin/install-ponytail install.sh tools/build_macos_ca_bundle.sh tests/test_synthetic.py tests/test_runtime_contracts.py; do
  if [[ -f "$CODEX_HOME/$executable" ]]; then
    chmod +x "$CODEX_HOME/$executable"
  fi
done

if [[ "$MODE" == "--copy-only" ]]; then
  echo "Bundle copied to $CODEX_HOME (copy-only mode; no installation/network actions were run)."
  exit 0
fi

CERGEA_DISTRIBUTION_ROOT="$BUNDLE_ROOT" "$CODEX_HOME/bin/install-cergea-codex"

cat <<EOF2

Cergea proxy is installed. Ponytail is an optional companion plugin from
https://github.com/DietrichGebert/ponytail. It encourages smaller, less overbuilt
coding changes; it is not a substitute for the proxy's history-size guard.
EOF2
if [[ -t 0 ]]; then
  read -r -p "Install the optional Ponytail Codex plugin now? [y/N] " answer
  answer="${answer:-N}"
  case "$answer" in
    y|Y|yes|YES)
      if ! "$CODEX_HOME/bin/install-ponytail"; then
        echo "Proxy setup succeeded, but Ponytail installation did not. See docs/PONYTAIL.md." >&2
      fi
      ;;
    *) echo "Skipped optional Ponytail. Install it later with: $CODEX_HOME/bin/install-ponytail" ;;
  esac
else
  echo "Non-interactive setup: Ponytail was not installed automatically. Run: $CODEX_HOME/bin/install-ponytail"
fi

echo
echo "Setup finished. Read $CODEX_HOME/docs/README.md and run the included smoke tests."
