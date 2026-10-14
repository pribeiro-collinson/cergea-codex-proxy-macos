# v5.2.2 — final clean-install distribution review

- Use Bun's documented `SSL_CERT_FILE` and `--use-system-ca` mechanisms for runtime and package-install TLS trust.
- Avoid exporting all certificates from mutable system/login keychains as unconditional trust anchors; use Apple's system-root bundle, Bun's OS trust store, and an explicit approved PEM for company TLS inspection.
- Add a short standalone QUICK-START.md for colleagues.
- Revalidate exact manifest coverage, fresh config generation, symlink safety, clean-package paths, secrets, and synthetic regression tests.
