# Changelog — v5.1.2

- Fixed bootstrap installation when the ZIP is extracted directly into `~/.codex`: the installer now detects same-file source/destination copies and skips them instead of allowing macOS `cp` to abort under `set -e`.
- Added a synthetic regression test for running `install.sh --copy-only` with the bundle root and target Codex home being the same directory.
- Updated the installation guide to explicitly support both temporary extraction and direct extraction into `~/.codex`.
- No proxy runtime behavior or model configuration changed.
