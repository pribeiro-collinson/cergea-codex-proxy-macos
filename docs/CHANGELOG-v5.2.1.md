# v5.2.1 — Bun TLS trust configuration and distribution review

- Use Bun's documented `SSL_CERT_FILE` environment variable to add the generated macOS CA bundle for dependency installation and runtime requests.
- Invoke the Bun runtime with `--use-system-ca` during the HTTPS preflight and proxy startup, while keeping certificate verification enabled.
- Remove reliance on the undocumented `NODE_USE_SYSTEM_CA` environment switch.
- Add a standalone first-install quick-start for colleagues.
- Re-run package-manifest, fresh-config, symlink, TLS, Python, and available runtime checks before distribution.
