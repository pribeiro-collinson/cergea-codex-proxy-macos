# v5.1.8

- Fix optional Ponytail installation when Codex CLI is bundled inside ChatGPT Desktop but not available on the shell `PATH`.
- Resolve the CLI using `CODEX_CLI_PATH`, then the CLI path in `~/.codex/config.toml`, then standard ChatGPT Desktop locations.
- Print the selected CLI path before invoking the official Ponytail marketplace/install commands.
- Add regression tests for configured and bundled CLI discovery while preserving the `PATH`-based CLI path.
