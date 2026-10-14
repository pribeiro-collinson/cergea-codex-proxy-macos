# v5.2.2 — clean-install and runtime TLS hardening

- Create a minimal valid `~/.codex/config.toml` on first install, with a conservative 120K auto-compaction limit and the legacy provider alias required by older threads.
- Validate Cergea connectivity with both curl and Bun's own HTTPS runtime before starting the proxy, so TLS-store differences fail early with actionable output.
- Combine the generated macOS CA bundle with Bun's system CA trust; support an explicitly supplied organization CA via `CERGEA_EXTRA_CA_CERT`.
- Keep the preflight model request tiny (`max_tokens: 8`) to avoid large default output budgets.
- Make the package installer backup names versioned, replace destination symlinks without writing through them, and default the optional Ponytail installation to no.
- Remove generated Python bytecode from the distribution and add fresh-install, TLS-preflight, manifest, symlink-safety, and optional-dependency tests.
