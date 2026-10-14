# Changelog — v5.1.3

Fixes the test and installer failures reported from macOS v5.1.2:

- Installer skips self-copy by exact path before checking filesystem identity, addressing Bash/macOS `cp` failures when the ZIP is extracted directly into `~/.codex`.
- Installs a distribution manifest and scopes personal-path/key checks to package-owned files, avoiding false positives from user `config.toml` and timestamped backups.
- Fixes the generated Bun output-cap test fixture so it does not export `toChatBody` twice.
- Adds regression coverage for the manifest being copied to a clean user's Codex home and for self-copy of the manifest.

No changes are made to the user's existing `config.toml` by copy-only mode.
