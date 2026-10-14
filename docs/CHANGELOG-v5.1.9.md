# v5.1.9

- Build the macOS trusted-CA bundle on every installation, not only when Bun dependencies are missing.
- Pass that bundle to the running Bun proxy through `NODE_EXTRA_CA_CERTS`, so runtime HTTPS uses the same trusted CAs as installation.
- Keep TLS verification enabled; no insecure-certificate bypasses are introduced.
- Add regression coverage for runtime CA propagation and the installer's unconditional bundle build.
